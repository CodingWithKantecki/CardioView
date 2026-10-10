"""Gemini heart: a patient, a situation or a rhythm described in words becomes the simulator's
settings (`Recipe` in sources/rhythm.py). Gemini fills the recipe with textbook-style values for
the description; the server clamps every number and plays it as a simulated rhythm, named and
marked as a simulation. It is a classroom simulation for the demo, never anyone's real heart.

The key is GEMINI_API_KEY, read at request time and sent in a header, as the chat does."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .chat import API_BASE, THINKING, TIMEOUT_S, error_message, extract_text, model_name
from .sources.rhythm import LIMITS, Recipe

log = logging.getLogger("cardioview.describe")
MAX_TEXT_CHARS = 300
MAX_NAME_CHARS = 28   # the status line says 'Simulated <name>' in one line
MAX_SUMMARY_CHARS = 140

# Plain words for every failure, shown under the text box.
WORDS = {
    "empty": "Describe a patient, a situation or a heart rhythm",
    "missing_key": "Gemini heart is not set up on this server",
    "rate_limit": "Gemini is busy, try again soon",
    "offline": "Gemini heart needs an internet connection",
    "timeout": "No answer in time, try again",
    "model": "The Gemini model is not available on this server",
    "upstream": "Gemini did not answer, try again",
    "refused": "Describe a patient, a situation or a heart rhythm",
}
STATUS = {"empty": 400, "missing_key": 503, "rate_limit": 429, "offline": 502, "timeout": 504, "model": 502, "upstream": 502, "refused": 400}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ok": {"type": "BOOLEAN"}, "reason": {"type": "STRING"},
        "name": {"type": "STRING"}, "summary": {"type": "STRING"},
        "bpm": {"type": "NUMBER"}, "jitter": {"type": "NUMBER"}, "irregular": {"type": "BOOLEAN"},
        "p_wave": {"type": "NUMBER"}, "pr_s": {"type": "NUMBER"}, "qrs_width": {"type": "NUMBER"},
        "st_mv": {"type": "NUMBER"}, "t_mv": {"type": "NUMBER"}, "pvc_every": {"type": "INTEGER"},
    },
    "required": ["ok", "reason", "name", "summary", "bpm", "jitter", "irregular", "p_wave", "pr_s", "qrs_width", "st_mv", "t_mv", "pvc_every"],
}

PROMPT = """You set up an ECG simulator for CardioView, a demo that shows a simulated heart beating on a screen. The user describes a patient, a situation or a heart rhythm in plain words. You answer with the simulator's settings that give a textbook-style single-lead ECG for that description. This is a classroom simulation, never anyone's real heart, and never advice.

Settings (every number is clamped to its range):
- bpm: heart rate, 30 to 220.
- jitter: beat-to-beat variation of the interval as a fraction, 0 to 0.4. A calm regular rhythm 0.02 to 0.04, a stressed one 0.05, atrial fibrillation 0.3 or more with irregular true.
- irregular: true for an irregularly irregular rhythm (atrial fibrillation): the intervals vary widely at random and the P wave is gone (set p_wave 0).
- p_wave: P wave height in millivolts, 0 to 0.3; 0.12 is normal, 0 means none (fibrillation, a ventricular rhythm).
- pr_s: seconds from the P wave to the R peak, 0.10 to 0.32; 0.18 normal, 0.24 or more for a first degree block.
- qrs_width: 1 is a normal narrow QRS; 2 to 3 is wide (ventricular tachycardia, a bundle branch block, hyperkalemia, a sodium channel blocker overdose). A wide QRS also gives the beat a ventricular shape with no P wave.
- st_mv: ST segment shift in millivolts, -0.3 to 0.5; 0 normal, positive is elevation (a heart attack 0.3 to 0.5), negative is depression (ischemia, digoxin, demand ischemia under stimulants).
- t_mv: T wave height in millivolts, -0.6 to 0.9; 0.3 normal, 0.6 or more tall and peaked (hyperkalemia), negative inverted (ischemia, ventricular beats).
- pvc_every: 0 for none, or an early wide extra beat every N beats, 3 to 12 (stimulants, caffeine, a tired heart).

Pick values a cardiology textbook would show for the description. Examples: cocaine, meth or a big energy drink: bpm 120 to 150, jitter 0.05, pvc_every 6 to 8, st_mv -0.1, t_mv 0.2. Opioids such as oxycodone, Percocet or heroin: bpm 40 to 55, jitter 0.02, everything else normal. A marathon runner at rest: bpm 42 to 50. A panic attack: bpm 110 to 130, jitter 0.04. Hyperkalemia: t_mv 0.9, qrs_width 2, p_wave 0.04. Atrial fibrillation: irregular true, jitter 0.35, p_wave 0, bpm 90 to 140. Ventricular tachycardia: bpm 150 to 190, qrs_width 3, p_wave 0, t_mv -0.5. A heart attack: st_mv 0.4, t_mv 0.6, bpm 95 to 110. A newborn: bpm 130 to 150, all shapes normal. A fever: the rate up about 10 for each degree. A beta blocker: bpm 50 to 60, pr_s 0.22. Deep sleep: bpm 50 to 58, jitter 0.06.

name: two or three short words in sentence case naming what is simulated, at most 28 characters, for example "Cocaine intoxication", "Opioid overdose", "Runner at rest", "Atrial fibrillation". summary: one plain sentence under 120 characters saying what the trace shows and why, for example "Fast and a little jittery, with an early beat every few seconds, as stimulants do." No medical advice, no second person, no em dashes, no diagnosis of any real person.

If the description is not about a person, a situation or a heart rhythm, or asks for anything else, answer ok false with a short reason in plain words such as "Describe a patient, a situation or a heart rhythm."; otherwise ok true with reason empty. Answer with JSON only."""


@dataclass
class Described:
    recipe: Recipe | None
    reply: str                   # words for the panel: the summary, or why there is no recipe
    error: str | None = None     # None, or a key of WORDS
    status: int = 200


def _clean(text: Any, limit: int) -> str:
    s = str(text or "").replace("—", ", ").replace("–", ", ").strip()
    return " ".join(s.split())[:limit]


def clamp(data: Any) -> Recipe | None:
    """A recipe from Gemini's answer (or a recipe sent back by the page), every number held to its
    range, the words trimmed; None when it is not a recipe at all."""
    if not isinstance(data, dict):
        return None
    name = _clean(data.get("name"), MAX_NAME_CHARS)
    if not name:
        return None
    summary = _clean(data.get("summary"), MAX_SUMMARY_CHARS)
    numbers: dict[str, float] = {}
    for key, (lo, hi, default) in LIMITS.items():
        try:
            v = float(data.get(key, default))
        except (TypeError, ValueError):
            v = default
        if v != v:   # NaN
            v = default
        numbers[key] = min(hi, max(lo, v))
    irregular = bool(data.get("irregular", False))
    if irregular:
        numbers["p_wave"] = 0.0
    pvc = int(round(numbers["pvc_every"]))
    if 0 < pvc < 3:
        pvc = 3
    return Recipe(name=name, summary=summary, bpm=numbers["bpm"], jitter=numbers["jitter"], irregular=irregular,
                  p_wave=numbers["p_wave"], pr_s=numbers["pr_s"], qrs_width=numbers["qrs_width"],
                  st_mv=numbers["st_mv"], t_mv=numbers["t_mv"], pvc_every=pvc)


def build_request(text: str, thinking: dict | None = THINKING) -> dict:
    config: dict[str, Any] = {"maxOutputTokens": 512, "temperature": 0.4,
                              "responseMimeType": "application/json", "responseSchema": SCHEMA}
    if thinking:
        config["thinkingConfig"] = dict(thinking)
    return {
        "systemInstruction": {"parts": [{"text": PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": config,
    }


def _fail(kind: str, reply: str | None = None) -> Described:
    return Described(None, reply or WORDS[kind], kind, STATUS[kind])


async def describe(text: str, client: httpx.AsyncClient, api_key: str | None = None) -> Described:
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    if not text:
        return _fail("empty")
    key = (api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key:
        return _fail("missing_key")
    url = f"{API_BASE}/{model_name()}:generateContent"
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    t0 = time.monotonic()
    try:
        resp = await client.post(url, headers=headers, json=build_request(text), timeout=TIMEOUT_S)
        if resp.status_code == 400 and THINKING:   # this model does not take the thinking field
            log.info("describe: retrying without thinkingConfig: %s", error_message(resp, key))
            resp = await client.post(url, headers=headers, json=build_request(text, thinking=None), timeout=TIMEOUT_S)
    except httpx.TimeoutException:
        log.warning("describe: gemini timed out after %.1fs", time.monotonic() - t0)
        return _fail("timeout")
    except httpx.HTTPError as e:
        log.warning("describe: no connection to gemini (%s)", type(e).__name__)
        return _fail("offline")
    if resp.status_code in (429, 503):
        log.warning("describe: gemini busy (%d): %s", resp.status_code, error_message(resp, key))
        return _fail("rate_limit")
    if resp.status_code != 200:
        log.warning("describe: gemini answered %d: %s", resp.status_code, error_message(resp, key))
        return _fail("model" if resp.status_code == 404 else "upstream")
    try:
        data = json.loads(extract_text(resp.json()))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        log.warning("describe: the answer was not a recipe")
        return _fail("upstream")
    if not data.get("ok", False):
        reason = _clean(data.get("reason"), MAX_SUMMARY_CHARS) or WORDS["refused"]
        log.info("describe: refused in %.1fs: %s", time.monotonic() - t0, reason)
        return _fail("refused", reason)
    recipe = clamp(data)
    if recipe is None:
        return _fail("upstream")
    log.info("describe: %s in %.1fs (%d bpm)", recipe.name, time.monotonic() - t0, round(recipe.bpm))
    return Described(recipe, recipe.summary)

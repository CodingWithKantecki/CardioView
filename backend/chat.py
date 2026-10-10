"""The chat widget's backend: one question about the data on screen, answered by Gemini.

The key comes from the GEMINI_API_KEY environment variable at request time and travels in a
header, never in a URL, so no log line can carry it. Nothing is stored between questions: the
viewer keeps its own short history and sends it back with each question."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

# The model, in one place. GEMINI_MODEL in the environment (or .env) overrides it.
# Checked 2026-10-10: gemini-2.5-flash is retired for new keys, gemini-3.8-flash was overloaded
# (503 and 20 s plus), gemini-3.5-flash answers in about 2 s with thinking off.
DEFAULT_MODEL = "gemini-3.5-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_S = 20.0
MAX_QUESTION_CHARS = 500
MAX_HISTORY_TURNS = 6           # question and answer pairs the viewer may send back
MAX_OUTPUT_TOKENS = 1024        # a cap, not a target: the prompt asks for two or three sentences
# Thinking off: a short factual answer needs none, and with it on the model can spend the whole
# output budget thinking and return no text. Models that reject the field get one retry without it.
THINKING = {"thinkingBudget": 0}
ECG_SUMMARY_S = 2.0             # the stretch of recent ECG summarized for the model
STALE_AFTER_S = 3.0             # no packet for this long counts as not streaming

# Plain words for every failure. The viewer shows `reply` whatever happened.
REPLIES = {
    "missing_key": "Chat is not set up on this server",
    "rate_limit": "Busy right now, try again soon",
    "offline": "The chat needs an internet connection",
    "timeout": "No answer in time, try again",
    "model": "Chat model is not available on this server",
    "upstream": "Chat failed, try again",
    "empty": "Ask a question about the data on screen",
}
STATUS = {"missing_key": 503, "rate_limit": 429, "offline": 502, "timeout": 504, "model": 502, "upstream": 502, "empty": 400}

log = logging.getLogger("cardioview.chat")
logging.getLogger("httpx").setLevel(logging.WARNING)   # no request line per question


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


SYSTEM_PROMPT = """You are the assistant inside CardioView, a live visualization of one person's ECG driving a 3D heart. You answer short questions about the data on the screen right now, and nothing else.

What is on screen and how each part is known:
- Measured: the ECG itself, one lead from a Polar H10 chest strap at 130 Hz in microvolts, or a recording or a simulation of one. The source field says which.
- Derived from the ECG: each beat's R peak time, the interval between beats (rr, seconds), the heart rate (bpm, 60 divided by the median of the last 5 intervals) and the chamber timing: offsets in seconds from the R peak when the right atrium (ra_on) and left atrium (la_on) start to squeeze, when the ventricles start (v_on) and when they relax (v_off). p_found true means the P wave was located on that beat; false means default timing was used.
- Modeled: the 3D heart is a textured model, the squeeze is a shader driven by the derived timing, and the small waves under the chamber labels are modeled pressure-style curves, not measurements.
- Signal: signal_ok false means no usable signal at all (pads off the skin or a flat line). streaming false means no data is arriving.

Rules:
- Answer only from the data given below. If something is not in it, say so plainly.
- Never diagnose, never name a heart rhythm or condition for live or recorded data, never say whether a reading is normal or abnormal, and never give medical advice. If asked, say that CardioView is a visualization, not a medical device, and suggest talking to a clinician for health questions.
- If the source is simulated, you may use the simulated rhythm's name exactly as the device field shows it, and say it is a simulation.
- Keep measured, derived and modeled apart: say which one a fact is when it matters.
- If a question is not about the data on this screen, say politely in one sentence that you can only talk about the data shown in CardioView.
- Reply in plain sentences, two or three at most, no lists, no markdown, no em dashes. Round numbers sensibly.
"""


@dataclass
class ChatReply:
    reply: str
    error: str | None = None     # None, or a key of REPLIES
    status: int = 200

    def body(self) -> dict:
        return {"reply": self.reply, "error": self.error}


def snapshot(hub: Any, last_packet_age_s: float | None = None) -> dict:
    """What the viewer is showing, from the server's own state: source and link state, signal,
    the recent beats and a summary of the last 2 s of ECG."""
    status = hub.status
    beats = [dict(b) for b in list(hub.beats)]
    for b in beats:
        b.pop("type", None)
        b.pop("source", None)
    last = beats[-1] if beats else {}
    streaming = status.get("state") == "streaming" and bool(hub.samples)
    if last_packet_age_s is not None and last_packet_age_s > STALE_AFTER_S:
        streaming = False
    ecg: dict[str, Any] = {"samples": 0}
    if hub.samples:
        msgs = list(hub.samples)
        t_end = msgs[-1]["t"] + len(msgs[-1]["uv"]) / msgs[-1]["fs"]
        uv: list[int] = []
        for m in reversed(msgs):
            uv = list(m["uv"]) + uv
            if m["t"] <= t_end - ECG_SUMMARY_S:
                break
        n = int(ECG_SUMMARY_S * msgs[-1]["fs"])
        uv = uv[-n:]
        if uv:
            ecg = {"samples": len(uv), "seconds": round(len(uv) / msgs[-1]["fs"], 2),
                   "peak_to_peak_uv": max(uv) - min(uv), "mean_uv": round(sum(uv) / len(uv))}
        ecg["stream_time_s"] = round(t_end, 2)
    return {
        "source": status.get("source"),
        "state": status.get("state"),
        "device": status.get("device") or None,
        "streaming": streaming,
        "signal_ok": bool(hub.signal.get("ok", True)),
        "signal_reason": hub.signal.get("reason") or None,
        "heart_rate_bpm": last.get("bpm"),
        "rr_s": last.get("rr"),
        "p_found_on_last_beat": last.get("p_found"),
        "recent_beats": beats,
        "ecg_recent": ecg,
    }


def clean_history(history: Any) -> list[dict]:
    """Keep only well-formed turns, the last MAX_HISTORY_TURNS pairs."""
    out: list[dict] = []
    if not isinstance(history, list):
        return out
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role not in ("user", "model") or not isinstance(text, str) or not text.strip():
            continue
        out.append({"role": role, "parts": [{"text": text.strip()[:MAX_QUESTION_CHARS * 4]}]})
    return out[-MAX_HISTORY_TURNS * 2:]


def build_request(question: str, history: Any, snap: dict, thinking: dict | None = THINKING) -> dict:
    system = SYSTEM_PROMPT + "\nCurrent data (JSON):\n" + json.dumps(snap, separators=(",", ":"))
    contents = clean_history(history) + [{"role": "user", "parts": [{"text": question}]}]
    config: dict[str, Any] = {"maxOutputTokens": MAX_OUTPUT_TOKENS, "temperature": 0.3}
    if thinking:
        config["thinkingConfig"] = dict(thinking)
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": config,
    }


def error_message(resp: httpx.Response, key: str) -> str:
    """Google's own one-line explanation of a failure, for the log: never the key, never the body."""
    try:
        msg = resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return ""
    return str(msg).replace(key, "<key>")[:200]


def extract_text(data: Any) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


async def ask(question: str, history: Any, snap: dict, client: httpx.AsyncClient,
              api_key: str | None = None) -> ChatReply:
    question = (question or "").strip()
    if not question:
        return ChatReply(REPLIES["empty"], "empty", STATUS["empty"])
    question = question[:MAX_QUESTION_CHARS]
    key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
    key = key.strip()
    if not key:
        return ChatReply(REPLIES["missing_key"], "missing_key", STATUS["missing_key"])
    url = f"{API_BASE}/{model_name()}:generateContent"
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    t0 = time.monotonic()
    try:
        resp = await client.post(url, headers=headers, json=build_request(question, history, snap),
                                 timeout=TIMEOUT_S)
        if resp.status_code == 400 and THINKING:   # this model does not take the thinking field
            log.info("chat: retrying without thinkingConfig: %s", error_message(resp, key))
            resp = await client.post(url, headers=headers,
                                     json=build_request(question, history, snap, thinking=None),
                                     timeout=TIMEOUT_S)
    except httpx.TimeoutException:
        log.warning("chat: gemini timed out after %.1fs", time.monotonic() - t0)
        return ChatReply(REPLIES["timeout"], "timeout", STATUS["timeout"])
    except httpx.HTTPError as e:
        log.warning("chat: no connection to gemini (%s)", type(e).__name__)
        return ChatReply(REPLIES["offline"], "offline", STATUS["offline"])
    if resp.status_code in (429, 503):   # over quota, or the model is overloaded: same advice
        log.warning("chat: gemini busy (%d): %s", resp.status_code, error_message(resp, key))
        return ChatReply(REPLIES["rate_limit"], "rate_limit", STATUS["rate_limit"])
    if resp.status_code != 200:
        log.warning("chat: gemini answered %d: %s", resp.status_code, error_message(resp, key))
        kind = "model" if resp.status_code == 404 else "upstream"
        return ChatReply(REPLIES[kind], kind, STATUS[kind])
    try:
        text = extract_text(resp.json())
    except ValueError:
        text = ""
    if not text:
        log.warning("chat: empty answer")
        return ChatReply(REPLIES["upstream"], "upstream", STATUS["upstream"])
    log.info("chat: answered in %.1fs", time.monotonic() - t0)
    return ChatReply(text.replace("\u2014", ", "))

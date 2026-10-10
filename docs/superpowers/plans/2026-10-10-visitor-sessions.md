# Visitor Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A booth visitor saves an opt-in, two-minute guided session and gets a summary of what their heart did, on the big screen with a QR code and on their own phone, with Neon holding the anonymous summary and a Hugging Face voice reading the steps.

**Architecture:** A `SessionManager` inside the existing FastAPI process sees every packet in `pump()`, runs the guided steps by counting received samples, saves the recording under `sessions/<id>/` and analyses it with NeuroKit2 when the steps end. A plain ES-module overlay shows the steps on Thomas's stage. One summary page serves the big screen, phones on the LAN, and a small Vercel FastAPI app that reads Neon.

**Tech Stack:** Python 3.12 (Windows dev box) and 3.14 (Thomas's Mac), FastAPI 0.143, NeuroKit2 0.2.13, segno 1.6.6, psycopg 3.3.6, plain ES modules and canvas, Neon Postgres, Vercel Python (FastAPI), Kokoro 82M from Hugging Face (dev tool only).

**Spec:** `docs/superpowers/specs/2026-10-10-visitor-sessions-design.md`

**How this plan was checked:** every file below was built and run in a scratch copy of the repo before it was written here. The Python files pass 72 tests there, the Task 3 state alone passes 55, and the overlay and summary page were screenshotted at 1920 by 1080 and 390 wide. Two spec details changed on the way and Task 10 writes them back into the spec: the Vercel copy of the summary page lives in `cloud/static/`, and QR codes are made server side with segno instead of a vendored JS encoder.

## Global Constraints

- No em dashes or en dashes anywhere: code, comments, UI text, docs, commit messages (repo rule in CLAUDE.md).
- UI text is short, plain, sentence case. No verdicts ("good", "normal", "healthy"), no condition or rhythm names, no reference ranges. The summary says "A visualization, not a medical device. It does not diagnose anything."
- The viewer stays plain ES modules and Three.js: no bundler, no framework, no build step, no CDN. It runs with no internet.
- Thomas's design language from CLAUDE.md: ink `#070A12`, hairlines `rgba(232, 236, 243, 0.10)`, text `#E8ECF3`, dim `#7F8AA0`, ECG green `#43E0A0` only on measured ECG, no panel fills, borders, pills or chips, IBM Plex Sans 400/600, Condensed 700 only for numerals and chamber letters, motion off under prefers-reduced-motion.
- Stage controls are keys only, like R, W and C: S twice starts (that is the consent), Esc twice stops and deletes, V turns the voice on or off.
- A visitor's ECG is never committed and never leaves the laptop. `sessions/` and `.env` are gitignored. Neon gets the anonymous summary only.
- Edits to Thomas's files (`backend/app.py`, `backend/__main__.py`, `frontend/main.js`, `frontend/index.html`) stay small and go in after a fresh `git fetch` and rebase. New code goes in new files.
- Pins: `segno==1.6.6` and `psycopg[binary]==3.3.6` in `requirements.txt`. The voice tool alone uses `kokoro==0.9.4` and `soundfile==0.14.0` on Python 3.12.
- CLAUDE.md stays under 200 lines and changes in the same commit as the behavior it describes.
- Commands are written for the Windows dev box in Git Bash: `.venv/Scripts/python` (Thomas's Mac: `.venv/bin/python`). Screenshots need `CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe"` and an explicit output path; `W` and `H` set the viewport.
- Create and edit files with the editor or the Write and Edit tools, never shell heredocs (a heredoc ate backslashes in this team's other repo).
- The live strap path is not tested on hardware by this plan. Say so, and give Thomas the command to run on the Mac.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. The strap is still settling when get ready reaches 30 s: the session must go on to rest, not hang. Rest sections may then say they could not be measured. Pinned by `test_get_ready_gives_up_waiting_after_30_s` (Task 2).
2. Every section is refused (noise, a loose strap): the summary shows five plain reasons, hides charts that would only show noise, and throws no script error. Pinned by `test_noise_only_measures_nothing` (Task 1) and the refused-session screenshot (Task 5, Step 6).
3. A phone cannot reach the booth and there is no cloud: the big screen still shows the summary and the QR caption says to use the booth Wi-Fi. Pinned by the end-to-end screenshot (Task 5, Step 7).
4. The operator starts the next visitor while a summary is still on screen: a new session starts and the previous summary stays readable by its link. Pinned by `test_a_new_session_can_start_while_a_summary_shows` (Task 2).
5. A phone deletes the session the big screen is showing: the booth deletes its copy and the big screen goes back to live. Pinned by `test_a_session_from_start_to_summary_qr_and_delete` (Task 3), `test_sync_applies_deletes_made_on_phones` (Task 7) and the delete-while-open screenshot (Task 5, Step 8).

## File map

| File | Job | Task |
|---|---|---|
| `backend/synth.py` | Synthetic sessions with known answers (tests, `/s/demo`) | 1 |
| `backend/analysis.py` | Recording plus step windows to the five summary sections | 1 |
| `backend/session.py` | `SessionStore` (folders on disk) and `SessionManager` (steps, consent, cancel, finish) | 2 |
| `backend/app.py` | Hub session slot, pump hook, ticker, routes, QR, demo | 3 |
| `backend/__main__.py` | `--keep-until`, `--public-host`, then `.env` and the cloud switch | 3, 7 |
| `frontend/session.js`, `session.css` | Stage overlay: keys, prompt, countdown, ring, voice | 4 |
| `frontend/main.js`, `index.html` | Four hooks and two elements for the overlay | 4 |
| `frontend/summary.html`, `.js`, `.css` | The summary page for big screen, phone and Vercel | 5 |
| `tools/make_voice.py`, `requirements-voice.txt`, `frontend/assets/voice/*.wav` | Voice coach | 6 |
| `backend/cloud.py` | Neon publish, unpublish, sync loop, `.env` loader | 7 |
| `tools/sessions.py` | `list`, `delete`, `wipe`, `cloud-init`, `deploy` | 8 |
| `cloud/` | The Vercel app: `app.py`, requirements, tests | 9 |
| `README.md`, `CLAUDE.md`, spec | Docs | 3 to 10 |

---

### Task 1: Synthetic sessions and the session analysis

**Files:**
- Create: `backend/synth.py`
- Create: `backend/analysis.py`
- Test: `backend/tests/test_analysis.py`

**Interfaces:**
- Consumes: `backend.sources.base.FS` (130), `backend.sources.replay.load_csv(path) -> list[int]`.
- Produces:
  - `synth.plan_steps(t0: float = 0.0) -> list[dict]` with `{"name", "start", "end"}` for `get_ready` (5 s), `rest` (30), `breathe` (40), `squats` (20), `recover` (30).
  - `synth.synth_session(seed: int = 1, t0: float = 0.0, tail_s: float = 0.0) -> SynthSession(t, uv, steps, r_times)`.
  - `analysis.analyze(t: np.ndarray, uv: np.ndarray, steps: list[dict]) -> dict`, never raises, strict-JSON-safe. Keys: `version`, `steps` (from 0), `effort`, `breathing`, `hrv`, `beat`, `timing`, `hr_chart`. Each section is `{"ok": True, ...values}` or `{"ok": False, "reason": str}`.
  - `effort`: `rest_bpm`, `peak_bpm`, `drop_bpm`. `breathing`: optional `rest_per_min`, `paced_per_min`, `swing_bpm`, `breaths`, plus `chart` `{"step_s", "bpm"}`. `hrv`: `rmssd_ms`, `sdnn_ms`, `n`, `window_s`. `beat`: `n`, `fs`, `t0`, `uv` (list), `waves` `{"p", "qrs": 0.0, "t"}` in seconds from R. `timing`: `rest`, `breathe` lists of `[rr, next_rr]`. `hr_chart`: `{"step_s": 1.0, "bpm": [...]}` with `null` for gaps.
  - Also public for tests: `Beats`, `find_beats`, `effort`, `breathing`, `hrv`, `timing`, `average_beat`, `hr_series`, `breaths_per_min`.

- [ ] **Step 1: Bring the branch up to date**

Run: `git fetch origin && git rebase origin/main`
Expected: success (the branch only holds the spec and this plan). Then `.venv/Scripts/python -m pytest -q` passes Thomas's suite.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_analysis.py`:

```python
"""Session analysis against synthetic sessions with known answers, and on bad input."""
import json
from pathlib import Path

import numpy as np
import pytest

from backend import analysis as A
from backend.sources.replay import load_csv
from backend.synth import synth_session

DATA = Path(__file__).resolve().parents[2] / "data"
SECTIONS = ("effort", "breathing", "hrv", "beat", "timing")


def truth(ses):
    """Beats at the true R peaks, all usable: what perfect detection would give."""
    r = ses.r_times
    rr = np.r_[np.nan, np.diff(r)]
    n = len(r)
    return A.Beats(r=r, rr=rr, usable=~np.isnan(rr), fixed=np.zeros(n, bool),
                   piece=np.zeros(n, int), idx=np.zeros(n, int))


@pytest.fixture(scope="module", params=[1, 2, 3], ids=lambda s: f"seed{s}")
def case(request):
    ses = synth_session(seed=request.param, t0=12.0)
    return ses, A.analyze(ses.t, ses.uv, ses.steps), truth(ses)


def test_every_true_beat_is_found_once(case):
    ses, _, _ = case
    beats, _ = A.find_beats(ses.t, ses.uv)
    assert len(beats.r) == len(ses.r_times)
    off = np.abs(beats.r - ses.r_times) * 130   # in samples
    assert np.median(off) <= 1.0 and off.max() <= 3.0


def test_effort_matches_the_design(case):
    ses, s, tb = case
    got, want = s["effort"], A.effort(tb, ses.steps)
    assert got["ok"] and want["ok"]
    assert abs(got["rest_bpm"] - want["rest_bpm"]) <= 2
    assert abs(got["peak_bpm"] - want["peak_bpm"]) <= 3
    assert abs(got["drop_bpm"] - want["drop_bpm"]) <= 4
    assert 125 <= got["peak_bpm"] <= 145 and got["drop_bpm"] > 20


def test_variability_matches_the_design(case):
    ses, s, tb = case
    got, want = s["hrv"], A.hrv(tb, ses.steps)
    assert got["ok"] and got["window_s"] == 30
    assert abs(got["rmssd_ms"] - want["rmssd_ms"]) <= 0.15 * want["rmssd_ms"]
    assert abs(got["sdnn_ms"] - want["sdnn_ms"]) <= 0.15 * want["sdnn_ms"]


def test_breathing_matches_the_design(case):
    ses, s, tb = case
    got = s["breathing"]
    assert got["ok"]
    assert abs(got["rest_per_min"] - 15) <= 1.5
    assert abs(got["paced_per_min"] - 6) <= 1.5
    assert abs(got["swing_bpm"] - A.breathing(tb, ses.steps)["swing_bpm"]) <= 3
    assert got["breaths"] == 4


def test_average_beat_labels_p_qrs_t_in_order(case):
    _, s, _ = case
    b = s["beat"]
    assert b["ok"] and b["n"] >= 30 and b["fs"] == 130
    assert 90 <= len(b["uv"]) <= 100 and b["t0"] < 0
    w = b["waves"]
    assert -0.30 <= w["p"] <= -0.05 and w["qrs"] == 0.0 and 0.15 <= w["t"] <= 0.45


def test_timing_has_points_for_rest_and_breathe(case):
    _, s, _ = case
    assert s["timing"]["ok"]
    assert len(s["timing"]["rest"]) >= 20 and len(s["timing"]["breathe"]) >= 30


def test_summary_is_strict_json_with_steps_from_zero(case):
    _, s, _ = case
    json.dumps(s, allow_nan=False)
    assert s["steps"][0] == {"name": "get_ready", "start": 0.0, "end": 5.0}
    assert len(s["hr_chart"]["bpm"]) == 125


def _session():
    return synth_session(seed=1, t0=12.0)


def _all_refused(s):
    for name in SECTIONS:
        assert s[name]["ok"] is False, name
        assert s[name]["reason"], name
    json.dumps(s, allow_nan=False)


def test_noise_only_measures_nothing():
    ses = _session()
    noise = np.round(np.random.default_rng(0).normal(0, 300, len(ses.uv))).astype(int)
    _all_refused(A.analyze(ses.t, noise, ses.steps))


def test_flat_line_measures_nothing():
    ses = _session()
    _all_refused(A.analyze(ses.t, np.zeros(len(ses.uv), int), ses.steps))


def test_empty_recording_measures_nothing():
    ses = _session()
    _all_refused(A.analyze(np.zeros(0), np.zeros(0, int), ses.steps))


def test_clipping_during_rest_blocks_rest_measures_only():
    ses = _session()
    uv = ses.uv.copy()
    rest = ses.steps[1]
    m = (ses.t >= rest["start"] + 2) & (ses.t < rest["end"] - 2) & (np.arange(len(uv)) % 40 < 6)
    uv[m] = 19930
    s = A.analyze(ses.t, uv, ses.steps)
    assert not s["effort"]["ok"] and not s["hrv"]["ok"]
    assert s["beat"]["ok"] and s["breathing"]["swing_bpm"] > 0


def test_session_that_ended_after_rest():
    ses = _session()
    steps = ses.steps[:2]
    cut = ses.t < steps[-1]["end"]
    s = A.analyze(ses.t[cut], ses.uv[cut], steps)
    assert "ended before squats" in s["effort"]["reason"]
    assert s["hrv"]["ok"] and s["beat"]["ok"] and s["breathing"]["rest_per_min"] == 15


def test_short_recovery_refuses_the_drop():
    ses = _session()
    steps = [dict(x) for x in ses.steps]
    steps[-1]["end"] = steps[-1]["start"] + 20
    cut = ses.t < steps[-1]["end"]
    s = A.analyze(ses.t[cut], ses.uv[cut], steps)
    assert "full 30 seconds" in s["effort"]["reason"]


def test_strap_gap_splits_the_recording_but_not_the_analysis():
    ses = _session()
    br = ses.steps[2]
    keep = ~((ses.t >= br["start"] + 15) & (ses.t < br["start"] + 23))
    s = A.analyze(ses.t[keep], ses.uv[keep], ses.steps)
    assert s["effort"]["ok"] and s["hrv"]["ok"] and s["beat"]["ok"]


def test_thomas_recording_as_rest_and_breathe():
    uv = np.array(load_csv(DATA / "h10_ecg_thomas.csv"))
    t = np.arange(len(uv)) / 130
    steps = [{"name": "get_ready", "start": 0.0, "end": 5.0}, {"name": "rest", "start": 5.0, "end": 35.0},
             {"name": "breathe", "start": 35.0, "end": 75.0}]
    s = A.analyze(t, uv, steps)
    assert s["hrv"]["ok"] and 10 <= s["hrv"]["rmssd_ms"] <= 120
    assert s["beat"]["ok"] and s["beat"]["waves"]["p"] < 0 < s["beat"]["waves"]["t"]
    json.dumps(s, allow_nan=False)


def test_breaths_per_min_reads_a_clean_rhythm():
    t = np.arange(0, 30, 0.25)
    assert abs(A.breaths_per_min(70 + 3 * np.sin(2 * np.pi * 0.25 * t), 0.1, 0.5) - 15) <= 0.5


def test_breaths_per_min_refuses_slow_drift():
    t = np.arange(0, 30, 0.25)
    assert A.breaths_per_min(70 + 0.2 * t, 0.1, 0.5) is None


def test_hr_series_blanks_stretches_without_beats():
    r = np.array([0.0, 1.0, 2.0, 6.0, 7.0])
    rr = np.r_[np.nan, np.diff(r)]
    rr[3] = 1.0   # pretend the RR is plausible so the beat stays usable
    b = A.Beats(r=r, rr=rr, usable=~np.isnan(rr), fixed=np.zeros(5, bool), piece=np.zeros(5, int), idx=np.zeros(5, int))
    grid, hr = A.hr_series(b, 0.0, 7.0, fs=1.0)
    assert np.isnan(hr[3]) and np.isnan(hr[4]) and not np.isnan(hr[1])
```

- [ ] **Step 3: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_analysis.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.analysis'`.

- [ ] **Step 4: Write the synthetic session generator**

Create `backend/synth.py`:

```python
"""Synthetic visitor sessions with known answers, for tests and the demo summary.

A session follows a designed heart rate curve per step. Beats are placed from
that curve, one simulated beat is drawn at each R peak at 1000 Hz, and the
result is band-limited and sampled at the strap's 130 Hz in integer microvolts.
The true R peak times come back too, so tests know the right answers.
Nobody's ECG is in here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import neurokit2 as nk
import numpy as np
from scipy.signal import butter, sosfiltfilt

from .sources.base import FS

HI_FS = 1000
STEP_PLAN = (("get_ready", 5.0), ("rest", 30.0), ("breathe", 40.0), ("squats", 20.0), ("recover", 30.0))
REST_BREATH_HZ = 0.25    # 15 breaths a minute at rest
PACED_BREATH_HZ = 0.1    # 6 a minute in the breathe step


@dataclass
class SynthSession:
    t: np.ndarray        # stream time of every sample, seconds
    uv: np.ndarray       # integer microvolts at 130 Hz
    steps: list[dict]    # {"name", "start", "end"} in stream time
    r_times: np.ndarray  # true R peaks, stream time


def plan_steps(t0: float = 0.0) -> list[dict]:
    steps, t = [], t0
    for name, length in STEP_PLAN:
        steps.append({"name": name, "start": t, "end": t + length})
        t += length
    return steps


def heart_rate_at(t: float) -> float:
    """The designed heart rate in bpm, t in seconds from the session start."""
    s = {x["name"]: x for x in plan_steps(0.0)}
    if t < s["breathe"]["start"]:
        return 70.0 + 3.0 * math.sin(2 * math.pi * REST_BREATH_HZ * t)
    if t < s["squats"]["start"]:
        return 72.0 + 6.0 * math.sin(2 * math.pi * PACED_BREATH_HZ * (t - s["breathe"]["start"]))
    if t < s["recover"]["start"]:
        return 75.0 + 65.0 * (1.0 - math.exp(-(t - s["squats"]["start"]) / 6.0))
    end_squats = 75.0 + 65.0 * (1.0 - math.exp(-(s["recover"]["start"] - s["squats"]["start"]) / 6.0))
    return 88.0 + (end_squats - 88.0) * math.exp(-(t - s["recover"]["start"]) / 20.0)


@lru_cache(maxsize=1)
def beat_template() -> np.ndarray:
    """One beat at 1000 Hz from 0.25 s before to 0.45 s after the R peak, in uV, ending at zero.

    ECGSYN angles, heights and widths are tuned so the beat looks like a typical adult one
    (P to QRS about 160 ms, QRS about 100 ms, QT about 400 ms at 70 bpm, T well below R).
    """
    sim = nk.ecg_simulate(duration=12, sampling_rate=HI_FS, heart_rate=70, heart_rate_std=0,
                          noise=0, method="ecgsyn", random_state=7,
                          ti=(-55, -10, 0, 10, 90), ai=(0.6, -5, 30, -7.5, 0.4),
                          bi=(0.25, 0.07, 0.07, 0.07, 0.4))
    _, info = nk.ecg_peaks(nk.ecg_clean(sim, sampling_rate=HI_FS), sampling_rate=HI_FS)
    r = int(info["ECG_R_Peaks"][5])
    beat = np.asarray(sim[r - 250:r + 450], dtype=float)
    beat -= np.linspace(beat[0], beat[-1], len(beat))
    ramp = 40
    taper = np.ones(len(beat))
    taper[:ramp] = np.hanning(2 * ramp)[:ramp]
    taper[-ramp:] = np.hanning(2 * ramp)[ramp:]
    beat *= taper
    return beat / beat[250] * 1200.0


def _to_strap_rate(x: np.ndarray) -> np.ndarray:
    """1000 Hz to 130 Hz without the ringing a sharp polyphase filter puts around each R peak."""
    y = sosfiltfilt(butter(2, 40.0, btype="low", fs=HI_FS, output="sos"), x)
    t_out = np.arange(int(len(y) * FS / HI_FS)) / FS
    return np.interp(t_out, np.arange(len(y)) / HI_FS, y)


def synth_session(seed: int = 1, t0: float = 0.0, tail_s: float = 0.0) -> SynthSession:
    """The planned steps from t0; tail_s more seconds of recovery after them."""
    rng = np.random.default_rng(seed)
    steps = plan_steps(t0)
    length = steps[-1]["end"] - t0 + tail_s
    r_times, r = [], 0.4
    while r < length - 0.5:
        r_times.append(r)
        r += 60.0 / heart_rate_at(r) * (1.0 + 0.025 * rng.standard_normal())
    rel = np.asarray(r_times)

    n_hi = int(round(length * HI_FS))
    x = np.zeros(n_hi)
    tpl = beat_template()
    rel_steps = {s["name"]: s for s in plan_steps(0.0)}
    for rt in rel:
        paced = rel_steps["breathe"]["start"] <= rt < rel_steps["breathe"]["end"]
        gain = 1.0 + 0.08 * math.sin(2 * math.pi * (PACED_BREATH_HZ if paced else REST_BREATH_HZ) * rt)
        i0 = int(round(rt * HI_FS)) - 250
        a, b = max(0, i0), min(n_hi, i0 + len(tpl))
        x[a:b] += gain * tpl[a - i0:b - i0]
    th = np.arange(n_hi) / HI_FS
    x += 60.0 * np.sin(2 * math.pi * 0.33 * th) + 40.0 * np.sin(2 * math.pi * 0.05 * th + 1.0)
    x += 12.0 * rng.standard_normal(n_hi)
    squats = (th >= rel_steps["squats"]["start"]) & (th < rel_steps["squats"]["end"])
    x[squats] += 40.0 * rng.standard_normal(int(squats.sum()))

    uv = np.round(_to_strap_rate(x)).astype(int)
    return SynthSession(t=t0 + np.arange(len(uv)) / FS, uv=uv, steps=steps, r_times=t0 + rel)
```

- [ ] **Step 5: Write the analysis**

Create `backend/analysis.py`:

```python
"""Analysis of a saved session: the recording and its step windows in, the summary out.

Every section is either measurements or {"ok": False, "reason": ...} in plain words.
Times in the input are stream times; the summary reports them from the session start.
Nothing here diagnoses. It measures rate, variability, breathing and the beat's shape.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import neurokit2 as nk
import numpy as np

from .sources.base import FS

log = logging.getLogger("cardioview.analysis")

CLIP_UV = 19000            # the strap pins at about plus or minus 19930 uV while settling
RR_MIN, RR_MAX = 0.3, 2.0  # 200 to 30 bpm
GAP_S = 1.5 / FS           # a bigger jump in stream time splits the recording
MIN_PIECE_S = 5.0
HR_FS = 4.0                # heart rate series for breathing and charts
BEAT_PRE_S, BEAT_POST_S = 0.25, 0.5


@dataclass
class Beats:
    r: np.ndarray       # R peak stream times
    rr: np.ndarray      # interval to the previous R in the same piece, nan for the first
    usable: np.ndarray  # RR in range and no clipped sample within 0.5 s
    fixed: np.ndarray   # moved or added by artifact correction
    piece: np.ndarray   # contiguous piece of the recording the beat is in
    idx: np.ndarray     # sample index into the recording


def _no(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _empty_beats() -> Beats:
    e = np.zeros(0)
    return Beats(r=e, rr=e, usable=e.astype(bool), fixed=e.astype(bool), piece=e.astype(int), idx=e.astype(int))


def step_window(steps: list[dict], name: str) -> dict | None:
    for s in steps:
        if s["name"] == name:
            return s
    return None


def pieces(t: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges of the contiguous stretches at least 5 s long."""
    cuts = np.flatnonzero(np.diff(t) > GAP_S) + 1
    bounds = [0, *cuts.tolist(), len(t)]
    return [(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if (b - a) / FS >= MIN_PIECE_S]


def find_beats(t: np.ndarray, uv: np.ndarray) -> tuple[Beats, np.ndarray]:
    """R peaks over the whole recording, plus the cleaned signal."""
    clean = np.zeros(len(uv))
    clipped = np.abs(uv) >= CLIP_UV
    cols: dict[str, list] = {"r": [], "rr": [], "usable": [], "fixed": [], "piece": [], "idx": []}
    for k, (a, b) in enumerate(pieces(t)):
        try:
            c = nk.ecg_clean(uv[a:b].astype(float), sampling_rate=FS)
            _, info = nk.ecg_peaks(c, sampling_rate=FS, correct_artifacts=True)
        except Exception as e:  # flat or odd signal: this piece has no beats
            log.info("no beats in piece %d: %s", k, e)
            continue
        clean[a:b] = c
        peaks = np.asarray(info["ECG_R_Peaks"], dtype=int)
        raw = np.asarray(info.get("ECG_R_Peaks_Uncorrected", peaks), dtype=int)
        prev = None
        for p in peaks:
            i = a + int(p)
            r = float(t[i])
            rr = r - prev if prev is not None else math.nan
            near = clipped[max(a, i - FS // 2):min(b, i + FS // 2)]
            cols["r"].append(r)
            cols["rr"].append(rr)
            cols["usable"].append(bool(not math.isnan(rr) and RR_MIN <= rr <= RR_MAX and not near.any()))
            cols["fixed"].append(bool(len(raw) == 0 or np.min(np.abs(raw - p)) > 1))
            cols["piece"].append(k)
            cols["idx"].append(i)
            prev = r
    beats = Beats(
        r=np.asarray(cols["r"], dtype=float), rr=np.asarray(cols["rr"], dtype=float),
        usable=np.asarray(cols["usable"], dtype=bool), fixed=np.asarray(cols["fixed"], dtype=bool),
        piece=np.asarray(cols["piece"], dtype=int), idx=np.asarray(cols["idx"], dtype=int),
    )
    return beats, clean


def in_window(beats: Beats, start: float, end: float) -> np.ndarray:
    return beats.usable & (beats.r >= start) & (beats.r < end)


def hr_series(beats: Beats, start: float, end: float, fs: float = HR_FS) -> tuple[np.ndarray, np.ndarray]:
    """Heart rate on a regular grid from usable beats; nan where usable beats are over 3 s apart."""
    grid = np.arange(start, end, 1.0 / fs)
    rt = beats.r[beats.usable]
    if len(rt) < 2:
        return grid, np.full(len(grid), np.nan)
    hr = 60.0 / beats.rr[beats.usable]
    out = np.interp(grid, rt, hr, left=np.nan, right=np.nan)
    j = np.searchsorted(rt, grid, side="right")   # rt[j-1] <= grid point < rt[j]
    lo = np.where(j > 0, rt[np.maximum(j - 1, 0)], -np.inf)
    hi = np.where(j < len(rt), rt[np.minimum(j, len(rt) - 1)], np.inf)
    out[hi - lo > 3.0] = np.nan
    return grid, out


def effort(beats: Beats, steps: list[dict]) -> dict:
    rest, squats, recover = (step_window(steps, n) for n in ("rest", "squats", "recover"))
    if rest is None or squats is None or recover is None:
        return _no("The session ended before squats and recovery.")
    m = in_window(beats, rest["start"], rest["end"])
    if beats.rr[m].sum() < 20.0:
        return _no("Not enough steady signal during rest.")
    resting = float(np.median(60.0 / beats.rr[m]))
    w = in_window(beats, squats["start"], recover["start"] + 10.0)
    if w.sum() < 10:
        return _no("Not enough steady signal during squats.")
    hr = 60.0 / beats.rr[w]
    peak = max(float(np.median(hr[i:i + 5])) for i in range(len(hr) - 4))
    if recover["end"] - recover["start"] < 29.5:
        return _no("The recovery step did not run its full 30 seconds.")
    q = in_window(beats, squats["end"] + 27.0, squats["end"] + 30.0)
    if q.sum() < 2:
        return _no("Not enough steady signal at the end of recovery.")
    after = float(np.median(60.0 / beats.rr[q]))
    return {"ok": True, "rest_bpm": round(resting), "peak_bpm": round(peak), "drop_bpm": round(peak - after)}


def breaths_per_min(hr: np.ndarray, lo_hz: float, hi_hz: float) -> float | None:
    """Breathing rate from a 4 Hz heart rate series: the strongest rhythm in the band.

    The heart speeds up on each in-breath, so the heart rate carries the breathing.
    Needs 15 s without inner gaps and a peak that stands out and is not on the band's edge.
    """
    ok = ~np.isnan(hr)
    if not ok.any():
        return None
    hr = hr[int(np.argmax(ok)):len(ok) - int(np.argmax(ok[::-1]))]   # trim blank ends
    if len(hr) < 15 * HR_FS or np.isnan(hr).any():
        return None
    x = (hr - hr.mean()) * np.hanning(len(hr))
    n = 4096
    power = np.abs(np.fft.rfft(x, n)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / HR_FS)
    band = np.flatnonzero((freqs >= lo_hz) & (freqs <= hi_hz))
    if len(band) < 3 or power[band].max() <= 0:
        return None
    j = int(np.argmax(power[band]))
    edge = max(1, len(band) // 20)
    if j < edge or j >= len(band) - edge:
        return None   # a peak on the edge is slow drift, not breathing
    if power[band[j]] < 3.0 * np.median(power[band]):
        return None
    return float(freqs[band[j]] * 60.0)


def breathing(beats: Beats, steps: list[dict]) -> dict:
    rest, br = step_window(steps, "rest"), step_window(steps, "breathe")
    out: dict = {"ok": False}
    if rest is not None:
        _, hr = hr_series(beats, rest["start"], rest["end"])
        rate = breaths_per_min(hr, 0.1, 0.5)
        if rate is not None:
            out["rest_per_min"] = round(rate)
    if br is not None:
        grid, hr = hr_series(beats, br["start"], br["end"])
        paced = breaths_per_min(hr, 0.05, 0.25)
        if paced is not None:
            out["paced_per_min"] = round(paced, 1)
        swings = []
        for k in range(int((br["end"] - br["start"]) // 10.0)):
            a = br["start"] + 10.0 * k
            seg = hr[(grid >= a) & (grid < a + 10.0)]
            if len(seg) and not np.isnan(seg).any():
                swings.append(float(seg.max() - seg.min()))
        if len(swings) >= 3:
            out["swing_bpm"] = round(float(np.median(swings)))
            out["breaths"] = len(swings)
        out["chart"] = {"step_s": 1.0 / HR_FS, "bpm": [round(float(v), 1) for v in hr]}
    out["ok"] = "rest_per_min" in out or "swing_bpm" in out
    if not out["ok"]:
        out["reason"] = "Not enough steady signal to see the breathing."
    return out


def hrv(beats: Beats, steps: list[dict]) -> dict:
    rest = step_window(steps, "rest")
    if rest is None:
        return _no("The session ended before rest.")
    m = in_window(beats, rest["start"], rest["end"])
    nn = beats.rr[m]
    if len(nn) < 20:
        return _no("Fewer than 20 steady beats during rest.")
    if beats.fixed[m].mean() > 0.10:
        return _no("Too many beats needed correcting during rest.")
    rmssd = float(np.sqrt(np.mean(np.diff(nn) ** 2)) * 1000.0)
    sdnn = float(np.std(nn, ddof=1) * 1000.0)
    return {"ok": True, "rmssd_ms": round(rmssd), "sdnn_ms": round(sdnn), "n": int(len(nn)),
            "window_s": round(rest["end"] - rest["start"])}


def timing(beats: Beats, steps: list[dict]) -> dict:
    """Each beat's RR against the next one, for rest and breathe."""
    out: dict = {"ok": False}
    for name in ("rest", "breathe"):
        s = step_window(steps, name)
        if s is None:
            continue
        idx = np.flatnonzero(in_window(beats, s["start"], s["end"]))
        out[name] = [[round(float(beats.rr[i]), 3), round(float(beats.rr[j]), 3)]
                     for i, j in zip(idx[:-1], idx[1:]) if j == i + 1 and beats.piece[i] == beats.piece[j]]
    if sum(len(v) for k, v in out.items() if k != "ok") < 10:
        return _no("Too few steady beats to plot.")
    out["ok"] = True
    return out


def average_beat(beats: Beats, clean: np.ndarray, t: np.ndarray, steps: list[dict]) -> dict:
    """The median beat over rest and breathe, with the P, QRS and T waves located at their peaks."""
    windows = [(s["start"], s["end"]) for s in (step_window(steps, "rest"), step_window(steps, "breathe")) if s]
    pre, post = int(round(BEAT_PRE_S * FS)), int(round(BEAT_POST_S * FS))
    chosen = []
    for i in range(len(beats.r)):
        if not beats.usable[i] or not any(a <= beats.r[i] < b for a, b in windows):
            continue
        local = float(np.nanmedian(beats.rr[max(0, i - 2):i + 3]))
        k = int(beats.idx[i])
        if abs(beats.rr[i] - local) > 0.2 * local or k - pre < 0 or k + post > len(clean):
            continue
        if np.any(np.diff(t[k - pre:k + post]) > GAP_S):
            continue
        chosen.append(i)
    if len(chosen) < 30:
        return _no("Fewer than 30 steady beats during rest and breathing.")
    mat = np.stack([clean[beats.idx[i] - pre:beats.idx[i] + post] for i in chosen])
    tpl = np.median(mat, axis=0)
    keep = np.array([np.corrcoef(row, tpl)[0, 1] for row in mat]) >= 0.8
    if keep.sum() < 30:
        return _no("The beats were not consistent enough to average.")
    kept = [chosen[j] for j in np.flatnonzero(keep)]
    tpl = np.median(mat[keep], axis=0)

    offsets: dict[str, list[float]] = {"p": [], "t": []}
    for piece in sorted({int(beats.piece[i]) for i in kept}):
        members = [i for i in kept if beats.piece[i] == piece]
        a = max(0, int(min(beats.idx[i] for i in members)) - pre)
        b = min(len(clean), int(max(beats.idx[i] for i in members)) + post)
        rp = np.array([int(beats.idx[i]) - a for i in members])
        try:
            _, waves = nk.ecg_delineate(clean[a:b], rp, sampling_rate=FS, method="dwt")
        except Exception as e:
            log.info("delineation failed on piece %d: %s", piece, e)
            continue
        for key, name in (("ECG_P_Peaks", "p"), ("ECG_T_Peaks", "t")):
            for r0, v in zip(rp, waves.get(key) or []):
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    offsets[name].append((int(v) - int(r0)) / FS)

    def where(name: str) -> float | None:
        v = offsets[name]
        return round(float(np.median(v)), 3) if len(v) >= 10 else None

    return {"ok": True, "n": int(keep.sum()), "fs": FS, "t0": -pre / FS,
            "uv": [round(float(v), 1) for v in tpl],
            "waves": {"p": where("p"), "qrs": 0.0, "t": where("t")}}


def hr_chart(beats: Beats, start: float, end: float) -> dict:
    _, hr = hr_series(beats, start, end, fs=1.0)
    return {"step_s": 1.0, "bpm": [round(float(v), 1) for v in hr]}


def _jsonable(x):
    """Plain Python types for json.dumps(allow_nan=False): nan becomes None."""
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(float(x)) or math.isinf(float(x)) else float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def analyze(t: np.ndarray, uv: np.ndarray, steps: list[dict]) -> dict:
    """The summary sections for one session. Never raises: a failure reads as couldn't measure."""
    t = np.asarray(t, dtype=float)
    uv = np.asarray(uv, dtype=int)
    start = steps[0]["start"] if steps else (float(t[0]) if len(t) else 0.0)
    end = steps[-1]["end"] if steps else start
    out: dict = {"version": 1,
                 "steps": [{"name": s["name"], "start": round(s["start"] - start, 2), "end": round(s["end"] - start, 2)}
                           for s in steps]}
    try:
        beats, clean = find_beats(t, uv)
    except Exception:
        log.exception("beat finding failed")
        beats, clean = _empty_beats(), None
    sections = {
        "effort": lambda: effort(beats, steps),
        "breathing": lambda: breathing(beats, steps),
        "hrv": lambda: hrv(beats, steps),
        "beat": lambda: average_beat(beats, clean, t, steps) if clean is not None else _no("No signal."),
        "timing": lambda: timing(beats, steps),
        "hr_chart": lambda: hr_chart(beats, start, end),
    }
    for name, fn in sections.items():
        try:
            out[name] = fn()
        except Exception:
            log.exception("analysis section %s failed", name)
            out[name] = _no("Something went wrong measuring this.")
    return _jsonable(out)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest backend/tests/test_analysis.py -q`
Expected: `32 passed` in about 7 s.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

- [ ] **Step 8: Commit**

```bash
git add backend/synth.py backend/analysis.py backend/tests/test_analysis.py
git commit -m "Sessions: synthetic sessions with known answers and the session analysis" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Session store and session manager

**Files:**
- Create: `backend/session.py`
- Test: `backend/tests/test_session.py`

**Interfaces:**
- Consumes: `analysis.analyze` (Task 1), `synth.synth_session` (tests), `backend.sources.base.FS, PACKET, PACKET_S, Packet`. Beats only need `.r`, `.rr` and `.bpm` (the pipeline's `Beat` has them).
- Produces:
  - `STEPS` (name, planned seconds), `SessionError`, `utcnow() -> datetime`.
  - `SessionStore(root)`: `valid_id(sid)`, `new_id()`, `path(sid)` (raises `ValueError` on a bad id), `create(sid, meta)`, `append(sid, packet, beats)`, `read_meta(sid)`, `write_meta(sid, meta)`, `read_recording(sid) -> (t, uv)`, `write_summary(sid, summary)`, `summary(sid, now) -> dict | None`, `delete(sid) -> bool`, `ids()`, `clean_up(now) -> int`.
  - `SessionManager(store, *, analyze, broadcast, link, publish, unpublish, keep_until, now, wall)`: `set_source(kind, device)`, `on_packet(packet, beats)`, `tick()`, `start() -> str` (raises `SessionError`), `async cancel()`, `dismiss()`, `async delete(sid) -> bool`, `update_link(sid, link)`, `message() -> dict`, attributes `state`, `sid`, `done_link`, `online`, `finishing` (the analysis task), `store`, `link`.
  - Messages: `{"type": "session", "state": "running", "id", "step", "index", "count", "elapsed_s", "length_s", "paused"}`, `{"state": "analyzing", "id"}`, `{"state": "done", "id", "link", "online"}`, `{"state": "idle"}` with an optional `"note": "stopped" | "write_failed"`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_session.py`:

```python
"""The session manager: steps by samples, pauses, consent, cancel, the store on disk."""
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.analysis import analyze
from backend.session import SessionError, SessionManager, SessionStore
from backend.sources.base import PACKET, PACKET_S, Packet
from backend.synth import synth_session

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


@dataclass
class FakeBeat:
    r: float
    rr: float | None
    bpm: int | None


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def packets_and_beats(ses, t_shift=0.0):
    """The synthetic session as strap packets, each with the true beats confirmed about 1 s late."""
    out = []
    r = ses.r_times
    done = 0
    for k in range(0, len(ses.uv) - PACKET + 1, PACKET):
        p = Packet(float(ses.t[k]) + t_shift, [int(v) for v in ses.uv[k:k + PACKET]])
        beats = []
        while done < len(r) and r[done] + 1.0 <= p.t_end - t_shift:
            rr = float(r[done] - r[done - 1]) if done else None
            beats.append(FakeBeat(float(r[done]) + t_shift, rr, round(60 / rr) if rr else None))
            done += 1
        out.append((p, beats))
    return out


def make(tmp_path, **kw):
    clock = Clock()
    sent = []
    m = SessionManager(SessionStore(tmp_path / "sessions"), analyze=kw.pop("analyze", analyze),
                       broadcast=sent.append, link=lambda sid: f"http://booth/s/{sid}",
                       keep_until=T0 + timedelta(days=1), now=clock, wall=lambda: T0, **kw)
    return m, clock, sent


def feed(m, clock, items):
    for p, beats in items:
        clock.t += PACKET_S
        m.on_packet(p, beats)


def test_start_needs_a_recent_signal(tmp_path):
    m, clock, _ = make(tmp_path)
    with pytest.raises(SessionError, match="No signal"):
        m.start()
    feed(m, clock, packets_and_beats(synth_session(seed=1, tail_s=10))[:2])
    clock.t += 3.0
    with pytest.raises(SessionError, match="No signal"):
        m.start()


def test_one_session_at_a_time_and_consent_is_written(tmp_path):
    m, clock, _ = make(tmp_path)
    feed(m, clock, packets_and_beats(synth_session(seed=1, tail_s=10))[:2])
    sid = m.start()
    with pytest.raises(SessionError, match="already running"):
        m.start()
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    assert meta["state"] == "recording" and meta["consent"]["how"] == "pressed S twice"
    assert meta["keep_until"] == (T0 + timedelta(days=1)).isoformat()


def test_a_full_session_runs_every_step_and_saves_a_summary(tmp_path):
    ses = synth_session(seed=1, tail_s=10)
    items = packets_and_beats(ses)

    async def run():
        m, clock, sent = make(tmp_path)
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        return m, sid, sent

    m, sid, sent = asyncio.run(run())
    order = []
    for msg in sent:
        if msg["state"] == "running" and (not order or order[-1] != msg["step"]):
            order.append(msg["step"])
    assert order == ["get_ready", "rest", "breathe", "squats", "recover"]
    assert m.state == "done" and m.message() == {"type": "session", "state": "done", "id": sid,
                                                 "link": f"http://booth/s/{sid}", "online": False}
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    seconds = {s["name"]: s["seconds"] for s in meta["steps"]}
    assert 5.0 <= seconds["get_ready"] <= 6.5
    assert all(seconds[n] == pytest.approx(want, abs=PACKET_S) for n, want in
               (("rest", 30), ("breathe", 40), ("squats", 20), ("recover", 30)))
    summary = m.store.summary(sid, T0)
    assert summary["effort"]["ok"] and summary["hrv"]["ok"] and summary["id"] == sid
    t, uv = m.store.read_recording(sid)
    assert len(t) == len(uv) and uv.dtype.kind == "i"


def test_steps_count_samples_so_a_strap_gap_pauses_them(tmp_path):
    ses = synth_session(seed=2, tail_s=10)
    items = packets_and_beats(ses)
    m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
    feed(m, clock, items[:2])
    m.start()
    feed(m, clock, items[2:30])                       # get ready and part of rest
    rest_before = m.steps[1].elapsed_s
    later = packets_and_beats(ses, t_shift=20.0)      # strap back: stream time jumped 20 s
    feed(m, clock, later[30:40])
    assert m.steps[1].name == "rest" and m.steps[1].elapsed_s == pytest.approx(rest_before + 10 * PACKET_S)
    assert m.state == "running" and m.steps[1].done is False


def test_a_long_drop_pauses_then_ends_with_the_finished_steps(tmp_path):
    ses = synth_session(seed=3, tail_s=10)
    items = packets_and_beats(ses)

    async def run():
        m, clock, sent = make(tmp_path)
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:80])                   # through rest, into breathe
        clock.t += 2.0
        m.tick()
        paused = sent[-1]["paused"]
        clock.t += 14.0
        m.tick()
        await m.finishing
        return m, sid, paused

    m, sid, paused = asyncio.run(run())
    assert paused is True
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    assert meta["ended_early"] is True
    assert [s["name"] for s in meta["steps"]] == ["get_ready", "rest"]
    summary = m.store.summary(sid, T0)
    assert summary["hrv"]["ok"] and summary["effort"]["ok"] is False


def test_cancel_deletes_the_folder_and_says_stopped(tmp_path):
    removed = []

    async def unpublish(sid):
        removed.append(sid)

    async def run():
        m, clock, sent = make(tmp_path, unpublish=unpublish)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:20])
        await m.cancel()
        return m, sid, sent

    m, sid, sent = asyncio.run(run())
    assert not (tmp_path / "sessions" / sid).exists()
    assert sent[-1] == {"type": "session", "state": "idle", "note": "stopped"} and removed == [sid]


def test_cancel_during_analysis_drops_the_result(tmp_path):
    async def run():
        m, clock, _ = make(tmp_path)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        assert m.state == "analyzing"
        await m.cancel()
        await m.finishing
        return m, sid

    m, sid = asyncio.run(run())
    assert m.state == "idle" and not (tmp_path / "sessions" / sid).exists()


def test_a_public_link_wins_and_a_failed_publish_falls_back(tmp_path):
    async def good(sid, summary, keep_until):
        return f"https://cloud/s/{sid}"

    async def bad(sid, summary, keep_until):
        raise ConnectionError("offline")

    async def run(publish, where):
        m, clock, _ = make(where, analyze=lambda t, uv, steps: {"version": 1}, publish=publish)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        return m.message(), sid

    msg, sid = asyncio.run(run(good, tmp_path / "a"))
    assert msg["link"] == f"https://cloud/s/{sid}" and msg["online"] is True
    msg, sid = asyncio.run(run(bad, tmp_path / "b"))
    assert msg["link"] == f"http://booth/s/{sid}" and msg["online"] is False


def test_update_link_and_dismiss(tmp_path):
    async def run():
        m, clock, sent = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        m.update_link(sid, "https://cloud/s/x")
        linked = sent[-1]
        m.dismiss()
        return linked, sent[-1]

    linked, last = asyncio.run(run())
    assert linked["link"] == "https://cloud/s/x" and linked["online"] is True
    assert last == {"type": "session", "state": "idle"}


def test_a_failed_write_stops_the_session(tmp_path, monkeypatch):
    m, clock, sent = make(tmp_path)
    items = packets_and_beats(synth_session(seed=1, tail_s=10))
    feed(m, clock, items[:2])
    sid = m.start()

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(m.store, "append", boom)
    feed(m, clock, items[2:3])
    assert m.state == "idle" and sent[-1]["note"] == "write_failed"
    assert not (tmp_path / "sessions" / sid).exists()


def test_store_refuses_ids_that_are_not_ours(tmp_path):
    store = SessionStore(tmp_path)
    for bad in ("../x", "..", "a/b", "", "x" * 21, "x" * 23, "abc def" + "x" * 15):
        assert not store.valid_id(bad)
        assert store.summary(bad, T0) is None and store.delete(bad) is False
        with pytest.raises(ValueError):
            store.path(bad)
    assert store.valid_id(store.new_id())


def test_clean_up_removes_unfinished_and_expired(tmp_path):
    store = SessionStore(tmp_path)
    keep = store.new_id()
    for sid, state, until in ((store.new_id(), "recording", T0 + timedelta(days=1)),
                              (store.new_id(), "done", T0 - timedelta(seconds=1)),
                              (keep, "done", T0 + timedelta(days=1))):
        store.create(sid, {"id": sid, "state": state, "keep_until": until.isoformat()})
        store.write_summary(sid, {"version": 1})
    assert store.clean_up(T0) == 2 and store.ids() == [keep]
    assert store.summary(keep, T0) == {"version": 1}
    assert store.summary(keep, T0 + timedelta(days=2)) is None


def test_get_ready_gives_up_waiting_after_30_s(tmp_path):
    """A strap still settling must not hang the session: get ready ends at 30 s and rest begins."""
    m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
    flat = [(Packet(k * PACKET_S, [0] * PACKET), []) for k in range(80)]   # no beats: never clean
    feed(m, clock, flat[:2])
    m.start()
    feed(m, clock, flat[2:])
    assert m.steps[0].done and m.steps[0].elapsed_s == pytest.approx(30, abs=PACKET_S)
    assert m.i == 1 and m.state == "running"


def test_a_new_session_can_start_while_a_summary_shows(tmp_path):
    async def run():
        m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        first = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        assert m.state == "done"
        return m, first, m.start()

    m, first, second = asyncio.run(run())
    assert second != first and m.state == "running"
    assert m.store.summary(first, T0)["id"] == first
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_session.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.session'`.

- [ ] **Step 3: Write the session module**

Create `backend/session.py`:

```python
"""Saved visitor sessions: the guided steps, the recording on disk and the summary.

A session only exists after the operator pressed S twice, which is the visitor's
consent to save it. Step clocks count samples that arrived, so a step pauses on
its own while the strap is away. Cancel deletes everything, here and in the cloud.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import re
import secrets
import shutil
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

from .sources.base import FS, PACKET_S, Packet

log = logging.getLogger("cardioview.session")

# name, planned seconds; get_ready is a maximum, it ends once the signal is clean for 5 s
STEPS = (("get_ready", 30.0), ("rest", 30.0), ("breathe", 40.0), ("squats", 20.0), ("recover", 30.0))
CLEAN_S = 5.0          # get_ready needs this long without clipping and with steady beats
CLIP_UV = 19000
RR_MIN, RR_MAX = 0.3, 2.0
PAUSED_S = 1.5         # no samples for this long: the stage says paused
DROP_LIMIT_S = 15.0    # no samples for this long: the session ends with the steps that finished
NO_SIGNAL_S = 2.0      # start needs a sample this recent
KEEP_DEFAULT = timedelta(hours=24)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionError(Exception):
    """A start that cannot happen, with a reason the stage can show."""


class SessionStore:
    """One folder per session under root: session.json, ecg.csv, beats.csv, summary.json."""

    def __init__(self, root: Path):
        self.root = Path(root)   # created on the first save, so a server that never saves leaves nothing

    @staticmethod
    def valid_id(sid: str) -> bool:
        return bool(ID_RE.match(sid or ""))

    def new_id(self) -> str:
        return secrets.token_urlsafe(16)   # 128 random bits, 22 characters

    def path(self, sid: str) -> Path:
        if not self.valid_id(sid):
            raise ValueError(f"not a session id: {sid!r}")
        return self.root / sid

    def create(self, sid: str, meta: dict) -> None:
        p = self.path(sid)
        p.mkdir(parents=True)
        self.write_meta(sid, meta)
        (p / "ecg.csv").write_text("time_s,ecg_uv\n")
        (p / "beats.csv").write_text("r,rr,bpm\n")

    def append(self, sid: str, packet: Packet, beats: list) -> None:
        p = self.path(sid)
        with open(p / "ecg.csv", "a", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerows((f"{packet.t + i / FS:.6f}", v) for i, v in enumerate(packet.uv))
        if beats:
            with open(p / "beats.csv", "a", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerows((b.r, "" if b.rr is None else b.rr, "" if b.bpm is None else b.bpm) for b in beats)

    def read_meta(self, sid: str) -> dict | None:
        try:
            return json.loads((self.path(sid) / "session.json").read_text())
        except (OSError, ValueError):
            return None

    def write_meta(self, sid: str, meta: dict) -> None:
        (self.path(sid) / "session.json").write_text(json.dumps(meta, indent=1))

    def read_recording(self, sid: str) -> tuple[np.ndarray, np.ndarray]:
        t, uv = [], []
        with open(self.path(sid) / "ecg.csv", newline="") as f:
            for row in csv.DictReader(f):
                t.append(float(row["time_s"]))
                uv.append(int(row["ecg_uv"]))
        return np.asarray(t, dtype=float), np.asarray(uv, dtype=int)

    def write_summary(self, sid: str, summary: dict) -> None:
        (self.path(sid) / "summary.json").write_text(json.dumps(summary, allow_nan=False))

    def summary(self, sid: str, now: datetime) -> dict | None:
        """The summary of a finished session that has not expired, else None."""
        if not self.valid_id(sid):
            return None
        meta = self.read_meta(sid)
        if not meta or meta.get("state") != "done" or datetime.fromisoformat(meta["keep_until"]) <= now:
            return None
        try:
            return json.loads((self.path(sid) / "summary.json").read_text())
        except (OSError, ValueError):
            return None

    def delete(self, sid: str) -> bool:
        if not self.valid_id(sid) or not self.path(sid).exists():
            return False
        shutil.rmtree(self.path(sid))
        return True

    def ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.valid_id(p.name))

    def clean_up(self, now: datetime) -> int:
        """Delete unfinished and expired sessions. Run at startup and by the wipe tool."""
        gone = 0
        for sid in self.ids():
            meta = self.read_meta(sid)
            if not meta or meta.get("state") != "done" or datetime.fromisoformat(meta["keep_until"]) <= now:
                self.delete(sid)
                gone += 1
        return gone


@dataclass
class StepClock:
    name: str
    length_s: float
    start: float | None = None   # stream time of the step's first sample
    end: float | None = None     # stream time after its last sample
    samples: int = 0
    done: bool = False

    @property
    def elapsed_s(self) -> float:
        return self.samples / FS

    def window(self) -> dict:
        return {"name": self.name, "start": self.start, "end": self.end}


class SessionManager:
    """The one session that can run at a time, driven by the server's packets.

    analyze(t, uv, steps) -> summary runs in a thread when the steps finish.
    publish(sid, summary, keep_until) -> public link or None, unpublish(sid): the cloud, optional.
    link(sid) -> the local link used when there is no public one.
    broadcast(message) sends a session message to every viewer.
    """

    def __init__(self, store: SessionStore, *, analyze: Callable[..., dict],
                 broadcast: Callable[[dict], None] = lambda m: None,
                 link: Callable[[str], str] = lambda sid: f"/s/{sid}",
                 publish: Callable[[str, dict, datetime], Awaitable[str | None]] | None = None,
                 unpublish: Callable[[str], Awaitable[None]] | None = None,
                 keep_until: datetime | None = None,
                 now: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = utcnow):
        self.store, self.analyze, self.broadcast, self.link = store, analyze, broadcast, link
        self.publish, self.unpublish = publish, unpublish
        self.now, self.wall = now, wall
        self.keep_until = keep_until or (wall() + KEEP_DEFAULT)
        self.source_kind, self.device = "simulated", ""
        self.state = "idle"            # idle, running, analyzing, done
        self.sid: str | None = None
        self.steps: list[StepClock] = []
        self.i = 0
        self.note: str | None = None   # why the last session stopped, for the stage
        self.done_link: str | None = None
        self.online = False
        self.finishing: asyncio.Task | None = None
        self._gen = 0                  # bumps on cancel, so a late analysis is dropped
        self._meta: dict = {}
        self._last_sample_at: float | None = None
        self._last_end: float | None = None
        self._last_t: float | None = None
        self._recent_uv: deque[int] = deque(maxlen=int(CLEAN_S * FS))
        self._recent_beats: deque[tuple[float, float | None]] = deque(maxlen=16)

    # inputs from the server ------------------------------------------------

    def set_source(self, kind: str, device: str) -> None:
        self.source_kind, self.device = kind, device

    def on_packet(self, packet: Packet, beats: list) -> None:
        self._last_sample_at = self.now()
        if self._last_end is not None and abs(packet.t - self._last_end) > PACKET_S:
            self._recent_uv.clear()
            self._recent_beats.clear()
        self._recent_uv.extend(packet.uv)
        self._recent_beats.extend((b.r, b.rr) for b in beats)
        self._last_t, self._last_end = packet.t_last, packet.t_end
        if self.state != "running":
            return
        try:
            self.store.append(self.sid, packet, beats)
        except OSError:
            log.exception("could not write the session")
            self._stop("write_failed")
            return
        st = self.steps[self.i]
        if st.start is None:
            st.start = packet.t
        st.samples += len(packet.uv)
        st.end = packet.t_end
        if st.elapsed_s >= st.length_s or (st.name == "get_ready" and st.elapsed_s >= CLEAN_S and self.clean()):
            st.done = True
            self.i += 1
            if self.i == len(self.steps):
                self._finish_soon(early=False)
                return
        self.broadcast(self.message())

    def tick(self) -> None:
        """Called about once a second: tells the stage about a pause, ends a session after a long drop."""
        if self.state != "running":
            return
        if self._last_sample_at is not None and self.now() - self._last_sample_at > DROP_LIMIT_S:
            self._finish_soon(early=True)
        else:
            self.broadcast(self.message())

    def clean(self) -> bool:
        """The last 5 s had no clipping and at least 3 steady beats."""
        if len(self._recent_uv) < self._recent_uv.maxlen or max(map(abs, self._recent_uv)) >= CLIP_UV:
            return False
        steady = [r for r, rr in self._recent_beats
                  if rr is not None and RR_MIN <= rr <= RR_MAX and r >= self._last_t - CLEAN_S]
        return len(steady) >= 3

    def paused(self) -> bool:
        return self._last_sample_at is not None and self.now() - self._last_sample_at > PAUSED_S

    # operator actions ------------------------------------------------------

    def start(self) -> str:
        if self.state in ("running", "analyzing"):
            raise SessionError("A session is already running.")
        if self._last_sample_at is None or self.now() - self._last_sample_at > NO_SIGNAL_S:
            raise SessionError("No signal yet.")
        sid = self.store.new_id()
        created = self.wall()
        self._meta = {
            "id": sid, "created": created.isoformat(), "keep_until": self.keep_until.isoformat(),
            "source": self.source_kind, "device": self.device, "state": "recording",
            "consent": {"by": "operator", "how": "pressed S twice", "at": created.isoformat()},
            "steps": [], "ended_early": False, "published": False,
        }
        try:
            self.store.create(sid, self._meta)
        except OSError as e:
            log.exception("could not create the session folder")
            raise SessionError("Could not save the session.") from e
        self.sid, self.state, self.i, self.note = sid, "running", 0, None
        self.steps = [StepClock(name, length) for name, length in STEPS]
        self.done_link, self.online = None, False
        self.broadcast(self.message())
        return sid

    async def cancel(self) -> None:
        if self.state not in ("running", "analyzing"):
            return
        await self._unpublish(self._stop("stopped"))

    def dismiss(self) -> None:
        if self.state == "done":
            self.state, self.sid, self.note = "idle", None, None
            self.broadcast(self.message())

    async def delete(self, sid: str) -> bool:
        """Delete one session everywhere. The running one is cancelled."""
        if sid == self.sid and self.state in ("running", "analyzing"):
            await self.cancel()
            return True
        existed = self.store.delete(sid)
        await self._unpublish(sid)
        if sid == self.sid and self.state == "done":
            self.state, self.sid = "idle", None
            self.broadcast(self.message())
        return existed

    def update_link(self, sid: str, link: str) -> None:
        """The cloud caught up: the summary on screen gets the public link."""
        if self.state == "done" and sid == self.sid:
            self.done_link, self.online = link, True
            self.broadcast(self.message())

    # messages --------------------------------------------------------------

    def message(self) -> dict:
        if self.state == "running":
            st = self.steps[self.i]
            return {"type": "session", "state": "running", "id": self.sid, "step": st.name,
                    "index": self.i, "count": len(self.steps), "elapsed_s": round(st.elapsed_s, 2),
                    "length_s": st.length_s, "paused": self.paused()}
        if self.state == "analyzing":
            return {"type": "session", "state": "analyzing", "id": self.sid}
        if self.state == "done":
            return {"type": "session", "state": "done", "id": self.sid, "link": self.done_link, "online": self.online}
        msg = {"type": "session", "state": "idle"}
        if self.note:
            msg["note"] = self.note
        return msg

    # finishing ---------------------------------------------------------------

    def _finish_soon(self, early: bool) -> None:
        self.state = "analyzing"
        self.broadcast(self.message())
        self.finishing = asyncio.get_running_loop().create_task(self._finish(self._gen, early))

    async def _finish(self, gen: int, early: bool) -> None:
        sid = self.sid
        steps = [s.window() for s in self.steps if s.done]
        try:
            t, uv = await asyncio.to_thread(self.store.read_recording, sid)
            summary = await asyncio.to_thread(self.analyze, t, uv, steps)
        except Exception:
            log.exception("could not analyze %s", sid)
            summary = {"version": 1, "steps": [], **{k: {"ok": False, "reason": "Something went wrong measuring this."}
                                                      for k in ("effort", "breathing", "hrv", "beat", "timing")}}
        if gen != self._gen:
            return   # cancelled while analyzing; _abort already deleted it
        meta = self._meta
        meta.update(state="done", ended_early=early,
                    steps=[{**w, "seconds": round(s.elapsed_s, 2)} for s, w in zip(self.steps, steps)])
        summary.update(id=sid, created=meta["created"], keep_until=meta["keep_until"],
                       source=meta["source"], ended_early=early)
        self.store.write_summary(sid, summary)
        self.store.write_meta(sid, meta)
        link, online = self.link(sid), False
        if self.publish is not None:
            try:
                public = await self.publish(sid, summary, self.keep_until)
            except Exception:
                log.exception("could not publish %s", sid)
                public = None
            if gen != self._gen:
                await self._unpublish(sid)   # cancelled while uploading: take it back down
                return
            if public:
                link, online = public, True
                meta["published"] = True
                self.store.write_meta(sid, meta)
        if gen != self._gen:
            return
        self.state, self.done_link, self.online = "done", link, online
        self.broadcast(self.message())

    def _stop(self, note: str) -> str | None:
        """End the session now and delete its folder. Returns the id for the cloud cleanup."""
        sid = self.sid
        self._gen += 1
        self.state, self.sid, self.note = "idle", None, note
        if sid:
            self.store.delete(sid)
        self.broadcast(self.message())
        return sid

    async def _unpublish(self, sid: str | None) -> None:
        if sid and self.unpublish is not None:
            try:
                await self.unpublish(sid)
            except Exception:
                log.exception("could not delete %s from the cloud", sid)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest backend/tests/test_session.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/session.py backend/tests/test_session.py
git commit -m "Sessions: store on disk and the step machine, timed by samples, with consent and cancel" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Sessions in the server

**Files:**
- Modify: `backend/app.py` (replace with the version below)
- Modify: `backend/__main__.py` (replace with the version below)
- Modify: `requirements.txt`, `.gitignore`, `CLAUDE.md`
- Test: `backend/tests/test_app_sessions.py`

**Interfaces:**
- Consumes: `SessionManager`, `SessionStore`, `SessionError`, `utcnow` (Task 2); `analysis.analyze`, `synth.synth_session` (Task 1).
- Produces:
  - `create_app(source, *, sessions_dir=None, keep_until=None, public_host=None, port=8000, cloud=None)`; `cloud` is any object with `publish`, `unpublish` and `run(manager)` (Task 7 supplies it). `app.state.sessions` is the manager.
  - Routes: `POST /api/session/start` (200 `{"id"}` or 409 `{"reason"}`), `POST /api/session/cancel`, `POST /api/session/dismiss`, `GET /api/s/{sid}` (`demo` is the synthetic one), `DELETE /api/s/{sid}`, `GET /api/s/{sid}/qr.svg`, `GET /s/{sid}` (serves `frontend/summary.html`, written in Task 5).
  - The backlog now starts with the status message and then the session message.
  - `__main__.parse_keep_until(value) -> datetime | None`; flags `--keep-until`, `--public-host`.

- [ ] **Step 1: Check Thomas has not changed the server since this plan**

Run: `git log --oneline 4ccb7ce..HEAD -- backend/app.py backend/__main__.py`
Expected: no output. If there is output, read his change and carry it into the versions below before replacing.

- [ ] **Step 2: Add segno**

Add this line to `requirements.txt` after `uvicorn==0.54.0`:

```text
segno==1.6.6
```

Run: `.venv/Scripts/pip install -r requirements.txt`
Expected: `Successfully installed segno-1.6.6` (or already satisfied).

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_app_sessions.py`:

```python
"""The session routes end to end: a fast synthetic source, the real detector and analysis."""
import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.__main__ import parse_keep_until
from backend.app import create_app
from backend.sources.base import PACKET, Packet, Source
from backend.synth import synth_session


class FastSource(Source):
    """The synthetic session looped as strap packets: a trickle until a session runs, then flat out."""

    kind = "simulated"

    def __init__(self):
        super().__init__()
        self.uv = synth_session(seed=1).uv
        self.go = lambda: False   # the fixture points this at "a session is running"

    async def packets(self):
        self.set_status("streaming", "Simulated 70 bpm")
        n, k = len(self.uv), 0
        while True:
            yield Packet(k / 130, [int(self.uv[(k + i) % n]) for i in range(PACKET)])
            k += PACKET
            await asyncio.sleep(0 if self.go() else 0.005)


def wait_for(cond, seconds=30.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def client(tmp_path):
    src = FastSource()
    app = create_app(src, sessions_dir=tmp_path / "sessions", public_host="booth.local", port=8000)
    src.go = lambda: app.state.sessions.state == "running"
    with TestClient(app) as c:
        yield c, app.state.sessions, tmp_path / "sessions"


def test_backlog_starts_with_status_then_session(client):
    c, _, _ = client
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "status"
        assert ws.receive_json() == {"type": "session", "state": "idle"}


def test_a_session_from_start_to_summary_qr_and_delete(client):
    c, sessions, root = client
    assert wait_for(lambda: sessions._last_sample_at is not None)
    r = c.post("/api/session/start")
    assert r.status_code == 200
    sid = r.json()["id"]
    assert c.post("/api/session/start").json() == {"reason": "A session is already running."}
    assert wait_for(lambda: sessions.state == "done", 60)
    assert sessions.message()["link"] == f"http://booth.local:8000/s/{sid}"

    s = c.get(f"/api/s/{sid}").json()
    assert s["id"] == sid and s["effort"]["ok"] and s["beat"]["ok"] and s["ended_early"] is False
    qr = c.get(f"/api/s/{sid}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")

    assert c.delete(f"/api/s/{sid}").json() == {"ok": True}
    assert c.get(f"/api/s/{sid}").status_code == 404
    assert not (root / sid).exists() and sessions.state == "idle"


def test_cancel_route_deletes_the_running_session(client):
    c, sessions, root = client
    assert wait_for(lambda: sessions._last_sample_at is not None)
    sid = c.post("/api/session/start").json()["id"]
    assert c.post("/api/session/cancel").json() == {"ok": True}
    assert sessions.message() == {"type": "session", "state": "idle", "note": "stopped"}
    assert not (root / sid).exists()


def test_unknown_bad_and_demo_ids(client):
    c, _, _ = client
    assert c.get("/api/s/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404
    assert c.get("/api/s/..%2F..%2Fetc").status_code == 404
    assert c.delete("/api/s/demo").status_code == 404
    demo = c.get("/api/s/demo").json()
    assert demo["demo"] is True and demo["effort"]["ok"] and demo["breathing"]["ok"]
    assert c.get("/api/s/demo/qr.svg").status_code == 200


def test_start_without_signal_is_refused(tmp_path):
    class Silent(Source):
        async def packets(self):
            await asyncio.sleep(3600)
            yield  # pragma: no cover

    with TestClient(create_app(Silent(), sessions_dir=tmp_path)) as c:
        r = c.post("/api/session/start")
        assert r.status_code == 409 and r.json() == {"reason": "No signal yet."}


def test_keep_until_reads_zones_and_local_time():
    assert parse_keep_until(None) is None
    assert parse_keep_until("2026-10-11T12:00+00:00") == datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    local = parse_keep_until("2026-10-11T12:00")
    assert local.tzinfo == timezone.utc and local == datetime(2026, 10, 11, 12, 0).astimezone(timezone.utc)
```

- [ ] **Step 4: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_app_sessions.py -q`
Expected: collection error, `ImportError: cannot import name 'parse_keep_until' from 'backend.__main__'`.

- [ ] **Step 5: Replace `backend/app.py`**

Thomas's Hub, pump and WebSocket stay as they were. Added: the session slot in `Hub` and its backlog, `sessions.on_packet` in `pump()`, a one-second ticker, `clean_up` at startup, the routes, `lan_address()` and `demo_summary()`.

```python
"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import segno
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analysis
from .pipeline import BeatDetector
from .session import SessionError, SessionManager, SessionStore, utcnow
from .sources.base import FS, Packet, Source, Status
from .synth import synth_session

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SESSIONS = FRONTEND.parent / "sessions"
BACKLOG_S = 8.0       # seconds of samples a late viewer gets
BACKLOG_BEATS = 12    # beats a late viewer gets
QUEUE_SIZE = 256      # per viewer; the oldest message is dropped when full

log = logging.getLogger("cardioview")


def dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def lan_address() -> str:
    """This machine's address on the network phones would use. No packet is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@lru_cache(maxsize=1)
def demo_summary() -> dict:
    """The summary page's demo: a synthetic session, nobody's ECG."""
    ses = synth_session(seed=1)
    summary = analysis.analyze(ses.t, ses.uv, ses.steps)
    now = utcnow()
    summary.update(id="demo", created=now.isoformat(), keep_until=(now + timedelta(days=365)).isoformat(),
                   source="simulated", ended_early=False, demo=True)
    return summary


class Hub:
    """Fan-out of messages to every viewer plus a short backlog for late ones."""

    def __init__(self, source_kind: str):
        self.source_kind = source_kind
        self.clients: set[asyncio.Queue] = set()
        self.samples: deque[dict] = deque()
        self.beats: deque[dict] = deque(maxlen=BACKLOG_BEATS)
        self.status = {"type": "status", "source": source_kind, "state": "connecting",
                       "device": "", "fs": FS}
        self.session = {"type": "session", "state": "idle"}

    def set_status(self, status: Status) -> None:
        self.status = {"type": "status", "source": self.source_kind, "state": status.state,
                       "device": status.device, "fs": FS}
        log.info("status: %s %s", status.state, status.device)
        self.broadcast(self.status)

    def set_session(self, msg: dict) -> None:
        self.session = msg
        self.broadcast(msg)

    def push_samples(self, packet: Packet) -> None:
        msg = {"type": "samples", "source": self.source_kind, "t": round(packet.t, 4),
               "fs": FS, "uv": list(packet.uv)}
        if self.samples and packet.t < self.samples[-1]["t"] - 1.0:
            self.samples.clear()
            self.beats.clear()
        self.samples.append(msg)
        while self.samples and self.samples[0]["t"] < packet.t_end - BACKLOG_S:
            self.samples.popleft()
        self.broadcast(msg)

    def push_beat(self, msg: dict) -> None:
        self.beats.append(msg)
        self.broadcast(msg)

    def broadcast(self, msg: dict) -> None:
        text = dumps(msg)
        for q in list(self.clients):
            if q.full():
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(text)

    def backlog(self) -> list[str]:
        out = [dumps(self.status), dumps(self.session)]
        out += [dumps(m) for m in self.samples]
        out += [dumps(m) for m in self.beats]
        return out

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)


def create_app(source: Source, *, sessions_dir: Path | None = None, keep_until: datetime | None = None,
               public_host: str | None = None, port: int = 8000, cloud=None) -> FastAPI:
    """cloud: an object with publish, unpublish and run(manager), or None to stay on the laptop."""
    hub = Hub(source.kind)
    detector = BeatDetector()
    store = SessionStore(sessions_dir or SESSIONS)
    host = public_host or lan_address()
    sessions = SessionManager(
        store, analyze=analysis.analyze, broadcast=hub.set_session,
        link=lambda sid: f"http://{host}:{port}/s/{sid}",
        publish=cloud.publish if cloud else None, unpublish=cloud.unpublish if cloud else None,
        keep_until=keep_until,
    )

    def on_status(status: Status) -> None:
        hub.set_status(status)
        sessions.set_source(source.kind, status.device)

    async def pump() -> None:
        try:
            async for packet in source.packets():
                hub.push_samples(packet)
                beats = await asyncio.to_thread(detector.feed, packet)
                for beat in beats:
                    hub.push_beat(beat.message(source.kind))
                sessions.on_packet(packet, beats)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("source stopped")

    async def ticker() -> None:
        while True:
            await asyncio.sleep(1.0)
            sessions.tick()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        gone = store.clean_up(utcnow())
        if gone:
            log.info("removed %d unfinished or expired sessions", gone)
        source.on_status(on_status)
        on_status(source.status)
        tasks = [asyncio.create_task(pump(), name="pump"), asyncio.create_task(ticker(), name="ticker")]
        if cloud is not None:
            tasks.append(asyncio.create_task(cloud.run(sessions), name="cloud"))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(title="CardioView", lifespan=lifespan)
    app.state.hub = hub
    app.state.sessions = sessions

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = hub.subscribe()

        async def send() -> None:
            for text in hub.backlog():
                await websocket.send_text(text)
            while True:
                await websocket.send_text(await q.get())

        async def receive() -> None:
            while True:
                await websocket.receive_text()

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                with suppress(WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                    t.result()
        finally:
            hub.unsubscribe(q)

    @app.post("/api/session/start")
    async def session_start():
        try:
            return {"id": sessions.start()}
        except SessionError as e:
            return JSONResponse({"reason": str(e)}, status_code=409)

    @app.post("/api/session/cancel")
    async def session_cancel():
        await sessions.cancel()
        return {"ok": True}

    @app.post("/api/session/dismiss")
    async def session_dismiss():
        sessions.dismiss()
        return {"ok": True}

    def find_summary(sid: str) -> dict | None:
        return demo_summary() if sid == "demo" else store.summary(sid, utcnow())

    @app.get("/api/s/{sid}")
    async def summary_get(sid: str):
        summary = find_summary(sid)
        if summary is None:
            return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        return summary

    @app.delete("/api/s/{sid}")
    async def summary_delete(sid: str):
        if sid == "demo" or not store.valid_id(sid) or not await sessions.delete(sid):
            return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        return {"ok": True}

    @app.get("/api/s/{sid}/qr.svg")
    async def summary_qr(sid: str):
        if find_summary(sid) is None:
            return Response(status_code=404)
        link = sessions.done_link if sid == sessions.sid and sessions.done_link else sessions.link(sid)
        buf = io.BytesIO()
        segno.make(link, error="m").save(buf, kind="svg", scale=8, border=3, dark="#070A12", light="#E8ECF3")
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.get("/s/{sid}")
    async def summary_page(sid: str):
        return FileResponse(FRONTEND / "summary.html")

    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app
```

- [ ] **Step 6: Replace `backend/__main__.py`**

```python
"""Run the CardioView server: python -m backend --source sim | data/<file>.csv | h10"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from .app import create_app
from .sources.base import Source
from .sources.replay import ReplaySource
from .sources.sim import SimSource

ROOT = Path(__file__).resolve().parent.parent


def build_source(spec: str, bpm: int, invert: bool) -> Source:
    if spec == "sim":
        return SimSource(bpm=bpm, invert=invert)
    if spec == "h10":
        from .sources.h10 import H10Source
        return H10Source(invert=invert)
    return ReplaySource(spec, invert=invert)


def parse_keep_until(value: str | None) -> datetime | None:
    """An ISO time; one without a zone is this machine's local time."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m backend", description="CardioView server")
    ap.add_argument("--source", default="sim", help="sim, h10, or a CSV path with time_s,ecg_uv")
    ap.add_argument("--bpm", type=int, default=72, help="simulated heart rate")
    ap.add_argument("--invert", action="store_true", help="flip the signal (strap worn upside down)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--keep-until", help="when saved sessions expire, e.g. 2026-10-11T12:00 (default: 24 hours from now)")
    ap.add_argument("--public-host", help="the address phones use for the LAN link (default: this machine's)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(build_source(args.source, args.bpm, args.invert), keep_until=parse_keep_until(args.keep_until),
                     public_host=args.public_host, port=args.port)
    print(f"CardioView: source {args.source}. Open http://localhost:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", ws="auto", log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python -m pytest backend/tests/test_app_sessions.py -q`
Expected: `6 passed` in about 15 s (one test runs a whole session through the real detector and analysis).

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes, Thomas's `test_app.py` included.

- [ ] **Step 8: Ignore sessions and secrets**

Append to `.gitignore`:

```text
sessions/
.env
```

Run: `git check-ignore sessions/x .env`
Expected: both paths printed.

- [ ] **Step 9: Update CLAUDE.md**

In `## Layout`, replace the code block with:

```
backend/    app.py (FastAPI, /ws, static files, session routes), pipeline.py, sources/ (base.py, sim.py, replay.py, h10.py),
            session.py (saved sessions), analysis.py (session summary), synth.py (synthetic sessions), tests/
frontend/   index.html, main.js, clock.js, chambers.js, heart.js, trace.js, style.css, vendor/, assets/ (heart model + heart.json)
tools/      h10_record.py (strap to CSV, no server), trim_csv.py, screenshot.mjs (headless check)
data/       ECG fixtures: CSV with header time_s,ecg_uv at 130 Hz, in microvolts
sessions/   saved visitor sessions, never committed (see Saved sessions)
```

In `## Messages`, add this line inside the json block after the `beat` line:

```json
{"type": "session", "state": "running", "id": "x7Qk...", "step": "breathe", "index": 2, "count": 5, "elapsed_s": 12.3, "length_s": 40, "paused": false}
```

and this paragraph after the paragraph that starts with "`t` is the stream time":

```markdown
`session` states are `idle` (with an optional `note`: `stopped` or `write_failed`), `running`, `analyzing` and `done` (with `link` and `online`). The backlog sends the current one right after the status.
```

Insert this section before `## Milestones`:

```markdown
## Saved sessions

Spec: `docs/superpowers/specs/2026-10-10-visitor-sessions-design.md`. Opt-in per visitor, measurements only.

- A session starts only from `POST /api/session/start`, sent after the visitor agreed; that is the consent, recorded in `session.json`. Cancel deletes everything.
- Steps: get ready (until the signal is clean for 5 s, at most 30 s), rest 30 s, breathe 40 s at 6 a minute, squats 20 s, recover 30 s. Step clocks count received samples, so a strap drop pauses them; 15 s without samples ends the session with the steps that finished.
- `backend/analysis.py` makes five sections: effort and recovery, breathing, heart rate variability, the average beat (waves labelled, no durations: the QRS onset moves 20 to 75 ms at 130 Hz) and beat timing. Each is values or a plain reason. No verdicts, no reference ranges.
- `sessions/<id>/` holds `ecg.csv` (replays with `--source`), `beats.csv`, `session.json` and `summary.json`. Never committed. Keep-until is 24 h by default (`--keep-until`); unfinished and expired sessions are deleted at startup.
```

Run: `wc -l CLAUDE.md`
Expected: under 200.

- [ ] **Step 10: Commit**

```bash
git add backend/app.py backend/__main__.py backend/tests/test_app_sessions.py requirements.txt .gitignore CLAUDE.md
git commit -m "Sessions in the server: routes, QR codes, demo summary, startup cleanup, keep-until" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The stage overlay

**Files:**
- Create: `frontend/session.js`, `frontend/session.css`
- Modify: `frontend/index.html` (3 small edits), `frontend/main.js` (5 small edits), `CLAUDE.md`

**Interfaces:**
- Consumes: the `session` messages and the start and cancel routes (Task 3); `reducedMotion` and `$` from `main.js`.
- Produces: `class SessionOverlay` with `handle(msg)`, `key(event) -> bool`, `frame(now)`. On `done` it opens `/s/<id>?screen=1` (Task 5) after the "All done" line has had 2.6 s. It plays `assets/voice/<key>.wav` (Task 6) for each step, `in` and `out` per breath, `done` and `stopped`; a missing file is silent.

- [ ] **Step 1: Make sure the viewer files are current**

Run: `git fetch origin && git diff HEAD origin/main --stat -- frontend/`
Expected: no output. If Thomas changed the viewer, run `git rebase origin/main` first, then check the snippets in Step 4 still match.

- [ ] **Step 2: Write `frontend/session.js`**

```js
// Saved visitor sessions on the stage: the operator's keys, the step prompt and countdown,
// the breathing ring and the voice. The server owns the session; this only shows it.

const PROMPT = {
  get_ready: 'Hold still while the signal settles',
  rest: 'Sit still and breathe normally',
  squats: 'Squats, keep going',
  recover: 'Stand still and catch your breath',
};
const NOTE = {
  stopped: 'Session stopped and deleted',
  write_failed: 'Could not save the session, nothing was kept',
};
const ARM_MS = 5000;        // a second S or Esc must come within this
const FLASH_MS = 4000;
const BREATH_S = 10;        // 5 s in, 5 s out: 6 breaths a minute
const VOICE_KEY = 'cardioview.voice';
const MIN_DONE_MS = 2600;   // let "All done" finish before the summary opens

function readVoice() {
  try { return localStorage.getItem(VOICE_KEY) !== 'off'; } catch { return true; }
}

function writeVoice(on) {
  try { localStorage.setItem(VOICE_KEY, on ? 'on' : 'off'); } catch { /* private window */ }
}

export class SessionOverlay {
  constructor({ box, prompt, sub, ring }, { reducedMotion = false } = {}) {
    this.box = box;
    this.prompt = prompt;
    this.sub = sub;
    this.ring = ring;
    this.reducedMotion = reducedMotion;
    this.msg = { state: 'idle' };
    this.at = 0;              // performance.now() when msg arrived
    this.armedS = 0;
    this.armedEsc = 0;
    this.flashText = '';
    this.flashUntil = 0;
    this.voiceOn = readVoice();
    this.clips = {};
    this.lastIndex = -1;
    this.lastBreath = '';
    this.analyzingAt = 0;
  }

  handle(msg) {
    const prev = this.msg;
    this.msg = msg;
    this.at = performance.now();
    if (msg.state === 'running' && msg.index !== this.lastIndex) {
      this.lastIndex = msg.index;
      this.lastBreath = '';
      this.say(msg.step);
    }
    if (msg.state === 'analyzing' && prev.state !== 'analyzing') {
      this.analyzingAt = performance.now();
      this.say('done');
    }
    if (msg.state === 'idle') {
      this.lastIndex = -1;
      if (msg.note && prev.state !== 'idle') {
        this.flash(NOTE[msg.note] || 'Session ended');
        if (msg.note === 'stopped') this.say('stopped');
      }
    }
    if (msg.state === 'done') {
      const wait = this.analyzingAt ? Math.max(0, MIN_DONE_MS - (performance.now() - this.analyzingAt)) : 0;
      setTimeout(() => location.assign(`/s/${encodeURIComponent(msg.id)}?screen=1`), wait);
    }
  }

  // true when the key belonged to the session controls
  key(e) {
    const k = e.key;
    const now = performance.now();
    const busy = this.msg.state === 'running' || this.msg.state === 'analyzing';
    if (k === 's' || k === 'S') {
      if (busy) { this.flash('A session is already running'); return true; }
      if (now - this.armedS < ARM_MS) {
        this.armedS = 0;
        this.post('/api/session/start');
      } else {
        this.armedS = now;
      }
      return true;
    }
    if (k === 'Escape') {
      if (this.armedS) { this.armedS = 0; return true; }
      if (!busy) return false;
      if (now - this.armedEsc < ARM_MS) {
        this.armedEsc = 0;
        this.post('/api/session/cancel');
      } else {
        this.armedEsc = now;
      }
      return true;
    }
    if (k === 'v' || k === 'V') {
      this.voiceOn = !this.voiceOn;
      writeVoice(this.voiceOn);
      this.flash(this.voiceOn ? 'Voice on' : 'Voice off');
      return true;
    }
    return false;
  }

  async post(path) {
    try {
      const res = await fetch(path, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        this.flash(body.reason || 'The server said no');
      }
    } catch {
      this.flash('Server offline');
    }
  }

  flash(text) {
    this.flashText = text;
    this.flashUntil = performance.now() + FLASH_MS;
  }

  say(key) {
    if (!this.voiceOn || !key) return;
    let clip = this.clips[key];
    if (!clip) {
      clip = new Audio(`assets/voice/${key}.wav`);
      this.clips[key] = clip;
    }
    clip.currentTime = 0;
    clip.play().catch(() => { /* no file yet, or no user gesture in this tab */ });
  }

  // the step clock between messages: it runs on while samples arrive and stops when paused
  elapsed(now) {
    const m = this.msg;
    if (m.state !== 'running') return 0;
    const extra = m.paused ? 0 : (now - this.at) / 1000;
    return Math.min(m.length_s, m.elapsed_s + extra);
  }

  frame(now) {
    const m = this.msg;
    let prompt = '';
    let sub = '';
    let ring = null;   // scale 0.7 to 1, or null to hide
    if (m.state === 'running') {
      const t = this.elapsed(now);
      if (m.step === 'breathe') {
        const phase = t % BREATH_S;
        const inhale = phase < BREATH_S / 2;
        const breath = inhale ? 'in' : 'out';
        if (breath !== this.lastBreath) {
          if (this.lastBreath) this.say(breath);
          this.lastBreath = breath;
        }
        const half = BREATH_S / 2;
        const p = inhale ? phase / half : 1 - (phase - half) / half;
        prompt = inhale ? 'Breathe in' : 'Breathe out';
        if (this.reducedMotion) {
          prompt += `, ${Math.ceil(half - (phase % half))}`;
        } else {
          ring = 0.7 + 0.3 * (0.5 - 0.5 * Math.cos(Math.PI * p));
        }
      } else {
        prompt = PROMPT[m.step] || '';
      }
      if (m.paused) sub = 'Paused, reconnecting to the strap';
      else if (m.step === 'get_ready') sub = 'Getting ready';
      else sub = `Step ${m.index} of ${m.count - 1}, ${Math.ceil(m.length_s - t)} s left`;
    } else if (m.state === 'analyzing') {
      prompt = 'Measuring your session';
      sub = 'A few seconds';
    }
    if (this.armedS && now - this.armedS < ARM_MS) {
      prompt = 'Visitor agreed to save this session?';
      sub = 'Press S again to start';
    } else if (this.armedEsc && now - this.armedEsc < ARM_MS) {
      sub = 'Press Esc again to stop and delete this session';
    }
    if (now < this.flashUntil) {
      if (prompt) sub = this.flashText;
      else prompt = this.flashText;
    }
    this.prompt.textContent = prompt;
    this.sub.textContent = sub;
    this.box.hidden = !prompt && !sub;
    if (ring === null) {
      this.ring.hidden = true;
    } else {
      this.ring.hidden = false;
      this.ring.style.transform = `translate(-50%, -50%) scale(${ring.toFixed(3)})`;
    }
  }
}
```

- [ ] **Step 3: Write `frontend/session.css`**

```css
/* saved sessions on the stage: one prompt line, one dim line, and the breathing ring behind the heart */
.session {
  position: absolute; left: 0; right: 0; top: 34px; z-index: 4; pointer-events: none;
  display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 0 var(--gutter);
}
.session-prompt { margin: 0; font-size: clamp(26px, 3.4vh, 36px); font-weight: 600; letter-spacing: -0.01em; }
.session-sub { margin: 0; font-size: 16px; color: var(--dim); }
.session-sub:empty { display: none; }
.session-ring {
  position: absolute; left: 50%; top: 46%; z-index: 0; pointer-events: none;
  width: min(84vh, 94%); aspect-ratio: 1; border-radius: 50%;   /* at 0.7 it still clears the heart */
  border: 2px solid rgba(232, 236, 243, 0.5);
  box-shadow: 0 0 80px rgba(232, 236, 243, 0.08) inset, 0 0 40px rgba(232, 236, 243, 0.06);
  transform: translate(-50%, -50%) scale(0.7);
}
```

- [ ] **Step 4: Hook it into the viewer**

In `frontend/index.html`:

1. After `<link rel="stylesheet" href="style.css">` add `<link rel="stylesheet" href="session.css">`.
2. After the floor line (the `<div class="floor" ...>` that ends with `<span class="ripple" id="ripple"></span></div>`) add:
   ```html
       <div class="session-ring" id="session-ring" hidden aria-hidden="true"></div>
   ```
3. Before `    <label class="opacity">` add:
   ```html
       <div class="session" id="session" hidden aria-live="polite"><p class="session-prompt" id="session-prompt"></p><p class="session-sub" id="session-sub"></p></div>
   ```

In `frontend/main.js`:

1. After `import { Heart } from './heart.js';` add `import { SessionOverlay } from './session.js';`.
2. After `heart.load();` add:
   ```js
   const session = new SessionOverlay(
     { box: $('session'), prompt: $('session-prompt'), sub: $('session-sub'), ring: $('session-ring') },
     { reducedMotion },
   );
   ```
3. In `handle(msg)`, after the `beat` branch, add:
   ```js
     } else if (msg.type === 'session') {
       session.handle(msg);
   ```
   so the chain ends `} else if (msg.type === 'beat') { lanes.push(msg); } else if (msg.type === 'session') { session.handle(msg); }`.
4. In `frame()`, after `placeFloor();` add `  session.frame(performance.now());`.
5. In the `keydown` listener, after `if (e.target instanceof HTMLInputElement) return;` add `  if (session.key(e)) return;   // S, Esc, V: saved sessions`.

Run: `node --check frontend/session.js && node --check frontend/main.js`
Expected: no output.

- [ ] **Step 5: See it on the stage**

Run the server in the background: `.venv/Scripts/python -m backend --source sim --host 127.0.0.1`

Then:

```bash
curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:8000/
curl -s -X POST http://127.0.0.1:8000/api/session/start
cd tools
CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe" WAIT_MS=12000 node screenshot.mjs http://127.0.0.1:8000/ out/rest.png
CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe" WAIT_MS=21000 node screenshot.mjs http://127.0.0.1:8000/ out/breathe.png
```

Expected: no `[pageerror]` lines. Open both images. `rest.png`: "Sit still and breathe normally" centered over the heart, "Step 1 of 4, N s left" under it, Thomas's labels and instruments unchanged. `breathe.png`: "Breathe in" or "Breathe out", "Step 2 of 4", and a clear ring around the heart.

Stop the server.

- [ ] **Step 6: Check the keys by hand**

In a real browser on `http://localhost:8000`: press S (the stage asks "Visitor agreed to save this session?"), S again (the session starts), Esc (it asks to press Esc again), Esc (it shows "Session stopped and deleted"), V (it shows "Voice off"). `python tools/sessions.py list` arrives in Task 8; until then `ls sessions` shows no folder for the stopped session.

- [ ] **Step 7: Update CLAUDE.md**

Add to the end of the `## Saved sessions` list:

```markdown
- Stage keys: S twice starts, Esc twice stops and deletes, V turns the voice on or off. `frontend/session.js` draws one prompt line, one dim line and a breathing ring behind the heart; nothing on the stage is clickable.
```

In `## Layout`, change the `frontend/` line to:

```
frontend/   index.html, main.js, clock.js, chambers.js, heart.js, trace.js, style.css, session.js/.css (stage overlay),
            vendor/, assets/ (heart model + heart.json)
```

- [ ] **Step 8: Commit**

```bash
git add frontend/session.js frontend/session.css frontend/index.html frontend/main.js CLAUDE.md
git commit -m "Stage: guided session overlay with prompt, countdown, breathing ring and S, Esc, V keys" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The summary page

**Files:**
- Create: `frontend/summary.html`, `frontend/summary.js`, `frontend/summary.css`
- Modify: `backend/tests/test_app_sessions.py` (one test appended), `CLAUDE.md`

**Interfaces:**
- Consumes: `GET /api/s/{sid}` (any host), `GET /api/s/{sid}/qr.svg`, `POST /api/session/dismiss` and the `session` messages (big screen only), `DELETE /api/s/{sid}` (phone).
- Produces: one page at `/s/<id>`; `?screen=1` adds the QR, Esc and a 3 minute return to live, and follows the booth's session state. Absolute URLs (`/summary.css`, `/summary.js`, `/vendor/fonts/...`) so the same files work under `/s/<id>` on the booth and on Vercel.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_app_sessions.py`:

```python
def test_summary_page_is_served_for_any_id(client):
    c, _, _ = client
    r = c.get("/s/demo")
    assert r.status_code == 200 and "/summary.js" in r.text
    assert c.get("/summary.css").status_code == 200
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_app_sessions.py -q -k summary_page`
Expected: FAIL, `RuntimeError: File at path ...summary.html does not exist.`

- [ ] **Step 3: Write `frontend/summary.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your heart, CardioView</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/summary.css">
</head>
<body>
<header class="top">
  <div class="brand">CardioView</div>
  <span class="meta" id="meta"></span>
</header>

<main class="sheet" id="sheet" hidden>
  <section class="block effort" id="effort">
    <h2>Effort and recovery</h2>
    <p class="text" id="effort-text"></p>
    <canvas class="chart" id="effort-chart"></canvas>
  </section>
  <section class="block breathing" id="breathing">
    <h2>Breathing</h2>
    <p class="text" id="breathing-text"></p>
    <canvas class="chart" id="breathing-chart"></canvas>
  </section>
  <section class="block hrv" id="hrv">
    <h2>Heart rate variability</h2>
    <p class="figure" id="hrv-figure"></p>
    <p class="text" id="hrv-text"></p>
  </section>
  <section class="block beat" id="beat">
    <h2>Your average heartbeat</h2>
    <canvas class="chart" id="beat-chart"></canvas>
    <p class="text" id="beat-text"></p>
  </section>
  <section class="block timing" id="timing">
    <h2>Beat timing</h2>
    <canvas class="chart" id="timing-chart"></canvas>
    <p class="text" id="timing-text"></p>
  </section>
  <aside class="take" id="take" hidden>
    <img id="qr" alt="QR code that opens this summary">
    <p id="qr-text">Scan to keep this on your phone</p>
    <p class="dim" id="until"></p>
  </aside>
  <footer class="foot">
    <p>A visualization, not a medical device. It does not diagnose anything.</p>
    <button type="button" id="delete" hidden>Delete my session</button>
  </footer>
</main>
<p class="gone" id="gone" hidden></p>
<script type="module" src="/summary.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `frontend/summary.css`**

```css
@font-face { font-family: "IBM Plex Sans"; font-weight: 400; font-style: normal; font-display: swap; src: url(/vendor/fonts/ibm-plex-sans-latin-400-normal.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 600; font-style: normal; font-display: swap; src: url(/vendor/fonts/ibm-plex-sans-latin-600-normal.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans Condensed"; font-weight: 700; font-style: normal; font-display: swap; src: url(/vendor/fonts/ibm-plex-sans-condensed-latin-700-normal.woff2) format("woff2"); }

:root {
  --ink: #070A12;
  --hair: rgba(232, 236, 243, 0.10);
  --text: #E8ECF3;
  --dim: #7F8AA0;
  --dimmer: #5A6478;
  --sans: "IBM Plex Sans", system-ui, sans-serif;
  --condensed: "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif;
  --gutter: 20px;
}

* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--ink); color: var(--text); font-family: var(--sans); font-size: 16px; line-height: 1.4;
  font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased;
}

.top { display: flex; align-items: baseline; gap: 20px; padding: 18px var(--gutter); border-bottom: 1px solid var(--hair); flex-wrap: wrap; }
.brand { font-weight: 600; font-size: 20px; letter-spacing: -0.01em; }
.meta { color: var(--dim); font-size: 15px; }

/* phone first: one column */
.sheet { display: grid; grid-template-columns: minmax(0, 1fr); }
.block { padding: 22px var(--gutter); border-bottom: 1px solid var(--hair); min-width: 0; }
.block h2 { margin: 0 0 8px; font-size: 15px; font-weight: 400; color: var(--dim); }
.text { margin: 0; }
.chart { display: block; width: 100%; height: 190px; margin-top: 12px; }
.timing .chart { height: 280px; }
.figure { margin: 0 0 6px; font-family: var(--condensed); font-weight: 700; font-size: 40px; line-height: 1.05; }
.block.refused .chart, .block.refused .figure { display: none; }
.block.refused .text { color: var(--dim); }
.take { display: none; }
.foot { padding: 22px var(--gutter) 40px; color: var(--dim); font-size: 14px; }
.foot p { margin: 0 0 18px; }
#delete {
  font: inherit; font-size: 15px; color: var(--text); background: transparent; cursor: pointer;
  border: 1px solid rgba(232, 236, 243, 0.3); border-radius: 6px; padding: 10px 16px;
}
#delete:focus-visible { outline: 2px solid var(--dim); outline-offset: 3px; }
.gone { margin: 22vh var(--gutter) 0; text-align: center; color: var(--dim); font-size: 18px; }
.dim { color: var(--dim); }

/* the big screen: effort across the top, four columns under it, the QR on the right */
body.screen { height: 100vh; overflow: hidden; display: flex; flex-direction: column; font-size: 17px; }
body.screen .top { flex: 0 0 64px; align-items: center; padding: 0 40px; }
body.screen .brand { font-size: 22px; }
body.screen .sheet {
  flex: 1 1 auto; min-height: 0; padding: 0 40px;
  grid-template-columns: repeat(4, minmax(0, 1fr)) 330px;
  grid-template-rows: minmax(0, 1.05fr) minmax(0, 1fr) auto;
}
body.screen .block { display: flex; flex-direction: column; padding: 24px 28px 22px 0; border-bottom: 0; }
body.screen .block + .block { padding-left: 28px; border-left: 1px solid var(--hair); }
body.screen .effort { grid-column: 1 / 5; grid-row: 1; border-bottom: 1px solid var(--hair); }
body.screen .block.breathing { grid-column: 1; grid-row: 2; border-left: 0; padding-left: 0; }
body.screen .hrv { grid-column: 2; grid-row: 2; }
body.screen .beat { grid-column: 3; grid-row: 2; }
body.screen .timing { grid-column: 4; grid-row: 2; }
body.screen .chart { flex: 1 1 auto; min-height: 0; height: auto; }
body.screen .figure { font-size: 64px; }
body.screen .take {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center;
  grid-column: 5; grid-row: 1 / 3; padding-left: 36px; border-left: 1px solid var(--hair);
}
body.screen .take img { width: 264px; height: 264px; border-radius: 6px; }
body.screen .take p { margin: 0; }
body.screen .foot { grid-column: 1 / 6; grid-row: 3; padding: 12px 0 18px; border-top: 1px solid var(--hair); }
body.screen .foot p { margin: 0; }
body.screen #delete { display: none; }
[hidden] { display: none !important; }
```

- [ ] **Step 5: Write `frontend/summary.js`**

```js
// One summary page for the big screen (?screen=1), a phone on the booth Wi-Fi, and the public link.
// It reads /api/s/<id> from whichever server sent it and draws every chart on canvas.

const $ = (id) => document.getElementById(id);
const sid = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
const screenMode = new URLSearchParams(location.search).has('screen');
const C = { text: '#E8ECF3', dim: '#7F8AA0', dimmer: '#5A6478', hair: 'rgba(232, 236, 243, 0.10)', ecg: '#43E0A0' };
const FONT = '13px "IBM Plex Sans", system-ui, sans-serif';
const STEP_NAME = { rest: 'Rest', breathe: 'Breathe', squats: 'Squats', recover: 'Recover' };
const IDLE_MS = 180000;   // the big screen goes back to live after 3 minutes
const GONE = 'This session is no longer available.';

let summary = null;
if (screenMode) document.body.classList.add('screen');

const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const day = (iso) => `${new Date(iso).toLocaleDateString([], { weekday: 'short' })} ${time(iso)}`;
const scale = (lo, hi, a, b) => (v) => a + ((v - lo) * (b - a)) / ((hi - lo) || 1);

function canvas2d(el) {
  const r = el.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  el.width = Math.max(1, Math.round(r.width * dpr));
  el.height = Math.max(1, Math.round(r.height * dpr));
  const g = el.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.font = FONT;
  return { g, w: r.width, h: r.height };
}

function hline(g, x0, x1, y) { g.beginPath(); g.moveTo(x0, y); g.lineTo(x1, y); g.stroke(); }
function vline(g, x, y0, y1) { g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y1); g.stroke(); }

// a polyline that lifts the pen over missing values
function trace(g, values, x, y, color, width) {
  g.strokeStyle = color;
  g.lineWidth = width;
  g.lineJoin = 'round';
  g.beginPath();
  let pen = false;
  values.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    if (pen) g.lineTo(x(i), y(v)); else g.moveTo(x(i), y(v));
    pen = true;
  });
  g.stroke();
}

function bpmAxis(g, lo, hi, y, x0, x1) {
  g.strokeStyle = C.hair;
  g.lineWidth = 1;
  g.fillStyle = C.dimmer;
  for (let v = Math.ceil(lo / 20) * 20; v <= hi; v += 20) {
    hline(g, x0, x1, y(v));
    g.fillText(String(v), 0, y(v) + 4);
  }
}

function effortChart(s) {
  const bpm = s.hr_chart?.bpm || [];
  const vals = bpm.filter((v) => v != null);
  if (vals.length < 0.5 * bpm.length || vals.length < 2) {   // mostly gaps: a chart would only show noise
    $('effort-chart').hidden = true;
    return;
  }
  const { g, w, h } = canvas2d($('effort-chart'));
  const lo = Math.floor(Math.min(...vals) / 10) * 10 - 5;
  const hi = Math.ceil(Math.max(...vals) / 10) * 10 + 5;
  const pad = { l: 36, r: 10, t: 24, b: 6 };
  const x = scale(0, bpm.length - 1, pad.l, w - pad.r);
  const y = scale(lo, hi, h - pad.b, pad.t);
  bpmAxis(g, lo, hi, y, pad.l, w - pad.r);
  for (const st of s.steps || []) {
    if (!STEP_NAME[st.name]) continue;
    const xs = x(Math.min(st.start, bpm.length - 1));
    g.strokeStyle = C.hair;
    vline(g, xs, 4, h - pad.b);
    g.fillStyle = C.dim;
    g.fillText(STEP_NAME[st.name], xs + 6, 15);
  }
  trace(g, bpm, x, y, C.text, 2);
  if (s.effort?.ok) {
    const i = bpm.indexOf(Math.max(...vals));
    g.fillStyle = C.text;
    g.beginPath(); g.arc(x(i), y(bpm[i]), 4, 0, 2 * Math.PI); g.fill();
    g.fillText(`Peak ${s.effort.peak_bpm}`, Math.min(x(i) + 8, w - 70), y(bpm[i]) + 4);
  }
}

function breathingChart(s) {
  const bpm = s.breathing?.chart?.bpm || [];
  const vals = bpm.filter((v) => v != null);
  if (vals.length < 2) return;
  const { g, w, h } = canvas2d($('breathing-chart'));
  const step = s.breathing.chart.step_s;
  const lo = Math.floor(Math.min(...vals) / 5) * 5 - 2;
  const hi = Math.ceil(Math.max(...vals) / 5) * 5 + 2;
  const pad = { l: 36, r: 6, t: 20, b: 6 };
  const x = scale(0, bpm.length - 1, pad.l, w - pad.r);
  const y = scale(lo, hi, h - pad.b, pad.t);
  bpmAxis(g, lo, hi, y, pad.l, w - pad.r);
  const perBreath = Math.round(10 / step);
  for (let i = 0; i < bpm.length; i += perBreath) {
    g.strokeStyle = C.hair;
    vline(g, x(i), 4, h - pad.b);
    g.fillStyle = C.dimmer;
    g.fillText('in', x(i) + 4, 14);
    if (i + perBreath / 2 < bpm.length) g.fillText('out', x(i + perBreath / 2) + 4, 14);
  }
  trace(g, bpm, x, y, C.text, 2);
}

function beatChart(s) {
  const b = s.beat;
  const { g, w, h } = canvas2d($('beat-chart'));
  const n = b.uv.length;
  const t = (i) => b.t0 + i / b.fs;
  const lo = Math.min(...b.uv);
  const hi = Math.max(...b.uv);
  const pad = { l: 6, r: 6, t: 26, b: 8 };
  const x = scale(t(0), t(n - 1), pad.l, w - pad.r);
  const y = scale(lo - 0.05 * (hi - lo), hi, h - pad.b, pad.t);
  g.strokeStyle = C.hair;
  hline(g, pad.l, w - pad.r, y(0));
  const xi = (i) => x(t(i));
  trace(g, b.uv, xi, y, C.ecg, 2.2);
  g.fillStyle = C.text;
  g.textAlign = 'center';
  for (const [name, at] of [['P', b.waves.p], ['QRS', b.waves.qrs], ['T', b.waves.t]]) {
    if (at == null) continue;
    const i = Math.round((at - b.t0) * b.fs);
    const near = b.uv.slice(Math.max(0, i - 5), i + 6);
    g.fillText(name, x(at), y(Math.max(...near)) - 10);
  }
  g.textAlign = 'start';
}

function timingChart(s) {
  const rest = s.timing.rest || [];
  const breathe = s.timing.breathe || [];
  const all = rest.concat(breathe).flat();
  const { g, w, h } = canvas2d($('timing-chart'));
  const lo = Math.min(...all) - 0.05;
  const hi = Math.max(...all) + 0.05;
  const side = Math.min(w, h);
  const ox = (w - side) / 2;
  const x = scale(lo, hi, ox + 24, ox + side - 6);
  const y = scale(lo, hi, side - 22, 6);
  g.strokeStyle = C.hair;
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(x(lo), y(lo)); g.lineTo(x(hi), y(hi)); g.stroke();
  for (const [pts, color] of [[breathe, C.dim], [rest, C.text]]) {
    g.fillStyle = color;
    for (const [a, b] of pts) { g.beginPath(); g.arc(x(a), y(b), 3, 0, 2 * Math.PI); g.fill(); }
  }
  g.fillStyle = C.dimmer;
  g.fillText('gap before', x(lo), side - 4);
  g.save(); g.translate(ox + 12, y(lo)); g.rotate(-Math.PI / 2); g.fillText('gap after', 0, 0); g.restore();
  g.fillStyle = C.text; g.fillText('Rest', ox + 30, 16);   // top left stays empty: dots hug the diagonal
  g.fillStyle = C.dim; g.fillText('Slow breathing', ox + 30, 32);
}

function refuse(block, reason) {
  $(block).classList.add('refused');
  $(`${block}-text`).textContent = reason;
}

function render(s) {
  const minutes = Math.max(1, Math.round((s.steps?.at(-1)?.end || 60) / 60));
  $('meta').textContent = s.demo
    ? 'Demo session, synthetic data'
    : `Your session, ${minutes} min, ${time(s.created)}${s.ended_early ? ', ended early' : ''}`;
  $('until').textContent = s.demo ? '' : `Available until ${day(s.keep_until)}`;

  const e = s.effort;
  if (!e.ok) $('effort-text').textContent = e.reason;
  else if (e.peak_bpm - e.rest_bpm < 10) $('effort-text').textContent = `Resting ${e.rest_bpm} bpm. Your heart rate stayed close to that during squats (peak ${e.peak_bpm} bpm).`;
  else $('effort-text').textContent = `Resting ${e.rest_bpm} bpm. Peak ${e.peak_bpm} bpm during squats. Dropped ${e.drop_bpm} bpm in the 30 s after.`;

  const br = s.breathing;
  if (br.ok) {
    const parts = [];
    if (br.rest_per_min != null) parts.push(`At rest you breathed about ${br.rest_per_min} times a minute (estimated from the ECG).`);
    if (br.swing_bpm != null) parts.push(`Breathing slowly, your heart rate rose and fell by about ${br.swing_bpm} bpm with each breath.`);
    if (br.paced_per_min != null) parts.push(`Measured breathing pace ${br.paced_per_min} a minute; the ring paced 6.`);
    $('breathing-text').textContent = parts.join(' ');
  } else refuse('breathing', br.reason);

  const v = s.hrv;
  if (v.ok) {
    $('hrv-figure').textContent = `${v.rmssd_ms} ms`;
    $('hrv-text').textContent = `RMSSD over ${v.window_s} s at rest, with SDNN ${v.sdnn_ms} ms. Both describe how much the time between beats changes from beat to beat.`;
  } else refuse('hrv', v.reason);

  const b = s.beat;
  if (b.ok) $('beat-text').textContent = `Averaged from ${b.n} beats. P wave: the atria contract. QRS: the ventricles contract. T wave: the ventricles relax.`;
  else refuse('beat', b.reason);

  const tm = s.timing;
  if (tm.ok) $('timing-text').textContent = 'Each dot is one beat: the gap before it against the gap after it. Steady timing makes a tight cluster; slow breathing stretches it along the diagonal.';
  else refuse('timing', tm.reason);

  $('sheet').hidden = false;
  draw(s);
  if (!screenMode && !s.demo) $('delete').hidden = false;
}

function draw(s) {
  effortChart(s);
  if (s.breathing.ok) breathingChart(s);
  if (s.beat.ok) beatChart(s);
  if (s.timing.ok) timingChart(s);
}

function gone(text) {
  $('sheet').hidden = true;
  $('gone').textContent = text;
  $('gone').hidden = false;
}

async function load() {
  let res = null;
  try { res = await fetch(`/api/s/${encodeURIComponent(sid)}`, { cache: 'no-store' }); } catch { /* offline */ }
  if (!res || !res.ok) { gone(res ? GONE : 'Could not reach the booth. Try again on the same Wi-Fi.'); return; }
  summary = await res.json();
  render(summary);
}

let armed = false;
$('delete').addEventListener('click', async () => {
  const btn = $('delete');
  if (!armed) {
    armed = true;
    btn.textContent = 'Tap again to delete';
    setTimeout(() => { armed = false; btn.textContent = 'Delete my session'; }, 5000);
    return;
  }
  const res = await fetch(`/api/s/${encodeURIComponent(sid)}`, { method: 'DELETE' }).catch(() => null);
  if (res && res.ok) gone('Deleted. Nothing from this session is kept.');
  else btn.textContent = 'Could not delete, try again';
});

window.addEventListener('resize', () => { if (summary) draw(summary); });

// big screen: the QR, back to live on Esc or after a while, and follow the booth's session state
function backToLive() {
  fetch('/api/session/dismiss', { method: 'POST' }).catch(() => {}).finally(() => location.assign('/'));
}

if (screenMode) {
  $('take').hidden = false;
  $('qr').src = `/api/s/${encodeURIComponent(sid)}/qr.svg`;
  setTimeout(backToLive, IDLE_MS);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') backToLive(); });
  let ours = false;   // seen this session on the booth; leave once it is dismissed, deleted or replaced
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type !== 'session') return;
    if (msg.state === 'done' && msg.id === sid) {
      ours = true;
      $('qr').src = `/api/s/${encodeURIComponent(sid)}/qr.svg?v=${Date.now()}`;
      $('qr-text').textContent = msg.online ? 'Scan to keep this on your phone' : 'Scan on the booth Wi-Fi to keep this on your phone';
    } else if (msg.state === 'running' || (ours && msg.state === 'idle')) {
      location.assign('/');
    }
  };
}

load();
```

Run: `node --check frontend/summary.js && .venv/Scripts/python -m pytest backend/tests/test_app_sessions.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Screenshot the demo and a refused session**

Start the server in the background (`.venv/Scripts/python -m backend --source sim --host 127.0.0.1`). Make a session whose every section is refused:

```bash
.venv/Scripts/python -c "
from datetime import timedelta
import numpy as np
from backend.analysis import analyze
from backend.session import SessionStore, utcnow
from backend.synth import synth_session
ses = synth_session(seed=1)
noise = np.round(np.random.default_rng(0).normal(0, 300, len(ses.uv))).astype(int)
s = analyze(ses.t, noise, ses.steps)
store = SessionStore('sessions'); sid = store.new_id(); now = utcnow(); until = (now + timedelta(days=1)).isoformat()
store.create(sid, {'id': sid, 'state': 'done', 'created': now.isoformat(), 'keep_until': until})
s.update(id=sid, created=now.isoformat(), keep_until=until, source='simulated', ended_early=False)
store.write_summary(sid, s); print(sid)
"
```

Then, with `C="C:/Program Files/Google/Chrome/Application/chrome.exe"` and `<sid>` the printed id:

```bash
cd tools
CHROME="$C" WAIT_MS=3000 node screenshot.mjs "http://127.0.0.1:8000/s/demo?screen=1" out/summary-screen.png
CHROME="$C" WAIT_MS=3000 W=390 H=1500 node screenshot.mjs http://127.0.0.1:8000/s/demo out/summary-phone.png
CHROME="$C" WAIT_MS=3000 W=390 H=900 node screenshot.mjs http://127.0.0.1:8000/s/<sid> out/summary-refused.png
```

Expected: no `[pageerror]` lines. `summary-screen.png`: "Demo session, synthetic data"; the effort chart rises to "Peak 139" in squats; four columns (breathing with in and out marks, "4x ms" variability, the green averaged beat with P, QRS and T, the dot plot with its legend top left); the QR on the right. `summary-phone.png`: the same sections stacked, no QR, no delete button (demo). `summary-refused.png`: five dim reasons, no charts, a "Delete my session" button.

Delete the refused session: `rm -r sessions/<sid>`.

- [ ] **Step 7: Run one whole session and watch the hand-off**

```bash
curl -s -X POST http://127.0.0.1:8000/api/session/start
cd tools
CHROME="$C" WAIT_MS=140000 node screenshot.mjs http://127.0.0.1:8000/ out/handoff.png
```

Expected: the viewer opened the summary by itself. `handoff.png` shows "Your session, 2 min, <time>", the QR, and the caption "Scan on the booth Wi-Fi to keep this on your phone" (no cloud yet). With the simulated source nobody does squats, so the effort line reads "Your heart rate stayed close to that during squats".

- [ ] **Step 8: Delete it while the big screen shows it**

With `<sid>` from Step 7 (`ls sessions`):

```bash
node -e "setTimeout(() => fetch('http://127.0.0.1:8000/api/s/<sid>', { method: 'DELETE' }).then(r => console.log('delete', r.status)), 3000)" &
CHROME="$C" WAIT_MS=8000 node screenshot.mjs "http://127.0.0.1:8000/s/<sid>?screen=1" out/after-delete.png
```

Expected: `delete 200`, and `after-delete.png` shows the live viewer, not the summary. Stop the server.

- [ ] **Step 9: Update CLAUDE.md**

Add to the end of the `## Saved sessions` list:

```markdown
- The summary page (`frontend/summary.html`) serves the big screen (`/s/<id>?screen=1`, with the QR), phones on the LAN and the public copy in `cloud/`. `/s/demo` is a synthetic session for screenshots.
```

and change the `frontend/` Layout lines to:

```
frontend/   index.html, main.js, clock.js, chambers.js, heart.js, trace.js, style.css, session.js/.css (stage overlay),
            summary.html/.js/.css (summary page), vendor/, assets/ (heart model + heart.json)
```

- [ ] **Step 10: Commit**

```bash
git add frontend/summary.html frontend/summary.js frontend/summary.css backend/tests/test_app_sessions.py CLAUDE.md
git commit -m "Summary page for the big screen, phones and the public link" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The voice coach

**Files:**
- Create: `tools/make_voice.py`, `tools/requirements-voice.txt`, `frontend/assets/voice/*.wav` (9 files)
- Modify: `.gitignore`, `CLAUDE.md`

**Interfaces:**
- Consumes: nothing from the app. `session.js` (Task 4) already asks for `assets/voice/<key>.wav` with keys `get_ready`, `rest`, `breathe`, `in`, `out`, `squats`, `recover`, `done`, `stopped`.
- Produces: the nine WAV files.

- [ ] **Step 1: A separate environment for the tool**

```bash
py -3.12 -m venv .venv-voice
```

Append `.venv-voice/` to `.gitignore`. Create `tools/requirements-voice.txt`:

```text
kokoro==0.9.4
soundfile==0.14.0
```

Run: `.venv-voice/Scripts/pip install -r tools/requirements-voice.txt`
Expected: installs kokoro, misaki, torch and transformers (several minutes, a few hundred MB). If misaki stops for espeak-ng, install eSpeak NG from its GitHub releases page (the Windows MSI) and run the command again.

- [ ] **Step 2: Write `tools/make_voice.py`**

```python
"""Render the session voice lines once with Kokoro 82M from Hugging Face. The WAV files are committed,
so the booth needs neither the model nor the internet.

    py -3.12 -m venv .venv-voice                      (kokoro needs Python 3.10 to 3.12)
    .venv-voice/Scripts/pip install -r tools/requirements-voice.txt       (Mac, Linux: .venv-voice/bin/pip)
    .venv-voice/Scripts/python tools/make_voice.py

Model: hexgrad/Kokoro-82M on Hugging Face, Apache 2.0. Voice af_heart, 24 kHz mono.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

OUT = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "voice"
RATE = 24000
VOICE = "af_heart"
LINES = {
    "get_ready": "Hold still while we get a clean signal.",
    "rest": "Sit still and breathe normally.",
    "breathe": "Now breathe with the ring.",
    "in": "In.",
    "out": "Out.",
    "squats": "Squats. Keep going.",
    "recover": "Stop. Stand still and catch your breath.",
    "done": "All done. Here is your heart.",
    "stopped": "Session stopped and deleted.",
}


def render(pipe: KPipeline, text: str) -> np.ndarray:
    parts = []
    for result in pipe(text, voice=VOICE):
        audio = result.audio
        parts.append(audio.cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio))
    return np.concatenate(parts).astype(np.float32)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code="a")   # American English
    for key, text in LINES.items():
        audio = render(pipe, text)
        sf.write(OUT / f"{key}.wav", audio, RATE, subtype="PCM_16")
        print(f"{key + '.wav':<14} {len(audio) / RATE:4.1f} s  {text}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Render the lines**

Run: `.venv-voice/Scripts/python tools/make_voice.py`
Expected: the first run downloads `hexgrad/Kokoro-82M` from Hugging Face, then nine lines like `rest.wav        1.9 s  Sit still and breathe normally.`, each between 0.3 and 4 s.

- [ ] **Step 4: Check the booth serves them**

With the server running: `for k in get_ready rest breathe in out squats recover done stopped; do curl -s -o /dev/null -w "$k %{http_code}\n" http://127.0.0.1:8000/assets/voice/$k.wav; done`
Expected: nine lines ending in `200`. Then by ear in a real browser: S, S, and the voice reads each step; V silences it.

- [ ] **Step 5: Update CLAUDE.md**

Add to the end of the `## Saved sessions` list:

```markdown
- Voice: `tools/make_voice.py` renders the step lines once with Kokoro 82M from Hugging Face (Python 3.12, its own `.venv-voice`); the WAVs in `frontend/assets/voice/` are committed, so the booth needs neither the model nor the internet.
```

- [ ] **Step 6: Commit**

```bash
git add tools/make_voice.py tools/requirements-voice.txt frontend/assets/voice .gitignore CLAUDE.md
git commit -m "Voice coach: step lines rendered with Kokoro 82M from Hugging Face" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Neon sync

**Files:**
- Create: `backend/cloud.py`
- Modify: `backend/__main__.py` (replace with the version below), `requirements.txt`, `CLAUDE.md`
- Test: `backend/tests/test_cloud.py`

**Interfaces:**
- Consumes: `SessionManager.delete`, `.update_link`, `.store` and `SessionStore` (Task 2); `create_app(..., cloud=...)` (Task 3).
- Produces:
  - `load_env(path)`, `SCHEMA` (the `session_summary` table), `NeonDb(dsn)` with `upsert`, `tombstones`, `remove`, `remove_expired`, `remove_all`.
  - `Cloud(db, public_url)`: `from_env()` (None unless `NEON_DATABASE_URL` and `CARDIOVIEW_PUBLIC_URL` are both set), `link(sid)`, `async publish(sid, summary, keep_until) -> str`, `async unpublish(sid)`, `async sync_once(manager)`, `async run(manager)` (every 30 s).

- [ ] **Step 1: Add psycopg**

Add `psycopg[binary]==3.3.6` to `requirements.txt` after `segno==1.6.6`, then `.venv/Scripts/pip install -r requirements.txt`.
Expected: `psycopg-3.3.6` and `psycopg-binary-3.3.6` installed (wheels exist for Windows Python 3.12 and macOS arm64 Python 3.14).

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_cloud.py`:

```python
"""Neon sync with a fake database: publish, retries, phone deletes, expiry, off without settings."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.cloud import Cloud, load_env
from backend.session import SessionManager, SessionStore

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self, fail=False):
        self.rows: dict[str, dict] = {}
        self.fail = fail
        self.expired_sweeps = 0

    def _check(self):
        if self.fail:
            raise ConnectionError("no route to Neon")

    def upsert(self, sid, keep_until, summary_json):
        self._check()
        row = self.rows.get(sid)
        if row and row["deleted_at"]:
            return
        self.rows[sid] = {"keep_until": keep_until, "summary": json.loads(summary_json), "deleted_at": None}

    def tombstones(self):
        self._check()
        return [sid for sid, r in self.rows.items() if r["deleted_at"]]

    def remove(self, sid):
        self._check()
        self.rows.pop(sid, None)

    def remove_expired(self):
        self._check()
        self.expired_sweeps += 1
        return 0

    def remove_all(self):
        n = len(self.rows)
        self.rows.clear()
        return n


def finished_session(store, published=False):
    sid = store.new_id()
    store.create(sid, {"id": sid, "state": "done", "keep_until": (T0 + timedelta(days=1)).isoformat(),
                       "published": published})
    store.write_summary(sid, {"version": 1, "id": sid})
    return sid


def manager_for(tmp_path, cloud):
    return SessionManager(SessionStore(tmp_path), analyze=lambda *a: {}, publish=cloud.publish,
                          unpublish=cloud.unpublish, keep_until=T0 + timedelta(days=1), wall=lambda: T0)


def test_publish_returns_the_public_link_and_stores_the_summary():
    db = FakeDb()
    cloud = Cloud(db, "https://cardioview.example/")
    link = asyncio.run(cloud.publish("x" * 22, {"version": 1}, T0))
    assert link == "https://cardioview.example/s/" + "x" * 22
    assert db.rows["x" * 22]["summary"] == {"version": 1}


def test_publish_refuses_nan():
    cloud = Cloud(FakeDb(), "https://c")
    with pytest.raises(ValueError):
        asyncio.run(cloud.publish("x" * 22, {"v": float("nan")}, T0))


def test_sync_publishes_what_was_missed_and_updates_the_screen(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    db = FakeDb()
    cloud = Cloud(db, "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store)
    m.state, m.sid, m.done_link = "done", sid, f"http://booth/s/{sid}"
    asyncio.run(cloud.sync_once(m))
    assert sid in db.rows and m.store.read_meta(sid)["published"] is True
    assert m.message()["link"] == f"https://c/s/{sid}" and m.message()["online"] is True
    assert db.expired_sweeps == 1


def test_sync_applies_deletes_made_on_phones(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    db = FakeDb()
    cloud = Cloud(db, "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store, published=True)
    db.rows[sid] = {"keep_until": T0, "summary": None, "deleted_at": T0}
    asyncio.run(cloud.sync_once(m))
    assert not (tmp_path / sid).exists() and sid not in db.rows


def test_sync_failure_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    cloud = Cloud(FakeDb(fail=True), "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store)
    with pytest.raises(ConnectionError):
        asyncio.run(cloud.sync_once(m))
    assert m.store.read_meta(sid)["published"] is False


def test_off_without_both_settings(monkeypatch):
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("CARDIOVIEW_PUBLIC_URL", raising=False)
    assert Cloud.from_env() is None
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://u:p@h/db")
    assert Cloud.from_env() is None
    monkeypatch.setenv("CARDIOVIEW_PUBLIC_URL", "https://c")
    assert Cloud.from_env() is not None


def test_load_env_reads_pairs_and_keeps_what_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEP_ME", "outer")
    monkeypatch.delenv("NEW_ONE", raising=False)
    p = tmp_path / ".env"
    p.write_text("# comment\nNEW_ONE='postgresql://a:b@c/d?sslmode=require'\nKEEP_ME=inner\n\nJUNK\n")
    load_env(p)
    import os
    assert os.environ["NEW_ONE"] == "postgresql://a:b@c/d?sslmode=require"
    assert os.environ["KEEP_ME"] == "outer"
```

- [ ] **Step 3: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_cloud.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'backend.cloud'`.

- [ ] **Step 4: Write `backend/cloud.py`**

```python
"""Neon sync: anonymous summaries go up so the QR link works on any network.

Off unless NEON_DATABASE_URL and CARDIOVIEW_PUBLIC_URL are set. It never blocks
the booth: every call has a timeout, and a failure only means the QR keeps the
LAN link until a retry gets through. The raw ECG never leaves the laptop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .session import utcnow

log = logging.getLogger("cardioview.cloud")

TIMEOUT_S = 4.0
SYNC_EVERY_S = 30.0

SCHEMA = """
create table if not exists session_summary (
  id text primary key,
  created_at timestamptz not null default now(),
  keep_until timestamptz not null,
  summary jsonb,
  deleted_at timestamptz
);
"""


def load_env(path: Path) -> None:
    """KEY=value lines from a local .env into the environment, without overriding what is set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class NeonDb:
    """The statements the booth needs, each on its own short connection."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _run(self, sql: str, params: tuple = (), fetch: bool = False):
        import psycopg   # imported here so a booth without the cloud never loads it
        with psycopg.connect(self.dsn, connect_timeout=int(TIMEOUT_S)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if fetch else cur.rowcount

    def upsert(self, sid: str, keep_until: datetime, summary_json: str) -> None:
        self._run(
            "insert into session_summary (id, keep_until, summary) values (%s, %s, %s::jsonb) "
            "on conflict (id) do update set keep_until = excluded.keep_until, summary = excluded.summary "
            "where session_summary.deleted_at is null",
            (sid, keep_until, summary_json))

    def tombstones(self) -> list[str]:
        return [r[0] for r in self._run("select id from session_summary where deleted_at is not null", fetch=True)]

    def remove(self, sid: str) -> None:
        self._run("delete from session_summary where id = %s", (sid,))

    def remove_expired(self) -> int:
        return self._run("delete from session_summary where keep_until <= now()")

    def remove_all(self) -> int:
        return self._run("delete from session_summary")


class Cloud:
    """What the session manager and the server need from Neon: publish, unpublish and a sync loop."""

    def __init__(self, db, public_url: str, every_s: float = SYNC_EVERY_S):
        self.db = db
        self.public_url = public_url.rstrip("/")
        self.every_s = every_s

    @classmethod
    def from_env(cls) -> "Cloud | None":
        dsn, url = os.environ.get("NEON_DATABASE_URL"), os.environ.get("CARDIOVIEW_PUBLIC_URL")
        if not dsn or not url:
            return None
        return cls(NeonDb(dsn), url)

    def link(self, sid: str) -> str:
        return f"{self.public_url}/s/{sid}"

    async def _call(self, fn, *args):
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), TIMEOUT_S)

    async def publish(self, sid: str, summary: dict, keep_until: datetime) -> str:
        await self._call(self.db.upsert, sid, keep_until, json.dumps(summary, allow_nan=False))
        return self.link(sid)

    async def unpublish(self, sid: str) -> None:
        await self._call(self.db.remove, sid)

    async def sync_once(self, manager) -> None:
        """Apply deletes made on phones, drop expired rows, and publish what an earlier try missed."""
        for sid in await self._call(self.db.tombstones):
            await manager.delete(sid)
        await self._call(self.db.remove_expired)
        store, now = manager.store, utcnow()
        for sid in store.ids():
            meta = store.read_meta(sid)
            if not meta or meta.get("state") != "done" or meta.get("published"):
                continue
            summary = store.summary(sid, now)
            if summary is None:
                continue
            link = await self.publish(sid, summary, datetime.fromisoformat(meta["keep_until"]))
            meta["published"] = True
            store.write_meta(sid, meta)
            manager.update_link(sid, link)

    async def run(self, manager) -> None:
        while True:
            try:
                await self.sync_once(manager)
            except Exception as e:
                log.info("cloud sync skipped: %s", e)
            await asyncio.sleep(self.every_s)
```

- [ ] **Step 5: Turn it on from the command line**

Replace `backend/__main__.py` with:

```python
"""Run the CardioView server: python -m backend --source sim | data/<file>.csv | h10"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from .app import create_app
from .cloud import Cloud, load_env
from .sources.base import Source
from .sources.replay import ReplaySource
from .sources.sim import SimSource

ROOT = Path(__file__).resolve().parent.parent


def build_source(spec: str, bpm: int, invert: bool) -> Source:
    if spec == "sim":
        return SimSource(bpm=bpm, invert=invert)
    if spec == "h10":
        from .sources.h10 import H10Source
        return H10Source(invert=invert)
    return ReplaySource(spec, invert=invert)


def parse_keep_until(value: str | None) -> datetime | None:
    """An ISO time; one without a zone is this machine's local time."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m backend", description="CardioView server")
    ap.add_argument("--source", default="sim", help="sim, h10, or a CSV path with time_s,ecg_uv")
    ap.add_argument("--bpm", type=int, default=72, help="simulated heart rate")
    ap.add_argument("--invert", action="store_true", help="flip the signal (strap worn upside down)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--keep-until", help="when saved sessions expire, e.g. 2026-10-11T12:00 (default: 24 hours from now)")
    ap.add_argument("--public-host", help="the address phones use for the LAN link (default: this machine's)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env(ROOT / ".env")
    cloud = Cloud.from_env()
    app = create_app(build_source(args.source, args.bpm, args.invert), keep_until=parse_keep_until(args.keep_until),
                     public_host=args.public_host, port=args.port, cloud=cloud)
    print(f"CardioView: source {args.source}. Open http://localhost:{args.port}", flush=True)
    if cloud is not None:
        print(f"Saved sessions publish to {cloud.public_url}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", ws="auto", log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes (`test_cloud.py`: 7 passed).

- [ ] **Step 7: Update CLAUDE.md**

Add to the end of the `## Saved sessions` list:

```markdown
- Cloud is optional: with `NEON_DATABASE_URL` and `CARDIOVIEW_PUBLIC_URL` in `.env`, the anonymous summary (never the ECG) goes to Neon and the QR opens the Vercel page in `cloud/`. Offline or without them, the QR is the LAN link; a sync loop retries every 30 s and applies deletes made on phones.
```

and add `cloud.py (Neon sync), ` before `tests/` on the second `backend/` Layout line.

- [ ] **Step 8: Commit**

```bash
git add backend/cloud.py backend/tests/test_cloud.py backend/__main__.py requirements.txt CLAUDE.md
git commit -m "Neon sync: publish anonymous summaries, retry, apply phone deletes, drop expired rows" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The sessions command

**Files:**
- Create: `tools/sessions.py`
- Test: `backend/tests/test_session_tools.py`

**Interfaces:**
- Consumes: `SessionStore`, `utcnow` (Task 2); `SCHEMA`, `NeonDb`, `load_env` (Task 7).
- Produces: `list_sessions(store)`, `delete(store, db, sid)`, `wipe(store, db) -> (local, remote)`, `dsn_for(owner_dsn, user, password)`, `cloud_init(owner_dsn) -> (booth_dsn, public_dsn)`, `deploy(frontend, cloud, run, which)`, and the CLI `list | delete <id> | wipe [--yes] | cloud-init <dsn> | deploy`. `PAGE` and `FONTS` name the files `deploy` copies.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_session_tools.py`:

```python
"""tools/sessions.py: list, delete, wipe, role connection strings, deploy."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.session import SessionStore

TOOL = Path(__file__).resolve().parents[2] / "tools" / "sessions.py"
_spec = importlib.util.spec_from_file_location("session_tools", TOOL)
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self):
        self.removed = []
        self.wiped = False

    def remove(self, sid):
        self.removed.append(sid)

    def remove_all(self):
        self.wiped = True
        return 2


def saved(store, n):
    ids = []
    for _ in range(n):
        sid = store.new_id()
        store.create(sid, {"id": sid, "state": "done", "created": T0.isoformat(),
                           "keep_until": (T0 + timedelta(days=1)).isoformat(), "published": True})
        ids.append(sid)
    return ids


def test_list_shows_each_session(tmp_path):
    store = SessionStore(tmp_path)
    ids = saved(store, 2)
    rows = tools.list_sessions(store)
    assert len(rows) == 2 and all(any(sid in r for r in rows) for sid in ids)
    assert "published" in rows[0] and "2026-10-10T14:00" in rows[0]


def test_delete_removes_the_local_copy_and_the_cloud_row(tmp_path):
    store, db = SessionStore(tmp_path), FakeDb()
    sid = saved(store, 1)[0]
    assert tools.delete(store, db, sid) is True
    assert store.ids() == [] and db.removed == [sid]


def test_wipe_clears_everything(tmp_path):
    store, db = SessionStore(tmp_path), FakeDb()
    saved(store, 3)
    assert tools.wipe(store, db) == (3, 2) and store.ids() == [] and db.wiped


def test_dsn_for_swaps_the_role_and_keeps_host_database_and_options():
    owner = ("postgresql://neondb_owner:abc@ep-cool-name-123-pooler.us-east-2.aws.neon.tech/neondb"
             "?sslmode=require&channel_binding=require")
    assert tools.dsn_for(owner, "cardioview_public", "p/w:@x") == (
        "postgresql://cardioview_public:p%2Fw%3A%40x@ep-cool-name-123-pooler.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require")


def test_deploy_copies_the_page_and_fonts_then_deploys_to_production(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "vendor" / "fonts").mkdir(parents=True)
    for name in tools.PAGE:
        (fe / name).write_text(name)
    for name in tools.FONTS:
        (fe / "vendor" / "fonts" / name).write_text(name)
    cloud = tmp_path / "cloud"
    (cloud / "static").mkdir(parents=True)
    (cloud / "static" / "stale.txt").write_text("old")
    calls = []
    tools.deploy(fe, cloud, run=lambda cmd, **kw: calls.append((cmd, kw)), which=lambda name: "/bin/vercel")
    assert (cloud / "static" / "summary.js").read_text() == "summary.js"
    assert (cloud / "static" / "vendor" / "fonts" / "LICENSE").exists()
    assert not (cloud / "static" / "stale.txt").exists()
    assert calls == [(["/bin/vercel", "deploy", "--prod", "--yes"], {"cwd": cloud, "check": True})]


def test_deploy_without_the_cli_says_how_to_get_it(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "vendor" / "fonts").mkdir(parents=True)
    for name in tools.PAGE:
        (fe / name).write_text(name)
    for name in tools.FONTS:
        (fe / "vendor" / "fonts" / name).write_text(name)
    with pytest.raises(SystemExit, match="npm i -g vercel"):
        tools.deploy(fe, tmp_path / "cloud", run=lambda *a, **k: None, which=lambda name: None)
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest backend/tests/test_session_tools.py -q`
Expected: collection error, `FileNotFoundError` for `tools/sessions.py`.

- [ ] **Step 3: Write `tools/sessions.py`**

```python
"""Saved sessions from the command line.

    python tools/sessions.py list
    python tools/sessions.py delete <id>
    python tools/sessions.py wipe [--yes]        after the event: every local session and every Neon row
    python tools/sessions.py cloud-init "<Neon owner connection string>"
    python tools/sessions.py deploy               copy the summary page into cloud/ and deploy it to Vercel

Neon is used when NEON_DATABASE_URL is set, in the environment or in .env at the repo root.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cloud import SCHEMA, NeonDb, load_env  # noqa: E402
from backend.session import SessionStore, utcnow  # noqa: E402

SESSIONS = ROOT / "sessions"
FRONTEND = ROOT / "frontend"
CLOUD = ROOT / "cloud"
PAGE = ("summary.html", "summary.js", "summary.css")
FONTS = ("ibm-plex-sans-latin-400-normal.woff2", "ibm-plex-sans-latin-600-normal.woff2",
         "ibm-plex-sans-condensed-latin-700-normal.woff2", "LICENSE")
GRANTS = (
    "grant usage on schema public to cardioview_booth, cardioview_public",
    "grant select, insert, update, delete on session_summary to cardioview_booth",
    "revoke all on session_summary from cardioview_public",
    "grant select on session_summary to cardioview_public",
    "grant update (summary, deleted_at) on session_summary to cardioview_public",
)


def list_sessions(store: SessionStore) -> list[str]:
    rows = []
    for sid in store.ids():
        m = store.read_meta(sid) or {}
        rows.append(f"{sid}  {m.get('created', '?')[:16]}  {m.get('state', '?'):<9}  "
                    f"{'published' if m.get('published') else 'local':<9}  until {m.get('keep_until', '?')[:16]}")
    return rows


def delete(store: SessionStore, db, sid: str) -> bool:
    existed = store.delete(sid)
    if db is not None:
        db.remove(sid)
    return existed


def wipe(store: SessionStore, db) -> tuple[int, int]:
    local = sum(store.delete(sid) for sid in store.ids())
    remote = db.remove_all() if db is not None else 0
    return local, remote


def dsn_for(owner_dsn: str, user: str, password: str) -> str:
    """The owner's connection string with another role's name and password in it."""
    u = urlsplit(owner_dsn)
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, f"{quote(user, safe='')}:{quote(password, safe='')}@{host}", u.path, u.query, u.fragment))


def cloud_init(owner_dsn: str) -> tuple[str, str]:
    """Create the table and the two roles, and return their connection strings (booth, public)."""
    import psycopg
    from psycopg import sql

    passwords = {"cardioview_booth": secrets.token_urlsafe(24), "cardioview_public": secrets.token_urlsafe(24)}
    with psycopg.connect(owner_dsn, autocommit=True) as conn:
        conn.execute(SCHEMA)
        for role, password in passwords.items():
            exists = conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
            verb = "alter" if exists else "create"
            conn.execute(sql.SQL(verb + " role {} with login password {}").format(sql.Identifier(role), sql.Literal(password)))
        for grant in GRANTS:
            conn.execute(grant)
    return (dsn_for(owner_dsn, "cardioview_booth", passwords["cardioview_booth"]),
            dsn_for(owner_dsn, "cardioview_public", passwords["cardioview_public"]))


def deploy(frontend: Path = FRONTEND, cloud: Path = CLOUD, run=subprocess.run, which=shutil.which) -> None:
    """Copy the summary page and its fonts into cloud/static, then deploy to production."""
    static = cloud / "static"
    if static.exists():
        shutil.rmtree(static)
    (static / "vendor" / "fonts").mkdir(parents=True)
    for name in PAGE:
        shutil.copy2(frontend / name, static / name)
    for name in FONTS:
        shutil.copy2(frontend / "vendor" / "fonts" / name, static / "vendor" / "fonts" / name)
    vercel = which("vercel")
    if vercel is None:
        raise SystemExit("The Vercel CLI is not installed: npm i -g vercel, then vercel login")
    run([vercel, "deploy", "--prod", "--yes"], cwd=cloud, check=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Saved CardioView sessions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("delete")
    d.add_argument("id")
    w = sub.add_parser("wipe")
    w.add_argument("--yes", action="store_true", help="do not ask")
    c = sub.add_parser("cloud-init")
    c.add_argument("owner_dsn")
    sub.add_parser("deploy")
    args = ap.parse_args(argv)

    load_env(ROOT / ".env")
    store = SessionStore(SESSIONS)
    dsn = os.environ.get("NEON_DATABASE_URL")
    db = NeonDb(dsn) if dsn else None

    if args.cmd == "list":
        rows = list_sessions(store)
        print("\n".join(rows) if rows else "no saved sessions")
    elif args.cmd == "delete":
        print("deleted" if delete(store, db, args.id) else "no such session here (the cloud copy was removed if there was one)")
    elif args.cmd == "wipe":
        if not args.yes and input(f"Delete every saved session{' and every Neon row' if db else ''}? Type yes: ") != "yes":
            print("nothing deleted")
            return
        local, remote = wipe(store, db)
        print(f"deleted {local} local sessions and {remote} Neon rows")
    elif args.cmd == "cloud-init":
        booth, public = cloud_init(args.owner_dsn)
        print("Put this in .env on the booth laptop (never commit it):")
        print(f"NEON_DATABASE_URL={booth}")
        print("\nAnd this in the Vercel project's environment variables:")
        print(f"NEON_PUBLIC_URL={public}")
    elif args.cmd == "deploy":
        deploy()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and try it**

Run: `.venv/Scripts/python -m pytest backend/tests/test_session_tools.py -q`
Expected: `6 passed`.

Run: `.venv/Scripts/python tools/sessions.py list`
Expected: `no saved sessions`, or one line per folder in `sessions/`.

- [ ] **Step 5: Update CLAUDE.md**

Add to the end of the `## Saved sessions` list:

```markdown
- `python tools/sessions.py wipe` after the event deletes every local session and every Neon row; `list` and `delete <id>` are there for the operator.
```

and add `sessions.py (list, delete, wipe, cloud-init, deploy)` to the `tools/` Layout line.

- [ ] **Step 6: Commit**

```bash
git add tools/sessions.py backend/tests/test_session_tools.py CLAUDE.md
git commit -m "tools/sessions.py: list, delete, wipe, Neon roles and the public page deploy" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The public summary page on Vercel

**Files:**
- Create: `cloud/__init__.py` (empty), `cloud/app.py`, `cloud/requirements.txt`, `cloud/.python-version`, `cloud/.vercelignore`, `cloud/tests/__init__.py` (empty), `cloud/tests/test_public_app.py`
- Modify: `pytest.ini`, `.gitignore`, `CLAUDE.md`

**Interfaces:**
- Consumes: the `session_summary` table and the `cardioview_public` role from `tools/sessions.py cloud-init` (Task 8); `deploy` (Task 8) fills `cloud/static/` from `frontend/`.
- Produces: `cloud.app.create_app(db=None, now=...)` and the module-level `app` Vercel runs: `GET /api/s/{sid}` (summary or 404 `{"reason": "This session is no longer available."}`, never cached), `DELETE /api/s/{sid}` (marks the row deleted for the booth to sweep), `GET /s/{sid}` (the page), static files from `cloud/static/`.

- [ ] **Step 1: Write the failing test**

Create empty `cloud/__init__.py` and `cloud/tests/__init__.py`. Set `pytest.ini` to:

```ini
[pytest]
testpaths = backend/tests cloud/tests
```

Create `cloud/tests/test_public_app.py`:

```python
"""The public summary function with a fake database: reads, deletes, expiry, bad ids."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from cloud.app import create_app

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
SID = "A" * 22


class FakePublicDb:
    def __init__(self):
        self.rows = {SID: [{"version": 1, "id": SID}, T0 + timedelta(days=1), None],
                     "B" * 22: [{"version": 1}, T0 - timedelta(seconds=1), None]}

    def get(self, sid):
        row = self.rows.get(sid)
        return tuple(row) if row else None

    def mark_deleted(self, sid):
        row = self.rows.get(sid)
        if not row or row[2] is not None or row[1] <= T0:
            return 0
        row[0], row[2] = None, T0
        return 1


def client():
    db = FakePublicDb()
    return TestClient(create_app(db=db, now=lambda: T0)), db


def test_reads_a_live_summary_without_caching():
    c, _ = client()
    r = c.get(f"/api/s/{SID}")
    assert r.status_code == 200 and r.json() == {"version": 1, "id": SID}
    assert r.headers["cache-control"] == "no-store"


def test_expired_unknown_and_bad_ids_are_gone():
    c, _ = client()
    for sid in ("B" * 22, "C" * 22, "short"):
        r = c.get(f"/api/s/{sid}")
        assert r.status_code == 404 and r.json() == {"reason": "This session is no longer available."}
    assert c.get("/api/s/..%2F..%2Fx").status_code == 404   # slashes: never reaches the route


def test_delete_leaves_a_tombstone_for_the_booth_and_then_reads_gone():
    c, db = client()
    assert c.delete(f"/api/s/{SID}").json() == {"ok": True}
    assert db.rows[SID][0] is None and db.rows[SID][2] == T0
    assert c.get(f"/api/s/{SID}").status_code == 404
    assert c.delete(f"/api/s/{SID}").status_code == 404
    assert c.delete(f"/api/s/{'B' * 22}").status_code == 404
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest cloud/tests -q`
Expected: collection error, `ModuleNotFoundError: No module named 'cloud.app'`.

- [ ] **Step 3: Write the app and its project files**

Create `cloud/app.py`:

```python
"""Public summary pages for CardioView: the QR link a visitor opens on their phone.

Reads anonymous summaries from Neon with a role that can only read them and mark
them deleted, and serves the same summary page the booth serves. Nothing else.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"          # filled from frontend/ by tools/sessions.py deploy
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
GONE = {"reason": "This session is no longer available."}


class NeonPublic:
    """Read one summary, or mark it deleted. Nothing else is granted to this role."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _run(self, sql: str, params: tuple, fetch: bool):
        import psycopg
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if fetch else cur.rowcount

    def get(self, sid: str):
        rows = self._run("select summary, keep_until, deleted_at from session_summary where id = %s", (sid,), True)
        return rows[0] if rows else None

    def mark_deleted(self, sid: str) -> int:
        return self._run("update session_summary set summary = null, deleted_at = now() "
                         "where id = %s and deleted_at is null and keep_until > now()", (sid,), False)


def create_app(db=None, now=lambda: datetime.now(timezone.utc)) -> FastAPI:
    db = db or NeonPublic(os.environ.get("NEON_PUBLIC_URL", ""))
    app = FastAPI(title="CardioView summaries", docs_url=None, redoc_url=None, openapi_url=None)

    def gone() -> JSONResponse:
        return JSONResponse(GONE, status_code=404, headers={"Cache-Control": "no-store"})

    @app.get("/api/s/{sid}")
    def get_summary(sid: str):
        if not ID_RE.match(sid):
            return gone()
        row = db.get(sid)
        if row is None:
            return gone()
        summary, keep_until, deleted_at = row
        if summary is None or deleted_at is not None or keep_until <= now():
            return gone()
        return JSONResponse(summary, headers={"Cache-Control": "no-store"})

    @app.delete("/api/s/{sid}")
    def delete_summary(sid: str):
        if not ID_RE.match(sid) or db.mark_deleted(sid) == 0:
            return gone()
        return {"ok": True}

    @app.get("/s/{sid}")
    def page(sid: str):
        return FileResponse(STATIC / "summary.html", headers={"Cache-Control": "no-store"})

    if STATIC.is_dir():   # absent until the first deploy copies the page in
        app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
```

Create `cloud/requirements.txt`:

```text
fastapi==0.143.0
psycopg[binary]==3.3.6
```

Create `cloud/.python-version` containing `3.12`, and `cloud/.vercelignore`:

```text
tests/
__pycache__/
*.pyc
```

Append to `.gitignore`:

```text
cloud/static/
cloud/.vercel/
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes (`cloud/tests`: 3 passed).

- [ ] **Step 5: Commit the code**

```bash
git add cloud pytest.ini .gitignore
git commit -m "Public summary pages: a Vercel FastAPI app that reads Neon with a read-and-delete role" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6 (you): Create the Neon project**

At neon.com, create a free project (region near Orlando, for example `aws-us-east-1`), then copy its connection string from the dashboard's Connect panel, with connection pooling on. It looks like `postgresql://neondb_owner:...@ep-...-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`.

- [ ] **Step 7: Create the table and the two roles**

Run: `.venv/Scripts/python tools/sessions.py cloud-init "<owner connection string>"`
Expected: two lines, `NEON_DATABASE_URL=postgresql://cardioview_booth:...` and `NEON_PUBLIC_URL=postgresql://cardioview_public:...`, shown once.

Write the first line into `.env` at the repo root. Run `git check-ignore .env` and expect `.env`.

- [ ] **Step 8 (you): Vercel CLI and login**

Run: `npm i -g vercel`, then type `! vercel login` in this session and finish the login in the browser.

- [ ] **Step 9: Link the project and give it the read role**

```bash
cd cloud
vercel link --yes --project cardioview
vercel env add NEON_PUBLIC_URL production
```

Expected: the project `cardioview` is created and linked (`cloud/.vercel/` appears and is ignored). The second command asks for the value: paste the `NEON_PUBLIC_URL` connection string. If this CLI version rejects `--project`, run `vercel link` and answer the questions with the project name `cardioview`.

- [ ] **Step 10: Deploy**

Run: `.venv/Scripts/python tools/sessions.py deploy`
Expected: Vercel builds the Python app and prints the production URL, for example `https://cardioview.vercel.app`.

Then:

```bash
curl -s https://<production url>/api/s/AAAAAAAAAAAAAAAAAAAAAA
curl -s -o /dev/null -w "%{http_code}\n" https://<production url>/summary.js
```

Expected: `{"reason":"This session is no longer available."}` (the app reached Neon and found nothing) and `200`.

Add `CARDIOVIEW_PUBLIC_URL=https://<production url>` to `.env`.

- [ ] **Step 11: One session through the cloud**

Restart the server (`.venv/Scripts/python -m backend --source sim --host 127.0.0.1`). It prints `Saved sessions publish to https://...`. Start a session (`curl -s -X POST http://127.0.0.1:8000/api/session/start`), wait about 2.5 minutes, then take its id from `.venv/Scripts/python tools/sessions.py list`.

Expected:
- `list` shows it `published`.
- `curl -s https://<production url>/api/s/<id>` returns JSON with `"effort"`.
- A phone (or `W=390 H=1500` screenshot) at `https://<production url>/s/<id>` shows the summary and the delete button.
- The big screen caption reads "Scan to keep this on your phone".
- `curl -s -X DELETE https://<production url>/api/s/<id>` returns `{"ok":true}`; within 30 s `tools/sessions.py list` no longer shows the session and the big screen is back on the live view.

- [ ] **Step 12: Update CLAUDE.md and commit**

Add `cloud/      public summary pages on Vercel (app.py reads Neon), deployed with tools/sessions.py deploy` to the Layout block before `data/`.

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: the cloud folder" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Docs, a full check, and the merge

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-10-10-visitor-sessions-design.md`

- [ ] **Step 1: README**

Add this section after `## The heart model`:

````markdown
## Saved sessions

A visitor can save a two minute session and take a summary of it home.

1. Strap them in and explain: their ECG is recorded for about two minutes, without their name, kept on this laptop until the end of the event, and they can delete it from their phone.
2. If they agree, press S, then S again. The stage walks them through it: hold still, rest, slow breathing with the ring, squats, recovery.
3. The big screen then shows their summary with a QR code. Esc goes back to the live view, and so does three minutes without a key.

Esc twice during a session stops it and deletes it. V turns the voice on or off.

The summary shows effort and recovery, breathing, heart rate variability, their average heartbeat and their beat timing. A section says what it could not measure when the signal was not good enough. It is a visualization, not a diagnosis.

Sessions live in `sessions/` on this machine and never go into git. After the event:

```
python tools/sessions.py wipe
```

`--keep-until 2026-10-11T18:00` on the server sets when sessions expire (default: 24 hours after it starts). `python tools/sessions.py list` shows what is saved.

### The public link (optional)

Without this, the QR opens the summary over the booth's Wi-Fi only. To make it open anywhere:

1. Create a free project at neon.com and copy its connection string.
2. `python tools/sessions.py cloud-init "<that connection string>"`, then put the two lines it prints where it says.
3. `npm i -g vercel`, `vercel login`, then in `cloud/`: `vercel link --project cardioview` and `vercel env add NEON_PUBLIC_URL production`.
4. `python tools/sessions.py deploy`, and put `CARDIOVIEW_PUBLIC_URL=<the URL it prints>` in `.env`. Restart the server.

Only the anonymous summary goes to Neon. The raw ECG stays on this machine.
````

In `## Credits`, add:

```markdown
- Voice: the session prompts were generated with Kokoro 82M (https://huggingface.co/hexgrad/Kokoro-82M), Apache 2.0.
- segno (BSD) for QR codes, psycopg (LGPL 3) for Neon.
```

- [ ] **Step 2: CLAUDE.md tests line**

In `## Tests`, add a sentence: "Sessions: the analysis against synthetic sessions with known answers and bad input, the step machine by samples (pause, drop, cancel, consent), the routes end to end, the Neon sync and the public app with fake databases, and the sessions command."

Run: `wc -l CLAUDE.md`
Expected: under 200.

- [ ] **Step 3: Write the plan's two changes back into the spec**

In the spec, replace `cloud/public/` with `cloud/static/` (two places), and in the `.gitignore` line add `.venv-voice/`. Under `## Cloud: Neon and Vercel`, change "a Python FastAPI function" to "a Python FastAPI app (`cloud/app.py`, which also serves the page and fonts)".

- [ ] **Step 4: Check the rules mechanically**

```bash
git diff --name-only origin/main...HEAD | xargs grep -n $'\xe2\x80\x94\|\xe2\x80\x93' || echo "no em or en dashes"
git status --short
```

Expected: `no em or en dashes`; nothing under `sessions/`, no `.env`, no `cloud/static/` in the status.

- [ ] **Step 5: Full suite and the live view**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

Start the server, take `tools/screenshot.mjs` of `/` with no session running, and compare it with Thomas's last screenshot: nothing on the stage but his view.

- [ ] **Step 6: Commit the docs**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-10-10-visitor-sessions-design.md
git commit -m "Docs: saved sessions in the README and CLAUDE.md, spec matches what shipped" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Rebase on Thomas's latest and check again**

```bash
git fetch origin
git rebase origin/main
```

If a conflict stops the rebase (most likely in `frontend/main.js` or `frontend/index.html`), keep Thomas's version of each hunk and re-apply the hooks from Task 4, Step 4. Then run the full suite again and repeat the screenshots from Task 4, Step 5 and Task 5, Step 6.

- [ ] **Step 8: Merge and push**

```bash
git switch main
git pull --ff-only
git merge --ff-only visitor-sessions
git push origin main
```

Expected: a fast-forward, then the push succeeds. If `--ff-only` refuses, Thomas pushed during the check: go back to Step 7.

- [ ] **Step 9: Tell Thomas**

Send him: "Saved sessions are on main. On the Mac: `.venv/bin/pip install -r requirements.txt` (adds segno and psycopg), then `python -m backend --source h10` as usual. S twice starts a session, Esc twice stops it. The live strap path for sessions is untested on hardware: run one session with the strap on and tell me whether the summary appears." Copy `.env` to the Mac by hand if the booth there should use the cloud; it is not in git.

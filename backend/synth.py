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

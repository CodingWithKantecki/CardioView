"""Labeled ECG windows for the demo-pattern classifier.

The beats are the rhythm simulator's own shapes (backend/sources/rhythm.py), placed and varied at
random: heart rate, ECG amplitude, baseline drift, noise, polarity and beat timing. One seed fixes a
whole recording, so a split by seed holds out complete recordings. Numpy and scipy only, so the main
venv can test it; the encoder and the head need the ML venv (tools/requirements-ml.txt).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from backend.sources.base import FS
from backend.sources.rhythm import LABELS, MI_BUILD_S, NO_P, NORMAL, UV_PER_MV, WIDE, RhythmSource, infarct

CLASSES = ["sinus", "brady", "afib", "pvc", "vt", "mi", "none"]
NAMES = {**{c: LABELS[c] for c in CLASSES[:-1]}, "none": "No match"}
DEMO = CLASSES[:-1]
VERSION = 1              # bump when the generator or prepare() changes, so cached embeddings rebuild
WINDOW_S = 10.0
HOP_S = 5.0
RECORDING_S = 40.0
CLIP_UV = 19930          # where the strap pins its samples when the pads leave the skin
MI_DEVELOPED = 0.6       # infarct(k) from here on counts as a heart attack window
SEED_BASE = {"train": 0, "val": 100_000, "test": 200_000, "demo": 300_000}

RATES = {"sinus": (60, 150), "brady": (36, 56), "afib": (65, 160), "pvc": (55, 110), "vt": (130, 220), "mi": (65, 120)}


@dataclass
class Recording:
    cls: str
    seed: int
    uv: np.ndarray
    ectopic: list[float] | None = None   # extra beat times; a pvc window needs one inside it
    labeled_from: float = 0.0            # windows starting earlier are not labeled
    meta: dict = field(default_factory=dict)


def split_seeds(split: str, n: int) -> range:
    """Seeds for a split. The ranges never overlap, so no recording is in two splits."""
    return range(SEED_BASE[split], SEED_BASE[split] + n)


def _vary(tpl, rng, amp=0.25, width=0.2, shift=0.02, sign=1.0):
    """One recording's version of a beat shape: every wave a little taller or shorter and wider or
    narrower, the P and T waves a little earlier or later. The QRS stays on the R peak."""
    out = []
    for c, a, w in tpl:
        c = c + rng.normal(0, shift) if abs(c) > 0.05 else c
        out.append((c, sign * a * rng.uniform(1 - amp, 1 + amp), w * rng.uniform(1 - width, 1 + width)))
    return out


def _qt(tpl, rr):
    """The T wave comes sooner at fast rates and later at slow ones, as a real QT interval does."""
    f = min(1.15, max(0.75, math.sqrt(rr / 0.83)))
    c, a, w = tpl[-1]
    return tpl[:-1] + [(c * f, a, w * f)]


def _render(beats, n):
    """The simulator's sum of Gaussians, beat by beat, in mV."""
    t = np.arange(n) / FS
    v = np.zeros(n)
    for r, tpl in beats:
        lo, hi = max(0, int((r - 0.5) * FS)), min(n, int((r + 0.7) * FS) + 1)
        if lo >= hi:
            continue
        dt = t[lo:hi] - r
        for c, a, w in tpl:
            v[lo:hi] += a * np.exp(-((dt - c) ** 2) / (2 * w * w))
    return v


def _beats(cls, rng, seconds):
    """R peak times and shapes for one recording of a class, and the extra beat times."""
    rr = 60.0 / rng.uniform(*RATES[cls])
    f_resp = rng.uniform(0.1, 0.4)
    sd = rng.uniform(0.005, 0.03)
    rsa = rng.uniform(0.0, 0.06)
    beats, ectopic = [], []
    t = -rng.uniform(0, rr)

    def sinus_rr(at):
        return max(0.25, rr * (1 + rsa * math.sin(2 * math.pi * f_resp * at) + rng.normal(0, sd)))

    if cls == "afib":
        tpl = _vary(NO_P, rng)
        irr = rng.uniform(0.25, 0.5)
        while t < seconds + 1:
            beats.append((t, tpl))
            t += max(0.28, rr * rng.uniform(1 - irr, 1 + irr))
        return beats, ectopic
    if cls == "vt":
        tpl = _vary(WIDE, rng, amp=0.3, width=0.3, sign=rng.choice([-1.0, 1.0]))
        jitter = rng.uniform(0.003, 0.015)
        while t < seconds + 1:
            beats.append((t, tpl))
            t += max(0.25, rr + rng.normal(0, jitter))
        return beats, ectopic

    tpl = _vary(infarct(rng.uniform(MI_DEVELOPED, 1.0)) if cls == "mi" else NORMAL, rng)
    every, p = 0, 0.0
    if cls == "pvc":
        every = int(rng.choice([0, 2, 3, 4, 5, 6]))   # 0: extra beats at random
        p = rng.uniform(0.15, 0.35)
    elif cls == "mi":
        p = rng.uniform(0.0, 0.12)
    wide = _vary(WIDE, rng, amp=0.3, width=0.25, sign=-1.0 if rng.random() < 0.3 else 1.0)
    coupling = rng.uniform(0.55, 0.72)
    i, last_ectopic = 0, False
    while t < seconds + 1:
        i += 1
        step = sinus_rr(t)
        extra = (i % every == 0) if every else (rng.random() < p)
        if extra and not last_ectopic:
            beats.append((t + coupling * step, wide))   # early and wide
            ectopic.append(t + coupling * step)
            t += 2 * step                               # the next normal beat keeps the sinus schedule
            last_ectopic = True
        else:
            t += step
            last_ectopic = False
        beats.append((t, _qt(tpl, step)))
    return beats, ectopic


def _fibrillation(rng, n):
    """Atrial fibrillation's wavy baseline in place of P waves."""
    t = np.arange(n) / FS
    out = np.zeros(n)
    for _ in range(2):
        out += rng.uniform(0.0, 0.04) * np.sin(2 * math.pi * rng.uniform(4, 8) * t + rng.uniform(0, 6.3))
    return out * (0.6 + 0.4 * np.sin(2 * math.pi * rng.uniform(0.2, 0.5) * t))


def _dress(x, rng):
    """What a chest strap adds, in mV: breathing modulation, baseline drift, noise, and now and
    then motion bumps or muscle noise."""
    n = len(x)
    t = np.arange(n) / FS
    x = x * (1 + rng.uniform(0, 0.15) * np.sin(2 * math.pi * rng.uniform(0.1, 0.4) * t + rng.uniform(0, 6.3)))
    for _ in range(int(rng.integers(1, 4))):
        x += rng.uniform(0, 0.25) * np.sin(2 * math.pi * rng.uniform(0.05, 0.5) * t + rng.uniform(0, 6.3))
    x += rng.normal(0, rng.uniform(0.005, 0.07), n)
    if rng.random() < 0.25:
        for _ in range(int(rng.integers(1, 5))):
            c, w = rng.uniform(0, n / FS), rng.uniform(0.1, 0.5)
            x += rng.uniform(0.2, 1.0) * rng.choice([-1, 1]) * np.exp(-((t - c) ** 2) / (2 * w * w))
    if rng.random() < 0.25:
        for _ in range(int(rng.integers(1, 4))):
            s, length = int(rng.integers(0, n)), int(rng.uniform(0.5, 2.0) * FS)
            burst = np.diff(rng.normal(0, rng.uniform(0.03, 0.12), length + 1))[: n - s]
            x[s:s + len(burst)] += burst
    return x


def _no_match(rng, n):
    """No demo pattern, in uV: the pads off the skin, a flat line, motion swamping the ECG, or noise."""
    t = np.arange(n) / FS
    kind = rng.choice(["pads", "flat", "motion", "noise"])
    if kind == "pads":
        x = np.cumsum(rng.normal(0, rng.uniform(200, 2000), n)) + rng.uniform(-CLIP_UV, CLIP_UV)
    elif kind == "flat":
        x = rng.uniform(-500, 500) + rng.normal(0, rng.uniform(0, 3), n)
    elif kind == "motion":
        x = np.zeros(n)
        for _ in range(int(rng.integers(2, 6))):
            x += rng.uniform(500, 4000) * np.sin(2 * math.pi * rng.uniform(0.3, 3.0) * t + rng.uniform(0, 6.3))
        x += rng.normal(0, rng.uniform(20, 300), n)
        if rng.random() < 0.5:
            beats, _ = _beats("sinus", rng, n / FS)
            x += _render(beats, n) * UV_PER_MV * rng.uniform(0.02, 0.1)
    else:
        x = rng.normal(0, rng.uniform(30, 400), n)
        if rng.random() < 0.5:
            x = np.cumsum(x) * rng.uniform(0.02, 0.2)   # redder noise
    return x


def recording(cls: str, seed: int, seconds: float = RECORDING_S) -> Recording:
    """One randomized recording of a class, as integer uV at 130 Hz like the strap."""
    rng = np.random.default_rng([seed, CLASSES.index(cls)])
    n = int(round(seconds * FS))
    ectopic = None
    if cls == "none":
        x = _no_match(rng, n)
    else:
        beats, ectopic = _beats(cls, rng, seconds)
        x = _render(beats, n)
        if cls == "afib":
            x += _fibrillation(rng, n)
        x = _dress(x, rng) * UV_PER_MV * rng.uniform(0.4, 2.0)
        if cls != "pvc":
            ectopic = None
    inverted = bool(rng.random() < 0.3)
    if inverted:
        x = -x
    uv = np.clip(np.round(x), -CLIP_UV, CLIP_UV).astype(np.int32)
    return Recording(cls, seed, uv, ectopic, meta={"inverted": inverted})


def demo_recording(pattern: str, seed: int, seconds: float = 60.0, invert: bool = False) -> Recording:
    """The demo's own RhythmSource stream, driven offline. A heart attack window counts once the
    ST elevation has developed (MI_DEVELOPED of the way through its build)."""
    n = int(round(seconds * FS))
    uv = np.fromiter(itertools.islice(RhythmSource(pattern, seed=seed)._samples, n), dtype=np.int32, count=n)
    if invert:
        uv = -uv
    start = MI_DEVELOPED * MI_BUILD_S if pattern == "mi" else 0.0
    return Recording(pattern, seed, uv, None, labeled_from=start, meta={"inverted": invert, "demo": True})


def windows(rec: Recording, window_s: float = WINDOW_S, hop_s: float = HOP_S):
    """(start index, label) for each labeled window of a recording. A pvc window without an extra
    beat inside it is skipped rather than relabeled."""
    win, hop = int(window_s * FS), int(hop_s * FS)
    for s in range(0, len(rec.uv) - win + 1, hop):
        t0 = s / FS
        if t0 < rec.labeled_from:
            continue
        if rec.ectopic is not None and not any(t0 + 0.3 <= e <= t0 + window_s - 0.3 for e in rec.ectopic):
            continue
        yield s, rec.cls


def load_csv(path) -> np.ndarray:
    """A strap recording (time_s,ecg_uv) as integer uV."""
    return np.loadtxt(path, delimiter=",", skiprows=1, usecols=1).astype(np.int32)


ENCODER_FS = 100
LEADS = 12
HALF = int(WINDOW_S / 2 * ENCODER_FS)
_SOS = signal.butter(2, [0.5, 47.0], btype="bandpass", fs=FS, output="sos")


def prepare(window_uv) -> np.ndarray:
    """One 10 s window at 130 Hz as HuBERT-ECG input: two rows of 6000 values, one per 5 s half.
    The encoder takes 12 leads of 5 s at 100 Hz, band-passed, min-max scaled to -1..1 and flattened
    lead by lead; the strap has one lead, so it fills all twelve."""
    x = np.asarray(window_uv, dtype=float)
    x = signal.sosfiltfilt(_SOS, x)
    x = signal.resample_poly(x, ENCODER_FS, FS)
    lo, hi = x.min(), x.max()
    x = 2 * (x - lo) / (hi - lo + 1e-8) - 1
    halves = x[: 2 * HALF].reshape(2, HALF)
    return np.tile(halves, (1, LEADS)).astype(np.float32)

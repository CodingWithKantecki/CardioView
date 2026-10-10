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

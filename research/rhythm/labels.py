"""Labels and splits: PTB-XL fits and tests, PhysioNet 2017 and MIT-BIH test from outside."""
from __future__ import annotations

import ast

import numpy as np
import pandas as pd

CONDITIONS = ("af", "flutter", "extra_beats", "avb1", "long_qt", "wpw")
NAMES = {"af": "Atrial fibrillation", "flutter": "Atrial flutter", "extra_beats": "Extra beats",
         "avb1": "First-degree AV block", "long_qt": "Long QT", "wpw": "WPW",
         "slow": "Slow rate", "fast": "Fast rate", "pause": "Pauses over 2 s"}
PTBXL_CODES = {"af": {"AFIB"}, "flutter": {"AFLT"}, "extra_beats": {"PVC", "PAC", "BIGU", "TRIGU"},
               "avb1": {"1AVB"}, "long_qt": {"LNGQT"}, "wpw": {"WPW"}}
VAL_FOLD, TEST_FOLD = 9, 10

PACED = {"102", "104", "107", "217"}
SVEB, VEB = set("AaJS"), set("VE")
NORMAL = set("NLRej")
LEFT_OUT = set("FQ/f")
BEATS = SVEB | VEB | NORMAL | LEFT_OUT
AF_RHYTHMS = ("(AFIB", "(AFL")


def ptbxl_labels(db: pd.DataFrame) -> pd.DataFrame:
    """db is ptbxl_database.csv indexed by ecg_id. A code counts at any likelihood (the PTB-XL benchmark)."""
    codes = db["scp_codes"].map(lambda s: set(ast.literal_eval(s)))
    out = pd.DataFrame(index=db.index)
    out["filename_hr"] = db["filename_hr"]
    out["strat_fold"] = db["strat_fold"].astype(int)
    out["split"] = np.where(out["strat_fold"] == TEST_FOLD, "test",
                            np.where(out["strat_fold"] == VAL_FOLD, "val", "train"))
    for c in CONDITIONS:
        out[c] = codes.map(lambda s, want=PTBXL_CODES[c]: int(bool(s & want)))
    for col, code in (("norm", "NORM"), ("sbrad", "SBRAD"), ("stach", "STACH")):
        out[col] = codes.map(lambda s, code=code: int(code in s))
    return out


def cinc2017_labels(ref: pd.DataFrame) -> pd.DataFrame:
    """REFERENCE-v3.csv (record, label): af is 1 for A, 0 for N and O, -1 for noisy (reported apart)."""
    out = ref.copy()
    out["af"] = out["label"].map({"A": 1, "N": 0, "O": 0, "~": -1})
    return out


def af_spans(symbols, samples, aux, n_samples: int) -> list[tuple[int, int]]:
    """Sample ranges inside an AF or flutter episode, from MIT-BIH's rhythm annotations ("+")."""
    spans, start, rhythm = [], 0, ""
    for sym, s, note in zip(symbols, samples, aux):
        if sym != "+":
            continue
        if rhythm in AF_RHYTHMS:
            spans.append((start, int(s)))
        rhythm, start = (note or "").strip("\x00 "), int(s)
    if rhythm in AF_RHYTHMS:
        spans.append((start, int(n_samples)))
    return spans


def beat_times(symbols, samples, fs: float) -> np.ndarray:
    """Seconds of every annotated beat."""
    return np.array([s / fs for sym, s in zip(symbols, samples) if sym in BEATS], dtype=float)


def mitbih_windows(symbols, samples, aux, fs: float, n_samples: int, window_s: float = 10.0) -> pd.DataFrame:
    """extra_beats per window: 1 with an SVEB or VEB beat, 0 with only N beats, -1 left out
    (an F or Q beat, inside AF or flutter, or no beat at all)."""
    symbols, samples = np.asarray(symbols), np.asarray(samples)
    spans = af_spans(symbols, samples, aux, n_samples)
    win = int(round(window_s * fs))
    rows = []
    for k in range(int(n_samples) // win):
        a, b = k * win, (k + 1) * win
        here = [x for x in symbols[(samples >= a) & (samples < b)] if x in BEATS]
        if not here or any(x in LEFT_OUT for x in here) or any(lo < b and hi > a for lo, hi in spans):
            label = -1
        elif any(x in SVEB or x in VEB for x in here):
            label = 1
        else:
            label = 0
        rows.append({"start_s": a / fs, "extra_beats": label})
    return pd.DataFrame(rows, columns=["start_s", "extra_beats"])


def rr_windows(times, n_windows: int, window_s: float = 10.0) -> pd.DataFrame:
    """Per window: the longest RR, the bpm of the median RR, and how many RRs. An RR belongs to the
    window of its second beat."""
    times = np.asarray(times, dtype=float)
    rr, ends = np.diff(times), times[1:]
    rows = []
    for k in range(n_windows):
        r = rr[(ends >= k * window_s) & (ends < (k + 1) * window_s)]
        rows.append({"start_s": k * window_s, "max_rr": float(r.max()) if len(r) else np.nan,
                     "bpm": float(60 / np.median(r)) if len(r) else np.nan, "n_rr": int(len(r))})
    return pd.DataFrame(rows, columns=["start_s", "max_rr", "bpm", "n_rr"])

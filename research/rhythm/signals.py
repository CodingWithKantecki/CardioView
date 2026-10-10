"""The two versions of every window: full quality at 500 Hz, and through the strap's 130 Hz in
integer microvolts, raised back to 500 Hz because that is ECGFounder's input rate."""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

MODEL_FS = 500
STRAP_FS = 130
WINDOW_S = 10
WINDOW_N = MODEL_FS * WINDOW_S


def resample(x, fs_in: int, fs_out: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if fs_in == fs_out:
        return x.copy()
    g = gcd(int(fs_in), int(fs_out))
    return resample_poly(x, int(fs_out) // g, int(fs_in) // g)   # its FIR filter is the anti-alias filter


def to_strap_uv(x_mv, fs_in: int) -> np.ndarray:
    """What the strap would send: 130 Hz, integer microvolts."""
    return np.rint(resample(x_mv, fs_in, STRAP_FS) * 1000.0).astype(np.int32)


def full_version(x_mv, fs_in: int) -> np.ndarray:
    return resample(x_mv, fs_in, MODEL_FS)


def strap_version(x_mv, fs_in: int) -> np.ndarray:
    """Through the strap and back up to the model's rate, in mV."""
    return resample(to_strap_uv(x_mv, fs_in) / 1000.0, STRAP_FS, MODEL_FS)


def windows(x, n: int = WINDOW_N) -> np.ndarray:
    """Every full non-overlapping window, shape (k, n); (0, n) when x is shorter than n."""
    k = len(x) // n
    return np.asarray(x[: k * n], dtype=np.float32).reshape(k, n)


def zscore(w) -> np.ndarray:
    """Per window, as ECGFounder's dataset.py does; a flat window stays zero."""
    w = np.asarray(w, dtype=np.float32)
    return (w - w.mean(axis=-1, keepdims=True)) / (w.std(axis=-1, keepdims=True) + 1e-8)

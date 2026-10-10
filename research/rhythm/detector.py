"""The lightweight rhythm detector: uncorrected NeuroKit2 beats, six rhythm features and tiny
logistic models stored as JSON. It uses only the booth's packages, so the backend can call it."""
from __future__ import annotations

import json
from pathlib import Path

import neurokit2 as nk
import numpy as np
import pandas as pd

FEATURES = ("bpm", "max_rr", "nrmssd", "irregular", "premature", "odd_shape")
AF_FEATURES = ("nrmssd", "irregular", "premature")
EXTRA_FEATURES = ("premature", "odd_shape", "nrmssd")
MIN_BEATS = 4
IRREGULAR = 0.15          # a successive RR difference over 15% of the median RR
EARLY, LATE = 0.85, 1.10  # an RR under 85% of the median, then one over 110%: an early beat and its pause
SHAPE_S = 0.10            # the beat shape window, either side of R


def find_peaks(uv, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """R peak indices and the cleaned signal. No artifact correction: it moves early beats back into line."""
    clean = nk.ecg_clean(np.asarray(uv, dtype=float), sampling_rate=fs)
    _, info = nk.ecg_peaks(clean, sampling_rate=fs, correct_artifacts=False)
    return np.asarray(info["ECG_R_Peaks"], dtype=int), clean


def rr_features(r_s) -> dict:
    """bpm, max_rr, nrmssd, irregular and premature from R times in seconds; {} under MIN_BEATS beats."""
    r = np.asarray(r_s, dtype=float)
    if len(r) < MIN_BEATS:
        return {}
    rr = np.diff(r)
    med = float(np.median(rr))
    d = np.diff(rr)
    early = (rr[:-1] < EARLY * med) & (rr[1:] > LATE * med)
    return {"bpm": 60.0 / med, "max_rr": float(rr.max()),
            "nrmssd": float(np.sqrt(np.mean(d ** 2)) / rr.mean()),
            "irregular": float(np.mean(np.abs(d) > IRREGULAR * med)),
            "premature": int(early.sum())}


def odd_shape(clean, peaks, fs: float) -> float:
    """One minus the lowest correlation of a beat (SHAPE_S either side of R) with the median beat."""
    h = int(round(SHAPE_S * fs))
    segs = np.array([clean[p - h:p + h + 1] for p in peaks if p - h >= 0 and p + h < len(clean)])
    if len(segs) < MIN_BEATS:
        return 0.0
    template = np.median(segs, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.array([np.corrcoef(s, template)[0, 1] for s in segs])
    corr = corr[np.isfinite(corr)]
    return float(1.0 - corr.min()) if len(corr) else 0.0


def features(uv, fs: float) -> dict:
    """The six features of a stretch in microvolts, or {} with fewer than MIN_BEATS beats."""
    try:
        peaks, clean = find_peaks(uv, fs)
    except Exception:   # NeuroKit2 raises on a flat or very short signal
        return {}
    f = rr_features(peaks / fs)
    if f:
        f["odd_shape"] = odd_shape(clean, peaks, fs)
    return f


class Model:
    """L2-regularized logistic regression on standardized features, fitted and run with numpy."""

    def __init__(self, names, mean, scale, weights, bias: float, threshold: float = 0.5):
        self.names = list(names)
        self.mean, self.scale = np.asarray(mean, dtype=float), np.asarray(scale, dtype=float)
        self.weights, self.bias, self.threshold = np.asarray(weights, dtype=float), float(bias), float(threshold)

    @classmethod
    def fit(cls, table: pd.DataFrame, y, names, l2: float = 1.0, steps: int = 3000, lr: float = 0.1) -> "Model":
        x = table[list(names)].to_numpy(dtype=float)
        y = np.asarray(y, dtype=float)
        mean, scale = x.mean(0), x.std(0) + 1e-9
        z = (x - mean) / scale
        weight = np.where(y == 1, (len(y) - y.sum()) / max(y.sum(), 1.0), 1.0)   # balance the rare class
        weight /= weight.mean()
        w, b = np.zeros(z.shape[1]), 0.0
        for _ in range(steps):
            g = weight * (_sigmoid(z @ w + b) - y)
            w -= lr * (z.T @ g / len(y) + l2 * w / len(y))
            b -= lr * g.mean()
        return cls(names, mean, scale, w, b)

    def score(self, table: pd.DataFrame) -> np.ndarray:
        """Probabilities per row, picking the features by name."""
        z = (table[self.names].to_numpy(dtype=float) - self.mean) / self.scale
        return _sigmoid(z @ self.weights + self.bias)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps({
            "features": self.names, "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "weights": self.weights.tolist(), "bias": self.bias, "threshold": self.threshold}, indent=1),
            encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Model":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["features"], d["mean"], d["scale"], d["weights"], d["bias"], d["threshold"])


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))

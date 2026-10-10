"""The pass bar, fixed before any run: AUROC, thresholds, bootstrap intervals, verdicts."""
from __future__ import annotations

import numpy as np
from scipy.stats import rankdata

SPEC_TARGET = 0.98    # each model threshold leaves 98% of fold 9's negatives unflagged
SPEC_FLOOR = 0.97     # pass: the lower bound of specificity
SENS_FLOOR = 0.80     # pass: sensitivity
MIN_POSITIVES = 50    # fewer in the test set: not enough data
BOOT = 2000


def auroc(y, s) -> float:
    y, s = np.asarray(y, dtype=bool), np.asarray(s, dtype=float)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if not n_pos or not n_neg:
        return float("nan")
    return float((rankdata(s)[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def threshold_for(y, s, spec: float = SPEC_TARGET) -> float:
    """Flag scores above this; it leaves `spec` of the negatives unflagged."""
    return float(np.quantile(np.asarray(s, dtype=float)[~np.asarray(y, dtype=bool)], spec))


def stats(y, flags, boot: int = BOOT, seed: int = 0) -> dict:
    """Sensitivity and specificity with 95% bootstrap intervals."""
    y, f = np.asarray(y, dtype=bool), np.asarray(flags, dtype=bool)
    out = {"positives": int(y.sum()), "negatives": int((~y).sum()),
           "sens": _ratio((f & y).sum(), y.sum()), "spec": _ratio((~f & ~y).sum(), (~y).sum())}
    idx = np.random.default_rng(seed).integers(0, len(y), size=(boot, len(y)))
    yb, fb = y[idx], f[idx]
    with np.errstate(invalid="ignore", divide="ignore"):
        sens_b = (fb & yb).sum(1) / yb.sum(1)
        spec_b = (~fb & ~yb).sum(1) / (~yb).sum(1)
    out["sens_lo"], out["sens_hi"] = _interval(sens_b)
    out["spec_lo"], out["spec_hi"] = _interval(spec_b)
    return out


def verdict(main: dict, outside: dict | None = None) -> str:
    if main["positives"] < MIN_POSITIVES:
        return "not enough data"
    ok = all(s["spec_lo"] >= SPEC_FLOOR and s["sens"] >= SENS_FLOOR for s in (main, outside) if s)
    return "pass" if ok else "fail"


def _ratio(a, b) -> float:
    return float(a / b) if b else float("nan")


def _interval(values) -> tuple[float, float]:
    v = values[np.isfinite(values)]   # a resample without positives has no sensitivity
    if not len(v):
        return float("nan"), float("nan")
    lo, hi = np.percentile(v, [2.5, 97.5])
    return float(lo), float(hi)

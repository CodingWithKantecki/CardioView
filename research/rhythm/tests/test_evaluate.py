"""Fitting and judging on a synthetic table: too-few-beat rows are skipped and never flagged."""
import numpy as np
import pandas as pd

from research.rhythm import detector as dt
from research.rhythm import evaluate as ev


def test_fit_and_judge_skips_stretches_with_too_few_beats():
    rng = np.random.default_rng(0)
    n = 4000
    y = (rng.random(n) < 0.2).astype(int)
    ptb = pd.DataFrame({"af": y, "norm": 1 - y, "split": rng.choice(["train", "val", "test"], n, p=[0.6, 0.2, 0.2]),
                        "nrmssd": y * 0.3 + rng.normal(0.02, 0.01, n), "irregular": y * 0.6 + rng.random(n) * 0.1,
                        "premature": rng.integers(0, 2, n)})
    few = np.flatnonzero(y == 0)[:30]
    ptb.loc[few, list(dt.AF_FEATURES)] = np.nan   # healthy stretches with too few beats
    model, row = ev.fit_and_judge(ptb, None, "af", dt.AF_FEATURES)
    assert row["main"]["sens"] == 1.0 and abs(row["main"]["spec"] - 0.98) < 0.03
    assert (ev.scores(model, ptb.loc[few]) == 0).all()

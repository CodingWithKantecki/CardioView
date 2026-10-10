# Rhythm Feasibility Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide, per condition, whether a lightweight detector (uncorrected NeuroKit2 beats, six rhythm features, two tiny logistic models) detects it reliably from one lead at the strap's 130 Hz, and publish the models with their results on the Hugging Face Hub.

**Architecture:** Torch-free modules hold every rule and are unit tested in the main suite: `signals` (done), `labels`, `scoring`, `detector`. `prepare` turns every stretch of PTB-XL, PhysioNet 2017, MIT-BIH and Thomas's recordings into features (native rate and strap version) cached as CSV. `evaluate` fits the two models per version, applies the pass bar, writes `RESULTS.md` and `models/*.json`. `publish` writes the model card and uploads only on the user's go-ahead.

**Tech Stack:** Python 3.12, numpy, scipy, pandas, neurokit2 0.2.13 (the booth's), wfdb, huggingface_hub.

**Spec:** `docs/superpowers/specs/2026-10-10-rhythm-feasibility-design.md` (v3, approved by the user and Thomas)

## Global Constraints

- No em or en dashes in anything we write. Local commits on `gabe_rhythm_feasibility` only; never push, never touch main.
- Never print `.env`, a token or a connection string. Publishing to the Hugging Face Hub is public: only on the user's explicit go-ahead.
- No torch, no Databricks. The booth's `requirements.txt` gains nothing; research packages live in `research/rhythm/requirements.txt` and `.venv-research`.
- `signals.py`, `labels.py`, `scoring.py`, `detector.py`, `evaluate.py` import only numpy, scipy, pandas, neurokit2 and each other, so the main suite tests them.
- Pass bar, exactly: model thresholds at specificity 0.98 on PTB-XL fold 9; pass needs specificity lower bound >= 0.97 and sensitivity >= 0.80 on the test set and the outside set where there is one; under 50 positives is "not enough data"; 95% bootstrap from 2,000 resamples. Fixed cutoffs: under 60 bpm, over 100 bpm, RR over 2.0 s (3.0 s reported).
- Detector constants, exactly: 4 beats minimum, irregular above 15% of the median RR, premature under 85% then over 110%, shape window 100 ms either side of R.
- CLAUDE.md under 200 lines, updated in the same commit as the change. Write files with the Write tool; run modules from the repo root as `python -m research.rhythm.<module>`.

## Review Focus

- A flat or very short stretch: NeuroKit2 raises; `features` must return `{}` (flagged for nothing), never crash a 20,000-record run. Pinned in Task 3.
- Stretches with too few beats inside a fit: they must be left out of fitting and score 0, not poison the model with NaN. Pinned in Task 4.
- A model file read with its features in another order (the backend builds a dict): scoring must go by feature name, not position. Pinned in Task 3.
- MIT-BIH rhythm notes end in a NUL byte: AF episodes must still be found. Pinned in Task 1.
- A condition with no positives in a resample or split: AUROC is NaN, intervals skip empty resamples. Pinned in Task 2.

## Already on the branch

`research/__init__.py`, `research/rhythm/__init__.py`, `research/rhythm/tests/__init__.py`, `requirements.txt` (neurokit2, numpy, scipy, pandas, wfdb, huggingface_hub, pytest), `.gitignore` entries, `pytest.ini` path, the CLAUDE.md section, `signals.py` (`STRAP_FS = 130`, `to_strap_uv(x_mv, fs_in) -> int32`), `download.py` (datasets into `research/rhythm/data/`).

---

### Task 1: `labels.py`

**Files:** Create `research/rhythm/labels.py`, `research/rhythm/tests/test_labels.py`.

**Interfaces:** Produces `CONDITIONS`, `NAMES`, `PACED`, `ptbxl_labels(db) -> DataFrame` (index ecg_id: `filename_hr`, `strat_fold`, `split`, the six conditions, `norm`, `sbrad`, `stach`), `cinc2017_labels(ref) -> DataFrame` (adds `af`: 1, 0, -1), `af_spans`, `beat_times(symbols, samples, fs) -> ndarray`, `mitbih_windows(symbols, samples, aux, fs, n_samples) -> DataFrame` (`start_s`, `extra_beats`), `rr_windows(times, n_windows) -> DataFrame` (`start_s`, `max_rr`, `bpm`, `n_rr`).

- [ ] **Step 1: Write the failing tests** (`test_labels.py`)

```python
"""Labels and splits for PTB-XL, PhysioNet 2017 and MIT-BIH, on small tables with known answers."""
import numpy as np
import pandas as pd

from research.rhythm import labels as lb


def test_ptbxl_codes_folds_and_rates():
    db = pd.DataFrame({
        "scp_codes": ["{'NORM': 100.0, 'SR': 0.0}", "{'PAC': 0.0, 'SR': 0.0}", "{'AFIB': 100.0}",
                      "{'SBRAD': 0.0, '1AVB': 100.0}"],
        "filename_hr": ["a", "b", "c", "d"], "strat_fold": [1, 9, 10, 3]},
        index=pd.Index([1, 2, 3, 4], name="ecg_id"))
    out = lb.ptbxl_labels(db)
    assert list(out["split"]) == ["train", "val", "test", "train"]
    assert out.loc[2, "extra_beats"] == 1 and out.loc[2, "af"] == 0   # a code counts at likelihood 0
    assert out.loc[3, "af"] == 1 and out.loc[4, "avb1"] == 1 and out.loc[4, "sbrad"] == 1
    assert out.loc[1, "norm"] == 1 and out.loc[1, list(lb.CONDITIONS)].sum() == 0


def test_cinc2017_sets_noisy_apart():
    ref = pd.DataFrame({"record": ["A1", "A2", "A3", "A4"], "label": ["A", "N", "O", "~"]})
    assert list(lb.cinc2017_labels(ref)["af"]) == [1, 0, 0, -1]


def test_mitbih_windows_label_extra_beats_and_leave_out_the_rest():
    fs, n = 100, 5000   # five 10 s windows of 1000 samples
    symbols = ["N", "N", "V", "N", "F", "N", "+", "N", "+"]
    samples = [100, 500, 1200, 1800, 2500, 2600, 3000, 3500, 4000]
    aux = ["", "", "", "", "", "", "(AFIB\x00", "", "(N\x00"]   # MIT-BIH notes end in a NUL byte
    w = lb.mitbih_windows(symbols, samples, aux, fs, n)
    assert list(w["extra_beats"]) == [0, 1, -1, -1, -1]   # normal, a PVC, an F beat, inside AF, no beat


def test_rr_windows_put_each_interval_in_its_second_beats_window():
    w = lb.rr_windows(np.array([1.0, 2.0, 3.0, 9.5, 10.5, 11.5]), 2)
    assert w.loc[0, "max_rr"] == 6.5 and w.loc[0, "n_rr"] == 3
    assert w.loc[1, "max_rr"] == 1.0 and round(w.loc[1, "bpm"]) == 60
```

- [ ] **Step 2: Run, expect `cannot import name 'labels'`:** `.venv/Scripts/python -m pytest -q research/rhythm/tests/test_labels.py`

- [ ] **Step 3: Write `labels.py`**

```python
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
```

- [ ] **Step 4: Run, expect 4 passed.** Commit: "Rhythm feasibility: labels and splits".

---

### Task 2: `scoring.py`, the pass bar

**Files:** Create `research/rhythm/scoring.py`, `research/rhythm/tests/test_scoring.py`.

**Interfaces:** Produces `auroc(y, s) -> float`, `threshold_for(y, s, spec=0.98) -> float` (flag `s > t`), `stats(y, flags) -> dict` (`positives`, `negatives`, `sens`, `spec`, `sens_lo`, `sens_hi`, `spec_lo`, `spec_hi`), `verdict(main, outside=None) -> "pass" | "fail" | "not enough data"`.

- [ ] **Step 1: Write the failing tests** (`test_scoring.py`)

```python
"""The pass bar on synthetic scores with known answers."""
import numpy as np

from research.rhythm import scoring as sc


def test_auroc_known_answers():
    assert sc.auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert sc.auroc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert sc.auroc([0, 1], [0.5, 0.5]) == 0.5
    assert np.isnan(sc.auroc([0, 0, 0], [0.1, 0.2, 0.3]))   # no positives: NaN, not an error


def test_the_threshold_leaves_98_percent_of_negatives_unflagged():
    rng = np.random.default_rng(1)
    y = np.r_[np.zeros(1000), np.ones(100)].astype(bool)
    s = np.r_[rng.normal(0, 1, 1000), rng.normal(3, 1, 100)]
    t = sc.threshold_for(y, s)
    assert abs((s[~y] <= t).mean() - 0.98) < 0.002


def test_a_perfect_separator_passes():
    y = np.r_[np.ones(60), np.zeros(940)].astype(bool)
    assert sc.verdict(sc.stats(y, y)) == "pass"


def test_49_positives_are_not_enough_data():
    y = np.r_[np.ones(49), np.zeros(951)].astype(bool)
    assert sc.verdict(sc.stats(y, y)) == "not enough data"


def test_five_false_alarms_in_a_hundred_fail_even_when_every_case_is_caught():
    y = np.r_[np.ones(100), np.zeros(900)].astype(bool)
    flags = y.copy()
    flags[100:145] = True   # 45 of 900 healthy recordings flagged: specificity 0.95
    s = sc.stats(y, flags)
    assert s["sens"] == 1.0 and round(s["spec"], 2) == 0.95
    assert sc.verdict(s) == "fail"


def test_the_outside_set_can_fail_a_condition():
    y = np.r_[np.ones(60), np.zeros(940)].astype(bool)
    missed = y.copy()
    missed[:30] = False   # outside: half the cases missed
    assert sc.verdict(sc.stats(y, y), sc.stats(y, missed)) == "fail"


def test_a_single_positive_still_gives_finite_specificity_bounds():
    y = np.r_[np.ones(1), np.zeros(999)].astype(bool)
    s = sc.stats(y, np.zeros(1000, dtype=bool))
    assert np.isfinite(s["spec_lo"]) and s["spec"] == 1.0 and s["sens"] == 0.0
```

- [ ] **Step 2: Run, expect `cannot import name 'scoring'`.**

- [ ] **Step 3: Write `scoring.py`**

```python
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
```

- [ ] **Step 4: Run, expect 7 passed.** Commit: "Rhythm feasibility: the pass bar".

---

### Task 3: `detector.py`, beats, features and the tiny models

**Files:** Create `research/rhythm/detector.py`, `research/rhythm/tests/test_detector.py`.

**Interfaces:** Produces `FEATURES`, `AF_FEATURES = ("nrmssd", "irregular", "premature")`, `EXTRA_FEATURES = ("premature", "odd_shape", "nrmssd")`, `find_peaks(uv, fs) -> (peaks, clean)`, `rr_features(r_s) -> dict`, `odd_shape(clean, peaks, fs) -> float`, `features(uv, fs) -> dict` (the six, or `{}`), `Model.fit(table, y, names)`, `Model.score(table) -> ndarray` (by name), `Model.save(path)`, `Model.load(path)`, `Model.threshold`.

- [ ] **Step 1: Write the failing tests** (`test_detector.py`)

```python
"""The detector on rhythms and beats with known answers."""
import neurokit2 as nk
import numpy as np
import pandas as pd

from research.rhythm import detector as dt


def times(rr):
    return np.concatenate([[0.0], np.cumsum(rr)])


def test_a_steady_rhythm():
    f = dt.rr_features(times([1.0] * 9))
    assert f["bpm"] == 60 and f["max_rr"] == 1.0 and f["nrmssd"] == 0 and f["irregular"] == 0 and f["premature"] == 0


def test_one_early_beat_and_its_pause_count_once():
    f = dt.rr_features(times([1, 1, 1, 0.7, 1.3, 1, 1]))
    assert f["premature"] == 1 and f["irregular"] > 0


def test_a_random_rhythm_is_irregular():
    f = dt.rr_features(times(np.random.default_rng(3).uniform(0.4, 1.2, 30)))
    assert f["nrmssd"] > 0.2 and f["irregular"] > 0.5


def test_too_few_beats_and_a_flat_line_give_no_features():
    assert dt.rr_features([0.0, 1.0, 2.0]) == {}
    assert dt.features(np.zeros(1300), 130) == {}


def test_beats_are_found_at_130_hz():
    uv = np.rint(nk.ecg_simulate(duration=10, sampling_rate=130, heart_rate=70, noise=0.01, random_state=1) * 1000)
    f = dt.features(uv, 130)
    assert abs(f["bpm"] - 70) < 3 and f["premature"] == 0 and set(f) == set(dt.FEATURES)


def test_one_wide_beat_raises_odd_shape():
    fs, t = 130, np.arange(1300) / 130
    peaks = np.arange(65, 1235, 104)   # 75 bpm, every window inside the stretch

    def beat(c, width):
        return np.exp(-0.5 * ((t - c / fs) / width) ** 2)

    same = sum(beat(p, 0.012) for p in peaks)
    odd = same - beat(peaks[5], 0.012) + beat(peaks[5], 0.045)
    assert dt.odd_shape(same, peaks, fs) < 0.01
    assert dt.odd_shape(odd, peaks, fs) > 0.2


def test_a_fitted_model_separates_and_its_json_copy_scores_by_name(tmp_path):
    rng = np.random.default_rng(0)
    table = pd.DataFrame({"a": np.r_[rng.uniform(1, 2, 50), rng.uniform(-2, -1, 200)], "b": rng.normal(0, 1, 250)})
    y = np.r_[np.ones(50), np.zeros(200)]
    m = dt.Model.fit(table, y, ["a", "b"])
    s = m.score(table)
    assert s[:50].min() > s[50:].max()
    m.threshold = 0.7
    m.save(tmp_path / "m.json")
    back = dt.Model.load(tmp_path / "m.json")
    assert np.allclose(back.score(table[["b", "a"]]), s) and back.threshold == 0.7
```

- [ ] **Step 2: Run, expect `cannot import name 'detector'`.**

- [ ] **Step 3: Write `detector.py`**

```python
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
```

- [ ] **Step 4: Run, expect 7 passed.** Commit: "Rhythm feasibility: the lightweight detector".

---

### Task 4: Features for every stretch, and `evaluate.py`

**Files:** Create `research/rhythm/prepare.py`, `research/rhythm/evaluate.py`, `research/rhythm/tests/test_evaluate.py`.

**Interfaces:** `prepare` writes `data/cache/{ptbxl,cinc2017,mitbih,thomas}.csv`: one row per stretch and `version` (native, strap), the six features (NaN with too few beats) and the labels (PTB-XL: `ecg_id`, `split`, the six conditions, `norm`, `sbrad`, `stach`; CinC: `record`, `af`; MIT-BIH: `record`, `start_s`, `extra_beats`, `true_max_rr`, `true_n_rr`; Thomas: `record`, `start_s`). `evaluate` produces `scores(model, table)`, `fit_and_judge(ptb, outside, condition, names) -> (Model, row)`, writes `models/af.json`, `models/extra_beats.json`, `RESULTS.md`.

- [ ] **Step 1: Write the failing test** (`test_evaluate.py`)

```python
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
```

- [ ] **Step 2: Run, expect `cannot import name 'evaluate'`.**

- [ ] **Step 3: Write `prepare.py`**

```python
"""Features for every stretch, native and strap, cached as CSV in data/cache/.

python -m research.rhythm.prepare [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io
import wfdb

from research.rhythm import detector as dt
from research.rhythm import labels as lb
from research.rhythm import signals as sg

HERE = Path(__file__).parent
DATA = HERE / "data"
CACHE = DATA / "cache"
REPO = HERE.parents[1]
CINC_FS, CINC_GAIN = 300, 1000.0   # PhysioNet 2017 headers: 300 Hz, 1000 units per mV
WINDOW_S = 10


def both(x_mv, fs) -> list[dict]:
    """The features of one stretch, native and strap."""
    x = np.nan_to_num(np.asarray(x_mv, dtype=float))
    return [{"version": "native", **dt.features(np.rint(x * 1000), fs)},
            {"version": "strap", **dt.features(sg.to_strap_uv(x, fs), sg.STRAP_FS)}]


def ptbxl_record(job):
    path, ecg_id = job
    sig, fields = wfdb.rdsamp(path, channel_names=["I"])
    return [{"ecg_id": ecg_id, **row} for row in both(sig[:, 0], fields["fs"])]


def cinc_record(path):
    x = scipy.io.loadmat(path + ".mat")["val"][0] / CINC_GAIN
    return [{"record": Path(path).name, **row} for row in both(x, CINC_FS)]


def mitbih_record(path):
    sig, fields = wfdb.rdsamp(path, channel_names=["MLII"])
    ann = wfdb.rdann(path, "atr")
    fs, x = fields["fs"], sig[:, 0]
    win = lb.mitbih_windows(ann.symbol, ann.sample, ann.aux_note, fs, len(x))
    truth = lb.rr_windows(lb.beat_times(ann.symbol, ann.sample, fs), len(win))
    strap, n_strap = sg.to_strap_uv(x, fs), WINDOW_S * sg.STRAP_FS
    rows = []
    for k in range(len(win)):
        a, b = int(k * WINDOW_S * fs), int((k + 1) * WINDOW_S * fs)
        meta = {"record": Path(path).name, "start_s": k * WINDOW_S, "extra_beats": int(win.loc[k, "extra_beats"]),
                "true_max_rr": truth.loc[k, "max_rr"], "true_n_rr": int(truth.loc[k, "n_rr"])}
        rows.append({**meta, "version": "native", **dt.features(np.rint(x[a:b] * 1000), fs)})
        rows.append({**meta, "version": "strap", **dt.features(strap[k * n_strap:(k + 1) * n_strap], sg.STRAP_FS)})
    return rows


def thomas() -> pd.DataFrame:
    rows, n = [], WINDOW_S * sg.STRAP_FS
    for path in sorted((REPO / "data").glob("h10_ecg_*.csv")):
        uv = pd.read_csv(path)["ecg_uv"].to_numpy(dtype=float)
        for k in range(len(uv) // n):
            rows.append({"record": path.stem, "start_s": k * WINDOW_S, "version": "strap",
                         **dt.features(uv[k * n:(k + 1) * n], sg.STRAP_FS)})
    return table(rows)


def table(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in dt.FEATURES:
        if c not in df:
            df[c] = np.nan
    return df


def save(name: str, df: pd.DataFrame) -> None:
    df.to_csv(CACHE / f"{name}.csv", index=False)
    print(f"{name}: {len(df)} rows, {int(df['bpm'].isna().sum())} with too few beats", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="smoke run: this many records per dataset")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    root = next(DATA.glob("ptbxl/**/ptbxl_database.csv")).parent
    meta = lb.ptbxl_labels(pd.read_csv(root / "ptbxl_database.csv", index_col="ecg_id"))
    ref = lb.cinc2017_labels(pd.read_csv(DATA / "cinc2017_reference.csv", header=None, names=["record", "label"]))
    cinc_dir = next(DATA.glob("cinc2017/**/A00001.hea")).parent
    mit_dir = next(DATA.glob("mitdb/**/100.hea")).parent
    records = sorted(p.stem for p in mit_dir.glob("*.hea") if p.stem.isdigit() and p.stem not in lb.PACED)
    if args.limit:
        meta, ref, records = meta.iloc[:args.limit], ref.iloc[:args.limit], records[:2]
    with ProcessPoolExecutor() as pool:
        ptb = table(r for rows in pool.map(ptbxl_record, [(str(root / f), i) for i, f in meta["filename_hr"].items()],
                                           chunksize=64) for r in rows)
        cinc = table(r for rows in pool.map(cinc_record, [str(cinc_dir / r) for r in ref["record"]], chunksize=64)
                     for r in rows)
        mit = table(r for rows in pool.map(mitbih_record, [str(mit_dir / r) for r in records]) for r in rows)
    save("ptbxl", ptb.merge(meta.reset_index(), on="ecg_id"))
    save("cinc2017", cinc.merge(ref, on="record"))
    save("mitbih", mit)
    save("thomas", thomas())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `evaluate.py`**

```python
"""Fit the two models per version, judge every condition against the pass bar, write RESULTS.md and models/.

python -m research.rhythm.evaluate
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.rhythm import detector as dt
from research.rhythm import labels as lb
from research.rhythm import scoring as sc

HERE = Path(__file__).parent
CACHE = HERE / "data" / "cache"
MODELS = HERE / "models"
MODEL_CONDITIONS = {"af": dt.AF_FEATURES, "extra_beats": dt.EXTRA_FEATURES}
SLOW, FAST, PAUSE, LONG_PAUSE = 60.0, 100.0, 2.0, 3.0
NOT_ATTEMPTED = "flutter, first-degree AV block, long QT and WPW"


def scores(model: dt.Model, df: pd.DataFrame) -> np.ndarray:
    """Model scores; a stretch with too few beats scores 0, so it is flagged for nothing."""
    ok = df[model.names].notna().all(axis=1).to_numpy()
    s = np.zeros(len(df))
    if ok.any():
        s[ok] = model.score(df[ok])
    return s


def fit_and_judge(ptb: pd.DataFrame, outside, condition: str, names) -> tuple[dt.Model, dict]:
    """Fit on folds 1 to 8, set the threshold on fold 9, judge fold 10 and the outside set (y, df)."""
    train = ptb[(ptb["split"] == "train") & ptb[list(names)].notna().all(axis=1)]
    model = dt.Model.fit(train, train[condition], names)
    val, test = ptb[ptb["split"] == "val"], ptb[ptb["split"] == "test"]
    model.threshold = sc.threshold_for(val[condition], scores(model, val))
    main = sc.stats(test[condition], scores(model, test) > model.threshold)
    out = sc.stats(outside[0], scores(model, outside[1]) > model.threshold) if outside is not None else None
    norm = test[test["norm"] == 1]
    return model, {"main": main, "outside": out, "verdict": sc.verdict(main, out),
                   "norm_spec": sc.stats(norm[condition], scores(model, norm) > model.threshold)["spec"]}


def judge(ptb, cinc, mit, thomas) -> tuple[dict, dict]:
    """Every condition for one version. Returns (rows by condition, the fitted models)."""
    outside = {"af": (cinc.loc[cinc["af"] >= 0, "af"], cinc[cinc["af"] >= 0]),
               "extra_beats": (mit.loc[mit["extra_beats"] >= 0, "extra_beats"], mit[mit["extra_beats"] >= 0])}
    rows, models = {}, {}
    for cond, names in MODEL_CONDITIONS.items():
        models[cond], rows[cond] = fit_and_judge(ptb, outside[cond], cond, names)
        rows[cond]["thomas"] = int((scores(models[cond], thomas) > models[cond].threshold).sum())
    has = mit[mit["true_n_rr"] >= 1]
    found = has["max_rr"].fillna(0)
    for key, y, flags, th in (("slow", ptb["sbrad"], ptb["bpm"] < SLOW, thomas["bpm"] < SLOW),
                              ("fast", ptb["stach"], ptb["bpm"] > FAST, thomas["bpm"] > FAST),
                              ("pause", has["true_max_rr"] > PAUSE, found > PAUSE, thomas["max_rr"] > PAUSE)):
        main = sc.stats(y, flags)
        rows[key] = {"main": main, "outside": None, "verdict": sc.verdict(main), "norm_spec": float("nan"),
                     "thomas": int(th.sum())}
    rows["pause3"] = sc.stats(has["true_max_rr"] > LONG_PAUSE, found > LONG_PAUSE)
    rows["too_few"] = {n: int(d["bpm"].isna().sum()) for n, d in (("PTB-XL", ptb), ("PhysioNet 2017", cinc),
                                                                     ("MIT-BIH", mit))}
    return rows, models


def pct(x) -> str:
    return "n/a" if x is None or x != x else f"{100 * x:.1f}%"


def write(strap: dict, native: dict, n_thomas: int) -> str:
    lines = ["# Rhythm feasibility: results", "",
             "Generated by `python -m research.rhythm.evaluate`; spec `docs/superpowers/specs/2026-10-10-rhythm-feasibility-design.md`. "
             "The pass bar was fixed before any run: the strap version must keep the 95% lower bound of specificity at or "
             "above 97% and catch at least 80% of cases, on the test set and on the outside set where there is one, with at "
             "least 50 cases. Model thresholds leave 98% of PTB-XL fold 9's negatives unflagged.", "",
             "| Condition | Verdict at 130 Hz | Cases | Strap: caught | Strap: unflagged (95% range) | Normal ECGs unflagged "
             "| Native rate: caught, unflagged | Outside (strap): caught, unflagged lower bound | Flags on Thomas's strap |",
             "|---|---|---|---|---|---|---|---|---|"]
    for key in ("af", "extra_beats", "slow", "fast", "pause"):
        s, n = strap[key], native[key]
        m, o = s["main"], s["outside"]
        lines.append(f"| {lb.NAMES[key]} | {s['verdict']} | {m['positives']} | {pct(m['sens'])} | "
                     f"{pct(m['spec'])} ({pct(m['spec_lo'])} to {pct(m['spec_hi'])}) | {pct(s['norm_spec'])} | "
                     f"{pct(n['main']['sens'])}, {pct(n['main']['spec'])} | "
                     f"{pct(o['sens']) if o else 'n/a'}, {pct(o['spec_lo']) if o else 'n/a'} | {s['thomas']} of {n_thomas} |")
    p3 = strap["pause3"]
    few = ", ".join(f"{k} {v}" for k, v in strap["too_few"].items())
    lines += ["", f"Pauses over 3 s: {p3['positives']} windows, caught {pct(p3['sens'])}, unflagged {pct(p3['spec'])}.",
              f"Stretches with too few beats (strap version, flagged for nothing): {few}.",
              f"Not attempted: {NOT_ATTEMPTED}. They depend on wave timing or shape that 130 Hz blurs.",
              "Slow rate, fast rate and pauses use fixed cutoffs (under 60 bpm, over 100 bpm, an RR over 2.0 s), not a "
              "model. A pass here is necessary, not sufficient, for showing a flag: the strap's own lead and noise were "
              "not modelled. This is not a medical device.", ""]
    text = "\n".join(lines)
    (HERE / "RESULTS.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    data = {n: pd.read_csv(CACHE / f"{n}.csv") for n in ("ptbxl", "cinc2017", "mitbih", "thomas")}
    out = {}
    for v in ("native", "strap"):
        part = {n: d[d["version"] == v] for n, d in data.items()}
        out[v] = judge(part["ptbxl"], part["cinc2017"], part["mitbih"], part["thomas"])
    MODELS.mkdir(exist_ok=True)
    for cond, model in out["strap"][1].items():
        model.save(MODELS / f"{cond}.json")
    print(write(out["strap"][0], out["native"][0], len(data["thomas"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the test, expect 1 passed:** `.venv/Scripts/python -m pytest -q research/rhythm/tests/test_evaluate.py`

- [ ] **Step 6: The research environment** (no torch; replace any earlier one)

```bash
cd /c/Users/barre/CardioView && rm -rf .venv-research && py -3.12 -m venv .venv-research
.venv-research/Scripts/python -m pip install -q -r research/rhythm/requirements.txt
```

- [ ] **Step 7: Smoke, then the full run**

`.venv-research/Scripts/python -m research.rhythm.prepare --limit 100` then `.venv-research/Scripts/python -m research.rhythm.evaluate`. Expected: four `rows` lines and a table (verdicts mostly "not enough data" at this size), no exception. Then the full `prepare` (a few minutes on 16 cores; expected rows: PTB-XL 43598, PhysioNet 2017 about 17056, MIT-BIH about 15840) and `evaluate`. Check one number by hand: AF `Cases` equals the AF count in PTB-XL fold 10.

- [ ] **Step 8: Commit** `prepare.py`, `evaluate.py`, the test, `RESULTS.md`, `models/af.json`, `models/extra_beats.json`: "Rhythm feasibility: features, the two models and the verdict".

---

### Task 5: `publish.py`, the Hugging Face card

**Files:** Create `research/rhythm/publish.py`, `research/rhythm/tests/test_publish.py`.

**Interfaces:** `card(results: str, license_id: str) -> str`; CLI writes `models/README.md`; `--upload` creates `<user>/cardioview-rhythm-detector` and uploads `models/` with `HF_TOKEN` from `.env`.

- [ ] **Step 1: Write the failing test** (`test_publish.py`)

```python
"""The model card says what the models are, what they are not, and carries the results."""
from research.rhythm import publish


def test_the_card_carries_the_results_and_the_plain_statements():
    results = "# Rhythm feasibility: results\n\n| Condition | Verdict at 130 Hz |\n|---|---|\n| Atrial fibrillation | pass |\n"
    text = publish.card(results, "mit")
    assert text.startswith("---\nlicense: mit\n")
    assert "| Atrial fibrillation | pass |" in text and "# Rhythm feasibility: results" not in text
    assert "not a medical device" in text and "PTB-XL" in text and "CC BY 4.0" in text
```

- [ ] **Step 2: Run, expect `cannot import name 'publish'`.**

- [ ] **Step 3: Write `publish.py`**

```python
"""The Hugging Face model card, and the upload. Publishing is public: it uploads only with --upload.

python -m research.rhythm.publish            writes models/README.md, the card, to read first
python -m research.rhythm.publish --upload   uploads models/ to <your account>/cardioview-rhythm-detector
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
MODELS = HERE / "models"
REPO_NAME = "cardioview-rhythm-detector"

BODY = """
# CardioView rhythm detector

Two tiny logistic models, `af.json` and `extra_beats.json`, that flag atrial fibrillation and extra beats from one chest-strap ECG lead sampled the way the Polar H10 samples it: 130 Hz, integer microvolts. They belong to CardioView, a KnightHacks IX project that shows a visitor's heart beating in 3D.

**This is not a medical device.** CardioView shows a visitor a condition only when it passes the bar below, and never as a diagnosis.

## How it works

NeuroKit2 cleans the stretch and finds R peaks without artifact correction (correction would move early beats back into line). From the beat-to-beat intervals and the beats come six features: `bpm`, `max_rr`, `nrmssd` (RMS of successive differences over the mean interval), `irregular` (share of successive differences over 15% of the median), `premature` (an interval under 85% of the median followed by one over 110%) and `odd_shape` (one minus the lowest correlation of a beat with the median beat). Each model is a logistic regression on standardized features: `score = sigmoid(sum(weights * (x - mean) / scale) + bias)`, flagged above `threshold`. The feature code is `research/rhythm/detector.py` in the CardioView repository.

## Results
{results}
## Data

- PTB-XL 1.0.3 (Wagner et al., PhysioNet), lead I: fitting, threshold and test folds. CC BY 4.0.
- PhysioNet/CinC Challenge 2017 training set: the outside test for atrial fibrillation. Open Data Commons Attribution 1.0.
- MIT-BIH Arrhythmia Database (Moody and Mark, PhysioNet): the outside test for extra beats and pauses. Open Data Commons Attribution 1.0.

Every stretch was also resampled to 130 Hz and rounded to integer microvolts, the strap version these models were fitted on.
"""


def card(results: str, license_id: str) -> str:
    body = results.split("\n", 1)[1] if results.startswith("# ") else results   # the card has its own title
    return f"---\nlicense: {license_id}\ntags: [ecg, arrhythmia, atrial-fibrillation, wearable, polar-h10]\n---\n" + BODY.replace("{results}", body)


def upload() -> None:
    from huggingface_hub import HfApi

    from backend.env import load_dotenv
    load_dotenv()
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN (a write token) is not in .env")
    api = HfApi(token=token)
    repo = f"{api.whoami()['name']}/{REPO_NAME}"
    api.create_repo(repo, repo_type="model", exist_ok=True)
    api.upload_folder(folder_path=str(MODELS), repo_id=repo, repo_type="model")
    print(f"published: https://huggingface.co/{repo}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--license", default="mit")
    args = ap.parse_args(argv)
    (MODELS / "README.md").write_text(card((HERE / "RESULTS.md").read_text(encoding="utf-8"), args.license),
                                      encoding="utf-8")
    print(f"card: {MODELS / 'README.md'}")
    if args.upload:
        upload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, expect 1 passed.** Then `.venv-research/Scripts/python -m research.rhythm.publish` writes the card. Check the repo's license (`LICENSE` on main) for `--license`; if there is none, ask the user. Commit `publish.py`, the test and `models/README.md`: "Rhythm feasibility: the Hugging Face model card". The upload waits for the user (needs `HF_TOKEN`, a write token, in `.env`).

---

### Task 6: Docs and the final checks

**Files:** Create `research/rhythm/README.md`; modify `README.md`, `CLAUDE.md`.

- [ ] **Step 1: `research/rhythm/README.md`**

```markdown
# Rhythm feasibility test

Which heart conditions can a lightweight detector find from one chest-strap lead at 130 Hz? Uncorrected NeuroKit2 beats, six rhythm features and two tiny logistic models, tested on PTB-XL, PhysioNet 2017 and MIT-BIH at each dataset's own rate and at the strap's 130 Hz integer microvolts, against a pass bar fixed before any run. Results: [RESULTS.md](RESULTS.md). Models and card: [models/](models/). Research only: nothing here reaches the booth yet.

## Run it (Windows paths; on Mac and Linux use `.venv-research/bin/python`)

    py -3.12 -m venv .venv-research
    .venv-research/Scripts/python -m pip install -r research/rhythm/requirements.txt
    .venv-research/Scripts/python -m research.rhythm.download    # about 2 GB from PhysioNet
    .venv-research/Scripts/python -m research.rhythm.prepare     # features, a few minutes
    .venv-research/Scripts/python -m research.rhythm.evaluate    # models/ and RESULTS.md
    .venv-research/Scripts/python -m research.rhythm.publish     # the model card; --upload publishes it

Data: PTB-XL 1.0.3, PhysioNet/CinC Challenge 2017, MIT-BIH Arrhythmia Database (PhysioNet). This is not a medical device.
```

- [ ] **Step 2: README pointer and the CLAUDE.md outcome**

README, after the saved sessions section: `The rhythm feasibility test (which conditions a 130 Hz strap lead can detect) lives in research/rhythm/; see its README.` CLAUDE.md, a bullet in the Rhythm feasibility section with the outcome from RESULTS.md (which conditions pass, fail, or lack data); stay under 200 lines.

- [ ] **Step 3: Final checks:** `.venv/Scripts/python -m pytest -q` (all pass), the dash check on `--changed`, `git status` shows nothing from `data/`, no push.

- [ ] **Step 4: Commit:** "Rhythm feasibility: README and the outcome in CLAUDE.md".

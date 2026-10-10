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

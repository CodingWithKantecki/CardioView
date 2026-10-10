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

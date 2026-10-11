"""tools/rhythm_model/data.py: the labeled windows the demo-pattern classifier trains on."""
import itertools

import numpy as np
import pytest

from backend.sources.base import FS
from backend.sources.rhythm import RhythmSource
from tools.rhythm_model import data as D


def test_splits_hold_out_whole_recordings():
    seeds = {s: set(D.split_seeds(s, 500)) for s in D.SEED_BASE}
    for a, b in itertools.combinations(seeds, 2):
        assert not seeds[a] & seeds[b], f"{a} and {b} share a seed"
    a, b = D.recording("afib", 7), D.recording("afib", 7)
    assert np.array_equal(a.uv, b.uv), "one seed is one recording"
    assert not np.array_equal(D.recording("afib", 8).uv, a.uv)
    assert not np.array_equal(D.recording("sinus", 7).uv[:500], D.recording("brady", 7).uv[:500])


@pytest.mark.parametrize("cls", D.CLASSES)
def test_recordings_look_like_the_strap(cls):
    r = D.recording(cls, 3)
    assert r.uv.dtype == np.int32 and len(r.uv) == int(D.RECORDING_S * FS)
    assert np.abs(r.uv).max() <= D.CLIP_UV
    assert list(D.windows(r)), "every class yields windows"


@pytest.mark.parametrize("cls", [c for c in D.CLASSES if c != "none"])
def test_rates_and_timing_follow_the_class(cls):
    lo, hi = D.RATES[cls]
    for seed in range(20):
        beats, ectopic = D._beats(cls, np.random.default_rng([seed, 0]), 40)
        rr = np.diff([b[0] for b in beats])
        cv = rr.std() / rr.mean()
        if cls in ("pvc", "mi"):
            assert ectopic or cls == "mi"
            continue
        assert lo - 6 <= 60 / np.median(rr) <= hi + 6
        if cls == "afib":
            assert cv > 0.12, "atrial fibrillation is irregular"
        else:
            assert cv < 0.1, "the regular rhythms stay regular"


def test_rates_are_randomized_per_recording():
    rates = [60 / np.median(np.diff([b[0] for b in D._beats("sinus", np.random.default_rng(s), 40)[0]])) for s in range(30)]
    assert max(rates) - min(rates) > 40


def test_extra_beat_windows_hold_an_extra_beat():
    for seed in range(10):
        r = D.recording("pvc", seed)
        for s, _ in D.windows(r):
            t0 = s / FS
            assert any(t0 <= e <= t0 + D.WINDOW_S for e in r.ectopic)


def test_demo_windows_come_from_the_demo_source():
    r = D.demo_recording("vt", 4, seconds=20)
    ref = list(itertools.islice(RhythmSource("vt", seed=4)._samples, 20 * FS))
    assert r.uv.tolist() == ref
    mi = D.demo_recording("mi", 4, seconds=40)
    starts = [s / FS for s, _ in D.windows(mi)]
    assert starts and min(starts) >= D.MI_DEVELOPED * 20.0, "a heart attack window needs its ST elevation"
    assert np.array_equal(D.demo_recording("sinus", 1, 10, invert=True).uv, -D.demo_recording("sinus", 1, 10).uv)


def test_prepare_fills_twelve_leads_at_100_hz():
    r = D.recording("sinus", 2)
    x = D.prepare(r.uv[: int(D.WINDOW_S * FS)])
    assert x.shape == (2, 12 * 500) and x.dtype == np.float32
    assert -1.0 <= x.min() and x.max() <= 1.0
    leads = x[0].reshape(12, 500)
    assert np.allclose(leads, leads[0]), "the one strap lead fills every lead slot"
    flat = D.prepare(np.zeros(int(D.WINDOW_S * FS), dtype=np.int32))
    assert np.isfinite(flat).all()

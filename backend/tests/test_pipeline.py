import neurokit2 as nk
import numpy as np
import pytest

from backend.pipeline import BeatDetector
from backend.sources.base import FS, PACKET, Packet
from backend.sources.sim import simulate


def packets(values, first_index=0):
    values = list(values)
    for k in range(0, len(values) - PACKET + 1, PACKET):
        yield Packet((first_index + k) / FS, values[k:k + PACKET])


def reference_peaks(values):
    clean = nk.ecg_clean(np.asarray(values, dtype=float), sampling_rate=FS)
    _, info = nk.ecg_peaks(clean, sampling_rate=FS)
    return np.asarray(info["ECG_R_Peaks"], dtype=float) / FS


@pytest.mark.parametrize("bpm", [60, 90, 140])
def test_sim_every_beat_once_and_on_time(bpm):
    values = simulate(bpm, seconds=60)
    det = BeatDetector()
    beats, latency = [], []
    for p in packets(values):
        for b in det.feed(p):
            beats.append(b)
            latency.append(p.t_last - b.r)
    assert beats, "no beats emitted"
    got = np.array([b.r for b in beats])
    ref = reference_peaks(values)
    ref = ref[(ref >= got[0] - 0.05) & (ref <= got[-1] + 0.05)]
    for r in ref:
        hits = int(np.sum(np.abs(got - r) <= 0.05))
        assert hits == 1, f"reference peak at {r:.3f} s matched {hits} emitted beats"
    assert len(got) == len(ref), "extra beats emitted"
    assert max(latency) <= 0.9
    bpms = [b.bpm for b in beats if b.bpm is not None]
    assert abs(np.median(bpms[5:]) - bpm) <= 2
    assert all(b.v_on == -0.04 and 0.20 <= b.v_off <= 0.42 for b in beats)
    assert all(-0.32 <= b.ra_on <= -0.10 and b.la_on == pytest.approx(b.ra_on + 0.03) for b in beats)


def test_p_wave_found_on_sim():
    values = simulate(72, seconds=40)
    det = BeatDetector()
    beats = [b for p in packets(values) for b in det.feed(p)]
    assert sum(b.p_found for b in beats) >= len(beats) // 2


def test_jump_restamps_beats():
    values = simulate(72, seconds=40)
    det = BeatDetector()
    before = []
    cut = 20 * FS
    for p in packets(values[:cut]):
        before += det.feed(p)
    assert before
    first_index = cut + 47 * FS           # stream time jumps 47 s ahead
    after = []
    for p in packets(values[cut:], first_index=first_index):
        for b in det.feed(p):
            after.append((p, b))
    assert after, "no beats after the jump"
    for p, b in after:
        assert b.r >= first_index / FS
        assert p.t_last - 1.0 <= b.r <= p.t_last


@pytest.mark.parametrize("bpm", [60, 140])
def test_prime_then_feed_finds_every_beat_once(bpm):
    values = list(simulate(bpm, seconds=40))
    det = BeatDetector()
    n = 17 * PACKET                     # a 10 s preroll, as the runner builds it
    beats = det.prime(Packet(0.0, values[:n]))
    assert len(beats) >= 8, "the preroll carries its beats"
    for p in packets(values[n:], first_index=n):
        beats += det.feed(p)
    got = np.array([b.r for b in beats])
    assert np.all(np.diff(got) > 0.25), "no beat emitted twice across the preroll boundary"
    ref = reference_peaks(values)
    ref = ref[(ref >= got[0] - 0.05) & (ref <= got[-1] + 0.05)]
    for r in ref:
        assert int(np.sum(np.abs(got - r) <= 0.05)) == 1, f"reference peak at {r:.3f} s matched wrong"
    assert len(got) == len(ref)

import numpy as np

from backend.pipeline import BeatDetector, SignalMonitor
from backend.sources.base import FS, PACKET, Packet
from backend.sources.sim import simulate


def packets(values, first_index=0):
    values = list(values)
    for k in range(0, len(values) - PACKET + 1, PACKET):
        yield Packet((first_index + k) / FS, values[k:k + PACKET])


def run(values, monitor=None, detector=None, first_index=0):
    monitor = monitor or SignalMonitor()
    detector = detector or BeatDetector()
    changes = []
    for p in packets(values, first_index):
        beats = detector.feed(p)
        c = monitor.update(p, beats)
        if c is not None:
            changes.append((round(p.t_last, 2), c.ok, c.reason))
    return monitor, detector, changes


def test_clean_signal_stays_ok():
    monitor, _, changes = run(simulate(72, seconds=30))
    assert changes == []
    assert monitor.signal.ok


def test_clipping_reports_pads_then_recovers():
    clean = list(simulate(72, seconds=30))
    bad = [19930 if i % 3 else -19930 for i in range(6 * FS)]
    monitor, detector, changes = run(clean[:15 * FS] + bad + clean[15 * FS:])
    assert changes[0][1] is False and changes[0][2] == "pads"
    assert 15.0 <= changes[0][0] <= 16.5, "lost should be reported within about a second"
    assert changes[-1][1] is True, "should recover on clean signal"
    assert changes[-1][0] >= 21 + 2.0


def test_flat_line_and_noise_reasons():
    _, _, flat = run([0] * (5 * FS))
    assert flat and flat[0][1] is False and flat[0][2] == "pads"
    rng = np.random.default_rng(1)
    _, _, noisy = run([int(v) for v in rng.uniform(-5000, 5000, 5 * FS)])
    assert noisy and noisy[0][1] is False and noisy[0][2] == "noise"


def test_no_beats_when_the_signal_is_just_hum():
    t = np.arange(10 * FS) / FS
    hum = [int(300 * np.sin(2 * np.pi * 1.0 * x)) for x in t]   # a slow wobble, no QRS
    _, _, changes = run(hum)
    assert changes and changes[0][1] is False
    assert changes[0][2] in ("no_beats", "pads")


def test_jump_resets_without_a_false_alarm():
    values = list(simulate(72, seconds=30))
    monitor, detector, changes = run(values[:15 * FS])
    _, _, after = run(values[15 * FS:], monitor, detector, first_index=15 * FS + 47 * FS)
    assert changes == [] and after == []

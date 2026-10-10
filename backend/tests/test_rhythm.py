import asyncio

import numpy as np
import pytest

from backend.pipeline import BeatDetector, SignalMonitor
from backend.sources.base import FS, PACKET, Packet
from backend.sources.rhythm import LABELS, RhythmSource


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def beats_for(pattern, seconds=30):
    clk = FakeClock()
    src = RhythmSource(pattern, sleep=clk.sleep, now=clk.now)

    async def run():
        out = []
        async for p in src.packets():
            out.append(p)
            if len(out) * PACKET >= seconds * FS:
                break
        return out
    packets = asyncio.run(run())
    det = BeatDetector()
    mon = SignalMonitor()
    beats, lost = [], []
    for p in packets:
        new = det.feed(p)
        beats += new
        if mon.update(p, new) is not None:
            lost.append(p.t)
    return beats, lost, packets


@pytest.mark.parametrize("pattern,lo,hi", [("sinus", 66, 78), ("tachy", 130, 150), ("brady", 38, 48), ("vt", 140, 160), ("mi", 92, 108)])
def test_rates_land_where_the_pattern_says(pattern, lo, hi):
    beats, lost, _ = beats_for(pattern)
    bpms = [b.bpm for b in beats if b.bpm]
    assert lo <= np.median(bpms[5:]) <= hi
    assert lost == [], "a simulated rhythm must never read as no signal"


def test_afib_is_irregular_and_pvcs_come_early():
    beats, _, _ = beats_for("afib", 40)
    rr = np.diff([b.r for b in beats])
    assert rr.std() > 0.12
    beats, _, _ = beats_for("pvc", 30)
    rr = np.diff([b.r for b in beats])
    assert (rr < 0.62).sum() >= 3 and (rr > 1.0).sum() >= 3


def test_heart_attack_lifts_the_st_segment_as_it_builds():
    from backend.sources.rhythm import infarct

    def after_r(k, s=0.10):   # mV at s seconds after the R peak
        return sum(a * np.exp(-((s - c) ** 2) / (2 * w * w)) for c, a, w in infarct(k))
    assert after_r(0) < 0.05 and after_r(1) > 0.35
    assert after_r(0.5) < after_r(1)


def test_labels_and_amplitude():
    clk = FakeClock()
    assert RhythmSource("sinus", sleep=clk.sleep, now=clk.now).status.device == "Simulated: Normal rhythm"
    src = RhythmSource("vt", sleep=clk.sleep, now=clk.now)
    assert src.status.device == "Simulated: Ventricular tachycardia"
    assert set(LABELS) == {"sinus", "tachy", "brady", "afib", "pvc", "vt", "mi"}
    amp = max(abs(v) for v in list(__import__("itertools").islice(src._stream(), 5 * FS)))
    assert 500 <= amp <= 800, "R peaks should sit near the strap's 600 uV"


def test_takeover_plays_out_the_old_beat_and_eases_into_the_new_rate():
    from backend.pipeline import BeatDetector
    from backend.sources.base import FS, Packet
    from backend.sources.rhythm import NORMAL, RhythmSource

    src = RhythmSource("brady")
    t0 = 20.0
    src.takeover(index=int(t0 * FS), last_uv=0, last_r=19.7, rr=0.80, template=NORMAL)
    uv = [next(src._samples) for _ in range(int(12 * FS))]
    assert uv[0] > 50, "the old beat's T wave is still playing out at the join"
    pad = int(2 * FS)
    beats = BeatDetector(delineate=False).prime(Packet(t0 - 2.0, [0] * pad + uv))
    rs = [b.r for b in beats if b.r > t0 + 0.1]   # the step from the flat pad into the T wave is not a beat
    assert rs and rs[0] == pytest.approx(19.7 + 0.95, abs=0.03), "the first beat lands one eased interval after the old last beat"
    rr = [b - a for a, b in zip(rs, rs[1:])]
    assert 1.03 < rr[0] < 1.17 and 1.17 < rr[1] < 1.33, "the interval glides toward bradycardia"
    assert all(1.25 < x < 1.55 for x in rr[2:6]), "then it is bradycardia"

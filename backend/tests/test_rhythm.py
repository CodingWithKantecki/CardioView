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


@pytest.mark.parametrize("pattern,lo,hi", [("sinus", 66, 78), ("tachy", 130, 150), ("brady", 38, 48), ("vt", 140, 160)])
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


def test_labels_and_amplitude():
    clk = FakeClock()
    assert RhythmSource("sinus", sleep=clk.sleep, now=clk.now).status.device == "Simulated: Sinus rhythm"
    src = RhythmSource("vt", sleep=clk.sleep, now=clk.now)
    assert src.status.device == "Simulated: Ventricular tachycardia"
    assert set(LABELS) == {"sinus", "tachy", "brady", "afib", "pvc", "vt"}
    amp = max(abs(v) for v in list(__import__("itertools").islice(src._stream(), 5 * FS)))
    assert 500 <= amp <= 800, "R peaks should sit near the strap's 600 uV"

import asyncio

import pytest

from backend.sources.base import FS, PACKET, PACKET_S
from backend.sources.replay import ReplaySource
from backend.sources.sim import SimSource


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def take(source, n):
    async def run():
        out = []
        async for p in source.packets():
            out.append(p)
            if len(out) == n:
                break
        return out
    return asyncio.run(run())


def test_sim_is_paced_like_the_strap():
    clk = FakeClock()
    src = SimSource(bpm=72, sleep=clk.sleep, now=clk.now)
    pk = take(src, 5)
    assert [len(p.uv) for p in pk] == [PACKET] * 5
    assert [p.t for p in pk] == pytest.approx([k * PACKET_S for k in range(5)])
    assert sum(clk.sleeps) == pytest.approx(5 * PACKET_S)
    assert src.kind == "simulated"
    assert src.status.state == "streaming"
    assert max(abs(v) for v in pk[0].uv) > 100   # microvolts, not millivolts


def test_replay_loops_and_keeps_counting(tmp_path):
    path = tmp_path / "h10_ecg_test.csv"
    n = 100
    path.write_text("time_s,ecg_uv\n" + "".join(f"{i / FS:.6f},{i}\n" for i in range(n)))
    clk = FakeClock()
    src = ReplaySource(str(path), sleep=clk.sleep, now=clk.now)
    pk = take(src, 3)
    flat = [v for p in pk for v in p.uv]
    assert flat == [i % n for i in range(3 * PACKET)]
    assert [p.t for p in pk] == pytest.approx([k * PACKET_S for k in range(3)])
    assert src.kind == "recorded"
    assert "h10_ecg_test" in src.status.device


def test_invert_flips_the_signal():
    a = take(SimSource(bpm=72, invert=True, sleep=FakeClock().sleep, now=FakeClock().now), 1)[0].uv
    b = take(SimSource(bpm=72, sleep=FakeClock().sleep, now=FakeClock().now), 1)[0].uv
    assert a == [-v for v in b]


def test_seed_continues_the_stream_clock():
    clk = FakeClock()
    src = SimSource(bpm=72, sleep=clk.sleep, now=clk.now)
    src.seed(1300, clk.now() - 0.2)      # the previous source sent sample 1299 a fifth of a second ago
    pk = take(src, 2)
    assert pk[0].t == pytest.approx(1300 / FS)
    assert pk[1].t == pytest.approx(1300 / FS + PACKET_S)
    assert clk.sleeps[0] == pytest.approx(PACKET_S - 0.2, abs=1e-6), "the next packet is due one packet after the last one"

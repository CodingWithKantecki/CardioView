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


def test_preroll_emits_history_at_once_then_paces():
    clk = FakeClock()
    src = SimSource(bpm=72, preroll_s=5.0, sleep=clk.sleep, now=clk.now)
    pk = take(src, 10)
    assert [p.t for p in pk] == pytest.approx([k * PACKET_S for k in range(10)])
    # the packets already due (8 of them for 5 s) come without sleeping, then pacing resumes exactly
    assert len(clk.sleeps) == 2
    assert clk.sleeps[0] == pytest.approx(9 * PACKET_S - 5.0)
    assert clk.sleeps[1] == pytest.approx(PACKET_S)


def test_anchor_continues_another_clock():
    clk = FakeClock()
    src = SimSource(bpm=72, sleep=clk.sleep, now=clk.now)
    src.index = 650                          # stream time 5.0 s
    src.anchor(5.0, clk.now() + 0.3)         # which is due 0.3 s from now
    pk = take(src, 1)
    assert pk[0].t == pytest.approx(5.0)
    assert clk.sleeps[0] == pytest.approx(0.3 + PACKET_S)


def test_takeover_meets_the_old_value_then_fades():
    from backend.sources.sim import simulate

    clk = FakeClock()
    src = SimSource(bpm=72, sleep=clk.sleep, now=clk.now)
    src.takeover(index=5 * PACKET, last_uv=-300)
    pkts = take(src, 3)
    raw = list(simulate(72))
    assert pkts[0].t == pytest.approx(5 * PACKET / FS), "stream time runs on from the join"
    assert pkts[0].uv[0] == -300, "the first sample is the old stream's last value"
    assert abs(pkts[0].uv[-1] - raw[PACKET - 1]) <= 1, "half a second later the step is down to a microvolt"
    assert pkts[2].uv == raw[2 * PACKET:3 * PACKET]


def test_replay_takeover_starts_where_the_next_peak_fits(tmp_path):
    from backend.sources.replay import peaks_of
    from backend.sources.rhythm import RhythmSource

    gen = RhythmSource("sinus")._samples
    values = [next(gen) for _ in range(int(20 * FS))]
    path = tmp_path / "h10_ecg_test.csv"
    path.write_text("time_s,ecg_uv\n" + "".join(f"{i / FS:.4f},{v}\n" for i, v in enumerate(values)))
    peaks = peaks_of(str(path))
    assert len(peaks) >= 15
    clk = FakeClock()
    src = ReplaySource(path, sleep=clk.sleep, now=clk.now)
    t0 = 40.0
    src.takeover(index=int(t0 * FS), last_uv=0, last_r=39.6, rr=0.8)   # so the next beat is wanted 0.4 s after the join
    assert any(p - src.start_s == pytest.approx(0.4, abs=1e-6) for p in peaks), "a peak lands one interval after the old last beat"
    assert src.start_s >= 0.6, "never the file's first second"
    first = take(src, 1)[0]
    s0 = int(round(src.start_s * FS))
    assert first.t == pytest.approx(t0)
    assert first.uv[0] == 0 and first.uv[-1] == values[s0 + PACKET - 1]

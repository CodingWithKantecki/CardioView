"""sources/h10.py against a fake BleakClient, so bleakheart's real decoder runs."""
import asyncio

import pytest

from backend.pipeline import BeatDetector
from backend.sources.base import FS, PACKET, PACKET_S
from backend.sources.h10 import H10Source, is_h10
from backend.sources.sim import simulate

CTRL = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8".lower()
DATA = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8".lower()
BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
START_ECG = bytes.fromhex("02000001820001010e00")
STOP_ECG = bytes.fromhex("0300")


def ecg_frame(samples, t_ns=123_456_789):
    body = b"".join(int(v).to_bytes(3, "little", signed=True) for v in samples)
    return bytearray([0x00]) + t_ns.to_bytes(8, "little") + bytearray([0x00]) + body


class FakeDevice:
    name = "Polar H10 223FD838"
    address = "AAAA-BBBB"


class FakeClient:
    """Answers bleakheart's control writes and pushes ECG frames, then optionally drops."""

    def __init__(self, device, disconnected_callback=None, frames=(), battery=87, drop=False):
        self.device = device
        self.on_drop = disconnected_callback
        self.frames = list(frames)
        self.battery = battery
        self.drop = drop
        self.handlers = {}
        self.writes = []
        self.connected = False

    async def __aenter__(self):
        self.connected = True
        return self

    async def __aexit__(self, *exc):
        self.connected = False
        return False

    async def start_notify(self, uuid, handler):
        self.handlers[str(uuid).lower()] = handler

    async def read_gatt_char(self, uuid):
        assert str(uuid).lower() == BATTERY
        return bytearray([self.battery])

    async def write_gatt_char(self, uuid, data, response=None):
        assert str(uuid).lower() == CTRL
        self.writes.append(bytes(data))
        cmd, meas = data[0], data[1]
        loop = asyncio.get_running_loop()
        loop.create_task(self.handlers[CTRL](None, bytearray([0xF0, cmd, meas, 0x00, 0x00])))
        if cmd == 0x02:
            loop.create_task(self._feed())

    async def _feed(self):
        for frame in self.frames:
            await asyncio.sleep(0)
            await self.handlers[DATA](None, frame)
        if self.drop and self.on_drop:
            await asyncio.sleep(0)
            self.on_drop(self)


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s
        await asyncio.sleep(0)


def collect(source, n):
    async def run():
        out = []
        async for p in source.packets():
            out.append(p)
            if len(out) == n:
                break
        return out
    return asyncio.run(run())


def make_source(clients, clk, **kw):
    """clients: list of FakeClient factories used in order on each connect."""
    it = iter(clients)

    def factory(device, disconnected_callback=None):
        return next(it)(device, disconnected_callback)

    async def scanner():
        return FakeDevice()

    return H10Source(scanner=scanner, client_factory=factory, sleep=clk.sleep, now=clk.now, **kw)


def test_filter_matches_by_name():
    class Adv:
        local_name = "Polar H10 223FD838"

    class Dev:
        name = None
    assert is_h10(Dev(), Adv())
    Adv.local_name = "Garmin"
    assert not is_h10(Dev(), Adv())


def test_decode_battery_and_status():
    clk = FakeClock()
    samples = list(range(-36, 37))
    frames = [ecg_frame(samples), ecg_frame([1000, -1000, 8388607, -8388608] + [0] * 69)]
    made = []

    def factory(device, cb):
        c = FakeClient(device, cb, frames=frames)
        made.append(c)
        return c
    src = make_source([factory], clk)
    states = []
    src.on_status(lambda s: states.append((s.state, s.device)))
    pk = collect(src, 2)
    assert pk[0].uv == samples
    assert pk[1].uv == [1000, -1000, 8388607, -8388608] + [0] * 69
    assert pk[0].t == 0 and pk[1].t == pytest.approx(PACKET_S)
    assert src.battery == 87
    assert made[0].writes[0] == START_ECG
    assert states[0] == ("connecting", "")
    assert states[1] == ("streaming", "Polar H10 223FD838")
    assert src.kind == "live"


def test_invert_flips_samples():
    clk = FakeClock()
    src = make_source([lambda d, cb: FakeClient(d, cb, frames=[ecg_frame([5, -7, 9] + [0] * 70)])], clk, invert=True)
    assert collect(src, 1)[0].uv[:3] == [-5, 7, -9]


def test_reconnect_advances_stream_time_and_detector_restamps():
    values = simulate(72, seconds=30)
    chunks = [values[k:k + PACKET] for k in range(0, len(values) - PACKET + 1, PACKET)]
    first, second = chunks[:12], chunks[12:24]
    clk = FakeClock()
    outage = 12.0

    class SlowScanner:
        calls = 0

    async def scanner():
        SlowScanner.calls += 1
        if SlowScanner.calls > 1:
            clk.t += outage          # the strap was off for a while
        return FakeDevice()

    clients = iter([
        lambda d, cb: FakeClient(d, cb, frames=[ecg_frame(c) for c in first], drop=True),
        lambda d, cb: FakeClient(d, cb, frames=[ecg_frame(c) for c in second]),
    ])
    src = H10Source(scanner=scanner, client_factory=lambda d, disconnected_callback=None: next(clients)(d, disconnected_callback),
                    sleep=clk.sleep, now=clk.now, backoff_s=1.0)
    states = []
    src.on_status(lambda s: states.append(s.state))
    pk = collect(src, 24)
    assert [s for s in states] == ["connecting", "streaming", "reconnecting", "streaming"]
    # packets before the drop are contiguous
    for a, b in zip(pk[:11], pk[1:12]):
        assert b.t == pytest.approx(a.t_end)
    gap = pk[12].t - pk[11].t_end
    expected = outage + 1.0 - PACKET_S   # outage plus the backoff, minus one packet span
    assert gap == pytest.approx(expected, abs=0.02)
    det = BeatDetector()
    before = [b for p in pk[:12] for b in det.feed(p)]
    assert before
    after = [(p, b) for p in pk[12:] for b in det.feed(p)]
    assert after, "no beats after the reconnect"
    for p, b in after:
        assert b.r >= pk[12].t
        assert p.t_last - 1.0 <= b.r <= p.t_last


def test_gives_up_after_max_scans():
    clk = FakeClock()

    async def scanner():
        return None
    src = H10Source(scanner=scanner, client_factory=None, sleep=clk.sleep, now=clk.now, max_scans=3, backoff_s=1.0)
    with pytest.raises(RuntimeError):
        collect(src, 1)
    assert clk.sleeps == [1.0, 1.0]

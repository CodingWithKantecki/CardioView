import asyncio
import json

import pytest

from fastapi.testclient import TestClient

from backend.app import Hub, create_app
from backend.sources.base import PACKET, PACKET_S, Packet, Source


def test_hub_backlog_keeps_8s_of_samples_and_12_beats():
    hub = Hub("simulated")
    for k in range(40):
        hub.push_samples(Packet(k * PACKET_S, [k] * PACKET))
    for k in range(20):
        hub.push_beat({"type": "beat", "source": "simulated", "r": float(k)})
    msgs = [json.loads(m) for m in hub.backlog()]
    assert msgs[0]["type"] == "status"
    samples = [m for m in msgs if m["type"] == "samples"]
    beats = [m for m in msgs if m["type"] == "beat"]
    assert len(beats) == 12 and beats[-1]["r"] == 19.0
    span = samples[-1]["t"] + PACKET_S - samples[0]["t"]
    assert 7.5 <= span <= 8.6
    assert samples[-1]["uv"] == [39] * PACKET


def test_hub_drops_oldest_when_a_viewer_is_slow():
    hub = Hub("simulated")
    q = hub.subscribe()
    for k in range(300):
        hub.push_beat({"type": "beat", "r": k})
    assert q.qsize() == q.maxsize
    assert json.loads(q.get_nowait())["r"] == 300 - q.maxsize


class FakeSource(Source):
    kind = "recorded"

    async def packets(self):
        self.set_status("streaming", "Fake strap")
        for k in range(4):
            yield Packet(k * PACKET_S, [0] * PACKET)
            await asyncio.sleep(0.01)
        await asyncio.sleep(30)


class OtherSource(FakeSource):
    kind = "simulated"


def test_websocket_sends_status_then_samples():
    app = create_app({"demo": FakeSource, "live": OtherSource}, "demo")
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and '<base href="/a/' in page.text, "assets are versioned"
        version = page.text.split('<base href="/a/')[1].split('/')[0]
        assert client.get(f"/a/{version}/theme.js").status_code == 200
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            assert first["source"] == "recorded"
            seen = []   # the rest of the backlog (signal, session), then hello, then the first samples
            for _ in range(6):
                m = ws.receive_json()
                seen.append(m)
                if m["type"] == "samples":
                    break
            assert any(m["type"] == "samples" and m["fs"] == 130 and len(m["uv"]) == PACKET for m in seen)


def test_viewer_can_switch_sources():
    app = create_app({"demo": FakeSource, "live": OtherSource}, "demo")
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "status" and first["source"] == "recorded"
            ws.send_json({"type": "source", "name": "live"})
            seen = []
            for _ in range(20):
                m = ws.receive_json()
                seen.append(m)
                if m["type"] == "status" and m["source"] == "simulated":
                    break
            assert any(m["type"] == "status" and m["source"] == "simulated" for m in seen)
            viewer = next(iter(app.state.viewers.values()))
            assert viewer.runner.name == "live"


def test_rhythm_message_starts_the_simulator_with_that_pattern():
    from backend.sources.rhythm import RhythmSource
    app = create_app({"demo": FakeSource, "live": OtherSource, "rhythm": lambda pattern="sinus": RhythmSource(pattern)}, "demo")
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "status"
            ws.send_json({"type": "rhythm", "name": "afib"})
            seen = []
            for _ in range(30):
                m = ws.receive_json()
                seen.append(m)
                if m["type"] == "status" and m.get("device") == "Simulated: Atrial fibrillation":
                    break
            assert any(m.get("device") == "Simulated: Atrial fibrillation" for m in seen)
            assert next(iter(app.state.viewers.values())).runner.name == "rhythm"


class Clk:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0.01)


def _drain(q):
    msgs = []
    while not q.empty():
        msgs.append(json.loads(q.get_nowait()))
    return msgs


def test_a_switch_to_the_strap_or_from_a_stale_strap_resets():
    from backend.app import Runner
    from backend.sources.sim import SimSource

    async def run():
        class LiveSim(SimSource):      # stands in for the strap
            kind = "live"

        hub = Hub("simulated")
        clk = Clk()
        runner = Runner(hub, {"a": lambda: LiveSim(bpm=72, sleep=clk.sleep, now=clk.now),
                              "b": lambda: SimSource(bpm=90, preroll_s=3.0, sleep=clk.sleep, now=clk.now)})
        await runner.start("a")
        await asyncio.sleep(0.4)
        assert hub.samples and hub.samples[-1]["t"] > 0
        q = hub.subscribe()
        runner._last_wall -= 10          # the strap went quiet: its clock must not rush to catch up
        await runner.start("b")
        await asyncio.sleep(0.4)
        msgs = _drain(q)
        assert msgs[0]["type"] == "status" and msgs[0]["source"] == "simulated"
        samples = [m for m in msgs if m["type"] == "samples"]
        assert samples[0]["t"] == 0.0, "the new source starts its clock at zero"
        assert len(samples[0]["uv"]) >= 300, "the preroll arrives as one message"
        beats = [m for m in msgs if m["type"] == "beat"]
        assert beats and beats[0]["r"] < 3.0, "the preroll's beats come with it"
        assert msgs.index(samples[0]) < msgs.index(beats[0]), "samples before beats, so the viewer keeps them"
        q2 = hub.subscribe()
        await runner.start("a")          # back to the strap: always a reset
        await asyncio.sleep(0.3)
        samples = [m for m in _drain(q2) if m["type"] == "samples"]
        assert samples and samples[0]["t"] == 0.0
        await runner.stop()
    asyncio.run(run())


def test_a_fresh_strap_hands_the_stream_to_the_demo():
    from backend.app import Runner
    from backend.sources.base import FS, PACKET
    from backend.sources.sim import SimSource

    async def run():
        class LiveSim(SimSource):
            kind = "live"

        hub = Hub("simulated")
        clk = Clk()
        runner = Runner(hub, {"a": lambda: LiveSim(bpm=72, sleep=clk.sleep, now=clk.now),
                              "b": lambda: SimSource(bpm=90, preroll_s=3.0, sleep=clk.sleep, now=clk.now)})
        await runner.start("a")
        for _ in range(400):
            await asyncio.sleep(0.01)
            if runner._index > 20 * PACKET:
                break
        q = hub.subscribe()
        t_switch = runner._index / FS
        last_uv = hub.samples[-1]["uv"][-1]
        await runner.start("b")
        await asyncio.sleep(0.5)
        msgs = _drain(q)
        samples = [m for m in msgs if m["type"] == "samples"]
        assert samples and samples[0]["t"] == pytest.approx(t_switch, abs=1e-3), "the stream time runs on from the strap"
        assert len(samples[0]["uv"]) == PACKET, "no preroll"
        assert samples[0]["uv"][0] == last_uv, "the first demo sample meets the strap's last value"
        await runner.stop()
    asyncio.run(run())


def test_demo_to_demo_takes_over_the_running_stream():
    from backend.app import Runner
    from backend.sources.base import FS, PACKET
    from backend.sources.sim import SimSource

    class Clk:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

        async def sleep(self, s):
            self.t += s
            await asyncio.sleep(0.005)

    async def run():
        hub = Hub("simulated")
        clk = Clk()
        runner = Runner(hub, {"a": lambda: SimSource(bpm=72, sleep=clk.sleep, now=clk.now),
                              "b": lambda: SimSource(bpm=140, preroll_s=10.0, sleep=clk.sleep, now=clk.now)})
        await runner.start("a")
        for _ in range(400):
            await asyncio.sleep(0.01)
            if runner._index > 20 * PACKET:
                break
        q = hub.subscribe()
        t_switch = runner._index / FS
        last_uv = hub.samples[-1]["uv"][-1]
        await runner.start("b")
        await asyncio.sleep(0.6)
        msgs = []
        while not q.empty():
            msgs.append(json.loads(q.get_nowait()))
        assert not [m for m in msgs if m["type"] == "handover"], "nothing already sent is replaced"
        samples = [m for m in msgs if m["type"] == "samples"]
        assert samples and samples[0]["t"] == pytest.approx(t_switch, abs=1e-3), "the stream time runs on"
        assert len(samples[0]["uv"]) == PACKET, "no preroll"
        assert samples[0]["uv"][0] == last_uv, "the first new sample meets the old stream's last value"
        for a, b in zip(samples, samples[1:]):
            assert b["t"] == pytest.approx(a["t"] + len(a["uv"]) / FS, abs=1e-3), "contiguous packets"
        assert all(m["t"] > 1.0 for m in samples), "no restart from zero"
        await runner.stop()
    asyncio.run(run())


def test_a_switch_never_waits_for_the_old_source_to_tear_down():
    import time

    from backend.app import Runner
    from backend.sources.sim import SimSource

    class SlowTeardown(SimSource):   # like the strap: waits inside its stream, a Bluetooth disconnect on the way out
        kind = "live"

        async def packets(self):
            self.set_status("streaming")
            try:
                yield Packet(0.0, [0] * PACKET)
                await asyncio.sleep(10)        # waiting for the next packet, where a switch finds it
                yield Packet(PACKET_S, [0] * PACKET)
            finally:
                await asyncio.sleep(2.0)       # the disconnect

    async def run():
        hub = Hub("simulated")
        clk = Clk()
        runner = Runner(hub, {"a": lambda: SlowTeardown(bpm=72, sleep=clk.sleep, now=clk.now),
                              "b": lambda: SimSource(bpm=90, preroll_s=3.0, sleep=clk.sleep, now=clk.now)})
        await runner.start("a")
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        await runner.start("b")
        assert time.monotonic() - t0 < 0.5, "the switch does not wait for the teardown"
        await asyncio.sleep(0.3)
        assert hub.samples and hub.source_kind == "simulated", "the demo streams while the strap is still tearing down"
        t1 = time.monotonic()
        await runner.stop()
        assert time.monotonic() - t1 >= 1.0, "shutdown does wait for it"
    asyncio.run(run())

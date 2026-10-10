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
        assert client.get("/").status_code == 200
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            assert first["source"] == "recorded"
            seen = [ws.receive_json() for _ in range(3)]
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
            assert app.state.runner.name == "live"


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
            assert app.state.runner.name == "rhythm"


def test_a_switch_starts_the_new_source_from_zero():
    from backend.app import Runner
    from backend.sources.sim import SimSource

    class Clk:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

        async def sleep(self, s):
            self.t += s
            await asyncio.sleep(0.01)

    async def run():
        class LiveSim(SimSource):      # stands in for the strap: a switch away from it is a full reset
            kind = "live"

        hub = Hub("simulated")
        clk = Clk()
        runner = Runner(hub, {"a": lambda: LiveSim(bpm=72, sleep=clk.sleep, now=clk.now),
                              "b": lambda: SimSource(bpm=90, preroll_s=3.0, sleep=clk.sleep, now=clk.now)})
        await runner.start("a")
        await asyncio.sleep(0.4)
        assert hub.samples and hub.samples[-1]["t"] > 0
        q = hub.subscribe()
        await runner.start("b")
        await asyncio.sleep(0.4)
        msgs = []
        while not q.empty():
            msgs.append(json.loads(q.get_nowait()))
        assert msgs[0]["type"] == "status" and msgs[0]["source"] == "simulated"
        samples = [m for m in msgs if m["type"] == "samples"]
        assert samples[0]["t"] == 0.0, "the new source starts its clock at zero"
        assert len(samples[0]["uv"]) >= 300, "the preroll arrives as one message"
        beats = [m for m in msgs if m["type"] == "beat"]
        assert beats and beats[0]["r"] < 3.0, "the preroll's beats come with it"
        first_beat = msgs.index(beats[0])
        assert msgs.index(samples[0]) < first_beat, "samples before beats, so the viewer keeps them"
        await runner.stop()
    asyncio.run(run())


def test_demo_to_demo_is_a_handover_not_a_reset():
    from backend.app import HANDOVER_OVERLAP, Runner
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
        for _ in range(200):
            await asyncio.sleep(0.01)
            if runner._index > 20 * PACKET:
                break
        q = hub.subscribe()
        t_switch = runner._index / FS
        await runner.start("b")
        await asyncio.sleep(0.6)
        msgs = []
        while not q.empty():
            msgs.append(json.loads(q.get_nowait()))
        hand = [m for m in msgs if m["type"] == "handover"]
        assert len(hand) == 1, "one handover message"
        assert abs(hand[0]["from"] - (t_switch - HANDOVER_OVERLAP * PACKET / FS)) < 0.6
        after = msgs[msgs.index(hand[0]) + 1:]
        samples = [m for m in after if m["type"] == "samples"]
        assert samples and samples[0]["t"] == pytest.approx(hand[0]["from"], abs=1e-3), "the new source starts exactly at the handover"
        assert all(m["t"] > 1.0 for m in samples), "no restart from zero"
        beats = [m for m in after if m["type"] == "beat"]
        assert beats and beats[0]["bpm"] is not None, "the detector was primed: the first beat already has a rate"
        assert all(b["r"] >= hand[0]["from"] for b in beats)
        await runner.stop()
    asyncio.run(run())

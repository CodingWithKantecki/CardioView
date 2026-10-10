import asyncio
import json

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


def test_websocket_sends_status_then_samples():
    app = create_app(FakeSource())
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            assert first["source"] == "recorded"
            seen = [ws.receive_json() for _ in range(3)]
            assert any(m["type"] == "samples" and m["fs"] == 130 and len(m["uv"]) == PACKET for m in seen)

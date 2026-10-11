"""backend/pattern.py: the closest demo pattern, read on each viewer's last 10 s every 5 s."""
import asyncio
import time

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.pattern import PatternModel, PatternWatch
from backend.sources.base import FS, PACKET, PACKET_S, Packet, Source


class FakeModel:
    def __init__(self, state="ready", answer=("afib", 0.91)):
        self.state = state
        self.answer = answer
        self.windows = []

    active = property(lambda self: self.state in ("loading", "ready"))
    ready = property(lambda self: self.state == "ready")

    async def classify(self, uv):
        self.windows.append(uv)
        await asyncio.sleep(0)
        return self.answer


def feed(watch, packets, start=0):
    async def run():
        for k in range(start, start + packets):
            watch.feed(Packet(k * PACKET_S, [k] * PACKET))
            for _ in range(3):
                await asyncio.sleep(0)
    asyncio.run(run())


def test_reads_once_the_window_is_full_then_every_5_s():
    model, sent = FakeModel(), []
    watch = PatternWatch(model, sent.append)
    feed(watch, 45)   # 25.3 s: readings at 10.1, 15.2, 20.2 and 25.3 s
    readings = [m for m in sent if m["name"]]
    assert len(readings) == 4
    assert all(len(w) == 10 * FS for w in model.windows), "always the last 10 s"
    assert readings[0]["t"] == round(18 * PACKET_S, 3), "the first reading as soon as 10 s are in"
    assert 4.9 < readings[1]["t"] - readings[0]["t"] < 5.2
    assert readings[0]["label"] == "Atrial fibrillation" and readings[0]["p"] == 0.91


def test_a_switch_or_a_gap_starts_over_and_says_so():
    model, sent = FakeModel(), []
    watch = PatternWatch(model, sent.append)
    watch.reset(0.0, "simulated")
    assert sent == [{"type": "pattern", "source": "simulated", "t": 0.0, "name": None}]
    feed(watch, 15)
    feed(watch, 15, start=40)   # a jump in stream time: a window never straddles it
    assert [m["name"] for m in sent] == [None, None]
    assert sent[1]["t"] == round(40 * PACKET_S, 3)
    feed(watch, 5, start=55)
    assert sent[-1]["name"] == "afib", "a full window after the gap is read"


def test_an_answer_about_an_old_stream_is_dropped():
    model, sent = FakeModel(), []
    watch = PatternWatch(model, sent.append)

    async def run():
        for k in range(18):
            watch.feed(Packet(k * PACKET_S, [0] * PACKET))
        watch.reset(30.0, "live")   # the strap took over while the model was busy
        for _ in range(5):
            await asyncio.sleep(0)
    asyncio.run(run())
    assert len(model.windows) == 1
    assert [m["name"] for m in sent] == [None]


def test_without_a_classifier_nothing_is_sent():
    sent = []
    watch = PatternWatch(FakeModel(state="failed"), sent.append)
    watch.reset(0.0, "simulated")
    feed(watch, 30)
    assert sent == []


def test_model_loads_in_the_background_and_a_failure_turns_it_off():
    class Clf:
        def closest(self, windows):
            return [("vt", 0.88) for _ in windows]

    async def run(loader):
        m = PatternModel(loader=loader)
        await m.load()
        out = await m.classify([0] * 1300) if m.ready else None
        m.close()
        return m.state, out

    assert asyncio.run(run(Clf)) == ("ready", ("vt", 0.88))

    def missing():
        raise ModuleNotFoundError("No module named 'torch'")
    assert asyncio.run(run(missing)) == ("failed", None)


class LongSource(Source):
    kind = "simulated"

    async def packets(self):
        self.set_status("streaming", "Simulated: Atrial fibrillation")
        k = 0
        while True:
            yield Packet(k * PACKET_S, [0] * PACKET)
            k += 1
            await asyncio.sleep(0.005)


def test_viewer_gets_readings_over_its_socket():
    class Clf:
        def closest(self, windows):
            return [("afib", 0.93) for _ in windows]

    model = PatternModel(loader=Clf)
    app = create_app({"demo": LongSource}, "demo", pattern=model)
    with TestClient(app) as client:
        for _ in range(200):
            if model.ready:
                break
            time.sleep(0.01)
        with client.websocket_connect("/ws") as ws:
            seen = []
            for _ in range(400):
                m = ws.receive_json()
                if m["type"] == "pattern":
                    seen.append(m)
                    if m["name"]:
                        break
    assert seen[0]["name"] is None and seen[0]["t"] == 0.0, "a new source says there is no reading yet"
    assert seen[-1]["name"] == "afib" and seen[-1]["label"] == "Atrial fibrillation"
    assert seen[-1]["source"] == "simulated" and seen[-1]["t"] >= 10.0

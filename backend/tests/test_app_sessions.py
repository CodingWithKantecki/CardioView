"""Saved sessions end to end, over a viewer's websocket: a fast synthetic source, the real detector and analysis."""
import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.__main__ import parse_keep_until
from backend.app import Hub, Runner, create_app
from backend.sources.base import PACKET, Packet, Source
from backend.synth import synth_session


class FastSource(Source):
    """The synthetic session looped as strap packets: a trickle until a session runs, then flat out."""

    kind = "simulated"

    def __init__(self, pause=0.005):
        super().__init__()
        self.uv = synth_session(seed=1).uv
        self.pause = pause
        self.go = lambda: False   # the fixture points this at "a session is running"

    async def packets(self):
        self.set_status("streaming", "Simulated 70 bpm")
        n, k = len(self.uv), 0
        while True:
            yield Packet(k / 130, [int(self.uv[(k + i) % n]) for i in range(PACKET)])
            k += PACKET
            await asyncio.sleep(0 if self.go() else self.pause)


class Quiet(Source):
    """A strap nobody is wearing: it never sends a packet."""

    kind = "live"

    async def packets(self):
        await asyncio.sleep(3600)
        yield  # pragma: no cover


class Booth:
    """One viewer's websocket: the session actions go down it, the answers come back up it."""

    def __init__(self, app, ws):
        self.app, self.ws = app, ws
        self.cid = None
        for _ in range(20):
            m = ws.receive_json()
            if m["type"] == "hello":
                self.cid = m["cid"]
                break
        assert self.cid, "no hello"

    @property
    def sessions(self):
        return self.app.state.viewers[self.cid].sessions

    @property
    def runner(self):
        return self.app.state.viewers[self.cid].runner

    def act(self, action):
        self.ws.send_json({"type": "session", "action": action})
        for _ in range(400):
            m = self.ws.receive_json()
            if m["type"] == "session_result" and m["action"] == action:
                return m
        raise AssertionError(f"no answer to {action}")


def wait_for(cond, seconds=30.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def client(tmp_path):
    src = FastSource()
    app = create_app({"demo": lambda: src, "live": Quiet}, "demo", strap_only=False,
                     sessions_dir=tmp_path / "sessions", public_host="booth.local", port=8000)
    src.go = lambda: any(v.sessions.state == "running" for v in app.state.viewers.values())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        yield c, Booth(app, ws), tmp_path / "sessions"


def test_backlog_starts_with_status_signal_session_then_hello(client):
    c, _, _ = client
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "status"
        assert ws.receive_json()["type"] == "signal"
        assert ws.receive_json() == {"type": "session", "state": "idle"}
        assert ws.receive_json()["type"] == "hello"


def test_a_session_from_start_to_summary_qr_and_delete(client):
    c, booth, root = client
    sessions = booth.sessions
    assert wait_for(lambda: sessions._last_sample_at is not None)
    r = booth.act("start")
    assert r["ok"], r
    sid = r["id"]
    assert booth.act("start")["reason"] == "A session is already running."
    assert wait_for(lambda: sessions.state == "done", 60)
    assert sessions.message()["link"] == f"http://booth.local:8000/s/{sid}"

    s = c.get(f"/api/s/{sid}").json()
    assert s["id"] == sid and s["effort"]["ok"] and s["beat"]["ok"] and s["ended_early"] is False
    qr = c.get(f"/api/s/{sid}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")

    assert c.delete(f"/api/s/{sid}").json() == {"ok": True}
    assert c.get(f"/api/s/{sid}").status_code == 404
    assert not (root / sid).exists() and sessions.state == "idle"


def test_cancel_route_deletes_the_running_session(client):
    c, booth, root = client
    sessions = booth.sessions
    assert wait_for(lambda: sessions._last_sample_at is not None)
    sid = booth.act("start")["id"]
    assert booth.act("cancel")["ok"]
    assert sessions.message() == {"type": "session", "state": "idle", "note": "stopped"}
    assert not (root / sid).exists()


def test_unknown_bad_and_demo_ids(client):
    c, _, _ = client
    assert c.get("/api/s/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404
    assert c.get("/api/s/..%2F..%2Fetc").status_code == 404
    assert c.delete("/api/s/demo").status_code == 404
    demo = c.get("/api/s/demo").json()
    assert demo["demo"] is True and demo["effort"]["ok"] and demo["breathing"]["ok"]
    assert c.get("/api/s/demo/qr.svg").status_code == 200


def test_start_without_signal_is_refused(tmp_path):
    app = create_app({"demo": Quiet}, "demo", sessions_dir=tmp_path, strap_only=False)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        assert Booth(app, ws).act("start") == {"type": "session_result", "action": "start", "ok": False, "reason": "No signal yet."}


def test_start_needs_the_strap_streaming_by_default(tmp_path):
    """The booth policy (Thomas): a session never runs on demo data, whatever the signal."""
    src = FastSource()
    app = create_app({"demo": lambda: src, "live": Quiet}, "demo", sessions_dir=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        assert Booth(app, ws).act("start")["reason"] == "Exercise needs the strap on and streaming."


def test_keep_until_reads_zones_and_local_time():
    assert parse_keep_until(None) is None
    assert parse_keep_until("2026-10-11T12:00+00:00") == datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    local = parse_keep_until("2026-10-11T12:00")
    assert local.tzinfo == timezone.utc and local == datetime(2026, 10, 11, 12, 0).astimezone(timezone.utc)


def test_source_and_rhythm_switches_wait_for_the_session(tmp_path):
    """A running session records one source, so Strap / Demo and rhythm switches are refused until it stops."""
    src = FastSource(pause=0.05)   # slow enough that the session is still running when the switch arrives
    app = create_app({"demo": lambda: src, "live": Quiet, "rhythm": lambda pattern="sinus": Quiet()}, "demo",
                     sessions_dir=tmp_path / "sessions", strap_only=False)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        booth = Booth(app, ws)
        sessions, runner = booth.sessions, booth.runner
        assert wait_for(lambda: sessions._last_sample_at is not None)
        assert booth.act("start")["ok"]
        ws.send_json({"type": "source", "name": "live"})
        ws.send_json({"type": "rhythm", "name": "afib"})
        assert not wait_for(lambda: runner.name != "demo", 1.0)
        assert sessions.state == "running"


def test_a_failing_session_hook_never_stops_the_live_view():
    """The session code runs inside the source pump: a bug there must not freeze the heart on screen."""
    async def run():
        hub = Hub("simulated")
        seen = []

        def broken(packet, beats):
            seen.append(packet.t)
            raise RuntimeError("a bug in the session code")

        runner = Runner(hub, {"demo": FastSource}, on_packet=broken)
        await runner.start("demo")
        for _ in range(300):
            await asyncio.sleep(0.01)
            if len(seen) >= 3:
                break
        await runner.stop()
        return len(seen)

    assert asyncio.run(run()) >= 3


def test_summary_page_is_served_for_any_id(client):
    c, _, _ = client
    r = c.get("/s/demo")
    assert r.status_code == 200 and "/summary.js" in r.text
    assert c.get("/summary.css").status_code == 200


def test_building_the_demo_summary_never_stalls_the_server(tmp_path, monkeypatch):
    """The demo summary takes seconds of NeuroKit work: it must not hold up the live view meanwhile."""
    import backend.app as app_module

    def slow_demo():
        time.sleep(1.0)
        return {"version": 1, "id": "demo", "demo": True}

    monkeypatch.setattr(app_module, "demo_summary", slow_demo)
    with TestClient(create_app({"demo": FastSource}, "demo", sessions_dir=tmp_path, strap_only=False)) as c:
        slow = threading.Thread(target=lambda: c.get("/api/s/demo"))
        slow.start()
        time.sleep(0.2)                    # the slow build is under way
        t = time.monotonic()
        assert c.get("/s/demo").status_code == 200
        took = time.monotonic() - t
        slow.join()
    assert took < 0.5, f"another request waited {took:.2f} s behind the demo build"

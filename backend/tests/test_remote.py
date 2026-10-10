"""The viewer's own strap: status and samples sent down the viewer's websocket become its live source."""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.sources.base import PACKET, PACKET_S


def test_browser_strap_packets_come_back_as_the_live_source(tmp_path):
    with TestClient(create_app({"demo": None}, "live", sessions_dir=tmp_path, base_url="https://booth.example")) as c:
        with c.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "status" and first["source"] == "live" and first["state"] == "connecting"
            ws.send_text(json.dumps({"type": "status", "state": "streaming", "device": "Polar H10 TEST"}))
            for k in range(3):
                ws.send_text(json.dumps({"type": "samples", "t": k * PACKET_S, "uv": [k] * PACKET}))
            seen = {"status": None, "samples": []}
            for _ in range(30):
                m = ws.receive_json()
                if m["type"] == "status" and m["state"] == "streaming":
                    seen["status"] = m
                elif m["type"] == "samples":
                    seen["samples"].append(m)
                if seen["status"] and len(seen["samples"]) >= 3:
                    break
            assert seen["status"]["device"] == "Polar H10 TEST"
            assert [s["uv"][0] for s in seen["samples"][:3]] == [0, 1, 2]
            ws.send_text(json.dumps({"type": "status", "state": "connecting", "device": ""}))
            for _ in range(30):   # the strap dropped: this viewer is not connected again
                m = ws.receive_json()
                if m["type"] == "status" and m["state"] == "connecting":
                    break
            else:
                raise AssertionError("no connecting status after the strap dropped")


def test_every_viewer_has_its_own_pipeline(tmp_path):
    app = create_app({"demo": None}, "live", sessions_dir=tmp_path)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
            assert len(app.state.viewers) == 2
            a.receive_json(); b.receive_json()
            a.send_text(json.dumps({"type": "status", "state": "streaming", "device": "Strap A"}))
            a.send_text(json.dumps({"type": "samples", "t": 0.0, "uv": [7] * PACKET}))
            got_a = None
            for _ in range(30):
                m = a.receive_json()
                if m["type"] == "samples":
                    got_a = m
                    break
            assert got_a and got_a["uv"][0] == 7
            # viewer b saw none of it: its own strap is still not connected
            for _ in range(6):
                m = b.receive_json()
                assert m["type"] != "samples", "a sample from another viewer's strap"
                if m["type"] == "hello":
                    break
        assert len(app.state.viewers) == 0, "viewers are forgotten when their tab leaves"


def test_links_use_the_base_url(tmp_path):
    app = create_app({"demo": None}, "live", sessions_dir=tmp_path, base_url="https://booth.example/")
    assert app.state.sessions.link("abc") == "https://booth.example/s/abc"


def test_a_session_can_start_on_the_browser_strap(tmp_path):
    """The whole point of per-viewer straps: a visitor's own strap carries their Exercise session."""
    import time
    app = create_app({"demo": None}, "live", sessions_dir=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        cid = None
        for _ in range(10):
            m = ws.receive_json()
            if m["type"] == "hello":
                cid = m["cid"]
                break
        ws.send_text(json.dumps({"type": "status", "state": "streaming", "device": "Polar H10 TEST"}))
        for k in range(4):
            ws.send_text(json.dumps({"type": "samples", "t": k * PACKET_S, "uv": [k] * PACKET}))
        time.sleep(0.5)
        ws.send_text(json.dumps({"type": "session", "action": "start"}))
        for _ in range(200):
            m = ws.receive_json()
            if m["type"] == "session_result":
                break
        assert m["ok"], m
        assert app.state.viewers[cid].sessions.state == "running"
        ws.send_text(json.dumps({"type": "session", "action": "cancel"}))

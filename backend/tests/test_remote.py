"""The strap bridge: packets sent to /ws/strap with the key become the live source."""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.sources.base import PACKET, PACKET_S
from backend.sources.remote import RemoteHub, RemoteSource


def make_app(remote):
    return create_app({"live": lambda: RemoteSource(remote)}, "live", remote=remote, bridge_key="secret", base_url="https://booth.example")


def test_bridge_needs_the_key():
    remote = RemoteHub()
    with TestClient(make_app(remote)) as c:
        for url in ("/ws/strap", "/ws/strap?key=wrong"):
            try:
                with c.websocket_connect(url) as ws:
                    ws.receive_text()
                refused = False
            except Exception:
                refused = True
            assert refused, url


def test_bridge_packets_reach_the_viewer():
    remote = RemoteHub()
    with TestClient(make_app(remote)) as c:
        with c.websocket_connect("/ws") as viewer:
            first = viewer.receive_json()
            assert first["type"] == "status" and first["source"] == "live" and first["state"] == "connecting"
            with c.websocket_connect("/ws/strap?key=secret") as bridge:
                bridge.send_text(json.dumps({"type": "status", "state": "streaming", "device": "Polar H10 TEST"}))
                for k in range(3):
                    bridge.send_text(json.dumps({"type": "samples", "t": k * PACKET_S, "uv": [k] * PACKET}))
                seen = {"status": None, "samples": []}
                for _ in range(20):
                    m = viewer.receive_json()
                    if m["type"] == "status" and m["state"] == "streaming":
                        seen["status"] = m
                    elif m["type"] == "samples":
                        seen["samples"].append(m)
                    if seen["status"] and len(seen["samples"]) >= 3:
                        break
                assert seen["status"]["device"] == "Polar H10 TEST"
                assert [s["uv"][0] for s in seen["samples"][:3]] == [0, 1, 2]
            for _ in range(20):   # the bridge left: the strap is not connected again
                m = viewer.receive_json()
                if m["type"] == "status" and m["state"] == "connecting":
                    break
            else:
                raise AssertionError("no connecting status after the bridge left")


def test_links_use_the_base_url(tmp_path):
    remote = RemoteHub()
    app = create_app({"live": lambda: RemoteSource(remote)}, "live", remote=remote, bridge_key="secret",
                     base_url="https://booth.example/", sessions_dir=tmp_path)
    assert app.state.sessions.link("abc") == "https://booth.example/s/abc"

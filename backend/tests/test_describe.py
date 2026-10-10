"""Gemini heart: words in, the simulator's recipe out, the viewer's demo switched to it."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import describe
from backend.app import create_app
from backend.sources.base import PACKET, PACKET_S, Packet, Source
from backend.sources.rhythm import RhythmSource

RECIPE = {"ok": True, "reason": "", "name": "Cocaine intoxication", "summary": "Fast and jittery, with an early beat now and then.",
          "bpm": 138, "jitter": 0.05, "irregular": False, "p_wave": 0.12, "pr_s": 0.18, "qrs_width": 1.0, "st_mv": -0.1, "t_mv": 0.2, "pvc_every": 7}


def gemini(body: dict, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-goog-api-key" in request.headers and "key=" not in str(request.url)
        sent = json.loads(request.content)
        assert sent["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(status, json={"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]} if status == 200 else {"error": {"message": "no"}})
    return httpx.MockTransport(handler)


class Quiet(Source):
    kind = "recorded"

    async def packets(self):
        self.set_status("streaming", "Recording test")
        k = 0
        while True:
            yield Packet(k * PACKET_S, [0] * PACKET)
            k += 1
            await asyncio.sleep(0.05)


def make_app(transport):
    return create_app({"demo": Quiet, "rhythm": lambda pattern="sinus", **kw: RhythmSource(pattern, **kw)}, "demo",
                      http=httpx.AsyncClient(transport=transport), strap_only=False)


def test_clamp_holds_every_number_to_its_range():
    r = describe.clamp({"name": "  Wild  heart ", "summary": "x" * 400, "bpm": 900, "jitter": -1, "irregular": True,
                        "p_wave": 0.2, "pr_s": "nope", "qrs_width": 9, "st_mv": 5, "t_mv": -5, "pvc_every": 1})
    assert r.name == "Wild heart" and len(r.summary) == describe.MAX_SUMMARY_CHARS
    assert r.bpm == 220 and r.jitter == 0 and r.pr_s == 0.18 and r.qrs_width == 3 and r.st_mv == 0.5 and r.t_mv == -0.6
    assert r.p_wave == 0, "irregular means no P wave"
    assert r.pvc_every == 3, "an extra beat every one or two beats is no rhythm"
    assert describe.clamp({"summary": "no name"}) is None and describe.clamp("text") is None


def test_describing_a_patient_switches_the_viewer_to_that_heart(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with TestClient(make_app(gemini(RECIPE))) as c:
        with c.websocket_connect("/ws") as ws:
            cid = None
            while cid is None:
                m = ws.receive_json()
                if m["type"] == "hello":
                    cid = m["cid"]
            res = c.post("/api/rhythm/describe", json={"cid": cid, "text": "a 40 year old man who just took cocaine"})
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["ok"] and body["name"] == "Cocaine intoxication" and body["recipe"]["bpm"] == 138
            seen = None
            for _ in range(40):
                m = ws.receive_json()
                if m["type"] == "status" and m["device"] == "Simulated: Cocaine intoxication":
                    seen = m
                    break
            assert seen is not None and seen["source"] == "simulated"
            # the page sends the recipe back after a reconnect: no Gemini call, the same heart
            ws.send_text(json.dumps({"type": "rhythm", "name": "custom", "recipe": body["recipe"]}))
            again = None
            for _ in range(40):
                m = ws.receive_json()
                if m["type"] == "status" and m["device"] == "Simulated: Cocaine intoxication":
                    again = m
                    break
            assert again is not None


def test_refusals_and_failures_come_back_as_words(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with TestClient(make_app(gemini({"ok": False, "reason": "Describe a patient, a situation or a heart rhythm."}))) as c:
        with c.websocket_connect("/ws") as ws:
            cid = None
            while cid is None:
                m = ws.receive_json()
                if m["type"] == "hello":
                    cid = m["cid"]
            res = c.post("/api/rhythm/describe", json={"cid": cid, "text": "write me a poem"})
            assert res.status_code == 400 and res.json()["ok"] is False and "Describe" in res.json()["reply"]
            assert c.post("/api/rhythm/describe", json={"cid": cid, "text": ""}).status_code == 400
        assert c.post("/api/rhythm/describe", json={"cid": "nobody", "text": "x"}).status_code == 404
    monkeypatch.delenv("GEMINI_API_KEY")
    with TestClient(make_app(gemini(RECIPE))) as c:
        with c.websocket_connect("/ws") as ws:
            cid = None
            while cid is None:
                m = ws.receive_json()
                if m["type"] == "hello":
                    cid = m["cid"]
            res = c.post("/api/rhythm/describe", json={"cid": cid, "text": "a runner"})
            assert res.status_code == 503 and res.json()["reply"] == describe.WORDS["missing_key"]


@pytest.mark.parametrize("status,error", [(429, "rate_limit"), (503, "rate_limit"), (404, "model"), (500, "upstream")])
def test_gemini_errors_map_to_plain_words(monkeypatch, status, error):
    async def run():
        async with httpx.AsyncClient(transport=gemini({}, status)) as client:
            return await describe.describe("a runner", client, api_key="k")
    out = asyncio.run(run())
    assert out.recipe is None and out.error == error and out.reply == describe.WORDS[error]

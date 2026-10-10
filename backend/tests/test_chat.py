"""The chat backend against a fake Gemini: no test here reaches the network."""
import asyncio
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import chat
from backend.app import Hub, create_app
from backend.env import load_dotenv
from backend.sources.base import PACKET, PACKET_S, Packet, Source

KEY = "test-key-not-real"


def gemini_reply(text: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]}


class FakeGemini:
    """Records the requests and answers each with the next of `answers` (the last one repeats):
    a (status, body) pair, or an exception to raise."""

    def __init__(self, status=200, body=None, raise_exc=None, answers=None):
        body = body if body is not None else gemini_reply("The heart rate is 72 bpm.")
        self.answers = list(answers) if answers else [raise_exc if raise_exc is not None else (status, body)]
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            answer = self.answers[min(len(self.requests) - 1, len(self.answers) - 1)]
            if isinstance(answer, BaseException):
                raise answer
            status, body = answer
            return httpx.Response(status, json=body)
        return httpx.MockTransport(handler)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())


def hub_with_data(source="live", state="streaming", bpm=72, n_beats=3) -> Hub:
    hub = Hub(source)
    hub.status = {"type": "status", "source": source, "state": state, "device": "Polar H10 223FD838", "fs": 130}
    for k in range(6):
        hub.push_samples(Packet(k * PACKET_S, [(-100 if i % 10 else 500) for i in range(PACKET)]))
    for k in range(n_beats):
        hub.push_beat({"type": "beat", "source": source, "r": 0.5 + k * 60 / bpm, "rr": 60 / bpm, "bpm": bpm,
                       "ra_on": -0.2, "la_on": -0.17, "v_on": -0.04, "v_off": 0.32, "p_found": k % 2 == 0})
    return hub


def run(coro):
    return asyncio.run(coro)


def test_snapshot_describes_what_is_on_screen():
    hub = hub_with_data()
    snap = chat.snapshot(hub, last_packet_age_s=0.3)
    assert snap["source"] == "live" and snap["state"] == "streaming" and snap["streaming"] is True
    assert snap["device"] == "Polar H10 223FD838"
    assert snap["signal_ok"] is True and snap["signal_reason"] is None
    assert snap["heart_rate_bpm"] == 72 and snap["rr_s"] == pytest.approx(60 / 72)
    assert len(snap["recent_beats"]) == 3 and "type" not in snap["recent_beats"][0]
    ecg = snap["ecg_recent"]
    assert ecg["samples"] == 260 and ecg["seconds"] == 2.0 and ecg["peak_to_peak_uv"] == 600
    json.dumps(snap)   # it must serialize


def test_snapshot_without_data_and_when_stale():
    hub = Hub("live")
    snap = chat.snapshot(hub)
    assert snap["streaming"] is False and snap["heart_rate_bpm"] is None and snap["recent_beats"] == []
    assert snap["ecg_recent"] == {"samples": 0}
    hub = hub_with_data()
    hub.push_signal({"type": "signal", "source": "live", "ok": False, "reason": "pads"})
    snap = chat.snapshot(hub, last_packet_age_s=5.0)
    assert snap["streaming"] is False and snap["signal_ok"] is False and snap["signal_reason"] == "pads"


def test_missing_key_makes_no_request(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake = FakeGemini()
    result = run(chat.ask("what is my heart rate", [], {}, fake.client()))
    assert result.error == "missing_key" and result.status == 503
    assert result.reply == "Chat is not set up on this server"
    assert fake.requests == []


def test_blank_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    fake = FakeGemini()
    result = run(chat.ask("hi", [], {}, fake.client()))
    assert result.error == "missing_key" and fake.requests == []


def test_reply_and_request_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    fake = FakeGemini()
    snap = chat.snapshot(hub_with_data(), 0.1)
    history = [{"role": "user", "text": "hello"}, {"role": "model", "text": "Hi, ask about the data."}]
    result = run(chat.ask("What is my heart rate?", history, snap, fake.client()))
    assert result.error is None and result.status == 200
    assert result.reply == "The heart rate is 72 bpm."
    req = fake.requests[0]
    # the key travels in a header and never in the URL
    assert req.headers["x-goog-api-key"] == KEY
    assert KEY not in str(req.url) and "key=" not in str(req.url)
    assert str(req.url) == f"{chat.API_BASE}/{chat.DEFAULT_MODEL}:generateContent"
    body = json.loads(req.content)
    system = body["systemInstruction"]["parts"][0]["text"]
    assert '"heart_rate_bpm":72' in system and '"source":"live"' in system
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][-1]["parts"][0]["text"] == "What is my heart rate?"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert len(fake.requests) == 1


def test_model_that_rejects_thinking_gets_one_retry_without_it(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(answers=[(400, {"error": {"code": 400, "message": "Request contains an invalid argument."}}),
                               (200, gemini_reply("72 bpm."))])
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error is None and result.reply == "72 bpm."
    assert len(fake.requests) == 2
    first, second = (json.loads(r.content)["generationConfig"] for r in fake.requests)
    assert "thinkingConfig" in first and "thinkingConfig" not in second


def test_model_name_is_configurable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
    fake = FakeGemini()
    run(chat.ask("rate?", [], {}, fake.client()))
    assert str(fake.requests[0].url).endswith("/gemini-2.0-flash-lite:generateContent")


def test_rate_limit_says_try_again_soon(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(status=429, body={"error": {"code": 429, "message": "quota"}})
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "rate_limit" and result.status == 429
    assert "try again soon" in result.reply


def test_overloaded_model_also_says_try_again_soon(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(status=503, body={"error": {"code": 503, "message": "high demand"}})
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "rate_limit" and result.status == 429


@pytest.mark.parametrize("exc", [httpx.ConnectError("no route"), httpx.RemoteProtocolError("cut")])
def test_no_internet_is_calm(monkeypatch, exc):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(raise_exc=exc)
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "offline" and result.status == 502
    assert result.reply == "The chat needs an internet connection"


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow")])
def test_timeout_asks_to_try_again(monkeypatch, exc):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(raise_exc=exc)
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "timeout" and result.status == 504
    assert result.reply == "No answer in time, try again"


def test_retired_model_name_is_named_in_the_reply(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(status=404, body={"error": {"code": 404, "message": "This model is no longer available. Use " + KEY}})
    with caplog.at_level("WARNING", logger="cardioview.chat"):
        result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "model" and result.status == 502
    assert result.reply == "Chat model is not available on this server"
    assert "no longer available" in caplog.text and KEY not in caplog.text   # the key never reaches a log


@pytest.mark.parametrize("status,body", [(500, {"error": "boom"}), (400, {"error": {"message": "bad"}}), (200, {"candidates": []}),
                                         (200, {"candidates": [{"content": {"parts": [{"text": "   "}]}}]})])
def test_other_failures_are_upstream(monkeypatch, status, body):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(status=status, body=body)
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert result.error == "upstream" and result.status == 502 and result.reply == "Chat failed, try again"


def test_empty_question(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini()
    result = run(chat.ask("   ", [], {}, fake.client()))
    assert result.error == "empty" and result.status == 400 and fake.requests == []


def test_history_is_cleaned_and_capped():
    junk = [None, 7, {"role": "system", "text": "x"}, {"role": "user", "text": "  "}, {"role": "user"}]
    good = [{"role": "user" if i % 2 == 0 else "model", "text": f"t{i}"} for i in range(30)]
    cleaned = chat.clean_history(junk + good)
    assert len(cleaned) == chat.MAX_HISTORY_TURNS * 2
    assert cleaned[-1]["parts"][0]["text"] == "t29"
    assert chat.clean_history("nope") == [] and chat.clean_history(None) == []


def test_question_is_truncated(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini()
    run(chat.ask("x" * 5000, [], {}, fake.client()))
    body = json.loads(fake.requests[0].content)
    assert len(body["contents"][-1]["parts"][0]["text"]) == chat.MAX_QUESTION_CHARS


def test_reply_never_carries_an_em_dash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini(body=gemini_reply("Measured \u2014 72 bpm."))
    result = run(chat.ask("rate?", [], {}, fake.client()))
    assert "\u2014" not in result.reply


def test_system_prompt_carries_the_product_rules():
    p = chat.SYSTEM_PROMPT
    assert "Never diagnose" in p and "never name a heart rhythm" in p
    assert "Measured:" in p and "Derived from the ECG:" in p and "Modeled:" in p
    assert "only talk about the data shown in CardioView" in p
    assert "not a medical device" in p
    assert "\u2014" not in p


class FakeSource(Source):
    kind = "recorded"

    async def packets(self):
        self.set_status("streaming", "h10_ecg_test")
        for k in range(3):
            yield Packet(k * PACKET_S, [(-100 if i % 10 else 500) for i in range(PACKET)])
            await asyncio.sleep(0.01)
        await asyncio.sleep(30)


def test_endpoint_answers_from_server_state(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    fake = FakeGemini()
    app = create_app({"demo": FakeSource, "live": FakeSource}, "demo", http=fake.client())
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:   # wait until samples flow
            for _ in range(5):
                if ws.receive_json()["type"] == "samples":
                    break
        r = client.post("/api/chat", json={"question": "What am I looking at?", "history": []})
        assert r.status_code == 200
        assert r.json() == {"reply": "The heart rate is 72 bpm.", "error": None}
        system = json.loads(fake.requests[0].content)["systemInstruction"]["parts"][0]["text"]
        assert '"source":"recorded"' in system and '"device":"h10_ecg_test"' in system
        assert '"streaming":true' in system


def test_endpoint_without_key_and_with_bad_bodies(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake = FakeGemini()
    app = create_app({"demo": FakeSource, "live": FakeSource}, "demo", http=fake.client())
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"question": "rate?"})
        assert r.status_code == 503 and r.json()["error"] == "missing_key"
        r = client.post("/api/chat", content=b"not json", headers={"content-type": "application/json"})
        assert r.status_code == 400 and r.json()["error"] == "empty"
        r = client.post("/api/chat", json=["a", "list"])
        assert r.status_code == 400
        r = client.post("/api/chat", json={"question": 42})
        assert r.status_code == 400
    assert fake.requests == []


def test_load_dotenv_sets_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nGEMINI_API_KEY=abc123\nexport GEMINI_MODEL='gemini-x'\nQUOTED=\"a=b\"\nBROKEN LINE\n=novalue\n")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "already")
    monkeypatch.delenv("QUOTED", raising=False)
    names = load_dotenv(env)
    assert names == ["GEMINI_API_KEY", "QUOTED"]
    assert os.environ["GEMINI_API_KEY"] == "abc123"
    assert os.environ["GEMINI_MODEL"] == "already"
    assert os.environ["QUOTED"] == "a=b"
    assert load_dotenv(tmp_path / "missing.env") == []
    assert load_dotenv(env, override=True) == ["GEMINI_API_KEY", "GEMINI_MODEL", "QUOTED"]
    assert os.environ["GEMINI_MODEL"] == "gemini-x"

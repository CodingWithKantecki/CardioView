"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import chat
from .pipeline import BeatDetector, SignalMonitor
from .sources.base import FS, PACKET, PACKET_S, PacedSource, Packet, Source, Status

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
BACKLOG_S = 8.0       # seconds of samples a late viewer gets
HANDOVER_SILENT = 15  # packets of the new source fed to the detector only, so its rhythm history is ready
HANDOVER_OVERLAP = 2  # packets that replace what the viewer has buffered but not shown yet
BACKLOG_BEATS = 12    # beats a late viewer gets
QUEUE_SIZE = 256      # per viewer; the oldest message is dropped when full

log = logging.getLogger("cardioview")


def dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


class Hub:
    """Fan-out of messages to every viewer plus a short backlog for late ones."""

    def __init__(self, source_kind: str):
        self.source_kind = source_kind
        self.clients: set[asyncio.Queue] = set()
        self.samples: deque[dict] = deque()
        self.beats: deque[dict] = deque(maxlen=BACKLOG_BEATS)
        self.status = {"type": "status", "source": source_kind, "state": "connecting",
                       "device": "", "fs": FS}
        self.signal = {"type": "signal", "source": source_kind, "ok": True, "reason": ""}

    def reset(self, source_kind: str) -> None:
        """A new source is starting from zero: forget the old backlog and signal state."""
        self.source_kind = source_kind
        self.samples.clear()
        self.beats.clear()
        self.signal = {"type": "signal", "source": source_kind, "ok": True, "reason": ""}

    def set_status(self, status: Status) -> None:
        self.status = {"type": "status", "source": self.source_kind, "state": status.state,
                       "device": status.device, "fs": FS}
        log.info("status: %s %s", status.state, status.device)
        self.broadcast(self.status)

    def push_samples(self, packet: Packet) -> None:
        msg = {"type": "samples", "source": self.source_kind, "t": round(packet.t, 4),
               "fs": FS, "uv": list(packet.uv)}
        if self.samples and packet.t < self.samples[-1]["t"] - 1.0:
            self.samples.clear()
            self.beats.clear()
        self.samples.append(msg)
        while self.samples and self.samples[0]["t"] + len(self.samples[0]["uv"]) / FS < packet.t_end - BACKLOG_S:
            self.samples.popleft()
        self.broadcast(msg)

    def push_beat(self, msg: dict) -> None:
        self.beats.append(msg)
        self.broadcast(msg)

    def handover(self, from_t: float) -> None:
        """A new source takes over from stream time `from_t`: everything after it is replaced."""
        kept: deque[dict] = deque()
        for m in self.samples:
            if m["t"] >= from_t:
                continue
            n = int(round((from_t - m["t"]) * FS))
            if n < len(m["uv"]):
                m = dict(m, uv=m["uv"][:n])
            kept.append(m)
        self.samples = kept
        self.beats = deque((b for b in self.beats if b["r"] < from_t), maxlen=BACKLOG_BEATS)
        self.broadcast({"type": "handover", "source": self.source_kind, "from": round(from_t, 4)})

    def push_signal(self, msg: dict) -> None:
        self.signal = msg
        log.info("signal: %s %s", "ok" if msg["ok"] else "lost", msg["reason"])
        self.broadcast(msg)

    def broadcast(self, msg: dict) -> None:
        text = dumps(msg)
        for q in list(self.clients):
            if q.full():
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(text)

    def backlog(self) -> list[str]:
        out = [dumps(self.status), dumps(self.signal)]
        out += [dumps(m) for m in self.samples]
        out += [dumps(m) for m in self.beats]
        return out

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)


class Runner:
    """Owns the running source. `start(name)` stops the current one and starts another from zero:
    fresh stream clock, fresh detector and monitor, empty backlog."""

    def __init__(self, hub: Hub, factories: dict[str, Callable[..., Source]]):
        self.hub = hub
        self.factories = factories
        self.name: str | None = None
        self.source: Source | None = None
        self.task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._index = 0                      # next stream sample index of the running source
        self._last_wall: float | None = None

    async def start(self, name: str, force: bool = False, **kwargs) -> None:
        if name not in self.factories:
            return
        async with self._lock:
            if name == self.name and not force:
                return
            # Between demo sources the new one takes over the running clock (a handover): the
            # screen keeps flowing and the new rhythm enters at the now line. To or from the
            # strap it is a full reset.
            handover = (self.source is not None and self.source.kind != "live" and name != "live"
                        and self._last_wall is not None
                        and self._index > (HANDOVER_SILENT + HANDOVER_OVERLAP) * PACKET)
            await self._stop()
            source = self.factories[name](**kwargs)
            hand_from: float | None = None
            if handover and isinstance(source, PacedSource):
                stream_t = self._index / FS
                source.index = self._index - (HANDOVER_SILENT + HANDOVER_OVERLAP) * PACKET
                source.anchor(stream_t, min(self._last_wall + PACKET_S, time.monotonic()))
                hand_from = (self._index - HANDOVER_OVERLAP * PACKET) / FS
            else:
                self._index = 0
                self._last_wall = None
                self.hub.reset(source.kind)
            self.name = name
            self.source = source
            self.hub.source_kind = source.kind
            source.on_status(lambda st, src=source: self.hub.set_status(st) if src is self.source else None)
            self.hub.set_status(source.status)
            self.hub.broadcast(self.hub.signal)
            self.task = asyncio.create_task(self._pump(source, hand_from), name=f"pump-{name}")
            log.info("source: %s %s%s", name, kwargs or "", " (handover)" if hand_from is not None else "")

    async def _stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None
        self.source = None
        self.name = None

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    def last_packet_age(self) -> float | None:
        """Seconds since the running source delivered a packet, or None before the first."""
        return None if self._last_wall is None else time.monotonic() - self._last_wall

    async def _pump(self, source: Source, hand_from: float | None = None) -> None:
        detector = BeatDetector()
        monitor = SignalMonitor()
        preroll = float(getattr(source, "preroll_s", 0.0) or 0.0) if hand_from is None else 0.0
        pending: list[Packet] = []
        silent: list[Packet] = []
        try:
            async for packet in source.packets():
                self._index = round(packet.t_end * FS)
                self._last_wall = time.monotonic()
                if hand_from is not None and packet.t_end <= hand_from + 1e-6:
                    silent.append(packet)         # the new source's past: the detector learns it, nobody sees it
                    continue
                if silent:
                    history = Packet(silent[0].t, [v for p in silent for v in p.uv])
                    silent = []
                    await asyncio.to_thread(detector.prime, history)
                    monitor.update(history, [])
                    self.hub.handover(hand_from)
                if preroll > 0 and packet.t_end <= preroll + 1e-6:
                    pending.append(packet)        # the history a source starts with: sent all at once below
                    continue
                if pending:
                    history = Packet(pending[0].t, [v for p in pending for v in p.uv])
                    pending = []
                    self.hub.push_samples(history)
                    beats = await asyncio.to_thread(detector.prime, history)
                    for beat in beats:
                        self.hub.push_beat(beat.message(source.kind))
                    changed = monitor.update(history, beats)
                    if changed is not None:
                        self.hub.push_signal(changed.message(source.kind))
                self.hub.push_samples(packet)
                beats = await asyncio.to_thread(detector.feed, packet)
                for beat in beats:
                    self.hub.push_beat(beat.message(source.kind))
                changed = monitor.update(packet, beats)
                if changed is not None:
                    if changed.ok:
                        detector.forget_rhythm()
                    self.hub.push_signal(changed.message(source.kind))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("source stopped")


def create_app(factories: dict[str, Callable[[], Source]], initial: str,
               http: httpx.AsyncClient | None = None) -> FastAPI:
    """`factories` maps a name (live, demo) to a function that builds that source. `http` is the
    client the chat uses to reach Gemini; tests pass one with a mock transport."""
    hub = Hub("simulated")
    runner = Runner(hub, factories)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = http or httpx.AsyncClient()
        await runner.start(initial)
        try:
            yield
        finally:
            await runner.stop()
            await app.state.http.aclose()

    app = FastAPI(title="CardioView", lifespan=lifespan)
    app.state.hub = hub
    app.state.runner = runner

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = hub.subscribe()

        async def send() -> None:
            for text in hub.backlog():
                await websocket.send_text(text)
            while True:
                await websocket.send_text(await q.get())

        async def receive() -> None:
            while True:
                text = await websocket.receive_text()
                try:
                    msg = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "source":
                    await runner.start(str(msg.get("name", "")))
                elif msg.get("type") == "rhythm":
                    pattern = str(msg.get("name", ""))
                    if not (runner.name == "rhythm" and getattr(runner.source, "pattern", None) == pattern):
                        await runner.start("rhythm", force=True, pattern=pattern)

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                with suppress(WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                    t.result()
        finally:
            hub.unsubscribe(q)

    @app.post("/api/chat")
    async def chat_endpoint(request: Request) -> JSONResponse:
        """One question about the data on screen. Body: {"question": str, "history": [{"role", "text"}]}.
        The answer is {"reply", "error"}; `reply` is always words to show, `error` is null or a reason."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        question = body.get("question")
        if not isinstance(question, str):
            question = ""
        snap = chat.snapshot(hub, runner.last_packet_age())
        result = await chat.ask(question, body.get("history"), snap, app.state.http)
        return JSONResponse(result.body(), status_code=result.status)

    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app

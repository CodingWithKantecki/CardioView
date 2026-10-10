"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .pipeline import BeatDetector, SignalMonitor
from .sources.base import FS, Packet, Source, Status

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
BACKLOG_S = 8.0       # seconds of samples a late viewer gets
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
        while self.samples and self.samples[0]["t"] < packet.t_end - BACKLOG_S:
            self.samples.popleft()
        self.broadcast(msg)

    def push_beat(self, msg: dict) -> None:
        self.beats.append(msg)
        self.broadcast(msg)

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


def create_app(source: Source) -> FastAPI:
    hub = Hub(source.kind)
    detector = BeatDetector()
    monitor = SignalMonitor()

    async def pump() -> None:
        try:
            async for packet in source.packets():
                hub.push_samples(packet)
                beats = await asyncio.to_thread(detector.feed, packet)
                for beat in beats:
                    hub.push_beat(beat.message(source.kind))
                changed = monitor.update(packet, beats)
                if changed is not None:
                    hub.push_signal(changed.message(source.kind))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("source stopped")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        source.on_status(hub.set_status)
        hub.set_status(source.status)
        task = asyncio.create_task(pump(), name="pump")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    app = FastAPI(title="CardioView", lifespan=lifespan)
    app.state.hub = hub

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
                await websocket.receive_text()

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

    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app

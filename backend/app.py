"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable

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

    async def start(self, name: str, force: bool = False, **kwargs) -> None:
        if name not in self.factories:
            return
        async with self._lock:
            if name == self.name and not force:
                return
            await self._stop()
            source = self.factories[name](**kwargs)
            self.name = name
            self.source = source
            self.hub.reset(source.kind)
            source.on_status(lambda st, src=source: self.hub.set_status(st) if src is self.source else None)
            self.hub.set_status(source.status)
            self.hub.broadcast(self.hub.signal)
            self.task = asyncio.create_task(self._pump(source), name=f"pump-{name}")
            log.info("source: %s %s", name, kwargs or "")

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

    async def _pump(self, source: Source) -> None:
        detector = BeatDetector()
        monitor = SignalMonitor()
        preroll = float(getattr(source, "preroll_s", 0.0) or 0.0)
        pending: list[Packet] = []
        try:
            async for packet in source.packets():
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


def create_app(factories: dict[str, Callable[[], Source]], initial: str) -> FastAPI:
    """`factories` maps a name (live, demo) to a function that builds that source."""
    hub = Hub("simulated")
    runner = Runner(hub, factories)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runner.start(initial)
        try:
            yield
        finally:
            await runner.stop()

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

    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app

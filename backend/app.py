"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .pipeline import REFRACTORY_S, BeatDetector, SignalMonitor
from .sources.base import FS, PACKET, PACKET_S, PacedSource, Packet, Source, Status

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
BACKLOG_S = 8.0       # seconds of samples a late viewer gets, and what a takeover's detector is primed on
TAKEOVER_FRESH_S = 1.5  # a source whose last packet is older than this is stale: switching away from it resets instead
BACKLOG_BEATS = 12    # beats a late viewer gets
QUEUE_SIZE = 256      # per viewer; the oldest message is dropped when full

log = logging.getLogger("cardioview")


def dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def asset_version(root: Path = FRONTEND) -> str:
    """A short hash of every viewer file's path, size and mtime: the assets are served under
    /a/<version>/, so a changed set of files gets new URLs and a browser can never pair an old
    cached module with a new one (Chrome's plain reload revalidates only the page itself)."""
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:10]


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

    def history(self) -> Packet | None:
        """The backlog as one packet (it is contiguous: a jump clears it)."""
        if not self.samples:
            return None
        return Packet(self.samples[0]["t"], [v for m in self.samples for v in m["uv"]])

    @property
    def last_beat_r(self) -> float | None:
        return self.beats[-1]["r"] if self.beats else None

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
        self._reaping: set[asyncio.Task] = set()   # old pumps finishing their teardown in the background

    async def start(self, name: str, force: bool = False, **kwargs) -> None:
        if name not in self.factories:
            return
        async with self._lock:
            if name == self.name and not force:
                return
            old = self.source
            # A demo source takes over the running stream from any source that is still fresh, the
            # strap included: nothing already sent is touched, the clock runs on, the next beat
            # lands where the old rhythm would have put it and the rate eases over a few beats.
            # To the strap it is a reset (the strap starts from zero once it connects), and so is
            # leaving a stale source, whose clock would otherwise rush to catch up.
            fresh = (self._last_wall is not None and time.monotonic() - self._last_wall < TAKEOVER_FRESH_S
                     and bool(self.hub.samples))
            await self._stop()
            source = self.factories[name](**kwargs)
            takeover = old is not None and fresh and source.kind != "live" and isinstance(source, PacedSource)
            detector = BeatDetector()
            monitor = SignalMonitor()
            if takeover:
                history = self.hub.history()
                # the fresh detector learns the old stream's last beats from the backlog; a beat the
                # old pump never got to send (it confirms 0.25 s after the R) goes out now
                primed = await asyncio.to_thread(detector.prime, history)
                monitor.update(history, primed)
                sent = self.hub.last_beat_r
                for beat in primed:
                    if sent is None or beat.r > sent + REFRACTORY_S:
                        self.hub.push_beat(beat.message(old.kind))
                last_r, rr = detector.last_r, detector.last_rr
                template = old.template_at(last_r) if last_r is not None and hasattr(old, "template_at") else None
                source.takeover(self._index, last_uv=history.uv[-1], last_r=last_r, rr=rr, template=template)
                # due from the last packet's arrival, but never so far back that the new source
                # bursts to catch up if the switch itself took a moment
                source.anchor(self._index / FS, max(self._last_wall, time.monotonic() - PACKET_S))
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
            self.task = asyncio.create_task(self._pump(source, detector, monitor, takeover), name=f"pump-{name}")
            log.info("source: %s %s%s", name, kwargs or "", " (takeover)" if takeover else "")

    async def _stop(self) -> None:
        if self.task is not None:
            task, self.task = self.task, None
            task.cancel()
            # the strap's teardown is a Bluetooth disconnect that can take a second: it finishes
            # on its own, the new source must not wait for it (Thomas: the switch stalled, then
            # rushed to catch up). A cancelled pump pushes nothing more.
            self._reaping.add(asyncio.create_task(self._reap(task)))
        self.source = None
        self.name = None

    async def _reap(self, task: asyncio.Task) -> None:
        with suppress(asyncio.CancelledError, Exception):
            await task
        self._reaping.discard(asyncio.current_task())

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()
            for t in list(self._reaping):
                with suppress(asyncio.CancelledError, Exception):
                    await t

    async def _pump(self, source: Source, detector: BeatDetector, monitor: SignalMonitor,
                    takeover: bool = False) -> None:
        preroll = 0.0 if takeover else float(getattr(source, "preroll_s", 0.0) or 0.0)
        pending: list[Packet] = []
        try:
            async for packet in source.packets():
                self._index = round(packet.t_end * FS)
                self._last_wall = time.monotonic()
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

    @app.middleware("http")
    async def revalidate(request, call_next):
        # belt and braces with the versioned asset path: every file is revalidated on a reload
        # (a 304 when unchanged), so an edit without a server restart shows up too
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    version = asset_version()

    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        # the page points every relative URL (styles, modules, the import map, the model) at the
        # versioned asset path; the WebSocket URL is absolute and unaffected
        html = (FRONTEND / "index.html").read_text()
        html = html.replace("<head>\n", f'<head>\n<base href="/a/{version}/">\n', 1)
        return HTMLResponse(html)

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

    app.mount(f"/a/{version}", StaticFiles(directory=FRONTEND), name="assets")
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app

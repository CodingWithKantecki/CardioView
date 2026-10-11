"""FastAPI app: serves the viewer and one WebSocket carrying samples, beats and status."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import secrets
import socket
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Callable

import httpx
import numpy as np
import segno
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analysis, chat, describe
from .pattern import PatternModel, PatternWatch
from .pipeline import REFRACTORY_S, BeatDetector, SignalMonitor
from .session import SessionError, SessionManager, SessionStore, utcnow
from .sources.base import FS, PACKET, PACKET_S, PacedSource, Packet, Source, Status
from .sources.remote import RemoteHub, RemoteSource
from .synth import synth_session

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SESSIONS = FRONTEND.parent / "sessions"
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


def lan_address() -> str:
    """This machine's address on the network phones would use. No packet is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@lru_cache(maxsize=1)
def demo_summary() -> dict:
    """The summary page's demo: a synthetic session, nobody's ECG."""
    ses = synth_session(seed=1)
    summary = analysis.analyze(ses.t, ses.uv, ses.steps)
    now = utcnow()
    summary.update(id="demo", created=now.isoformat(), keep_until=(now + timedelta(days=365)).isoformat(),
                   source="simulated", ended_early=False, demo=True)
    return summary


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
        self.session = {"type": "session", "state": "idle"}
        self.on_samples: Callable[[Packet], None] | None = None   # the closest-pattern reader sees what is sent

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

    def set_session(self, msg: dict) -> None:
        self.session = msg
        self.broadcast(msg)

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
        if self.on_samples is not None:
            try:
                self.on_samples(packet)
            except Exception:
                log.exception("pattern hook failed; the live view goes on")

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
        out = [dumps(self.status), dumps(self.signal), dumps(self.session)]
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

    def __init__(self, hub: Hub, factories: dict[str, Callable[..., Source]],
                 on_packet: Callable[[Packet, list], None] | None = None,
                 on_switch: Callable[[float, str], None] | None = None):
        self.hub = hub
        self.factories = factories
        self.on_packet = on_packet           # saved sessions see every live packet and its beats
        self.on_switch = on_switch           # (stream time, kind) each time a source starts
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
            if self.on_switch is not None:
                try:
                    self.on_switch(self._index / FS, source.kind)
                except Exception:
                    log.exception("pattern switch hook failed; the live view goes on")
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

    def last_packet_age(self) -> float | None:
        """Seconds since the running source delivered a packet, or None before the first."""
        return None if self._last_wall is None else time.monotonic() - self._last_wall

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
                if self.on_packet is not None:
                    try:
                        self.on_packet(packet, beats)
                    except Exception:
                        log.exception("saved session hook failed; the live view goes on")
                changed = monitor.update(packet, beats)
                if changed is not None:
                    if changed.ok:
                        detector.forget_rhythm()
                    self.hub.push_signal(changed.message(source.kind))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("source stopped")


class Viewer:
    """One browser tab: its own hub (one subscriber), its own runner and sources, its own strap feed
    (the visitor's Polar H10 through Web Bluetooth, sent over the same websocket) and its own saved
    session. The server keeps no shared heart: every tab is its own world (Thomas, 2026-10-10)."""

    def __init__(self, cid: str, factories: dict[str, Callable[..., Source]], initial: str, *, store: SessionStore,
                 base: str, keep_until: datetime | None, cloud, invert: bool = False,
                 pattern: PatternModel | None = None):
        self.cid = cid
        self.hub = Hub("simulated")
        self.pattern = PatternWatch(pattern, self.hub.broadcast) if pattern is not None else None
        if self.pattern is not None:
            self.hub.on_samples = self.pattern.feed
        self.strap = RemoteHub()
        own = dict(factories)
        if "live" not in own:   # the browser's strap; tests may hand in a live source of their own
            own["live"] = lambda: RemoteSource(self.strap, invert=invert)
        self.sessions = SessionManager(
            store, analyze=analysis.analyze, broadcast=self.hub.set_session,
            link=lambda sid: f"{base}/s/{sid}",
            publish=cloud.publish if cloud else None, unpublish=cloud.unpublish if cloud else None,
            keep_until=keep_until,
        )
        self.runner = Runner(self.hub, own, on_packet=self.sessions.on_packet,
                             on_switch=self.pattern.reset if self.pattern is not None else None)
        self.initial = initial

    async def start(self) -> None:
        await self.runner.start(self.initial)

    async def close(self) -> None:
        if self.sessions.state in ("running", "analyzing"):
            with suppress(Exception):
                await self.sessions.cancel()   # the tab left mid-session: nothing half done is kept
        await self.runner.stop()
        if self.pattern is not None:
            self.pattern.close()


def create_app(factories: dict[str, Callable[[], Source]], initial: str, http: httpx.AsyncClient | None = None, *,
               sessions_dir: Path | None = None, keep_until: datetime | None = None, public_host: str | None = None,
               port: int = 8000, cloud=None, strap_only: bool = True, base_url: str | None = None,
               invert: bool = False, pattern: PatternModel | None = None) -> FastAPI:
    """`factories` maps demo and rhythm (and, for tests, live) to functions that build a source; each
    viewer gets its own instances, and its live source is its own strap unless live is given. `http`
    is the client the chat uses to reach Gemini; tests pass one with a mock transport. `cloud` is an
    object with publish, unpublish and run(manager), or None to keep saved sessions on the laptop.
    With `strap_only` a session starts only while that viewer's strap streams (Thomas: never on demo
    data). `base_url` is the public address links are built on (https://host). `pattern` is the shared
    closest-demo-pattern classifier (backend/pattern.py), loaded in the background at startup, or None."""
    store = SessionStore(sessions_dir or SESSIONS)
    host = public_host or lan_address()
    base = (base_url or f"http://{host}:{port}").rstrip("/")
    viewers: dict[str, Viewer] = {}
    # one manager with no viewer: links and publishing for exports, deletes from phones, the cloud sync
    admin = SessionManager(store, analyze=analysis.analyze, link=lambda sid: f"{base}/s/{sid}",
                           publish=cloud.publish if cloud else None, unpublish=cloud.unpublish if cloud else None,
                           keep_until=keep_until)

    async def ticker() -> None:
        while True:
            await asyncio.sleep(1.0)
            for v in list(viewers.values()):
                v.sessions.tick()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = http or httpx.AsyncClient()
        gone = store.clean_up(utcnow())
        if gone:
            log.info("removed %d unfinished or expired sessions", gone)
        tasks = [asyncio.create_task(ticker(), name="ticker")]
        if cloud is not None:
            tasks.append(asyncio.create_task(cloud.run(admin), name="cloud"))
        if pattern is not None and pattern.state == "off":
            tasks.append(asyncio.create_task(pattern.load(), name="pattern"))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task
            for v in list(viewers.values()):
                await v.close()
            if pattern is not None:
                pattern.close()
            await app.state.http.aclose()

    app = FastAPI(title="CardioView", lifespan=lifespan)
    app.state.viewers = viewers
    app.state.store = store
    app.state.sessions = admin

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

    async def session_action(viewer: Viewer, action: str) -> dict:
        """start, cancel or dismiss this viewer's session; the answer goes back on the socket."""
        sessions, hub = viewer.sessions, viewer.hub
        if action == "start":
            if strap_only and (hub.status["source"] != "live" or hub.status["state"] != "streaming"):
                return {"ok": False, "reason": "Exercise needs the strap on and streaming."}
            sessions.set_source(hub.status["source"], hub.status["device"])
            try:
                return {"ok": True, "id": sessions.start()}
            except SessionError as e:
                age = None if sessions._last_sample_at is None else round(time.monotonic() - sessions._last_sample_at, 2)
                log.info("session start refused for %s: %s (last sample %s s ago, runner %s)", viewer.cid, e, age, viewer.runner.name)
                return {"ok": False, "reason": str(e)}
        if action == "cancel":
            await sessions.cancel()
            return {"ok": True}
        if action == "dismiss":
            sessions.dismiss()
            return {"ok": True}
        return {"ok": False, "reason": "Unknown session action."}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        """One viewer: the backlog, then everything its pipeline produces. In: source and rhythm
        choices, the browser strap's status and samples, and session actions."""
        await websocket.accept()
        cid = secrets.token_urlsafe(9)
        viewer = Viewer(cid, factories, initial, store=store, base=base, keep_until=keep_until, cloud=cloud, invert=invert,
                        pattern=pattern)
        viewers[cid] = viewer
        hub, runner, sessions = viewer.hub, viewer.runner, viewer.sessions
        q = hub.subscribe()
        await viewer.start()

        async def send() -> None:
            texts = hub.backlog()   # status, signal, session, then whatever samples and beats are kept
            for text in texts[:3]:
                await websocket.send_text(text)
            await websocket.send_text(dumps({"type": "hello", "cid": cid}))
            for text in texts[3:]:
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
                kind = msg.get("type")
                if kind in ("source", "rhythm") and sessions.state in ("running", "analyzing"):
                    continue   # a session records one source: stop it first
                if kind == "source":
                    await runner.start(str(msg.get("name", "")))
                elif kind == "rhythm":
                    pattern = str(msg.get("name", ""))
                    if pattern == "custom":   # a described rhythm sent back by the page (after a reconnect)
                        recipe = describe.clamp(msg.get("recipe"))
                        if recipe is not None:
                            await runner.start("rhythm", force=True, pattern="custom", recipe=recipe)
                    elif not (runner.name == "rhythm" and getattr(runner.source, "pattern", None) == pattern):
                        await runner.start("rhythm", force=True, pattern=pattern)
                elif kind == "samples" and isinstance(msg.get("uv"), list):
                    try:
                        viewer.strap.push_samples(float(msg.get("t", 0.0)), [int(v) for v in msg["uv"]])
                    except (TypeError, ValueError):
                        log.warning("strap samples from %s were not whole microvolts; dropped", cid)
                        continue
                elif kind == "status":
                    viewer.strap.push_status(str(msg.get("state", "connecting")), str(msg.get("device", ""))[:80])
                elif kind == "session":
                    action = str(msg.get("action", ""))
                    result = await session_action(viewer, action)
                    hub.broadcast({"type": "session_result", "action": action, **result})

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
            viewers.pop(cid, None)
            await viewer.close()

    @app.post("/api/rhythm/describe")
    async def rhythm_describe(request: Request) -> JSONResponse:
        """Gemini heart. Body: {"cid", "text"}: a patient, a situation or a rhythm in words. Gemini
        fills the simulator's recipe (backend/describe.py), the viewer's demo switches to it, and
        the answer is {"ok", "name", "summary", "recipe", "reply"}; `reply` is always words for the panel."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        viewer = viewers.get(str(body.get("cid", "")))
        if viewer is None:
            return JSONResponse({"ok": False, "reply": "Reload the page and try again", "error": "viewer"}, status_code=404)
        if viewer.sessions.state in ("running", "analyzing"):
            return JSONResponse({"ok": False, "reply": "Stop the session first", "error": "session"}, status_code=409)
        text = body.get("text")
        result = await describe.describe(text if isinstance(text, str) else "", app.state.http)
        if result.recipe is None:
            return JSONResponse({"ok": False, "reply": result.reply, "error": result.error}, status_code=result.status)
        await viewer.runner.start("rhythm", force=True, pattern="custom", recipe=result.recipe)
        return JSONResponse({"ok": True, "name": result.recipe.name, "summary": result.recipe.summary,
                             "recipe": asdict(result.recipe), "reply": result.recipe.summary})

    @app.post("/api/chat")
    async def chat_endpoint(request: Request) -> JSONResponse:
        """One question about the data on screen. Body: {"question": str, "history": [{"role", "text"}],
        "cid": the viewer's id from its hello}. The answer is {"reply", "error"}; `reply` is always words
        to show, `error` is null or a reason."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        question = body.get("question")
        if not isinstance(question, str):
            question = ""
        viewer = viewers.get(str(body.get("cid", "")))
        snap = chat.snapshot(viewer.hub if viewer else Hub("simulated"), viewer.runner.last_packet_age() if viewer else None)
        result = await chat.ask(question, body.get("history"), snap, app.state.http)
        return JSONResponse(result.body(), status_code=result.status)

    async def find_summary(sid: str) -> dict | None:
        # in a thread: the first demo summary takes seconds of NeuroKit work, and the pumps share this loop
        return await asyncio.to_thread(lambda: demo_summary() if sid == "demo" else store.summary(sid, utcnow()))

    @app.post("/api/export/report")
    async def export_report(request: Request):
        """The page's ECG buffer in (fs, t0, uv, source, device); a saved summary out, served like a
        session at /s/<id> with its QR, so the printed report's code opens the same page later."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("uv"), list):
            return JSONResponse({"reason": "Send fs, t0 and uv."}, status_code=400)
        try:
            uv = [int(v) for v in body["uv"]]
            t0 = float(body.get("t0", 0.0))
        except (TypeError, ValueError):
            return JSONResponse({"reason": "uv must be whole microvolts and t0 a number."}, status_code=400)
        if len(uv) < 5 * FS:
            return JSONResponse({"reason": "Less than 5 seconds of ECG, nothing to measure yet."}, status_code=409)
        if len(uv) > 15 * 60 * FS:
            return JSONResponse({"reason": "More than 15 minutes; export a shorter stretch."}, status_code=413)
        source = str(body.get("source", "unknown"))[:20]
        device = str(body.get("device", ""))[:80]
        sid = store.new_id()
        created = utcnow()
        packet = Packet(t0, uv)
        seconds = round(len(uv) / FS, 2)
        meta = {"id": sid, "created": created.isoformat(), "keep_until": admin.keep_until.isoformat(),
                "source": source, "device": device, "state": "recording",
                "consent": {"by": "operator", "how": "export", "at": created.isoformat()},
                "steps": [], "ended_early": False, "published": False, "export": True}
        rest = [{"name": "rest", "start": t0, "end": packet.t_end}]   # the whole stretch measures as rest

        def build() -> dict:
            store.create(sid, meta)
            store.append(sid, packet, [])
            t = t0 + np.arange(len(uv)) / FS
            return analysis.analyze(t, np.asarray(uv), rest)

        summary = await asyncio.to_thread(build)
        summary["steps"] = [{"name": "export", "start": 0.0, "end": seconds}]
        summary.update(id=sid, created=meta["created"], keep_until=meta["keep_until"], source=source,
                       ended_early=False, export=True, seconds=round(seconds))
        link = admin.link(sid)
        if admin.publish is not None:
            try:
                public = await admin.publish(sid, summary, admin.keep_until)
            except Exception:
                log.exception("could not publish export %s", sid)
                public = None
            if public:
                link, meta["published"] = public, True
        meta.update(state="done", link=link, steps=[{"name": "export", "start": t0, "end": packet.t_end, "seconds": seconds}])
        await asyncio.to_thread(store.write_summary, sid, summary)
        await asyncio.to_thread(store.write_meta, sid, meta)
        return {"id": sid, "link": link, "seconds": round(seconds)}

    @app.get("/api/s/{sid}")
    async def summary_get(sid: str):
        summary = await find_summary(sid)
        if summary is None:
            return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        return summary

    @app.delete("/api/s/{sid}")
    async def summary_delete(sid: str):
        if sid == "demo" or not store.valid_id(sid):
            return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        owner = next((v.sessions for v in list(viewers.values()) if v.sessions.sid == sid), admin)   # its viewer forgets it too
        if not await owner.delete(sid):
            return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        return {"ok": True}

    @app.get("/api/s/{sid}/ecg")
    async def summary_ecg(sid: str):
        """The session's whole ECG for the report's rhythm strips: raw microvolts at 130 Hz from
        the stored recording (the demo's from the synthetic session). The cloud copy has no ECG."""
        if sid == "demo":
            t, uv = await asyncio.to_thread(lambda: (lambda ses: (ses.t, ses.uv))(synth_session(seed=1)))
        else:
            if not store.valid_id(sid) or await find_summary(sid) is None:
                return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
            try:
                t, uv = await asyncio.to_thread(store.read_recording, sid)
            except OSError:
                return JSONResponse({"reason": "This session is no longer available."}, status_code=404)
        if len(uv) == 0:
            return JSONResponse({"reason": "No ECG was kept for this session."}, status_code=404)
        return {"fs": FS, "t0": round(float(t[0]), 4), "uv": [int(v) for v in uv]}

    @app.get("/api/s/{sid}/qr.svg")
    async def summary_qr(sid: str):
        if await find_summary(sid) is None:
            return Response(status_code=404)
        stored = (store.read_meta(sid) or {}).get("link") if sid != "demo" and store.valid_id(sid) else None
        link = stored or admin.link(sid)
        buf = io.BytesIO()
        segno.make(link, error="m").save(buf, kind="svg", scale=8, border=3, dark="#0A1115", light="#E8F1F2")
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.get("/s/{sid}")
    async def summary_page(sid: str):
        return FileResponse(FRONTEND / "summary.html")

    app.mount(f"/a/{version}", StaticFiles(directory=FRONTEND), name="assets")
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="viewer")
    return app

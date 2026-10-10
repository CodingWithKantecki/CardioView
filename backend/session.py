"""Saved visitor sessions: the guided steps, the recording on disk and the summary.

A session only exists after the operator pressed S twice, which is the visitor's
consent to save it. Step clocks count samples that arrived, so a step pauses on
its own while the strap is away. Cancel deletes everything, here and in the cloud.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import re
import secrets
import shutil
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

from .sources.base import FS, PACKET_S, Packet

log = logging.getLogger("cardioview.session")

# name, planned seconds; get_ready is a maximum, it ends once the signal is clean for 5 s
STEPS = (("get_ready", 30.0), ("rest", 30.0), ("breathe", 40.0), ("squats", 20.0), ("recover", 30.0))
CLEAN_S = 5.0          # get_ready needs this long without clipping and with steady beats
CLIP_UV = 19000
RR_MIN, RR_MAX = 0.3, 2.0
PAUSED_S = 1.5         # no samples for this long: the stage says paused
DROP_LIMIT_S = 15.0    # no samples for this long: the session ends with the steps that finished
NO_SIGNAL_S = 2.0      # start needs a sample this recent
KEEP_DEFAULT = timedelta(hours=24)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionError(Exception):
    """A start that cannot happen, with a reason the stage can show."""


class SessionStore:
    """One folder per session under root: session.json, ecg.csv, beats.csv, summary.json."""

    def __init__(self, root: Path):
        self.root = Path(root)   # created on the first save, so a server that never saves leaves nothing

    @staticmethod
    def valid_id(sid: str) -> bool:
        return bool(ID_RE.match(sid or ""))

    def new_id(self) -> str:
        return secrets.token_urlsafe(16)   # 128 random bits, 22 characters

    def path(self, sid: str) -> Path:
        if not self.valid_id(sid):
            raise ValueError(f"not a session id: {sid!r}")
        return self.root / sid

    def create(self, sid: str, meta: dict) -> None:
        p = self.path(sid)
        p.mkdir(parents=True)
        self.write_meta(sid, meta)
        (p / "ecg.csv").write_text("time_s,ecg_uv\n")
        (p / "beats.csv").write_text("r,rr,bpm\n")

    def append(self, sid: str, packet: Packet, beats: list) -> None:
        p = self.path(sid)
        with open(p / "ecg.csv", "a", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerows((f"{packet.t + i / FS:.6f}", v) for i, v in enumerate(packet.uv))
        if beats:
            with open(p / "beats.csv", "a", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerows((b.r, "" if b.rr is None else b.rr, "" if b.bpm is None else b.bpm) for b in beats)

    def read_meta(self, sid: str) -> dict | None:
        try:
            return json.loads((self.path(sid) / "session.json").read_text())
        except (OSError, ValueError):
            return None

    def write_meta(self, sid: str, meta: dict) -> None:
        (self.path(sid) / "session.json").write_text(json.dumps(meta, indent=1))

    def read_recording(self, sid: str) -> tuple[np.ndarray, np.ndarray]:
        t, uv = [], []
        with open(self.path(sid) / "ecg.csv", newline="") as f:
            for row in csv.DictReader(f):
                t.append(float(row["time_s"]))
                uv.append(int(row["ecg_uv"]))
        return np.asarray(t, dtype=float), np.asarray(uv, dtype=int)

    def write_summary(self, sid: str, summary: dict) -> None:
        (self.path(sid) / "summary.json").write_text(json.dumps(summary, allow_nan=False))

    def summary(self, sid: str, now: datetime) -> dict | None:
        """The summary of a finished session that has not expired, else None."""
        if not self.valid_id(sid):
            return None
        meta = self.read_meta(sid)
        if not meta or meta.get("state") != "done" or datetime.fromisoformat(meta["keep_until"]) <= now:
            return None
        try:
            return json.loads((self.path(sid) / "summary.json").read_text())
        except (OSError, ValueError):
            return None

    def delete(self, sid: str) -> bool:
        if not self.valid_id(sid) or not self.path(sid).exists():
            return False
        shutil.rmtree(self.path(sid))
        return True

    def ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.valid_id(p.name))

    def clean_up(self, now: datetime) -> int:
        """Delete unfinished and expired sessions. Run at startup and by the wipe tool."""
        gone = 0
        for sid in self.ids():
            meta = self.read_meta(sid)
            if not meta or meta.get("state") != "done" or datetime.fromisoformat(meta["keep_until"]) <= now:
                self.delete(sid)
                gone += 1
        return gone


@dataclass
class StepClock:
    name: str
    length_s: float
    start: float | None = None   # stream time of the step's first sample
    end: float | None = None     # stream time after its last sample
    samples: int = 0
    done: bool = False

    @property
    def elapsed_s(self) -> float:
        return self.samples / FS

    def window(self) -> dict:
        return {"name": self.name, "start": self.start, "end": self.end}


class SessionManager:
    """The one session that can run at a time, driven by the server's packets.

    analyze(t, uv, steps) -> summary runs in a thread when the steps finish.
    publish(sid, summary, keep_until) -> public link or None, unpublish(sid): the cloud, optional.
    link(sid) -> the local link used when there is no public one.
    broadcast(message) sends a session message to every viewer.
    """

    def __init__(self, store: SessionStore, *, analyze: Callable[..., dict],
                 broadcast: Callable[[dict], None] = lambda m: None,
                 link: Callable[[str], str] = lambda sid: f"/s/{sid}",
                 publish: Callable[[str, dict, datetime], Awaitable[str | None]] | None = None,
                 unpublish: Callable[[str], Awaitable[None]] | None = None,
                 keep_until: datetime | None = None,
                 now: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = utcnow):
        self.store, self.analyze, self.broadcast, self.link = store, analyze, broadcast, link
        self.publish, self.unpublish = publish, unpublish
        self.now, self.wall = now, wall
        self.keep_until = keep_until or (wall() + KEEP_DEFAULT)
        self.source_kind, self.device = "simulated", ""
        self.state = "idle"            # idle, running, analyzing, done
        self.sid: str | None = None
        self.steps: list[StepClock] = []
        self.i = 0
        self.note: str | None = None   # why the last session stopped, for the stage
        self.done_link: str | None = None
        self.online = False
        self.finishing: asyncio.Task | None = None
        self._gen = 0                  # bumps on cancel, so a late analysis is dropped
        self._meta: dict = {}
        self._last_sample_at: float | None = None
        self._last_end: float | None = None
        self._last_t: float | None = None
        self._recent_uv: deque[int] = deque(maxlen=int(CLEAN_S * FS))
        self._recent_beats: deque[tuple[float, float | None]] = deque(maxlen=16)

    # inputs from the server ------------------------------------------------

    def set_source(self, kind: str, device: str) -> None:
        self.source_kind, self.device = kind, device

    def on_packet(self, packet: Packet, beats: list) -> None:
        self._last_sample_at = self.now()
        if self._last_end is not None and abs(packet.t - self._last_end) > PACKET_S:
            self._recent_uv.clear()
            self._recent_beats.clear()
        self._recent_uv.extend(packet.uv)
        self._recent_beats.extend((b.r, b.rr) for b in beats)
        self._last_t, self._last_end = packet.t_last, packet.t_end
        if self.state != "running":
            return
        try:
            self.store.append(self.sid, packet, beats)
        except OSError:
            log.exception("could not write the session")
            self._stop("write_failed")
            return
        st = self.steps[self.i]
        if st.start is None:
            st.start = packet.t
        st.samples += len(packet.uv)
        st.end = packet.t_end
        if st.elapsed_s >= st.length_s or (st.name == "get_ready" and st.elapsed_s >= CLEAN_S and self.clean()):
            st.done = True
            self.i += 1
            if self.i == len(self.steps):
                self._finish_soon(early=False)
                return
        self.broadcast(self.message())

    def tick(self) -> None:
        """Called about once a second: tells the stage about a pause, ends a session after a long drop."""
        if self.state != "running":
            return
        if self._last_sample_at is not None and self.now() - self._last_sample_at > DROP_LIMIT_S:
            self._finish_soon(early=True)
        else:
            self.broadcast(self.message())

    def clean(self) -> bool:
        """The last 5 s had no clipping and at least 3 steady beats."""
        if len(self._recent_uv) < self._recent_uv.maxlen or max(map(abs, self._recent_uv)) >= CLIP_UV:
            return False
        steady = [r for r, rr in self._recent_beats
                  if rr is not None and RR_MIN <= rr <= RR_MAX and r >= self._last_t - CLEAN_S]
        return len(steady) >= 3

    def paused(self) -> bool:
        return self._last_sample_at is not None and self.now() - self._last_sample_at > PAUSED_S

    # operator actions ------------------------------------------------------

    def start(self) -> str:
        if self.state in ("running", "analyzing"):
            raise SessionError("A session is already running.")
        if self._last_sample_at is None or self.now() - self._last_sample_at > NO_SIGNAL_S:
            raise SessionError("No signal yet.")
        sid = self.store.new_id()
        created = self.wall()
        self._meta = {
            "id": sid, "created": created.isoformat(), "keep_until": self.keep_until.isoformat(),
            "source": self.source_kind, "device": self.device, "state": "recording",
            "consent": {"by": "operator", "how": "pressed S twice", "at": created.isoformat()},
            "steps": [], "ended_early": False, "published": False,
        }
        try:
            self.store.create(sid, self._meta)
        except OSError as e:
            log.exception("could not create the session folder")
            raise SessionError("Could not save the session.") from e
        self.sid, self.state, self.i, self.note = sid, "running", 0, None
        self.steps = [StepClock(name, length) for name, length in STEPS]
        self.done_link, self.online = None, False
        self.broadcast(self.message())
        return sid

    async def cancel(self) -> None:
        if self.state not in ("running", "analyzing"):
            return
        await self._unpublish(self._stop("stopped"))

    def dismiss(self) -> None:
        if self.state == "done":
            self.state, self.sid, self.note = "idle", None, None
            self.broadcast(self.message())

    async def delete(self, sid: str) -> bool:
        """Delete one session everywhere. The running one is cancelled."""
        if sid == self.sid and self.state in ("running", "analyzing"):
            await self.cancel()
            return True
        existed = self.store.delete(sid)
        await self._unpublish(sid)
        if sid == self.sid and self.state == "done":
            self.state, self.sid = "idle", None
            self.broadcast(self.message())
        return existed

    def update_link(self, sid: str, link: str) -> None:
        """The cloud caught up: the summary on screen gets the public link."""
        if self.state == "done" and sid == self.sid:
            self.done_link, self.online = link, True
            self.broadcast(self.message())

    # messages --------------------------------------------------------------

    def message(self) -> dict:
        if self.state == "running":
            st = self.steps[self.i]
            return {"type": "session", "state": "running", "id": self.sid, "step": st.name,
                    "index": self.i, "count": len(self.steps), "elapsed_s": round(st.elapsed_s, 2),
                    "length_s": st.length_s, "paused": self.paused()}
        if self.state == "analyzing":
            return {"type": "session", "state": "analyzing", "id": self.sid}
        if self.state == "done":
            return {"type": "session", "state": "done", "id": self.sid, "link": self.done_link, "online": self.online}
        msg = {"type": "session", "state": "idle"}
        if self.note:
            msg["note"] = self.note
        return msg

    # finishing ---------------------------------------------------------------

    def _finish_soon(self, early: bool) -> None:
        self.state = "analyzing"
        self.broadcast(self.message())
        self.finishing = asyncio.get_running_loop().create_task(self._finish(self._gen, early))

    async def _finish(self, gen: int, early: bool) -> None:
        sid = self.sid
        steps = [s.window() for s in self.steps if s.done]
        try:
            t, uv = await asyncio.to_thread(self.store.read_recording, sid)
            summary = await asyncio.to_thread(self.analyze, t, uv, steps)
        except Exception:
            log.exception("could not analyze %s", sid)
            summary = {"version": 1, "steps": [], **{k: {"ok": False, "reason": "Something went wrong measuring this."}
                                                      for k in ("effort", "breathing", "hrv", "beat", "timing")}}
        if gen != self._gen:
            return   # cancelled while analyzing; _abort already deleted it
        meta = self._meta
        meta.update(state="done", ended_early=early,
                    steps=[{**w, "seconds": round(s.elapsed_s, 2)} for s, w in zip(self.steps, steps)])
        summary.update(id=sid, created=meta["created"], keep_until=meta["keep_until"],
                       source=meta["source"], ended_early=early)
        self.store.write_summary(sid, summary)
        self.store.write_meta(sid, meta)
        link, online = self.link(sid), False
        if self.publish is not None:
            try:
                public = await self.publish(sid, summary, self.keep_until)
            except Exception:
                log.exception("could not publish %s", sid)
                public = None
            if gen != self._gen:
                await self._unpublish(sid)   # cancelled while uploading: take it back down
                return
            if public:
                link, online = public, True
                meta["published"] = True
                self.store.write_meta(sid, meta)
        if gen != self._gen:
            return
        self.state, self.done_link, self.online = "done", link, online
        self.broadcast(self.message())

    def _stop(self, note: str) -> str | None:
        """End the session now and delete its folder. Returns the id for the cloud cleanup."""
        sid = self.sid
        self._gen += 1
        self.state, self.sid, self.note = "idle", None, note
        if sid:
            self.store.delete(sid)
        self.broadcast(self.message())
        return sid

    async def _unpublish(self, sid: str | None) -> None:
        if sid and self.unpublish is not None:
            try:
                await self.unpublish(sid)
            except Exception:
                log.exception("could not delete %s from the cloud", sid)

"""Closest demo pattern (experimental): the classifier in tools/rhythm_model, run on each viewer's last
10 s of samples every 5 s. It needs torch and the HuBERT-ECG package (tools/requirements-ml.txt); without
them, or without the trained head, it stays off and the viewer shows nothing.

Messages, viewer bound: {"type": "pattern", "source", "t", "name", "label", "p"} where `t` is the stream
time the read window ends at and `name` is a demo pattern, "none", "unsure", or null for "no reading
yet from here on" (a source switch or a gap in the samples)."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np

from .sources.base import FS, Packet

WINDOW_S = 10.0
HOP_S = 5.0
THREADS = 2   # torch threads: the beat pipeline keeps the rest of the CPU

log = logging.getLogger("cardioview")


def _load_classifier():
    import torch

    torch.set_num_threads(THREADS)
    from tools.rhythm_model.classify import Classifier

    return Classifier()


class PatternModel:
    """The classifier, loaded once in the background and shared by every viewer. One worker thread
    runs it, so readings queue there and never hold up the threads the beat detector uses."""

    def __init__(self, loader: Callable = _load_classifier):
        self._loader = loader
        self._clf = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pattern")
        self.state = "off"   # off, loading, ready, failed

    @property
    def active(self) -> bool:
        return self.state in ("loading", "ready")

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    async def load(self) -> None:
        self.state = "loading"
        try:
            self._clf = await asyncio.get_running_loop().run_in_executor(self._pool, self._loader)
        except Exception as e:   # no torch, no head, no cached weights offline: the label stays off
            self.state = "failed"
            log.info("pattern: closest demo pattern is off (%s: %s)", type(e).__name__, e)
            return
        self.state = "ready"
        log.info("pattern: closest demo pattern is on")

    async def classify(self, uv: np.ndarray) -> tuple[str, float]:
        return await asyncio.get_running_loop().run_in_executor(self._pool, lambda: self._clf.closest([uv])[0])

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def label_for(name: str) -> str:
    from tools.rhythm_model.data import NAMES

    return NAMES.get(name, "Unsure")


class PatternWatch:
    """One viewer: keeps the last 10 s of what its hub sent and asks the model about it every 5 s."""

    def __init__(self, model: PatternModel, send: Callable[[dict], None]):
        self.model = model
        self.send = send
        self.source = "simulated"
        self._buf = np.zeros(0, dtype=np.int32)
        self._t_end: float | None = None   # stream time just after the last kept sample
        self._new = 0                       # samples since the last reading
        self._read_any = False              # a reading has been asked for since the last reset
        self._gen = 0                       # bumps on a reset, so an answer about an old stream is dropped
        self._busy = False
        self._tasks: set[asyncio.Task] = set()

    def reset(self, t: float, source: str | None = None) -> None:
        """A new source from stream time t: forget the window and say there is no reading yet."""
        if source is not None:
            self.source = source
        self._buf = np.zeros(0, dtype=np.int32)
        self._t_end = None
        self._new = 0
        self._read_any = False
        self._gen += 1
        if self.model.active:
            self.send({"type": "pattern", "source": self.source, "t": round(t, 3), "name": None})

    def feed(self, packet: Packet) -> None:
        if not self.model.active or not packet.uv:
            return
        if self._t_end is not None and abs(packet.t - self._t_end) > 1.5 / FS:
            self.reset(packet.t)   # a gap or a jump: a window must never straddle it
        win = int(WINDOW_S * FS)
        self._buf = np.concatenate([self._buf, np.asarray(packet.uv, dtype=np.int32)])[-win:]
        self._t_end = packet.t + len(packet.uv) / FS
        self._new += len(packet.uv)
        if len(self._buf) < win or self._busy or not self.model.ready:
            return
        if self._read_any and self._new < int(HOP_S * FS):
            return   # read as soon as the window is full, then every 5 s
        self._read_any = True
        self._new = 0
        self._busy = True
        task = asyncio.get_running_loop().create_task(self._read(self._buf.copy(), self._t_end, self._gen))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(self, uv: np.ndarray, t_end: float, gen: int) -> None:
        try:
            name, p = await self.model.classify(uv)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pattern: a reading failed; the live view goes on")
            return
        finally:
            self._busy = False
        if gen == self._gen:
            self.send({"type": "pattern", "source": self.source, "t": round(t_end, 3), "name": name,
                       "label": label_for(name), "p": round(p, 3)})

    def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()

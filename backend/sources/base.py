"""Shared types and the strap-like pacing used by every source."""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Iterable, Iterator

FS = 130                 # samples per second
PACKET = 73              # samples per packet, like the strap
PACKET_S = PACKET / FS   # about 0.56 s
PREROLL_S = 10.0         # history a simulated or recorded source emits at once when it starts, so a switch fills the screen instantly
JOIN_TAU_S = 0.08        # at a takeover, the step from the old stream's last value decays with this time constant
MIN_FIRST_BEAT_S = 0.30  # after a takeover the first beat comes no sooner than this after the join


@dataclass
class Packet:
    t: float          # stream time of the first sample, seconds
    uv: list[int]     # signed microvolts

    @property
    def t_last(self) -> float:
        return self.t + (len(self.uv) - 1) / FS

    @property
    def t_end(self) -> float:
        """Stream time of the sample that follows this packet."""
        return self.t + len(self.uv) / FS


@dataclass
class Status:
    state: str = "connecting"   # connecting, streaming, reconnecting
    device: str = ""


class Source:
    """Base for every ECG source. Subclasses yield Packets in real time."""

    kind = "simulated"   # simulated, recorded, live

    def __init__(self, invert: bool = False):
        self.invert = invert
        self.status = Status()
        self._listeners: list[Callable[[Status], None]] = []

    def on_status(self, fn: Callable[[Status], None]) -> None:
        self._listeners.append(fn)

    def set_status(self, state: str, device: str | None = None) -> None:
        if device is not None:
            self.status.device = device
        self.status.state = state
        for fn in self._listeners:
            fn(self.status)

    def _oriented(self, uv: Iterable[int]) -> list[int]:
        return [-v for v in uv] if self.invert else list(uv)

    async def packets(self) -> AsyncIterator[Packet]:
        raise NotImplementedError
        yield  # pragma: no cover


def cycle_forever(values: list[int], start: int = 0) -> Iterator[int]:
    if not values:
        raise ValueError("no samples to play")
    start %= len(values)
    yield from values[start:]
    while True:
        yield from values


class PacedSource(Source):
    """Plays an endless sample stream like the strap does.

    73 samples per packet, a packet when its last sample is due, scheduled
    against an absolute start so it never drifts. The first `preroll_s` seconds
    are already due when it starts, so they come out at once. `sleep` and `now`
    can be swapped for fakes in tests.
    """

    def __init__(self, samples: Iterator[int], invert: bool = False,
                 sleep=asyncio.sleep, now=time.monotonic, preroll_s: float = 0.0):
        super().__init__(invert)
        self._samples = samples
        self._sleep = sleep
        self._now = now
        self.index = 0   # stream index of the next sample
        self.preroll_s = preroll_s
        self._anchor: tuple[float, float] | None = None   # (stream time, wall time it is due)
        self._join_uv: int | None = None   # the old stream's last value, met at a takeover
        self._join_offset = 0.0
        self._join_n = 0

    def anchor(self, stream_s: float, wall: float) -> None:
        """Pin the schedule for a handover: stream time `stream_s` is due at wall time `wall`,
        so this source continues another one's clock without a skip."""
        self._anchor = (stream_s, wall)

    def takeover(self, index: int, last_uv: int | None = None, last_r: float | None = None,
                 rr: float | None = None, template=None) -> None:
        """Continue another source's stream: start at sample `index` so stream time runs on, meet
        its last value `last_uv` (the step decays over JOIN_TAU_S), and carry on from its last beat
        (`last_r`, that beat's interval `rr` and, from a rhythm source, its template), which
        subclasses use to place the next beat and ease the rate. No preroll."""
        self.index = index
        self.preroll_s = 0.0
        self._join_uv = last_uv
        self._join_n = 0

    def _joined(self, uv: list[int]) -> list[int]:
        """Meet the old stream's last value: a decaying offset, gone after about half a second."""
        if self._join_n == 0:
            self._join_offset = float(self._join_uv - uv[0])
        k = FS * JOIN_TAU_S
        out = [v + int(round(self._join_offset * math.exp(-(self._join_n + i) / k))) for i, v in enumerate(uv)]
        self._join_n += len(uv)
        if abs(self._join_offset) * math.exp(-self._join_n / k) < 0.5:
            self._join_uv = None
        return out

    async def packets(self) -> AsyncIterator[Packet]:
        start = (self._anchor[1] - self._anchor[0]) if self._anchor else (self._now() - self.preroll_s)
        self.set_status("streaming")
        while True:
            uv = self._oriented([next(self._samples) for _ in range(PACKET)])
            if self._join_uv is not None:
                uv = self._joined(uv)
            t = self.index / FS
            self.index += PACKET
            delay = start + self.index / FS - self._now()
            if delay > 0:
                await self._sleep(delay)
            yield Packet(t, uv)

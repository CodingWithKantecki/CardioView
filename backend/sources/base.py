"""Shared types and the strap-like pacing used by every source."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Iterable, Iterator

FS = 130                 # samples per second
PACKET = 73              # samples per packet, like the strap
PACKET_S = PACKET / FS   # about 0.56 s


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

    def seed(self, index: int, last_wall: float | None) -> None:
        """Continue another source's stream clock: the next packet starts at sample `index`,
        due one packet after `last_wall` (monotonic time of the previous packet)."""

    async def packets(self) -> AsyncIterator[Packet]:
        raise NotImplementedError
        yield  # pragma: no cover


def cycle_forever(values: list[int]) -> Iterator[int]:
    if not values:
        raise ValueError("no samples to play")
    while True:
        yield from values


class PacedSource(Source):
    """Plays an endless sample stream like the strap does.

    73 samples per packet, a packet when its last sample is due, scheduled
    against an absolute start so it never drifts. `sleep` and `now` can be
    swapped for fakes in tests.
    """

    def __init__(self, samples: Iterator[int], invert: bool = False,
                 sleep=asyncio.sleep, now=time.monotonic):
        super().__init__(invert)
        self._samples = samples
        self._sleep = sleep
        self._now = now
        self.index = 0   # stream index of the next sample
        self._start_hint: float | None = None

    def seed(self, index: int, last_wall: float | None) -> None:
        self.index = index
        self._start_hint = last_wall

    async def packets(self) -> AsyncIterator[Packet]:
        start = (self._start_hint if self._start_hint is not None else self._now()) - self.index / FS
        self.set_status("streaming")
        while True:
            uv = [next(self._samples) for _ in range(PACKET)]
            t = self.index / FS
            self.index += PACKET
            delay = start + self.index / FS - self._now()
            if delay > 0:
                await self._sleep(delay)
            yield Packet(t, self._oriented(uv))

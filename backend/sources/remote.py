"""The strap over the network: a bridge on the booth laptop (tools/bridge.py) reads the Polar H10
and streams its packets to the server's /ws/strap, and RemoteSource plays them as the live source.
The cloud copy of CardioView has no Bluetooth; this is how it shows a real heart."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import AsyncIterator

from .base import Packet, Source

log = logging.getLogger("cardioview.remote")
KEEP = 64   # packets kept while nobody plays them (about 36 s), the oldest dropped first


class RemoteHub:
    """What the bridge sends, for whichever RemoteSource is running: a queue of packets and the
    bridge's latest status. One bridge at a time; a new one replaces the old."""

    def __init__(self) -> None:
        self.queue: deque = deque(maxlen=KEEP)
        self.wake = asyncio.Event()
        self.state = "connecting"
        self.device = ""
        self.bridges = 0

    def push_status(self, state: str, device: str) -> None:
        self.state, self.device = state, device
        self.queue.append(("status", state, device))
        self.wake.set()

    def push_samples(self, t: float, uv: list[int]) -> None:
        self.queue.append(("samples", t, uv))
        self.wake.set()

    def bridge_gone(self) -> None:
        self.push_status("connecting", "")


class RemoteSource(Source):
    kind = "live"

    def __init__(self, hub: RemoteHub, invert: bool = False):
        super().__init__(invert)
        self.hub = hub
        self.status.device = hub.device

    async def packets(self) -> AsyncIterator[Packet]:
        hub = self.hub
        hub.queue.clear()   # whatever piled up before this source started is stale
        self.set_status(hub.state if hub.state == "streaming" else "connecting", hub.device)
        while True:
            while not hub.queue:
                hub.wake.clear()
                await hub.wake.wait()
            item = hub.queue.popleft()
            if item[0] == "status":
                self.set_status(item[1], item[2])
            else:
                yield Packet(item[1], self._oriented(item[2]))

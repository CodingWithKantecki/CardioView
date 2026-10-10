"""Live ECG from a Polar H10 over Bluetooth LE, with reconnect.

Stream time is a running sample index / 130. When the strap drops and comes
back, the index advances by the wall-clock gap so the viewer clock stays
aligned. The scanner and client can be swapped for fakes in tests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Awaitable, Callable

from bleak import BleakClient, BleakScanner
from bleakheart import BatteryLevel, PolarMeasurementData

from .base import FS, PACKET_S, Packet, Source

log = logging.getLogger("cardioview.h10")
NAME = "polar h10"
SCAN_TIMEOUT_S = 15.0


def is_h10(device, adv) -> bool:
    name = getattr(adv, "local_name", None) or getattr(device, "name", None) or ""
    return NAME in name.lower()


async def find_strap(timeout: float = SCAN_TIMEOUT_S):
    """The first Polar H10 that advertises, or None after `timeout` seconds."""
    return await BleakScanner.find_device_by_filter(is_h10, timeout=timeout)


class H10Source(Source):
    kind = "live"

    def __init__(self, invert: bool = False, *,
                 scanner: Callable[[], Awaitable] = find_strap,
                 client_factory=BleakClient,
                 backoff_s: float = 1.0,
                 max_scans: int | None = None,
                 silence_s: float = 5.0,
                 sleep=asyncio.sleep, now=time.monotonic):
        super().__init__(invert)
        self._scan = scanner
        self._client_factory = client_factory
        self._backoff = backoff_s
        self._max_scans = max_scans
        self._silence = silence_s
        self._sleep = sleep
        self._now = now
        self.index = 0              # stream index of the next sample
        self.battery: int | None = None
        self._last_wall: float | None = None

    def seed(self, index: int, last_wall: float | None) -> None:
        self.index = index
        self._last_wall = last_wall   # the gap until the strap streams again is added on resume

    async def packets(self) -> AsyncIterator[Packet]:
        scans = 0
        first = True
        while True:
            self.set_status("connecting" if first else "reconnecting")
            try:
                device = await self._scan()
            except Exception as e:
                log.warning("scan failed: %s", e)
                device = None
            if device is None:
                scans += 1
                log.info("no Polar H10 seen yet (scan %d)", scans)
                if self._max_scans is not None and scans >= self._max_scans:
                    raise RuntimeError("no Polar H10 found. Wet the pads, wear the strap, close Polar apps.")
                await self._sleep(self._backoff)
                continue
            scans = 0
            name = getattr(device, "name", None) or "Polar H10"
            try:
                async for packet in self._stream(device, name):
                    yield packet
            except Exception as e:
                log.warning("strap link lost: %s", e)
            first = False
            await self._sleep(self._backoff)

    async def _stream(self, device, name: str) -> AsyncIterator[Packet]:
        queue: asyncio.Queue = asyncio.Queue()
        dropped = asyncio.Event()

        def on_drop(_client) -> None:
            dropped.set()

        async with self._client_factory(device, disconnected_callback=on_drop) as client:
            try:
                raw = await BatteryLevel(client).read()
                self.battery = int(raw[0]) if isinstance(raw, (bytes, bytearray)) else int(raw)
            except Exception as e:
                log.info("battery level not read: %s", e)
            pmd = PolarMeasurementData(client, ecg_queue=queue)
            err, msg, _ = await pmd.start_streaming("ECG")
            if err != 0:
                raise RuntimeError(f"ECG stream did not start: {msg}")
            resumed = False
            self.set_status("streaming", name)
            log.info("streaming from %s, battery %s%%", name, self.battery)
            try:
                while True:
                    _, _t_ns, samples = await self._next(queue, dropped)
                    wall = self._now()
                    if not resumed:
                        if self._last_wall is not None:
                            extra = max(0.0, wall - self._last_wall - PACKET_S)
                            self.index += int(round(extra * FS))
                        resumed = True
                    self._last_wall = wall
                    packet = Packet(self.index / FS, self._oriented(samples))
                    self.index += len(samples)
                    yield packet
            finally:
                if not dropped.is_set():
                    try:
                        await asyncio.wait_for(pmd.stop_streaming("ECG"), timeout=2)
                    except Exception:
                        pass

    async def _next(self, queue: asyncio.Queue, dropped: asyncio.Event):
        get = asyncio.create_task(queue.get())
        drop = asyncio.create_task(dropped.wait())
        try:
            done, _ = await asyncio.wait({get, drop}, timeout=self._silence,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (get, drop):
                if not t.done():
                    t.cancel()
        if get in done:
            return get.result()
        if drop in done:
            raise ConnectionError("strap disconnected")
        raise TimeoutError(f"no ECG for {self._silence:.0f} s")

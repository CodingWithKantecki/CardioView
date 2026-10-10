"""The strap bridge: reads the Polar H10 on this computer and streams it to one or more CardioView
servers' /ws/strap, so the public copy (which has no Bluetooth) shows a real heart. Only one
program can hold the strap, so at the booth the local server runs with --live remote too and the
bridge feeds both it and the public site:

    python tools/bridge.py ws://localhost:8000 wss://cardioview.onrender.com --key <BRIDGE_KEY>
    python tools/bridge.py ws://localhost:8002 --key test --source data/h10_ecg_thomas.csv   # no strap

The key is the servers' BRIDGE_KEY (Render: the service's Environment tab). Each link reconnects
on its own; stop with Ctrl+C. The servers decide what viewers see: the bridge only feeds the strap.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets  # noqa: E402

from backend.sources.base import Source  # noqa: E402

log = logging.getLogger("bridge")


def make_source(spec: str, invert: bool) -> Source:
    if spec == "h10":
        from backend.sources.h10 import H10Source
        return H10Source(invert=invert)
    from backend.sources.replay import ReplaySource

    class LiveReplay(ReplaySource):   # a recording played like the strap, for checks without hardware
        kind = "live"

    src = LiveReplay(spec, invert=invert)
    src.status.device = f"Polar H10 (replay of {Path(spec).stem})"
    return src


def put(queue: asyncio.Queue, msg: dict) -> None:
    if queue.full():
        queue.get_nowait()   # that link is behind: drop its oldest, viewers prefer fresh
    queue.put_nowait(msg)


async def feed(url: str, key: str, queue: asyncio.Queue, source: Source) -> None:
    """One server: connect, send what the queue holds, reconnect for as long as the bridge runs."""
    endpoint = url.rstrip("/") + f"/ws/strap?key={key}"
    while True:
        try:
            async with websockets.connect(endpoint, max_size=None, ping_interval=20) as ws:
                log.info("bridge connected to %s", url)
                await ws.send(json.dumps({"type": "status", "state": source.status.state, "device": source.status.device}))
                while True:
                    msg = await queue.get()
                    await ws.send(json.dumps(msg, separators=(",", ":")))
        except (websockets.exceptions.WebSocketException, OSError) as e:
            log.warning("link to %s lost (%s), retrying in 2 s", url, type(e).__name__)
            await asyncio.sleep(2)


async def run(urls: list[str], key: str, spec: str, invert: bool) -> None:
    source = make_source(spec, invert)
    queues = [asyncio.Queue(maxsize=256) for _ in urls]

    def on_status(st) -> None:
        for q in queues:
            put(q, {"type": "status", "state": st.state, "device": st.device})

    source.on_status(on_status)

    async def read() -> None:
        async for packet in source.packets():
            msg = {"type": "samples", "t": round(packet.t, 4), "uv": list(packet.uv)}
            for q in queues:
                put(q, msg)

    tasks = [asyncio.create_task(read())] + [asyncio.create_task(feed(u, key, q, source)) for u, q in zip(urls, queues)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()


def main() -> None:
    ap = argparse.ArgumentParser(description="Stream the Polar H10 to a CardioView server")
    ap.add_argument("urls", nargs="+", metavar="url", help="the servers, e.g. ws://localhost:8000 wss://cardioview.onrender.com")
    ap.add_argument("--key", required=True, help="the server's BRIDGE_KEY")
    ap.add_argument("--source", default="h10", help="h10 (default) or a CSV to play as if it were the strap")
    ap.add_argument("--invert", action="store_true", help="flip the signal (strap worn upside down)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args.urls, args.key, args.source, args.invert))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

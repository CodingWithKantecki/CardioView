"""Run the CardioView server: python -m backend --source sim | data/<file>.csv | h10"""
from __future__ import annotations

import argparse
import logging

import uvicorn

from .app import create_app
from .sources.base import Source
from .sources.replay import ReplaySource
from .sources.sim import SimSource


def build_source(spec: str, bpm: int, invert: bool) -> Source:
    if spec == "sim":
        return SimSource(bpm=bpm, invert=invert)
    if spec == "h10":
        from .sources.h10 import H10Source
        return H10Source(invert=invert)
    return ReplaySource(spec, invert=invert)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m backend", description="CardioView server")
    ap.add_argument("--source", default="sim", help="sim, h10, or a CSV path with time_s,ecg_uv")
    ap.add_argument("--bpm", type=int, default=72, help="simulated heart rate")
    ap.add_argument("--invert", action="store_true", help="flip the signal (strap worn upside down)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(build_source(args.source, args.bpm, args.invert))
    print(f"CardioView: source {args.source}. Open http://localhost:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", ws="auto", log_level="warning")


if __name__ == "__main__":
    main()

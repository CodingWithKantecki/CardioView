"""Run the CardioView server: python -m backend --source sim | data/<file>.csv | h10"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from .app import create_app
from .cloud import Cloud, load_env
from .env import load_dotenv
from .sources.base import PREROLL_S, Source
from .sources.replay import ReplaySource
from .sources.rhythm import RhythmSource
from .sources.sim import SimSource


DATA = Path(__file__).resolve().parent.parent / "data"


def demo_factory(spec: str | None, bpm: int, invert: bool):
    """The demo source: a CSV path, "sim", or by default the first recording in data/."""
    if spec is None:
        fixtures = sorted(p for p in DATA.glob("h10_ecg_*.csv") if not p.stem.endswith("_raw"))
        spec = str(fixtures[0]) if fixtures else "sim"
    if spec == "sim":
        return lambda: SimSource(bpm=bpm, invert=invert, preroll_s=PREROLL_S)
    return lambda: ReplaySource(spec, invert=invert, preroll_s=PREROLL_S)


def live_factory(invert: bool):
    def make():
        from .sources.h10 import H10Source
        return H10Source(invert=invert)
    return make


def parse_keep_until(value: str | None) -> datetime | None:
    """An ISO time; one without a zone is this machine's local time."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m backend", description="CardioView server")
    ap.add_argument("--source", default="sim", help="what to start with: sim, h10, or a CSV path with time_s,ecg_uv")
    ap.add_argument("--demo", default=None, help="the demo source the viewer can switch to: a CSV path or sim (default: the first recording in data/)")
    ap.add_argument("--bpm", type=int, default=72, help="simulated heart rate")
    ap.add_argument("--invert", action="store_true", help="flip the signal (strap worn upside down)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--keep-until", help="when saved sessions expire, e.g. 2026-10-11T12:00 (default: 24 hours from now)")
    ap.add_argument("--public-host", help="the address phones use for the LAN link (default: this machine's)")
    args = ap.parse_args(argv)
    load_dotenv()   # GEMINI_API_KEY and GEMINI_MODEL for the chat, from .env in the repo root
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env(DATA.parent / ".env")   # the cloud settings live in a local .env, never in git
    cloud = Cloud.from_env()
    def rhythm(pattern: str = "sinus") -> RhythmSource:
        return RhythmSource(pattern, invert=args.invert, preroll_s=PREROLL_S)

    if args.source == "h10":
        factories = {"live": live_factory(args.invert), "demo": demo_factory(args.demo, args.bpm, args.invert), "rhythm": rhythm}
        initial = "live"
    else:
        factories = {"live": live_factory(args.invert), "demo": demo_factory(args.source, args.bpm, args.invert), "rhythm": rhythm}
        initial = "demo"
    app = create_app(factories, initial, keep_until=parse_keep_until(args.keep_until),
                     public_host=args.public_host, port=args.port, cloud=cloud)
    print(f"CardioView: source {args.source}. Open http://localhost:{args.port}", flush=True)
    if cloud is not None:
        print(f"Saved sessions publish to {cloud.public_url}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", ws="auto", log_level="warning")


if __name__ == "__main__":
    main()

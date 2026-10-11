"""Run the CardioView server: python -m backend [--source sim | data/<file>.csv]"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from .app import create_app
from .cloud import Cloud
from .env import load_dotenv
from .pattern import PatternModel
from .sources.base import PREROLL_S, Source
from .sources.replay import ReplaySource
from .sources.rhythm import RhythmSource
from .sources.sim import SimSource


DATA = Path(__file__).resolve().parent.parent / "data"


def demo_factory(spec: str | None, bpm: int, invert: bool):
    """The demo source: a CSV path, "sim", or by default the simulated normal rhythm (Thomas,
    2026-10-10 evening: the public demo must not play his recording)."""
    if spec is None:
        return lambda: RhythmSource("sinus", invert=invert, preroll_s=PREROLL_S)
    if spec == "sim":
        return lambda: SimSource(bpm=bpm, invert=invert, preroll_s=PREROLL_S)
    return lambda: ReplaySource(spec, invert=invert, preroll_s=PREROLL_S)


def parse_keep_until(value: str | None) -> datetime | None:
    """An ISO time; one without a zone is this machine's local time."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m backend", description="CardioView server")
    ap.add_argument("--source", default=None, help="the demo source every viewer starts on: sim, or a CSV path with time_s,ecg_uv such as data/h10_ecg_thomas.csv (default: the simulated normal rhythm)")
    ap.add_argument("--bpm", type=int, default=72, help="simulated heart rate")
    ap.add_argument("--invert", action="store_true", help="flip every strap signal (a strap worn upside down)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--keep-until", help="when saved sessions expire, e.g. 2026-10-11T12:00 (default: 24 hours from now)")
    ap.add_argument("--public-host", help="the address phones use for the LAN link (default: this machine's)")
    ap.add_argument("--no-pattern", action="store_true", help="never load the closest-demo-pattern classifier (it needs tools/requirements-ml.txt)")
    args = ap.parse_args(argv)
    load_dotenv()   # the chat key and the cloud settings, from .env in the repo root, never in git
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cloud = Cloud.from_env()
    def rhythm(pattern: str = "sinus", **kw) -> RhythmSource:   # kw: a Gemini heart's recipe
        return RhythmSource(pattern, invert=args.invert, preroll_s=PREROLL_S, **kw)

    factories = {"demo": demo_factory(args.source, args.bpm, args.invert), "rhythm": rhythm}   # the strap is each viewer's own
    app = create_app(factories, "demo", keep_until=parse_keep_until(args.keep_until), public_host=args.public_host,
                     port=args.port, cloud=cloud, base_url=os.environ.get("CARDIOVIEW_BASE_URL") or None, invert=args.invert,
                     pattern=None if args.no_pattern else PatternModel())
    print(f"CardioView: demo {args.source or 'normal rhythm'}; each viewer connects their own strap. Open http://localhost:{args.port}", flush=True)
    if cloud is not None:
        print(f"Saved sessions publish to {cloud.public_url}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", ws="auto", log_level="warning")


if __name__ == "__main__":
    main()

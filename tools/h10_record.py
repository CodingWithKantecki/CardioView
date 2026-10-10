"""Record ECG from the Polar H10 to a CSV, no server.

    python tools/h10_record.py --seconds 90 --out data/h10_ecg_<name>_raw.csv

Prints the battery level and running sample counts. The first 20 to 30 s
after strapping in are junk; trim them with tools/trim_csv.py afterwards.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.sources.base import FS  # noqa: E402
from backend.sources.h10 import H10Source  # noqa: E402


async def record(seconds: float, out: Path, invert: bool) -> int:
    source = H10Source(invert=invert, max_scans=5)
    source.on_status(lambda s: print(f"[{s.state}] {s.device}".rstrip(), flush=True))
    rows: list[tuple[float, int]] = []
    announced = False
    next_report = 5.0
    print("scanning for the strap (wet pads, worn on the chest)...", flush=True)
    try:
        async for packet in source.packets():
            if not announced:
                print(f"battery {source.battery}%", flush=True)
                announced = True
            for i, v in enumerate(packet.uv):
                rows.append((packet.t + i / FS, v))
            elapsed = len(rows) / FS
            if elapsed >= next_report:
                clipped = sum(1 for _, v in rows[-5 * FS:] if abs(v) > 19000)
                print(f"{elapsed:6.1f} s  {len(rows):6d} samples  last 5 s: "
                      f"{min(v for _, v in rows[-5 * FS:])} to {max(v for _, v in rows[-5 * FS:])} uV"
                      + ("  (clipping, still settling)" if clipped else ""), flush=True)
                next_report += 5.0
            if elapsed >= seconds:
                break
    except KeyboardInterrupt:
        print("stopped early", flush=True)
    if not rows:
        print("nothing recorded", flush=True)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "ecg_uv"])
        for t, v in rows:
            w.writerow([f"{t:.6f}", v])
    print(f"saved {out}: {len(rows)} samples, {len(rows) / FS:.1f} s", flush=True)
    return 0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Record Polar H10 ECG to CSV")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--out", default="data/h10_ecg_raw.csv")
    ap.add_argument("--invert", action="store_true", help="strap worn upside down")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    code = asyncio.run(record(args.seconds, Path(args.out), args.invert))
    raise SystemExit(code)


if __name__ == "__main__":
    main()

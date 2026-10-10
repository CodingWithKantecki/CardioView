"""Trim the settling lead-in from a recording and rebase time to 0.

Usage: python tools/trim_csv.py in.csv out.csv --start 30 [--end 90]
"""
from __future__ import annotations

import argparse
import csv

FS = 130


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Trim a time_s,ecg_uv recording")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--start", type=float, default=30.0, help="seconds to drop from the start")
    ap.add_argument("--end", type=float, default=None, help="keep nothing after this many seconds")
    args = ap.parse_args(argv)

    with open(args.src, newline="") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if float(r["time_s"]) >= args.start
            and (args.end is None or float(r["time_s"]) < args.end)]
    if not kept:
        raise SystemExit("nothing left after trimming")
    with open(args.dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "ecg_uv"])
        for i, r in enumerate(kept):
            w.writerow([f"{i / FS:.6f}", int(round(float(r["ecg_uv"])))])
    print(f"{args.dst}: {len(kept)} samples, {len(kept) / FS:.1f} s")


if __name__ == "__main__":
    main()

"""Replay of a recorded CSV (time_s,ecg_uv at 130 Hz), looped, paced like the strap."""
from __future__ import annotations

import csv
from pathlib import Path

from .base import PacedSource, cycle_forever


def load_csv(path: str | Path) -> list[int]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "ecg_uv" not in reader.fieldnames:
            raise ValueError(f"{path}: expected a header with ecg_uv")
        return [int(round(float(row["ecg_uv"]))) for row in reader]


class ReplaySource(PacedSource):
    kind = "recorded"

    def __init__(self, path: str | Path, invert: bool = False, **kw):
        values = load_csv(path)
        if not values:
            raise ValueError(f"{path}: no samples")
        super().__init__(cycle_forever(values), invert=invert, **kw)
        self.status.device = f"Recording {Path(path).stem}"

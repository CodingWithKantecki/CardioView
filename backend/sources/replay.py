"""Replay of a recorded CSV (time_s,ecg_uv at 130 Hz), looped, paced like the strap."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .base import FS, MIN_FIRST_BEAT_S, PacedSource, Packet, cycle_forever


def load_csv(path: str | Path) -> list[int]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "ecg_uv" not in reader.fieldnames:
            raise ValueError(f"{path}: expected a header with ecg_uv")
        return [int(round(float(row["ecg_uv"]))) for row in reader]


@lru_cache(maxsize=8)
def samples_of(path: str) -> tuple[int, ...]:
    return tuple(load_csv(path))


@lru_cache(maxsize=8)
def peaks_of(path: str) -> tuple[float, ...]:
    """R peak times (seconds into the file), found once by the same detector the server runs."""
    from ..pipeline import BeatDetector   # here, not at the top: pipeline imports this package

    beats = BeatDetector(delineate=False).prime(Packet(0.0, list(samples_of(path))))
    return tuple(b.r for b in beats)


class ReplaySource(PacedSource):
    kind = "recorded"

    def __init__(self, path: str | Path, invert: bool = False, **kw):
        self.path = str(path)
        self._values = list(samples_of(self.path))
        if not self._values:
            raise ValueError(f"{path}: no samples")
        self.start_s = 0.0   # where in the file playback begins
        super().__init__(cycle_forever(self._values), invert=invert, **kw)
        self.status.device = f"Recording {Path(path).stem}"

    def takeover(self, index: int, last_uv: int | None = None, last_r: float | None = None,
                 rr: float | None = None, template=None) -> None:
        """Start the file at a point whose next R peak lands one interval after the old stream's
        last beat, so the rate reads right from the first beat."""
        super().takeover(index, last_uv, last_r, rr, template)
        t0 = index / FS
        want = (last_r + (rr if rr is not None else 0.8)) if last_r is not None else t0 + 0.6
        gap = max(MIN_FIRST_BEAT_S, want - t0)
        for p in peaks_of(self.path):
            if p >= gap + 1.0:            # not the file's first second
                self.start_s = p - gap
                break
        self._samples = cycle_forever(self._values, int(round(self.start_s * FS)))

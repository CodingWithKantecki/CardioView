"""Simulated ECG, generated once with NeuroKit2 and looped."""
from __future__ import annotations

from functools import lru_cache

import neurokit2 as nk
import numpy as np

from .base import FS, PacedSource, cycle_forever


@lru_cache(maxsize=8)
def simulate(bpm: int = 72, seconds: int = 120, seed: int = 42) -> tuple[int, ...]:
    """Integer microvolts at 130 Hz for `seconds` of ECG at about `bpm`."""
    sig = nk.ecg_simulate(duration=seconds, sampling_rate=FS, heart_rate=bpm,
                          heart_rate_std=2, noise=0.02, random_state=seed)
    return tuple(int(v) for v in np.rint(np.asarray(sig, dtype=float) * 1000))


class SimSource(PacedSource):
    kind = "simulated"

    def __init__(self, bpm: int = 72, invert: bool = False, **kw):
        super().__init__(cycle_forever(list(simulate(bpm))), invert=invert, **kw)
        self.status.device = f"Simulated {bpm} bpm"

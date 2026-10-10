"""Simulated rhythms for the demo. A rhythm change takes over the running stream (see `takeover`).

Each beat is a sum of Gaussians (the morphology model ecgsyn uses too), placed at R peak times
chosen per pattern. Values are microvolts with an R peak near 600 uV, like the strap on a chest.
This is a simulation for the screen, named as such; it is never shown for strap data.
"""
from __future__ import annotations

import math
from typing import Iterator

import numpy as np

from .base import FS, MIN_FIRST_BEAT_S, PacedSource

# (center s from the R peak, amplitude mV, width s) for P, Q, R, S, T
NORMAL = [(-0.18, 0.12, 0.022), (-0.03, -0.10, 0.009), (0.0, 1.0, 0.011), (0.025, -0.25, 0.010), (0.25, 0.30, 0.050)]
NO_P = NORMAL[1:]
WIDE = [(-0.01, 1.1, 0.035), (0.06, -0.7, 0.045), (0.30, -0.45, 0.075)]   # wide QRS, inverted T, no P

LABELS = {
    "sinus": "Normal rhythm",
    "tachy": "Tachycardia",
    "brady": "Bradycardia",
    "afib": "Atrial fibrillation",
    "pvc": "Extra beats",
    "vt": "Ventricular tachycardia",
}
UV_PER_MV = 600.0
EASE_BEATS = 3   # beats over which the interval eases from the old rhythm's to this pattern's


class RhythmSource(PacedSource):
    kind = "simulated"

    def __init__(self, pattern: str = "sinus", invert: bool = False, seed: int = 1, **kw):
        self.pattern = pattern if pattern in LABELS else "sinus"
        self._rng = np.random.default_rng(seed)
        self._beats: list[tuple[float, list]] = []   # (R peak time, template)
        self._i = 0
        self._floor = 0.0                 # no beat before this stream time (set by a takeover)
        self._ease: list[float] = []      # weights pulling the next intervals toward the old rr
        self._ease_rr: float | None = None
        super().__init__(self._stream(), invert=invert, **kw)
        self.status.device = f"Simulated: {LABELS[self.pattern]}"

    def takeover(self, index: int, last_uv: int | None = None, last_r: float | None = None,
                 rr: float | None = None, template=None) -> None:
        """Carry on from the old stream's last beat: its template plays out its tail, the next beat
        lands one (eased) interval after it, and the rate glides to this pattern's over EASE_BEATS."""
        super().takeover(index, last_uv, last_r, rr, template)
        t0 = index / FS
        if last_r is not None:
            self._beats = [(last_r, template if template is not None else NORMAL)]
        self._floor = t0 + MIN_FIRST_BEAT_S
        if rr is not None:
            self._ease_rr = rr
            self._ease = [(EASE_BEATS - k) / (EASE_BEATS + 1) for k in range(EASE_BEATS)]   # 0.75, 0.5, 0.25

    def template_at(self, t: float):
        """The template of the latest beat at or before stream time t, for the source that follows."""
        tpl = None
        for r, candidate in self._beats:
            if r <= t:
                tpl = candidate
        return tpl

    def _next(self) -> tuple[float, list]:
        rr, tpl = self._pattern_next()
        if self._ease:
            rr += (self._ease_rr - rr) * self._ease.pop(0)
        return rr, tpl

    def _pattern_next(self) -> tuple[float, list]:
        """The interval to the next beat and its shape, by pattern."""
        rng = self._rng
        i = self._i
        self._i += 1
        p = self.pattern
        if p == "tachy":
            return 0.43 + rng.normal(0, 0.01), NORMAL
        if p == "brady":
            return 1.40 + rng.normal(0, 0.05), NORMAL
        if p == "afib":
            return float(rng.uniform(0.35, 1.05)), NO_P
        if p == "vt":
            return 0.40 + rng.normal(0, 0.008), WIDE
        if p == "pvc":
            k = i % 4
            if k == 3:
                return 0.52, WIDE                     # early, wide
            if k == 0 and i > 0:
                return 1.15, NORMAL                   # the pause after it
            return 0.83 + rng.normal(0, 0.02), NORMAL
        return 0.83 + rng.normal(0, 0.025), NORMAL

    def _schedule(self, until: float) -> None:
        last = self._beats[-1][0] if self._beats else until - 0.6   # a fresh start: the first beat 0.2 s plus an interval in
        while last < until:
            rr, tpl = self._next()
            last = max(last + rr, self._floor)
            self._beats.append((last, tpl))
        if len(self._beats) > 8:
            self._beats = [b for b in self._beats if b[0] > until - 2.0]

    def _stream(self) -> Iterator[int]:
        n = self.index   # after a takeover the stream continues from there
        while True:
            t = n / FS
            self._schedule(t + 0.8)
            v = 0.0
            for r, tpl in self._beats:
                dt = t - r
                if -0.5 < dt < 0.7:
                    for c, a, w in tpl:
                        v += a * math.exp(-((dt - c) ** 2) / (2 * w * w))
            if self.pattern == "afib":   # fibrillatory baseline instead of P waves
                v += 0.045 * math.sin(2 * math.pi * 6.3 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 0.37 * t))
            v += self._rng.normal(0, 0.04)   # a strap-like noise floor, so a quiet stretch is never a flat line
            yield int(round(v * UV_PER_MV))
            n += 1

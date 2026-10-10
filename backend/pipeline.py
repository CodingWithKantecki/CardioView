"""Beat detection and chamber timing on packets of ECG.

The detector keeps the last 8 s, finds R peaks on every packet, and emits each
beat once it is at least 0.25 s old. Every time is stream time (sample index /
130), taken from the packets. A jump in stream time resets the window.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass

import neurokit2 as nk
import numpy as np

from .sources.base import FS, PACKET_S, Packet

WINDOW_S = 8.0        # seconds of signal kept
WARMUP_S = 3.0        # no beats before this much contiguous data
CONFIRM_S = 0.25      # a peak must be this much older than the newest sample
REFRACTORY_S = 0.25   # minimum gap between accepted peaks
EMIT_WINDOW_S = 1.0   # only peaks from the last second are emitted
JUMP_S = 0.5 * PACKET_S

RA_ON = -0.20
LA_ON = -0.17
V_ON = -0.04
ATRIA_S = 0.12        # how long the atria squeeze (used by the viewer)

CLIP_UV = 19000       # the strap pins samples near 19930 uV when the pads lose skin
QUALITY_WINDOW_S = 2.0
FLAT_UV = 40          # peak to peak below this is no contact
NOISE_UV = 6000       # peak to peak above this is motion or a settling contact
NO_BEAT_S = 3.0       # no accepted beat for this long is not a usable signal
LOST_AFTER_S = 0.5    # bad for this long (about two packets) before reporting lost
OK_AFTER_S = 1.5      # clean for this long before reporting ok again, unless a strong pair comes first
SHAPE_PRE_S = 0.10    # QRS window around each R peak compared with the previous beat
SHAPE_POST_S = 0.15
SHAPE_BAD = 0.6       # consecutive beats correlating below this do not look like the same heart
STRONG_PAIR = 0.85    # one pair this alike, after a loss, is a heart again: recover at once
REASON_HOLD_S = 2.0   # while lost, a different reason must persist this long before it replaces the shown one


@dataclass
class Beat:
    r: float
    rr: float | None
    bpm: int | None
    ra_on: float
    la_on: float
    v_on: float
    v_off: float
    p_found: bool

    def message(self, source: str) -> dict:
        d = {"type": "beat", "source": source}
        d.update(asdict(self))
        return d


def v_off_for(rr: float | None) -> float:
    if rr is None:
        return 0.32
    return min(0.42, max(0.20, 0.40 * math.sqrt(rr) - 0.04))


class BeatDetector:
    def __init__(self, fs: int = FS, delineate: bool = True):
        self.fs = fs
        self.delineate = delineate
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float64)
        self._t0 = 0.0            # stream time of _buf[0]
        self._t_end = None        # stream time after the newest sample
        self._peaks: list[float] = []
        self._rr: deque[float] = deque(maxlen=5)
        self._last_v_off: float | None = None
        self._data_s = 0.0        # contiguous seconds seen since the last reset

    def forget_rhythm(self) -> None:
        """Drop the RR history (after a signal loss) so bpm rebuilds from real beats."""
        self._rr.clear()
        self._last_v_off = None

    def feed(self, packet: Packet) -> list[Beat]:
        if self._t_end is None or abs(packet.t - self._t_end) > JUMP_S:
            self.reset()
            self._t0 = packet.t
        uv = np.asarray(packet.uv, dtype=np.float64)
        self._buf = np.concatenate([self._buf, uv])
        self._t_end = packet.t + len(uv) / self.fs
        self._data_s += len(uv) / self.fs
        max_n = int(WINDOW_S * self.fs)
        if len(self._buf) > max_n:
            drop = len(self._buf) - max_n
            self._buf = self._buf[drop:]
            self._t0 += drop / self.fs
        if self._data_s < WARMUP_S:
            return []

        t_newest = self._t_end - 1 / self.fs
        try:
            clean = nk.ecg_clean(self._buf, sampling_rate=self.fs)
            _, info = nk.ecg_peaks(clean, sampling_rate=self.fs)
            idx = np.asarray(info["ECG_R_Peaks"], dtype=int)
        except Exception:
            return []

        emitted: list[tuple[int, Beat]] = []
        for i in idx:
            r = self._t0 + int(i) / self.fs
            if r > t_newest - CONFIRM_S:
                continue
            if self._peaks and r <= self._peaks[-1] + REFRACTORY_S:
                continue
            rr = r - self._peaks[-1] if self._peaks else None
            self._peaks.append(r)
            if len(self._peaks) > 16:
                del self._peaks[:-16]
            if rr is not None:
                self._rr.append(rr)
            beat = self._make_beat(r, rr)
            if r >= t_newest - EMIT_WINDOW_S:
                emitted.append((int(i), beat))

        if emitted and self.delineate and len(idx) >= 4:
            self._refine_p(clean, idx, emitted)
        return [b for _, b in emitted]

    def _make_beat(self, r: float, rr: float | None) -> Beat:
        v_off = v_off_for(rr)
        ra_on = RA_ON
        if rr is not None and self._last_v_off is not None:
            # atria may not start before the previous ventricles are off
            ra_on = min(-0.10, max(RA_ON, self._last_v_off - rr))
        self._last_v_off = v_off
        bpm = int(round(60.0 / float(np.median(self._rr)))) if self._rr else None
        return Beat(r=round(r, 3), rr=round(rr, 3) if rr is not None else None,
                    bpm=bpm, ra_on=round(ra_on, 3), la_on=round(ra_on + 0.03, 3),
                    v_on=V_ON, v_off=round(v_off, 3), p_found=False)

    def _refine_p(self, clean: np.ndarray, idx: np.ndarray,
                  emitted: list[tuple[int, Beat]]) -> None:
        try:
            _, waves = nk.ecg_delineate(clean, idx, sampling_rate=self.fs, method="dwt")
        except Exception:
            return
        onsets = waves.get("ECG_P_Onsets") or []
        by_peak: dict[int, int] = {}
        for ri, p in zip(idx, onsets):
            if p is None or (isinstance(p, float) and math.isnan(p)):
                continue
            by_peak[int(ri)] = int(p)
        for i, beat in emitted:
            p = by_peak.get(i)
            if p is None:
                continue
            lead = (i - p) / self.fs
            if 0.08 <= lead <= 0.32:
                beat.ra_on = round(-lead, 3)
                beat.la_on = round(-lead + 0.03, 3)
                beat.p_found = True


@dataclass
class Signal:
    ok: bool
    reason: str = ""   # "" when ok, else pads, noise or no_beats

    def message(self, source: str) -> dict:
        return {"type": "signal", "source": source, "ok": self.ok, "reason": self.reason}


class SignalMonitor:
    """Says whether the ECG can be trusted right now.

    Looks at the last 2 s of raw samples for clipping, a flat line or huge swings,
    and at the detector's beats for silence. Reports a change after a short hold
    so a single bad packet does not flip the screen.
    """

    def __init__(self, fs: int = FS):
        self.fs = fs
        self.signal = Signal(True)
        self._reset()

    def _reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float64)
        self._t0 = 0.0                      # stream time of _buf[0]
        self._t_end: float | None = None
        self._data_s = 0.0
        self._last_beat: float | None = None
        self._bad_since: float | None = None
        self._good_since: float | None = None
        self._prev_shape: np.ndarray | None = None
        self._shape_corr: deque[float] = deque(maxlen=4)
        self._candidate: tuple[str, float] | None = None   # (reason, since) while lost
        self._lost_at = float("-inf")

    def _window(self, t_from: float, t_to: float) -> np.ndarray | None:
        i0 = int(round((t_from - self._t0) * self.fs))
        i1 = int(round((t_to - self._t0) * self.fs))
        if i0 < 0 or i1 > len(self._buf) or i1 - i0 < 8:
            return None
        return self._buf[i0:i1]

    def _note_shape(self, r: float) -> None:
        """Correlate this beat's QRS window with the previous beat's."""
        w = self._window(r - SHAPE_PRE_S, r + SHAPE_POST_S)
        if w is None:
            return
        w = w - w.mean()
        norm = float(np.linalg.norm(w))
        if norm < 1e-6:
            return
        w = w / norm
        if self._prev_shape is not None and len(self._prev_shape) == len(w):
            self._shape_corr.append(float(np.dot(w, self._prev_shape)))
        self._prev_shape = w

    def _shape_bad(self) -> bool:
        c = list(self._shape_corr)
        return len(c) >= 3 and sum(1 for v in c[-4:] if v < SHAPE_BAD) >= 3

    def _strong_pair(self) -> bool:
        """The newest two beats, both after the loss began, match closely."""
        return (len(self._shape_corr) > 0 and self._shape_corr[-1] >= STRONG_PAIR
                and self._last_beat is not None and self._last_beat > self._lost_at + 0.3)

    def update(self, packet: Packet, beats: list) -> Signal | None:
        """Feed one packet and the beats it produced. Returns a Signal when the state changes."""
        if self._t_end is not None and abs(packet.t - self._t_end) > JUMP_S:
            self._reset()
        uv = np.asarray(packet.uv, dtype=np.float64)
        if self._t_end is None:
            self._t0 = packet.t
        self._buf = np.concatenate([self._buf, uv])
        keep = int(6.0 * self.fs)
        if len(self._buf) > keep:
            drop = len(self._buf) - keep
            self._buf = self._buf[drop:]
            self._t0 += drop / self.fs
        self._t_end = packet.t_end
        self._data_s += len(uv) / self.fs
        for b in beats:
            self._last_beat = b.r
            self._note_shape(b.r)
        now = packet.t_last

        recent = self._buf[-int(QUALITY_WINDOW_S * self.fs):]
        clipped = float(np.mean(np.abs(recent) >= CLIP_UV))
        p2p = float(recent.max() - recent.min())
        if clipped > 0.05 or p2p < FLAT_UV:
            reason = "pads"
        elif p2p > NOISE_UV:
            reason = "noise"
        elif (self._last_beat is None and self._data_s > NO_BEAT_S + WARMUP_S) or \
             (self._last_beat is not None and now - self._last_beat > NO_BEAT_S):
            reason = "no_beats"
        elif self._shape_bad() and not (not self.signal.ok and self._strong_pair()):
            reason = "no_beats"
        else:
            reason = ""

        changed = None
        if reason:
            self._good_since = None
            if self._bad_since is None:
                self._bad_since = now
            if self.signal.ok and now - self._bad_since >= LOST_AFTER_S:
                self.signal = Signal(False, reason)
                self._candidate = None
                self._lost_at = now
                changed = self.signal
            elif not self.signal.ok and self.signal.reason != reason:
                if self._candidate is None or self._candidate[0] != reason:
                    self._candidate = (reason, now)
                elif now - self._candidate[1] >= REASON_HOLD_S:
                    self.signal = Signal(False, reason)
                    self._candidate = None
                    changed = self.signal
            else:
                self._candidate = None
        else:
            self._bad_since = None
            if self._good_since is None:
                self._good_since = now
            if not self.signal.ok and (self._strong_pair() or now - self._good_since >= OK_AFTER_S):
                self.signal = Signal(True)
                self._shape_corr.clear()   # a new loss needs fresh evidence, not the old garbage pairs
                changed = self.signal
        return changed

"""Every recording in data/ must replay through the detector without gaps over 2 s."""
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline import BeatDetector
from backend.sources.base import FS, PACKET, Packet
from backend.sources.replay import load_csv

DATA = Path(__file__).resolve().parents[2] / "data"
FIXTURES = sorted(DATA.glob("h10_ecg_*.csv"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.name for p in FIXTURES])
def test_recording_replays_without_gaps(path):
    values = load_csv(path)
    assert len(values) >= 30 * FS, "recording shorter than 30 s"
    assert max(abs(v) for v in values) < 19000, "clipped samples: trim the settling lead-in"
    det = BeatDetector()
    beats = []
    for k in range(0, len(values) - PACKET + 1, PACKET):
        beats += det.feed(Packet(k / FS, values[k:k + PACKET]))
    assert beats, "no beats found"
    rs = np.array([b.r for b in beats])
    gaps = np.diff(rs)
    assert gaps.max() <= 2.0, f"gap of {gaps.max():.2f} s between beats"
    assert beats[0].r <= 5.0
    assert rs[-1] >= len(values) / FS - 3.0
    bpms = [b.bpm for b in beats if b.bpm]
    assert 40 <= np.median(bpms) <= 200


def test_fixture_header_is_time_s_ecg_uv():
    for path in FIXTURES:
        assert path.read_text().splitlines()[0] == "time_s,ecg_uv"

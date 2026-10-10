"""Session analysis against synthetic sessions with known answers, and on bad input."""
import json
from pathlib import Path

import numpy as np
import pytest

from backend import analysis as A
from backend.sources.replay import load_csv
from backend.synth import synth_session

DATA = Path(__file__).resolve().parents[2] / "data"
SECTIONS = ("effort", "breathing", "hrv", "beat", "timing")


def truth(ses):
    """Beats at the true R peaks, all usable: what perfect detection would give."""
    r = ses.r_times
    rr = np.r_[np.nan, np.diff(r)]
    n = len(r)
    return A.Beats(r=r, rr=rr, usable=~np.isnan(rr), fixed=np.zeros(n, bool),
                   piece=np.zeros(n, int), idx=np.zeros(n, int))


@pytest.fixture(scope="module", params=[1, 2, 3], ids=lambda s: f"seed{s}")
def case(request):
    ses = synth_session(seed=request.param, t0=12.0)
    return ses, A.analyze(ses.t, ses.uv, ses.steps), truth(ses)


def test_every_true_beat_is_found_once(case):
    ses, _, _ = case
    beats, _ = A.find_beats(ses.t, ses.uv)
    assert len(beats.r) == len(ses.r_times)
    off = np.abs(beats.r - ses.r_times) * 130   # in samples
    assert np.median(off) <= 1.0 and off.max() <= 3.0


def test_effort_matches_the_design(case):
    ses, s, tb = case
    got, want = s["effort"], A.effort(tb, ses.steps)
    assert got["ok"] and want["ok"]
    assert abs(got["rest_bpm"] - want["rest_bpm"]) <= 2
    assert abs(got["peak_bpm"] - want["peak_bpm"]) <= 3
    assert abs(got["drop_bpm"] - want["drop_bpm"]) <= 4
    assert 125 <= got["peak_bpm"] <= 145 and got["drop_bpm"] > 20


def test_variability_matches_the_design(case):
    ses, s, tb = case
    got, want = s["hrv"], A.hrv(tb, ses.steps)
    assert got["ok"] and got["window_s"] == 30
    assert abs(got["rmssd_ms"] - want["rmssd_ms"]) <= 0.15 * want["rmssd_ms"]
    assert abs(got["sdnn_ms"] - want["sdnn_ms"]) <= 0.15 * want["sdnn_ms"]


def test_breathing_matches_the_design(case):
    ses, s, tb = case
    got = s["breathing"]
    assert got["ok"]
    assert abs(got["rest_per_min"] - 15) <= 1.5
    assert abs(got["paced_per_min"] - 6) <= 1.5
    assert abs(got["swing_bpm"] - A.breathing(tb, ses.steps)["swing_bpm"]) <= 3
    assert got["breaths"] == 4


def test_average_beat_labels_p_qrs_t_in_order(case):
    _, s, _ = case
    b = s["beat"]
    assert b["ok"] and b["n"] >= 30 and b["fs"] == 130
    assert 90 <= len(b["uv"]) <= 100 and b["t0"] < 0
    w = b["waves"]
    assert -0.30 <= w["p"] <= -0.05 and w["qrs"] == 0.0 and 0.15 <= w["t"] <= 0.45


def test_timing_has_points_for_rest_and_breathe(case):
    _, s, _ = case
    assert s["timing"]["ok"]
    assert len(s["timing"]["rest"]) >= 20 and len(s["timing"]["breathe"]) >= 30


def test_summary_is_strict_json_with_steps_from_zero(case):
    _, s, _ = case
    json.dumps(s, allow_nan=False)
    assert s["steps"][0] == {"name": "get_ready", "start": 0.0, "end": 5.0}
    assert len(s["hr_chart"]["bpm"]) == 125


def _session():
    return synth_session(seed=1, t0=12.0)


def _all_refused(s):
    for name in SECTIONS:
        assert s[name]["ok"] is False, name
        assert s[name]["reason"], name
    json.dumps(s, allow_nan=False)


def test_noise_only_measures_nothing():
    ses = _session()
    noise = np.round(np.random.default_rng(0).normal(0, 300, len(ses.uv))).astype(int)
    _all_refused(A.analyze(ses.t, noise, ses.steps))


def test_flat_line_measures_nothing():
    ses = _session()
    _all_refused(A.analyze(ses.t, np.zeros(len(ses.uv), int), ses.steps))


def test_empty_recording_measures_nothing():
    ses = _session()
    _all_refused(A.analyze(np.zeros(0), np.zeros(0, int), ses.steps))


def test_clipping_during_rest_blocks_rest_measures_only():
    ses = _session()
    uv = ses.uv.copy()
    rest = ses.steps[1]
    m = (ses.t >= rest["start"] + 2) & (ses.t < rest["end"] - 2) & (np.arange(len(uv)) % 40 < 6)
    uv[m] = 19930
    s = A.analyze(ses.t, uv, ses.steps)
    assert not s["effort"]["ok"] and not s["hrv"]["ok"]
    assert s["beat"]["ok"] and s["breathing"]["swing_bpm"] > 0


def test_session_that_ended_after_rest():
    ses = _session()
    steps = ses.steps[:2]
    cut = ses.t < steps[-1]["end"]
    s = A.analyze(ses.t[cut], ses.uv[cut], steps)
    assert "ended before squats" in s["effort"]["reason"]
    assert s["hrv"]["ok"] and s["beat"]["ok"] and s["breathing"]["rest_per_min"] == 15


def test_short_recovery_refuses_the_drop():
    ses = _session()
    steps = [dict(x) for x in ses.steps]
    steps[-1]["end"] = steps[-1]["start"] + 20
    cut = ses.t < steps[-1]["end"]
    s = A.analyze(ses.t[cut], ses.uv[cut], steps)
    assert "full 30 seconds" in s["effort"]["reason"]


def test_strap_gap_splits_the_recording_but_not_the_analysis():
    ses = _session()
    br = ses.steps[2]
    keep = ~((ses.t >= br["start"] + 15) & (ses.t < br["start"] + 23))
    s = A.analyze(ses.t[keep], ses.uv[keep], ses.steps)
    assert s["effort"]["ok"] and s["hrv"]["ok"] and s["beat"]["ok"]


def test_thomas_recording_as_rest_and_breathe():
    uv = np.array(load_csv(DATA / "h10_ecg_thomas.csv"))
    t = np.arange(len(uv)) / 130
    steps = [{"name": "get_ready", "start": 0.0, "end": 5.0}, {"name": "rest", "start": 5.0, "end": 35.0},
             {"name": "breathe", "start": 35.0, "end": 75.0}]
    s = A.analyze(t, uv, steps)
    assert s["hrv"]["ok"] and 10 <= s["hrv"]["rmssd_ms"] <= 120
    assert s["beat"]["ok"] and s["beat"]["waves"]["p"] < 0 < s["beat"]["waves"]["t"]
    json.dumps(s, allow_nan=False)


def test_breaths_per_min_reads_a_clean_rhythm():
    t = np.arange(0, 30, 0.25)
    assert abs(A.breaths_per_min(70 + 3 * np.sin(2 * np.pi * 0.25 * t), 0.1, 0.5) - 15) <= 0.5


def test_breaths_per_min_refuses_slow_drift():
    t = np.arange(0, 30, 0.25)
    assert A.breaths_per_min(70 + 0.2 * t, 0.1, 0.5) is None


def test_hr_series_blanks_stretches_without_beats():
    r = np.array([0.0, 1.0, 2.0, 6.0, 7.0])
    rr = np.r_[np.nan, np.diff(r)]
    rr[3] = 1.0   # pretend the RR is plausible so the beat stays usable
    b = A.Beats(r=r, rr=rr, usable=~np.isnan(rr), fixed=np.zeros(5, bool), piece=np.zeros(5, int), idx=np.zeros(5, int))
    grid, hr = A.hr_series(b, 0.0, 7.0, fs=1.0)
    assert np.isnan(hr[3]) and np.isnan(hr[4]) and not np.isnan(hr[1])

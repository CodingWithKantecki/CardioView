"""The session manager: steps by samples, pauses, consent, cancel, the store on disk."""
import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.analysis import analyze
from backend.session import SessionError, SessionManager, SessionStore
from backend.sources.base import PACKET, PACKET_S, Packet
from backend.synth import synth_session

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


@dataclass
class FakeBeat:
    r: float
    rr: float | None
    bpm: int | None


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def packets_and_beats(ses, t_shift=0.0):
    """The synthetic session as strap packets, each with the true beats confirmed about 1 s late."""
    out = []
    r = ses.r_times
    done = 0
    for k in range(0, len(ses.uv) - PACKET + 1, PACKET):
        p = Packet(float(ses.t[k]) + t_shift, [int(v) for v in ses.uv[k:k + PACKET]])
        beats = []
        while done < len(r) and r[done] + 1.0 <= p.t_end - t_shift:
            rr = float(r[done] - r[done - 1]) if done else None
            beats.append(FakeBeat(float(r[done]) + t_shift, rr, round(60 / rr) if rr else None))
            done += 1
        out.append((p, beats))
    return out


def make(tmp_path, **kw):
    clock = Clock()
    sent = []
    m = SessionManager(SessionStore(tmp_path / "sessions"), analyze=kw.pop("analyze", analyze),
                       broadcast=sent.append, link=lambda sid: f"http://booth/s/{sid}",
                       keep_until=T0 + timedelta(days=1), now=clock, wall=lambda: T0, **kw)
    return m, clock, sent


def feed(m, clock, items):
    for p, beats in items:
        clock.t += PACKET_S
        m.on_packet(p, beats)


def test_start_needs_a_recent_signal(tmp_path):
    m, clock, _ = make(tmp_path)
    with pytest.raises(SessionError, match="No signal"):
        m.start()
    feed(m, clock, packets_and_beats(synth_session(seed=1, tail_s=10))[:2])
    clock.t += 3.0
    with pytest.raises(SessionError, match="No signal"):
        m.start()


def test_one_session_at_a_time_and_consent_is_written(tmp_path):
    m, clock, _ = make(tmp_path)
    feed(m, clock, packets_and_beats(synth_session(seed=1, tail_s=10))[:2])
    sid = m.start()
    with pytest.raises(SessionError, match="already running"):
        m.start()
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    assert meta["state"] == "recording" and meta["consent"]["how"] == "pressed S twice"
    assert meta["keep_until"] == (T0 + timedelta(days=1)).isoformat()


def test_a_full_session_runs_every_step_and_saves_a_summary(tmp_path):
    ses = synth_session(seed=1, tail_s=10)
    items = packets_and_beats(ses)

    async def run():
        m, clock, sent = make(tmp_path)
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        return m, sid, sent

    m, sid, sent = asyncio.run(run())
    order = []
    for msg in sent:
        if msg["state"] == "running" and (not order or order[-1] != msg["step"]):
            order.append(msg["step"])
    assert order == ["get_ready", "rest", "breathe", "squats", "recover"]
    assert m.state == "done" and m.message() == {"type": "session", "state": "done", "id": sid,
                                                 "link": f"http://booth/s/{sid}", "online": False}
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    seconds = {s["name"]: s["seconds"] for s in meta["steps"]}
    assert 5.0 <= seconds["get_ready"] <= 6.5
    assert all(seconds[n] == pytest.approx(want, abs=PACKET_S) for n, want in
               (("rest", 30), ("breathe", 40), ("squats", 20), ("recover", 30)))
    summary = m.store.summary(sid, T0)
    assert summary["effort"]["ok"] and summary["hrv"]["ok"] and summary["id"] == sid
    t, uv = m.store.read_recording(sid)
    assert len(t) == len(uv) and uv.dtype.kind == "i"


def test_steps_count_samples_so_a_strap_gap_pauses_them(tmp_path):
    ses = synth_session(seed=2, tail_s=10)
    items = packets_and_beats(ses)
    m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
    feed(m, clock, items[:2])
    m.start()
    feed(m, clock, items[2:30])                       # get ready and part of rest
    rest_before = m.steps[1].elapsed_s
    later = packets_and_beats(ses, t_shift=20.0)      # strap back: stream time jumped 20 s
    feed(m, clock, later[30:40])
    assert m.steps[1].name == "rest" and m.steps[1].elapsed_s == pytest.approx(rest_before + 10 * PACKET_S)
    assert m.state == "running" and m.steps[1].done is False


def test_a_long_drop_pauses_then_ends_with_the_finished_steps(tmp_path):
    ses = synth_session(seed=3, tail_s=10)
    items = packets_and_beats(ses)

    async def run():
        m, clock, sent = make(tmp_path)
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:80])                   # through rest, into breathe
        clock.t += 2.0
        m.tick()
        paused = sent[-1]["paused"]
        clock.t += 14.0
        m.tick()
        await m.finishing
        return m, sid, paused

    m, sid, paused = asyncio.run(run())
    assert paused is True
    meta = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    assert meta["ended_early"] is True
    assert [s["name"] for s in meta["steps"]] == ["get_ready", "rest"]
    summary = m.store.summary(sid, T0)
    assert summary["hrv"]["ok"] and summary["effort"]["ok"] is False


def test_cancel_deletes_the_folder_and_says_stopped(tmp_path):
    removed = []

    async def unpublish(sid):
        removed.append(sid)

    async def run():
        m, clock, sent = make(tmp_path, unpublish=unpublish)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:20])
        await m.cancel()
        return m, sid, sent

    m, sid, sent = asyncio.run(run())
    assert not (tmp_path / "sessions" / sid).exists()
    assert sent[-1] == {"type": "session", "state": "idle", "note": "stopped"} and removed == [sid]


def test_cancel_during_analysis_drops_the_result(tmp_path):
    async def run():
        m, clock, _ = make(tmp_path)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        assert m.state == "analyzing"
        await m.cancel()
        await m.finishing
        return m, sid

    m, sid = asyncio.run(run())
    assert m.state == "idle" and not (tmp_path / "sessions" / sid).exists()


def test_a_cancel_while_the_recording_is_read_still_stops_and_cleans_up(tmp_path):
    """On Windows an open file cannot be deleted: a cancel during the read must still stop the session."""
    reading, release = threading.Event(), threading.Event()
    measured = []

    class LockedWhileRead(SessionStore):
        def read_recording(self, sid):
            reading.set()
            release.wait(10)
            try:
                return super().read_recording(sid)
            finally:
                reading.clear()

        def delete(self, sid):
            if reading.is_set():
                raise PermissionError("the recording is open")   # what Windows says
            return super().delete(sid)

    async def run():
        m, clock, sent = make(tmp_path, analyze=lambda *a: measured.append(a) or {})
        m.store = LockedWhileRead(tmp_path / "sessions")
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        try:
            feed(m, clock, items[2:])
            assert await asyncio.to_thread(reading.wait, 5), "the analysis reads the recording"
            await m.cancel()
            stopped, kept = sent[-1], (tmp_path / "sessions" / sid).exists()
        finally:
            release.set()
        await m.finishing
        return m, sid, stopped, kept

    m, sid, stopped, kept = asyncio.run(run())
    assert stopped == {"type": "session", "state": "idle", "note": "stopped"}, "every screen hears the cancel"
    assert kept, "the open recording could not go yet"
    assert m.state == "idle" and not (tmp_path / "sessions" / sid).exists(), "it goes once the read is done"
    assert not measured, "a cancelled session is not measured"


def test_a_public_link_wins_and_a_failed_publish_falls_back(tmp_path):
    async def good(sid, summary, keep_until):
        return f"https://cloud/s/{sid}"

    async def bad(sid, summary, keep_until):
        raise ConnectionError("offline")

    async def run(publish, where):
        m, clock, _ = make(where, analyze=lambda t, uv, steps: {"version": 1}, publish=publish)
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        return m.message(), sid

    msg, sid = asyncio.run(run(good, tmp_path / "a"))
    assert msg["link"] == f"https://cloud/s/{sid}" and msg["online"] is True
    msg, sid = asyncio.run(run(bad, tmp_path / "b"))
    assert msg["link"] == f"http://booth/s/{sid}" and msg["online"] is False


def test_update_link_and_dismiss(tmp_path):
    async def run():
        m, clock, sent = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        sid = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        m.update_link(sid, "https://cloud/s/x")
        linked = sent[-1]
        m.dismiss()
        return linked, sent[-1]

    linked, last = asyncio.run(run())
    assert linked["link"] == "https://cloud/s/x" and linked["online"] is True
    assert last == {"type": "session", "state": "idle"}


def test_a_failed_write_stops_the_session(tmp_path, monkeypatch):
    m, clock, sent = make(tmp_path)
    items = packets_and_beats(synth_session(seed=1, tail_s=10))
    feed(m, clock, items[:2])
    sid = m.start()

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(m.store, "append", boom)
    feed(m, clock, items[2:3])
    assert m.state == "idle" and sent[-1]["note"] == "write_failed"
    assert not (tmp_path / "sessions" / sid).exists()


def test_store_refuses_ids_that_are_not_ours(tmp_path):
    store = SessionStore(tmp_path)
    for bad in ("../x", "..", "a/b", "", "x" * 21, "x" * 23, "abc def" + "x" * 15):
        assert not store.valid_id(bad)
        assert store.summary(bad, T0) is None and store.delete(bad) is False
        with pytest.raises(ValueError):
            store.path(bad)
    assert store.valid_id(store.new_id())


def test_clean_up_removes_unfinished_and_expired(tmp_path):
    store = SessionStore(tmp_path)
    keep = store.new_id()
    for sid, state, until in ((store.new_id(), "recording", T0 + timedelta(days=1)),
                              (store.new_id(), "done", T0 - timedelta(seconds=1)),
                              (keep, "done", T0 + timedelta(days=1))):
        store.create(sid, {"id": sid, "state": state, "keep_until": until.isoformat()})
        store.write_summary(sid, {"version": 1})
    assert store.clean_up(T0) == 2 and store.ids() == [keep]
    assert store.summary(keep, T0) == {"version": 1}
    assert store.summary(keep, T0 + timedelta(days=2)) is None


def test_get_ready_gives_up_waiting_after_30_s(tmp_path):
    """A strap still settling must not hang the session: get ready ends at 30 s and rest begins."""
    m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
    flat = [(Packet(k * PACKET_S, [0] * PACKET), []) for k in range(80)]   # no beats: never clean
    feed(m, clock, flat[:2])
    m.start()
    feed(m, clock, flat[2:])
    assert m.steps[0].done and m.steps[0].elapsed_s == pytest.approx(30, abs=PACKET_S)
    assert m.i == 1 and m.state == "running"


def test_a_new_session_can_start_while_a_summary_shows(tmp_path):
    async def run():
        m, clock, _ = make(tmp_path, analyze=lambda t, uv, steps: {"version": 1})
        items = packets_and_beats(synth_session(seed=1, tail_s=10))
        feed(m, clock, items[:2])
        first = m.start()
        feed(m, clock, items[2:])
        await m.finishing
        assert m.state == "done"
        return m, first, m.start()

    m, first, second = asyncio.run(run())
    assert second != first and m.state == "running"
    assert m.store.summary(first, T0)["id"] == first

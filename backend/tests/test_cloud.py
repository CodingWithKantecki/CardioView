"""Neon sync with a fake database: publish, retries, phone deletes, expiry, off without settings."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.cloud import Cloud, load_env
from backend.session import SessionManager, SessionStore

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self, fail=False):
        self.rows: dict[str, dict] = {}
        self.fail = fail
        self.expired_sweeps = 0

    def _check(self):
        if self.fail:
            raise ConnectionError("no route to Neon")

    def upsert(self, sid, keep_until, summary_json):
        self._check()
        row = self.rows.get(sid)
        if row and row["deleted_at"]:
            return
        self.rows[sid] = {"keep_until": keep_until, "summary": json.loads(summary_json), "deleted_at": None}

    def tombstones(self):
        self._check()
        return [sid for sid, r in self.rows.items() if r["deleted_at"]]

    def remove(self, sid):
        self._check()
        self.rows.pop(sid, None)

    def remove_expired(self):
        self._check()
        self.expired_sweeps += 1
        return 0

    def remove_all(self):
        n = len(self.rows)
        self.rows.clear()
        return n


def finished_session(store, published=False):
    sid = store.new_id()
    store.create(sid, {"id": sid, "state": "done", "keep_until": (T0 + timedelta(days=1)).isoformat(),
                       "published": published})
    store.write_summary(sid, {"version": 1, "id": sid})
    return sid


def manager_for(tmp_path, cloud):
    return SessionManager(SessionStore(tmp_path), analyze=lambda *a: {}, publish=cloud.publish,
                          unpublish=cloud.unpublish, keep_until=T0 + timedelta(days=1), wall=lambda: T0)


def test_publish_returns_the_public_link_and_stores_the_summary():
    db = FakeDb()
    cloud = Cloud(db, "https://cardioview.example/")
    link = asyncio.run(cloud.publish("x" * 22, {"version": 1}, T0))
    assert link == "https://cardioview.example/s/" + "x" * 22
    assert db.rows["x" * 22]["summary"] == {"version": 1}


def test_publish_refuses_nan():
    cloud = Cloud(FakeDb(), "https://c")
    with pytest.raises(ValueError):
        asyncio.run(cloud.publish("x" * 22, {"v": float("nan")}, T0))


def test_sync_publishes_what_was_missed_and_updates_the_screen(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    db = FakeDb()
    cloud = Cloud(db, "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store)
    m.state, m.sid, m.done_link = "done", sid, f"http://booth/s/{sid}"
    asyncio.run(cloud.sync_once(m))
    assert sid in db.rows and m.store.read_meta(sid)["published"] is True
    assert m.message()["link"] == f"https://c/s/{sid}" and m.message()["online"] is True
    assert db.expired_sweeps == 1


def test_sync_applies_deletes_made_on_phones(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    db = FakeDb()
    cloud = Cloud(db, "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store, published=True)
    db.rows[sid] = {"keep_until": T0, "summary": None, "deleted_at": T0}
    asyncio.run(cloud.sync_once(m))
    assert not (tmp_path / sid).exists() and sid not in db.rows


def test_sync_failure_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.cloud.utcnow", lambda: T0)
    cloud = Cloud(FakeDb(fail=True), "https://c")
    m = manager_for(tmp_path, cloud)
    sid = finished_session(m.store)
    with pytest.raises(ConnectionError):
        asyncio.run(cloud.sync_once(m))
    assert m.store.read_meta(sid)["published"] is False


def test_off_without_both_settings(monkeypatch):
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("CARDIOVIEW_PUBLIC_URL", raising=False)
    assert Cloud.from_env() is None
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://u:p@h/db")
    assert Cloud.from_env() is None
    monkeypatch.setenv("CARDIOVIEW_PUBLIC_URL", "https://c")
    assert Cloud.from_env() is not None


def test_load_env_reads_pairs_and_keeps_what_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEP_ME", "outer")
    monkeypatch.delenv("NEW_ONE", raising=False)
    p = tmp_path / ".env"
    p.write_text("# comment\nNEW_ONE='postgresql://a:b@c/d?sslmode=require'\nKEEP_ME=inner\n\nJUNK\n")
    load_env(p)
    import os
    assert os.environ["NEW_ONE"] == "postgresql://a:b@c/d?sslmode=require"
    assert os.environ["KEEP_ME"] == "outer"

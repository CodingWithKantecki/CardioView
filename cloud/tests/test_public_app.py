"""The public summary function with a fake database: reads, deletes, expiry, bad ids."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from cloud.app import create_app

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
SID = "A" * 22


class FakePublicDb:
    def __init__(self):
        self.rows = {SID: [{"version": 1, "id": SID}, T0 + timedelta(days=1), None],
                     "B" * 22: [{"version": 1}, T0 - timedelta(seconds=1), None]}

    def get(self, sid):
        row = self.rows.get(sid)
        return tuple(row) if row else None

    def mark_deleted(self, sid):
        row = self.rows.get(sid)
        if not row or row[2] is not None or row[1] <= T0:
            return 0
        row[0], row[2] = None, T0
        return 1


def client():
    db = FakePublicDb()
    return TestClient(create_app(db=db, now=lambda: T0)), db


def test_reads_a_live_summary_without_caching():
    c, _ = client()
    r = c.get(f"/api/s/{SID}")
    assert r.status_code == 200 and r.json() == {"version": 1, "id": SID}
    assert r.headers["cache-control"] == "no-store"


def test_expired_unknown_and_bad_ids_are_gone():
    c, _ = client()
    for sid in ("B" * 22, "C" * 22, "short"):
        r = c.get(f"/api/s/{sid}")
        assert r.status_code == 404 and r.json() == {"reason": "This session is no longer available."}
    assert c.get("/api/s/..%2F..%2Fx").status_code == 404   # slashes: never reaches the route


def test_delete_leaves_a_tombstone_for_the_booth_and_then_reads_gone():
    c, db = client()
    assert c.delete(f"/api/s/{SID}").json() == {"ok": True}
    assert db.rows[SID][0] is None and db.rows[SID][2] == T0
    assert c.get(f"/api/s/{SID}").status_code == 404
    assert c.delete(f"/api/s/{SID}").status_code == 404
    assert c.delete(f"/api/s/{'B' * 22}").status_code == 404

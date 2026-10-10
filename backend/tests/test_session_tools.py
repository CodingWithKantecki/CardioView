"""tools/sessions.py: list, delete, wipe, role connection strings, deploy."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.session import SessionStore

TOOL = Path(__file__).resolve().parents[2] / "tools" / "sessions.py"
_spec = importlib.util.spec_from_file_location("session_tools", TOOL)
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)

T0 = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self):
        self.removed = []
        self.wiped = False

    def remove(self, sid):
        self.removed.append(sid)

    def remove_all(self):
        self.wiped = True
        return 2


def saved(store, n):
    ids = []
    for _ in range(n):
        sid = store.new_id()
        store.create(sid, {"id": sid, "state": "done", "created": T0.isoformat(),
                           "keep_until": (T0 + timedelta(days=1)).isoformat(), "published": True})
        ids.append(sid)
    return ids


def test_list_shows_each_session(tmp_path):
    store = SessionStore(tmp_path)
    ids = saved(store, 2)
    rows = tools.list_sessions(store)
    assert len(rows) == 2 and all(any(sid in r for r in rows) for sid in ids)
    assert "published" in rows[0] and "2026-10-10T14:00" in rows[0]


def test_delete_removes_the_local_copy_and_the_cloud_row(tmp_path):
    store, db = SessionStore(tmp_path), FakeDb()
    sid = saved(store, 1)[0]
    assert tools.delete(store, db, sid) is True
    assert store.ids() == [] and db.removed == [sid]


def test_wipe_clears_everything(tmp_path):
    store, db = SessionStore(tmp_path), FakeDb()
    saved(store, 3)
    assert tools.wipe(store, db) == (3, 2) and store.ids() == [] and db.wiped


def test_dsn_for_swaps_the_role_and_keeps_host_database_and_options():
    owner = ("postgresql://neondb_owner:abc@ep-cool-name-123-pooler.us-east-2.aws.neon.tech/neondb"
             "?sslmode=require&channel_binding=require")
    assert tools.dsn_for(owner, "cardioview_public", "p/w:@x") == (
        "postgresql://cardioview_public:p%2Fw%3A%40x@ep-cool-name-123-pooler.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require")


def test_deploy_copies_the_page_and_fonts_then_deploys_to_production(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "vendor" / "fonts").mkdir(parents=True)
    for name in tools.PAGE:
        (fe / name).write_text(name)
    for name in tools.FONTS:
        (fe / "vendor" / "fonts" / name).write_text(name)
    cloud = tmp_path / "cloud"
    (cloud / "static").mkdir(parents=True)
    (cloud / "static" / "stale.txt").write_text("old")
    calls = []
    tools.deploy(fe, cloud, run=lambda cmd, **kw: calls.append((cmd, kw)), which=lambda name: "/bin/vercel")
    assert (cloud / "static" / "summary.js").read_text() == "summary.js"
    assert (cloud / "static" / "vendor" / "fonts" / "LICENSE-jetbrains-mono").exists()
    assert not (cloud / "static" / "stale.txt").exists()
    assert calls == [(["/bin/vercel", "deploy", "--prod", "--yes"], {"cwd": cloud, "check": True})]


def test_deploy_without_the_cli_says_how_to_get_it(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "vendor" / "fonts").mkdir(parents=True)
    for name in tools.PAGE:
        (fe / name).write_text(name)
    for name in tools.FONTS:
        (fe / "vendor" / "fonts" / name).write_text(name)
    with pytest.raises(SystemExit, match="npm i -g vercel"):
        tools.deploy(fe, tmp_path / "cloud", run=lambda *a, **k: None, which=lambda name: None)

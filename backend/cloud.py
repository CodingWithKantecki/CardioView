"""Neon sync: anonymous summaries go up so the QR link works on any network.

Off unless NEON_DATABASE_URL and CARDIOVIEW_PUBLIC_URL are set. It never blocks
the booth: every call has a timeout, and a failure only means the QR keeps the
LAN link until a retry gets through. The raw ECG never leaves the laptop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .session import utcnow

log = logging.getLogger("cardioview.cloud")

TIMEOUT_S = 4.0
SYNC_EVERY_S = 30.0

SCHEMA = """
create table if not exists session_summary (
  id text primary key,
  created_at timestamptz not null default now(),
  keep_until timestamptz not null,
  summary jsonb,
  deleted_at timestamptz
);
"""


def load_env(path: Path) -> None:
    """KEY=value lines from a local .env into the environment, without overriding what is set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class NeonDb:
    """The statements the booth needs, each on its own short connection."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _run(self, sql: str, params: tuple = (), fetch: bool = False):
        import psycopg   # imported here so a booth without the cloud never loads it
        with psycopg.connect(self.dsn, connect_timeout=int(TIMEOUT_S)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if fetch else cur.rowcount

    def upsert(self, sid: str, keep_until: datetime, summary_json: str) -> None:
        self._run(
            "insert into session_summary (id, keep_until, summary) values (%s, %s, %s::jsonb) "
            "on conflict (id) do update set keep_until = excluded.keep_until, summary = excluded.summary "
            "where session_summary.deleted_at is null",
            (sid, keep_until, summary_json))

    def tombstones(self) -> list[str]:
        return [r[0] for r in self._run("select id from session_summary where deleted_at is not null", fetch=True)]

    def remove(self, sid: str) -> None:
        self._run("delete from session_summary where id = %s", (sid,))

    def remove_expired(self) -> int:
        return self._run("delete from session_summary where keep_until <= now()")

    def remove_all(self) -> int:
        return self._run("delete from session_summary")


class Cloud:
    """What the session manager and the server need from Neon: publish, unpublish and a sync loop."""

    def __init__(self, db, public_url: str, every_s: float = SYNC_EVERY_S):
        self.db = db
        self.public_url = public_url.rstrip("/")
        self.every_s = every_s

    @classmethod
    def from_env(cls) -> "Cloud | None":
        dsn, url = os.environ.get("NEON_DATABASE_URL"), os.environ.get("CARDIOVIEW_PUBLIC_URL")
        if not dsn or not url:
            return None
        return cls(NeonDb(dsn), url)

    def link(self, sid: str) -> str:
        return f"{self.public_url}/s/{sid}"

    async def _call(self, fn, *args):
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), TIMEOUT_S)

    async def publish(self, sid: str, summary: dict, keep_until: datetime) -> str:
        await self._call(self.db.upsert, sid, keep_until, json.dumps(summary, allow_nan=False))
        return self.link(sid)

    async def unpublish(self, sid: str) -> None:
        await self._call(self.db.remove, sid)

    async def sync_once(self, manager) -> None:
        """Apply deletes made on phones, drop expired rows, and publish what an earlier try missed."""
        for sid in await self._call(self.db.tombstones):
            await manager.delete(sid)
        await self._call(self.db.remove_expired)
        store, now = manager.store, utcnow()
        for sid in store.ids():
            meta = store.read_meta(sid)
            if not meta or meta.get("state") != "done" or meta.get("published"):
                continue
            summary = store.summary(sid, now)
            if summary is None:
                continue
            link = await self.publish(sid, summary, datetime.fromisoformat(meta["keep_until"]))
            meta["published"] = True
            store.write_meta(sid, meta)
            manager.update_link(sid, link)

    async def run(self, manager) -> None:
        while True:
            try:
                await self.sync_once(manager)
            except Exception as e:
                log.info("cloud sync skipped: %s", e)
            await asyncio.sleep(self.every_s)

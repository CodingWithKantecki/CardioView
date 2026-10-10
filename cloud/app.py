"""Public summary pages for CardioView: the QR link a visitor opens on their phone.

Reads anonymous summaries from Neon with a role that can only read them and mark
them deleted, and serves the same summary page the booth serves. Nothing else.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"          # filled from frontend/ by tools/sessions.py deploy
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
GONE = {"reason": "This session is no longer available."}


class NeonPublic:
    """Read one summary, or mark it deleted. Nothing else is granted to this role."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _run(self, sql: str, params: tuple, fetch: bool):
        import psycopg
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if fetch else cur.rowcount

    def get(self, sid: str):
        rows = self._run("select summary, keep_until, deleted_at from session_summary where id = %s", (sid,), True)
        return rows[0] if rows else None

    def mark_deleted(self, sid: str) -> int:
        return self._run("update session_summary set summary = null, deleted_at = now() "
                         "where id = %s and deleted_at is null and keep_until > now()", (sid,), False)


def create_app(db=None, now=lambda: datetime.now(timezone.utc)) -> FastAPI:
    db = db or NeonPublic(os.environ.get("NEON_PUBLIC_URL", ""))
    app = FastAPI(title="CardioView summaries", docs_url=None, redoc_url=None, openapi_url=None)

    def gone() -> JSONResponse:
        return JSONResponse(GONE, status_code=404, headers={"Cache-Control": "no-store"})

    @app.get("/api/s/{sid}")
    def get_summary(sid: str):
        if not ID_RE.match(sid):
            return gone()
        row = db.get(sid)
        if row is None:
            return gone()
        summary, keep_until, deleted_at = row
        if summary is None or deleted_at is not None or keep_until <= now():
            return gone()
        return JSONResponse(summary, headers={"Cache-Control": "no-store"})

    @app.delete("/api/s/{sid}")
    def delete_summary(sid: str):
        if not ID_RE.match(sid) or db.mark_deleted(sid) == 0:
            return gone()
        return {"ok": True}

    @app.get("/s/{sid}")
    def page(sid: str):
        return FileResponse(STATIC / "summary.html", headers={"Cache-Control": "no-store"})

    if STATIC.is_dir():   # absent until the first deploy copies the page in
        app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()

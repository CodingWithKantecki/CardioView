"""Saved sessions from the command line.

    python tools/sessions.py list
    python tools/sessions.py delete <id>
    python tools/sessions.py wipe [--yes]        after the event: every local session and every Neon row
    python tools/sessions.py cloud-init "<Neon owner connection string>"
    python tools/sessions.py deploy               copy the summary page into cloud/ and deploy it to Vercel

Neon is used when NEON_DATABASE_URL is set, in the environment or in .env at the repo root.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cloud import SCHEMA, NeonDb, load_env  # noqa: E402
from backend.session import SessionStore, utcnow  # noqa: E402

SESSIONS = ROOT / "sessions"
FRONTEND = ROOT / "frontend"
CLOUD = ROOT / "cloud"
PAGE = ("summary.html", "summary.js", "summary.css")
ASSETS = ("logo-mark.png", "favicon.png")   # the header's heart mark and the tab icon, from frontend/assets
FONTS = ("jetbrains-mono-latin-600-normal.woff2", "jetbrains-mono-latin-700-normal.woff2", "LICENSE-jetbrains-mono")
GRANTS = (
    "grant usage on schema public to cardioview_booth, cardioview_public",
    "grant select, insert, update, delete on session_summary to cardioview_booth",
    "revoke all on session_summary from cardioview_public",
    "grant select on session_summary to cardioview_public",
    "grant update (summary, deleted_at) on session_summary to cardioview_public",
)


def list_sessions(store: SessionStore) -> list[str]:
    rows = []
    for sid in store.ids():
        m = store.read_meta(sid) or {}
        rows.append(f"{sid}  {m.get('created', '?')[:16]}  {m.get('state', '?'):<9}  "
                    f"{'published' if m.get('published') else 'local':<9}  until {m.get('keep_until', '?')[:16]}")
    return rows


def delete(store: SessionStore, db, sid: str) -> bool:
    existed = store.delete(sid)
    if db is not None:
        db.remove(sid)
    return existed


def wipe(store: SessionStore, db) -> tuple[int, int]:
    local = sum(store.delete(sid) for sid in store.ids())
    remote = db.remove_all() if db is not None else 0
    return local, remote


def dsn_for(owner_dsn: str, user: str, password: str) -> str:
    """The owner's connection string with another role's name and password in it."""
    u = urlsplit(owner_dsn)
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, f"{quote(user, safe='')}:{quote(password, safe='')}@{host}", u.path, u.query, u.fragment))


def cloud_init(owner_dsn: str) -> tuple[str, str]:
    """Create the table and the two roles, and return their connection strings (booth, public)."""
    import psycopg
    from psycopg import sql

    passwords = {"cardioview_booth": secrets.token_urlsafe(24), "cardioview_public": secrets.token_urlsafe(24)}
    with psycopg.connect(owner_dsn, autocommit=True) as conn:
        conn.execute(SCHEMA)
        for role, password in passwords.items():
            exists = conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
            verb = "alter" if exists else "create"
            conn.execute(sql.SQL(verb + " role {} with login password {}").format(sql.Identifier(role), sql.Literal(password)))
        for grant in GRANTS:
            conn.execute(grant)
    return (dsn_for(owner_dsn, "cardioview_booth", passwords["cardioview_booth"]),
            dsn_for(owner_dsn, "cardioview_public", passwords["cardioview_public"]))


def deploy(frontend: Path = FRONTEND, cloud: Path = CLOUD, run=subprocess.run, which=shutil.which) -> None:
    """Copy the summary page and its fonts into cloud/static, then deploy to production."""
    static = cloud / "static"
    if static.exists():
        shutil.rmtree(static)
    (static / "vendor" / "fonts").mkdir(parents=True)
    for name in PAGE:
        shutil.copy2(frontend / name, static / name)
    for name in FONTS:
        shutil.copy2(frontend / "vendor" / "fonts" / name, static / "vendor" / "fonts" / name)
    (static / "assets").mkdir()
    for name in ASSETS:
        shutil.copy2(frontend / "assets" / name, static / "assets" / name)
    vercel = which("vercel")
    if vercel is None:
        raise SystemExit("The Vercel CLI is not installed: npm i -g vercel, then vercel login")
    run([vercel, "deploy", "--prod", "--yes"], cwd=cloud, check=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Saved CardioView sessions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("delete")
    d.add_argument("id")
    w = sub.add_parser("wipe")
    w.add_argument("--yes", action="store_true", help="do not ask")
    c = sub.add_parser("cloud-init")
    c.add_argument("owner_dsn")
    sub.add_parser("deploy")
    args = ap.parse_args(argv)

    load_env(ROOT / ".env")
    store = SessionStore(SESSIONS)
    dsn = os.environ.get("NEON_DATABASE_URL")
    db = NeonDb(dsn) if dsn else None

    if args.cmd == "list":
        rows = list_sessions(store)
        print("\n".join(rows) if rows else "no saved sessions")
    elif args.cmd == "delete":
        print("deleted" if delete(store, db, args.id) else "no such session here (the cloud copy was removed if there was one)")
    elif args.cmd == "wipe":
        if not args.yes and input(f"Delete every saved session{' and every Neon row' if db else ''}? Type yes: ") != "yes":
            print("nothing deleted")
            return
        local, remote = wipe(store, db)
        print(f"deleted {local} local sessions and {remote} Neon rows")
    elif args.cmd == "cloud-init":
        booth, public = cloud_init(args.owner_dsn)
        print("Put this in .env on the booth laptop (never commit it):")
        print(f"NEON_DATABASE_URL={booth}")
        print("\nAnd this in the Vercel project's environment variables:")
        print(f"NEON_PUBLIC_URL={public}")
    elif args.cmd == "deploy":
        deploy()


if __name__ == "__main__":
    main()

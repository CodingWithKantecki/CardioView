"""The three datasets from PhysioNet's open S3 mirror into research/rhythm/data/ (skips what is there).

python -m research.rhythm.download

The mirror holds the same files as physionet.org, which served the PTB-XL zip at about 80 KB/s.
"""
from __future__ import annotations

import csv
import http.client
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA = Path(__file__).parent / "data"
S3 = "https://physionet-open.s3.amazonaws.com"
AGENT = {"User-Agent": "cardioview-rhythm-feasibility"}


def fetch(name: str, url: str, tries: int = 30) -> Path:
    """Download url to data/<name>. A dropped connection can end a read early without an error,
    so the bytes are counted against Content-Length and the transfer resumes where it stopped."""
    path = DATA / name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    total = None
    for _ in range(tries):
        have = part.stat().st_size if part.exists() else 0
        headers = dict(AGENT)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                resumed = have and r.status == 206   # a server that ignores the range sends it all again
                total = (have if resumed else 0) + int(r.headers.get("Content-Length") or 0) or total
                with open(part, "ab" if resumed else "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
        except (OSError, http.client.HTTPException) as e:
            print(f"{name}: {e}; resuming", flush=True)
        if total and part.exists() and part.stat().st_size >= total:
            part.replace(path)
            return path
    raise RuntimeError(f"{name}: stopped at {part.stat().st_size if part.exists() else 0} of {total} bytes")


def mirror(jobs: dict, workers: int = 32, tries: int = 5) -> int:
    """Fetch many small files (local path to URL) in parallel, skipping those already there.
    A body shorter than its Content-Length is tried again. Returns how many files it fetched."""
    todo = {Path(p): u for p, u in jobs.items() if not Path(p).exists()}

    def one(item):
        path, url = item
        path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60) as r:
                    body = r.read()
                    want = int(r.headers.get("Content-Length") or len(body))
            except (OSError, http.client.HTTPException):
                continue
            if len(body) == want:
                part = path.with_name(path.name + ".part")
                part.write_bytes(body)
                part.replace(path)
                return
        raise RuntimeError(f"{url}: no complete copy after {tries} tries")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo.items()))
    return len(todo)


def main() -> int:
    ptb = f"{S3}/ptb-xl/1.0.3"
    with open(fetch("ptbxl/ptbxl_database.csv", f"{ptb}/ptbxl_database.csv"), newline="", encoding="utf-8") as f:
        names = [row["filename_hr"] for row in csv.DictReader(f)]
    jobs = {DATA / "ptbxl" / f"{n}{ext}": f"{ptb}/{n}{ext}" for n in names for ext in (".hea", ".dat")}
    print(f"ptbxl: fetched {mirror(jobs)} of {len(jobs)} files", flush=True)

    cinc = f"{S3}/challenge-2017/1.0.0"
    with open(fetch("cinc2017_reference.csv", f"{cinc}/REFERENCE-v3.csv"), newline="", encoding="utf-8") as f:
        records = [row[0] for row in csv.reader(f) if row]
    jobs = {DATA / "cinc2017" / f"{r}{ext}": f"{cinc}/training/{r[:3]}/{r}{ext}" for r in records for ext in (".hea", ".mat")}
    print(f"cinc2017: fetched {mirror(jobs)} of {len(jobs)} files", flush=True)

    mit = f"{S3}/mitdb/1.0.0"
    records = fetch("mitdb/RECORDS", f"{mit}/RECORDS").read_text(encoding="utf-8").split()
    jobs = {DATA / "mitdb" / f"{r}{ext}": f"{mit}/{r}{ext}" for r in records for ext in (".hea", ".dat", ".atr")}
    print(f"mitdb: fetched {mirror(jobs)} of {len(jobs)} files", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

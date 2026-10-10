"""The three datasets from PhysioNet into research/rhythm/data/ (about 2 GB; skips what is there).

python -m research.rhythm.download
"""
from __future__ import annotations

import http.client
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).parent / "data"
FILES = {
    "ptbxl.zip": "https://physionet.org/static/published-projects/ptb-xl/ptb-xl-a-large-publicly-available-electrocardiography-dataset-1.0.3.zip",
    "cinc2017.zip": "https://physionet.org/files/challenge-2017/1.0.0/training2017.zip",
    "cinc2017_reference.csv": "https://physionet.org/files/challenge-2017/1.0.0/REFERENCE-v3.csv",
    "mitdb.zip": "https://physionet.org/static/published-projects/mitdb/mit-bih-arrhythmia-database-1.0.0.zip",
}
UNZIP = {"ptbxl.zip": "ptbxl", "cinc2017.zip": "cinc2017", "mitdb.zip": "mitdb"}


def fetch(name: str, url: str, tries: int = 30) -> Path:
    """Download url to data/<name>. A dropped connection can end a read early without an error,
    so the bytes are counted against Content-Length and the transfer resumes where it stopped."""
    path = DATA / name
    if path.exists():
        return path
    part = path.with_name(name + ".part")
    total = None
    for _ in range(tries):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "cardioview-rhythm-feasibility"}
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


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        path = fetch(name, url)
        print(f"{name}: {path.stat().st_size / 1e6:.0f} MB", flush=True)
        if name in UNZIP and not (DATA / UNZIP[name]).exists():
            with zipfile.ZipFile(path) as z:
                z.extractall(DATA / UNZIP[name])
    return 0


if __name__ == "__main__":
    sys.exit(main())

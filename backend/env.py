"""Load KEY=VALUE lines from a .env file into the environment, without a dependency."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env", override: bool = False) -> list[str]:
    """Set each KEY=VALUE from `path` that is not already in the environment. Returns the names
    that were set. Blank lines and # comments are skipped; quotes around a value are removed.
    Values are never logged or printed here, so a key cannot leak through this module."""
    if not path.is_file():
        return []
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            names.append(key)
    return names

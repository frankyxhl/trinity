"""Profile loader.

A profile names its credential by source only; the core never reads the value.
Profiles are read from the JSON set passed by the caller.
"""

from __future__ import annotations

import json
from pathlib import Path


def load(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("profiles") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("profile set holds no profile list")
    return {
        entry["name"]: entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name")
    }

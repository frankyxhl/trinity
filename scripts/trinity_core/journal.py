"""Append-only journal writer and reader.

The journal holds pointers and metadata only, never prompt, thinking, tool or
output text (LAW-08). Every line is one self-contained JSON object appended by
one write under an exclusive lock, so parallel writers cannot interleave
(LED-006).
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_NAME = "journal.jsonl"
ERROR_LOG_NAME = "error.log"
VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def journal_path(root: str | os.PathLike) -> Path:
    return Path(root) / JOURNAL_NAME


def resolve_root() -> str:
    root = os.environ.get("TRINITY_ROOT")
    if root:
        return root
    guard = load_guard()
    if guard and guard.get("journal_root"):
        return str(guard["journal_root"])
    return os.getcwd()


def load_guard() -> dict | None:
    raw = os.environ.get("TRINITY_GUARD")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def append(root: str | os.PathLike, record: dict) -> None:
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"v": VERSION, **record}, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read(root: str | os.PathLike) -> list[dict]:
    path = journal_path(root)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def append_error(root: str | os.PathLike, fields: dict) -> None:
    path = Path(root) / ERROR_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(fields, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

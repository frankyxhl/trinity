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
import re
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_NAME = "journal.jsonl"
ERROR_LOG_NAME = "error.log"
VERSION = 1

_SECRET_SEGMENTS = frozenset(
    {
        "key",
        "apikey",
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "auth",
    }
)
_SECRET_SUFFIXES = ("password", "passwd", "secret", "token")
_KEY_PREFIX = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:sk-ant-|sk-|ghp_|gho_|ghu_|ghs_|ghr_|xox[baprs]-|glpat-)"
    r"([A-Za-z0-9_-]{16,})"
)
_BEARER = re.compile(r"(?i)(authorization\s*:\s*|bearer\s+)(\S+)")
_NAME = r"[A-Za-z_][A-Za-z0-9_.\-]*"
_ASSIGN = re.compile(r"(?i)\b((?:export\s+)?" + _NAME + r")\s*([=:])\s*(\S+)")
_MEMBER = re.compile(r'"(' + _NAME + r')"\s*:\s*"([^"]*)"')


def _is_secret_name(name: str) -> bool:
    segments = re.split(r"[_\-.]+|(?<=[a-z])(?=[A-Z])", name)
    for segment in segments:
        lowered = segment.lower()
        if lowered in _SECRET_SEGMENTS or lowered.endswith(_SECRET_SUFFIXES):
            return True
    return False


def _mask_member(match: re.Match) -> str:
    if _is_secret_name(match.group(1)):
        return f'"{match.group(1)}": "[redacted:member]"'
    return match.group(0)


def _mask_assignment(match: re.Match) -> str:
    bare = match.group(1).split(None, 1)[-1]
    if _is_secret_name(bare):
        return f"{match.group(1)}{match.group(2)}[redacted:assignment]"
    return match.group(0)


def redact(text: str) -> str:
    """Mask secret-shaped runs (RDR-008 kinds 1, 2, 4, 5)."""
    if not isinstance(text, str):
        return text
    out = _KEY_PREFIX.sub(lambda m: "[redacted:key]", text)
    out = _BEARER.sub(lambda m: m.group(1) + "[redacted:bearer]", out)
    out = _MEMBER.sub(_mask_member, out)
    out = _ASSIGN.sub(_mask_assignment, out)
    return out


def would_redact(text: str) -> bool:
    """DSP-017: a caller text a value the redaction function changes is refused."""
    return redact(text) != text


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

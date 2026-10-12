"""Quota check.

Runs the profile's quota source command and turns its answer into the fields of
a `check` record. A missing, failed or unreadable answer is `unknown`, which
stops the node before it starts (fail closed, LAW-06).
"""

from __future__ import annotations

import json
import subprocess

READ_TIMEOUT_S = 10


def _unknown(source_kind: str | None) -> dict:
    return {"result": "unknown", "source_kind": source_kind, "read_at": None}


def check(profile: dict) -> dict:
    source = profile.get("quota_source") or {}
    source_kind = source.get("kind")
    command = source.get("command")
    if not command:
        return _unknown(source_kind)
    try:
        proc = subprocess.run(
            [command], capture_output=True, text=True, timeout=READ_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return _unknown(source_kind)
    if proc.returncode != 0:
        return _unknown(source_kind)
    payload = _last_json_line(proc.stdout)
    if payload is None:
        return _unknown(source_kind)
    used = payload.get("used_pct")
    result = "exhausted" if isinstance(used, (int, float)) and used >= 100 else "ok"
    return {
        "result": result,
        "source_kind": source_kind,
        "read_at": payload.get("read_at"),
        "used_pct": used if isinstance(used, (int, float)) else None,
    }


def _last_json_line(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None

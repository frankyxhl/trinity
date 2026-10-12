"""Quota check.

Runs the profile's quota source command and turns its answer into the fields of
a `check` record. A missing, failed, invalid or stale answer is `unknown`, which
stops the node before it starts (fail closed, LAW-06). The command runs in its
own process group, killed on timeout so no grandchild outlives the read.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import datetime, timezone

READ_TIMEOUT_S = 10
_NUMBER = (int, float)


def _unknown(source_kind: str | None) -> dict:
    return {"result": "unknown", "source_kind": source_kind, "read_at": None}


def check(profile: dict) -> dict:
    source = profile.get("quota_source") or {}
    source_kind = source.get("kind")
    command = source.get("command")
    if not command:
        return _unknown(source_kind)
    payload = _read(command)
    if payload is None:
        return _unknown(source_kind)
    used = payload.get("used_pct")
    if isinstance(used, bool) or not isinstance(used, _NUMBER):
        return _unknown(source_kind)
    read_at = payload.get("read_at")
    freshness = profile.get("freshness_limit")
    if isinstance(freshness, bool) or not isinstance(freshness, _NUMBER):
        return _unknown(source_kind)
    age = _age_seconds(read_at)
    if age is None or age > freshness:
        return _unknown(source_kind)
    result = "exhausted" if used >= 100 else "ok"
    return {
        "result": result,
        "source_kind": source_kind,
        "read_at": read_at,
        "used_pct": used,
    }


def _read(command: str) -> dict | None:
    try:
        proc = subprocess.Popen(
            [command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError:
        return None
    try:
        out, _err = proc.communicate(timeout=READ_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.communicate()
        return None
    except KeyboardInterrupt:
        _kill_group(proc)
        proc.communicate()
        raise
    if proc.returncode != 0:
        return None
    return _last_json_line(out)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        pass


def _age_seconds(read_at) -> float | None:
    if not isinstance(read_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(read_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


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

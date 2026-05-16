"""TRN-2018 M1: live review metadata helpers.

Owns atomic read/write of `<review_dir>/metadata.json` plus per-review-dir
locking. `run_providers` (scripts/codex.py:1802) uses
`ThreadPoolExecutor(max_workers)` so per-provider state updates execute
in parallel; without locking, the read-modify-write pattern in
`update_provider_state` would race and silently drop concurrent updates.

Public surface:
- init_metadata(review_dir, *, review_id, review_dir_str, providers,
                preset, scope, root, input) -> None
- update_provider_state(review_dir, provider, **fields) -> None
- finalize_metadata(review_dir, results) -> None
- read_metadata(review_dir) -> dict   (single 100ms retry on JSONDecodeError)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
import time
from pathlib import Path

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(review_dir: Path) -> threading.Lock:
    key = str(review_dir)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _metadata_path(review_dir: Path) -> Path:
    return review_dir / "metadata.json"


def read_metadata(review_dir: Path) -> dict:
    """Read metadata.json, retrying once after 100ms on JSONDecodeError.

    The retry guards against a status reader catching an atomic mid-write
    on filesystems where a brief inconsistency is observable. After the
    single retry, decode errors propagate.
    """
    path = _metadata_path(review_dir)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        time.sleep(0.1)
        return json.loads(path.read_text())


def _write_atomic(review_dir: Path, data: dict) -> None:
    """Atomic write via tempfile + os.replace().

    Caller must hold _lock_for(review_dir).
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=".metadata.", suffix=".json.tmp", dir=str(review_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _metadata_path(review_dir))
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def init_metadata(
    review_dir: Path,
    *,
    review_id: str,
    review_dir_str: str,
    providers: list[str],
    preset,
    scope: str,
    root: str,
    input: dict,
) -> None:
    """Write the initial metadata.json before any provider executes.

    Top-level shape preserves all keys currently written post-completion
    by cmd_review (codex.py:2254-2261) so existing readers (status,
    test_codex_adapter, downstream consumers) see no missing keys; M1
    additions (review_id, review_dir, status, started_at, finished_at,
    provider_states) are additive.
    """
    data = {
        "review_id": review_id,
        "review_dir": review_dir_str,
        "status": "running",
        "started_at": _now_iso(),
        "finished_at": None,
        "scope": scope,
        "root": root,
        "providers": list(providers),
        "preset": preset,
        "input": input,
        "results": [],
        "provider_states": {p: {"status": "queued"} for p in providers},
    }
    with _lock_for(review_dir):
        _write_atomic(review_dir, data)


def update_provider_state(review_dir: Path, provider: str, **fields) -> None:
    """Read-modify-write for one provider's state entry under lock.

    Used by run_provider's transition points (queued→running on Popen
    start; running→finished/failed/timed_out on each return path in
    scripts/codex.py L1732/1745/1769).

    Defensive: silently no-op if metadata.json doesn't exist. The
    production flow always calls init_metadata first, but unit tests
    that exercise run_provider in isolation (test_provider_env.py)
    bypass init.
    """
    with _lock_for(review_dir):
        try:
            data = read_metadata(review_dir)
        except FileNotFoundError:
            return
        state = data.setdefault("provider_states", {}).setdefault(provider, {})
        state.update(fields)
        _write_atomic(review_dir, data)


def finalize_metadata(review_dir: Path, results: list[dict]) -> None:
    """Set finished_at + results + recompute top-level status.

    Status precedence: failed > timed_out > finished. Any 'failed' provider
    flips top-level to 'failed'; otherwise any 'timed_out' makes it
    'timed_out'; otherwise 'finished'.
    """
    with _lock_for(review_dir):
        data = read_metadata(review_dir)
        data["finished_at"] = _now_iso()
        data["results"] = list(results)
        terminal = [s.get("status") for s in data.get("provider_states", {}).values()]
        if "failed" in terminal:
            data["status"] = "failed"
        elif "timed_out" in terminal:
            data["status"] = "timed_out"
        else:
            data["status"] = "finished"
        _write_atomic(review_dir, data)

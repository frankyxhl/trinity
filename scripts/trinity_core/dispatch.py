"""Dispatch core: one call path (LAW-01).

A front end hands a request here; the core resolves the profile, writes the
node, runs the checks, hands the call to the adapter, and records the outcome.
The core never retries on its own (CHK-008).
"""

from __future__ import annotations

import uuid

from . import claude_code, journal
from . import profiles as profiles_mod
from . import quota

_ADAPTERS = {claude_code.ADAPTER: claude_code}


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def _new_session_id() -> str:
    return str(uuid.uuid4())


def call(request: dict) -> dict:
    root = journal.resolve_root()
    guard = journal.load_guard()
    is_root = guard is None

    try:
        profiles = profiles_mod.load(request["profiles_path"])
    except (OSError, ValueError):
        journal.append_error(root, {"error": "profiles_unreadable"})
        return _result(None, None, "bad_request", None, None, root)

    profile = profiles.get(request.get("profile"))
    if profile is None:
        journal.append_error(root, {"error": "unknown_profile"})
        return _result(None, None, "bad_request", None, None, root)
    if not profile.get("enabled", True):
        return _result(None, None, "profile_refused", None, profile, root)

    adapter = _ADAPTERS.get(profile.get("adapter"))
    if adapter is None:
        journal.append_error(root, {"error": "unknown_adapter"})
        return _result(None, None, "profile_refused", None, profile, root)

    if is_root:
        run_id = _new_id("r-")
        parent = None
        depth = 0
        max_depth = int(request.get("max_depth") or 0)
    else:
        run_id = guard.get("run")
        parent = guard.get("node")
        depth = int(guard.get("depth", 0)) + 1
        max_depth = int(guard.get("max_depth", 0))
        if not run_id or depth > max_depth:
            journal.append_error(
                root,
                {
                    "error": "nesting_refused",
                    "run": run_id,
                    "depth": depth,
                    "max_depth": max_depth,
                },
            )
            return _result(run_id, None, "nesting_refused", None, profile, root)

    node_id = _new_id("n-")
    session_mode = request.get("session", "new")
    session_id = _new_session_id() if session_mode == "new" else session_mode
    step = request.get("step") or ""

    if is_root:
        journal.append(
            root,
            {"kind": "run", "run": run_id, "event": "start", "t": journal.utc_now()},
        )
    journal.append(
        root,
        {
            "kind": "node",
            "run": run_id,
            "node": node_id,
            "parent": parent,
            "step": step,
            "round": 1,
            "label": step,
            "depth": depth,
            "harness": adapter.ADAPTER,
            "profile": profile.get("name"),
            "profile_reason": "named",
            "model": profile.get("model"),
            "session": {"id": session_id, "mode": session_mode, "source": "assigned"},
            "t": journal.utc_now(),
        },
    )
    journal.append(
        root,
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": "queued",
            "t": journal.utc_now(),
        },
    )

    check = quota.check(profile)
    journal.append(
        root,
        {
            "kind": "check",
            "run": run_id,
            "node": node_id,
            "check": "quota",
            **check,
            "t": journal.utc_now(),
        },
    )
    if check.get("result") != "ok":
        return _finish(root, run_id, node_id, is_root, "check_failed", "none", None, 0)

    journal.append(
        root,
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": "running",
            "t": journal.utc_now(),
        },
    )
    outcome = adapter.run(
        profile,
        prompt=request.get("prompt", ""),
        cwd=request.get("cwd") or ".",
        session_id=session_id,
        run_id=run_id,
        node_id=node_id,
        depth=depth,
        max_depth=max_depth,
        root=root,
    )

    exit_class = outcome.get("exit_class", "unknown")
    journal.append(
        root,
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": "done",
            "exit_class": exit_class,
            "output_kind": outcome.get("output_kind", "none"),
            "wall_s": outcome.get("wall_s", 0),
            **({"usage": outcome["usage"]} if outcome.get("usage") else {}),
            "t": journal.utc_now(),
        },
    )
    if is_root:
        journal.append(
            root, {"kind": "run", "run": run_id, "event": "end", "t": journal.utc_now()}
        )

    return {
        "run": run_id,
        "node": node_id,
        "exit_class": exit_class,
        "session_id": outcome.get("session_id") or session_id,
        "output_kind": outcome.get("output_kind", "none"),
        "output_ref": None,
        "transcript_ref": None,
        "usage": outcome.get("usage"),
        "ended_at": journal.utc_now(),
        "journal_complete": True,
    }


def _finish(root, run_id, node_id, is_root, exit_class, output_kind, usage, wall_s):
    journal.append(
        root,
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": "failed",
            "exit_class": exit_class,
            "output_kind": output_kind,
            "wall_s": wall_s,
            "t": journal.utc_now(),
        },
    )
    if is_root:
        journal.append(
            root, {"kind": "run", "run": run_id, "event": "end", "t": journal.utc_now()}
        )
    return {
        "run": run_id,
        "node": node_id,
        "exit_class": exit_class,
        "session_id": None,
        "output_kind": output_kind,
        "journal_complete": True,
    }


def _result(run_id, node_id, exit_class, session_id, profile, root):
    return {
        "run": run_id,
        "node": node_id,
        "exit_class": exit_class,
        "session_id": session_id,
        "output_kind": "none",
        "journal_complete": True,
    }

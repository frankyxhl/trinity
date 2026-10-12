"""Dispatch core: one call path (LAW-01).

A front end hands a request here; the core resolves the profile, writes the
node, runs the checks, hands the call to the adapter, and records the outcome.
The core never retries on its own (CHK-008). It owns every journal line,
heartbeat rows included (CHK-006), and journals only whitelisted numeric usage
fields and validated labels (DSP-017, LED-008).
"""

from __future__ import annotations

import os
import uuid

from . import claude_code, journal
from . import profiles as profiles_mod
from . import quota

_ADAPTERS = {claude_code.ADAPTER: claude_code}

MAX_LABEL_LEN = 64
_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }
)
_DEFAULT_POLL_S = 15.0


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def _new_session_id() -> str:
    return str(uuid.uuid4())


def state_for_exit_class(exit_class: str) -> str:
    if exit_class == "ok":
        return "done"
    if exit_class == "interrupted":
        return "interrupted"
    return "failed"


def _valid_label(value) -> bool:
    if not isinstance(value, str) or not (1 <= len(value) <= MAX_LABEL_LEN):
        return False
    return all(char.isprintable() for char in value)


def _max_depth(request: dict) -> int:
    allow = request.get("allow_nesting")
    if allow is True:
        return 2
    if isinstance(allow, dict):
        value = allow.get("max_depth")
        return int(value) if value is not None else 2
    if isinstance(allow, bool):
        return 0
    if isinstance(allow, int):
        return allow
    return 0


def _prompt_text(request: dict) -> str:
    prompt = request.get("prompt")
    if isinstance(prompt, dict):
        return str(prompt.get("text") or "")
    return str(prompt or "")


def _sanitize_usage(usage) -> dict | None:
    if not isinstance(usage, dict):
        return None
    clean = {
        key: value
        for key, value in usage.items()
        if key in _USAGE_FIELDS
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }
    return clean or None


def _time_limit(request: dict) -> float | None:
    limits = request.get("limits") or {}
    time_s = limits.get("time_s")
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
        return None
    return float(time_s) if time_s > 0 else None


def _heartbeat_poll_s() -> float:
    raw = os.environ.get("TRINITY_HEARTBEAT_POLL_S")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _DEFAULT_POLL_S
        if value > 0:
            return value
    return _DEFAULT_POLL_S


def call(request: dict) -> dict:
    root = journal.resolve_root()
    guard = journal.load_guard()
    is_root = guard is None

    step = request.get("step") or ""
    label = request.get("label")
    if not _valid_label(step) or (label is not None and not _valid_label(label)):
        return _result(None, None, "bad_request", None)

    try:
        profiles = profiles_mod.load(request["profiles_path"])
    except (KeyError, OSError, ValueError):
        journal.append_error(root, {"error": "profiles_unreadable"})
        return _result(None, None, "bad_request", None)

    profile = profiles.get(request.get("profile"))
    if profile is None:
        journal.append_error(root, {"error": "unknown_profile"})
        return _result(None, None, "bad_request", None)
    if not profile.get("enabled", True):
        return _result(None, None, "profile_refused", None)

    adapter = _ADAPTERS.get(profile.get("adapter"))
    if adapter is None:
        journal.append_error(root, {"error": "unknown_adapter"})
        return _result(None, None, "profile_refused", None)

    if is_root:
        run_id = _new_id("r-")
        parent = None
        depth = 0
        max_depth = _max_depth(request)
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
            return _result(run_id, None, "nesting_refused", None)

    node_id = _new_id("n-")
    session_mode = request.get("session") or "new"
    session_id = _new_session_id() if session_mode == "new" else session_mode

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
        return _finish(root, run_id, node_id, is_root, "check_failed", "none", 0)

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

    def record_heartbeat(source: str) -> None:
        journal.append(
            root,
            {
                "kind": "heartbeat",
                "run": run_id,
                "node": node_id,
                "source": source,
                "t": journal.utc_now(),
            },
        )

    outcome = adapter.run(
        profile,
        prompt=_prompt_text(request),
        cwd=request.get("cwd") or os.getcwd(),
        session_id=session_id,
        run_id=run_id,
        node_id=node_id,
        depth=depth,
        max_depth=max_depth,
        root=root,
        heartbeat=record_heartbeat,
        poll_s=_heartbeat_poll_s(),
        time_s=_time_limit(request),
    )

    exit_class = outcome.get("exit_class", "unknown")
    usage = _sanitize_usage(outcome.get("usage"))
    journal.append(
        root,
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": state_for_exit_class(exit_class),
            "exit_class": exit_class,
            "output_kind": outcome.get("output_kind", "none"),
            "wall_s": outcome.get("wall_s", 0),
            **({"usage": usage} if usage else {}),
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
        "session_id": outcome.get("session_id"),
        "output_kind": outcome.get("output_kind", "none"),
        "output_ref": None,
        "transcript_ref": None,
        "usage": usage,
        "ended_at": journal.utc_now(),
        "journal_complete": True,
    }


def _finish(root, run_id, node_id, is_root, exit_class, output_kind, wall_s):
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


def _result(run_id, node_id, exit_class, session_id):
    return {
        "run": run_id,
        "node": node_id,
        "exit_class": exit_class,
        "session_id": session_id,
        "output_kind": "none",
        "journal_complete": True,
    }

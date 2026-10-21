"""Dispatch core: one call path (LAW-01).

A front end hands a request here; the core resolves the profile, writes the
node, runs the checks, hands the call to the adapter, and records the outcome.
The core never retries on its own (CHK-008). It owns every journal line,
heartbeat rows included (CHK-006), and journals only whitelisted numeric usage
fields and validated labels (DSP-017, LED-008).
"""

from __future__ import annotations

import os
import math
import re
import stat
import sys
import time
import uuid
from pathlib import Path

from . import claude_code, codex_exec, journal, memory_gate, opencode_run
from . import profile_checks
from . import profiles as profiles_mod

_ADAPTERS = {
    claude_code.ADAPTER: claude_code,
    codex_exec.ADAPTER: codex_exec,
    opencode_run.ADAPTER: opencode_run,
}

MAX_LABEL_LEN = 64
_USAGE_FIELDS = frozenset(
    {
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }
)
_DEFAULT_POLL_S = 15.0
_MIN_STALL_LIMIT_S = 60.0
_MAX_STALL_LIMIT_S = 1_000_000_000.0


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
    if not all(char.isprintable() for char in value):
        return False
    return not journal.would_redact(value)


_DEPTH_RE = re.compile(r"^[+-]?[0-9]+$")


def _max_depth(request: dict) -> int | None:
    """Return the run's nesting depth, 0 for off, or None for a bad shape."""
    allow = request.get("allow_nesting")
    if allow is None or allow is False:
        return 0
    if allow is True:
        return 2
    if not isinstance(allow, dict):
        return None
    value = allow.get("max_depth")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        depth = value
    elif isinstance(value, str) and _DEPTH_RE.match(value):
        depth = int(value)
    else:
        return None
    return depth if 1 <= depth <= 5 else None


def _resolve_prompt(request: dict) -> str | None:
    prompt = request.get("prompt")
    if isinstance(prompt, dict):
        if "file" in prompt:
            path = prompt.get("file")
            if not isinstance(path, str) or not path:
                return None
            try:
                text = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return None
        else:
            value = prompt.get("text")
            if value is None:
                return None
            text = str(value)
    elif isinstance(prompt, str):
        text = prompt
    else:
        return None
    return text or None


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
    if not isinstance(limits, dict):
        return None
    time_s = limits.get("time_s")
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
        return None
    try:
        value = float(time_s)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _stall_limit(request: dict, profile: dict) -> float | None:
    limits = request.get("limits")
    if limits is None:
        limits = {}
    if not isinstance(limits, dict):
        return None
    value = limits.get(
        "stall_s", profile.get("stall_limit_s", claude_code.DEFAULT_STALL_LIMIT_S)
    )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < _MIN_STALL_LIMIT_S or value > _MAX_STALL_LIMIT_S:
        return None
    try:
        normalized = float(value)
    except OverflowError:
        return None
    return normalized if math.isfinite(normalized) else None


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


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"not a regular file: {path}")
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _redact_text(text: str) -> str:
    return "\n".join(journal.redact(piece) for piece in text.split("\n"))


def _gate_check(gate: str, reading: dict | None, decision: str) -> dict:
    if reading is None:
        values = {key: None for key in memory_gate.READING_KEYS}
    else:
        values = {key: reading[key] for key in memory_gate.READING_KEYS}
    return {"check": "memory_gate", "gate": gate, "decision": decision, **values}


def _gate_record(run_id: str, node_id: str, gate: str, reading, decision: str) -> dict:
    return {
        "kind": "check",
        "run": run_id,
        "node": node_id,
        **_gate_check(gate, reading, decision),
        "t": journal.utc_now(),
    }


def _gate_line(gate: str, reading: dict | None, decision: str) -> str:
    if reading is None:
        values = {key: "na" for key in memory_gate.READING_KEYS}
    else:
        values = {key: reading[key] for key in memory_gate.READING_KEYS}
    return (
        f"gate={gate} level={values['level']} free={values['free_pct']} "
        f"swap_mb={values['swap_mb']} load5={values['load5']} "
        f"decision={decision}\n"
    )


def _write_log_dir(log_dir: str, log, start: float, end: float) -> None:
    if isinstance(log, dict):
        rc = log.get("rc")
        rc_text = f"rc={rc}" if rc is not None else "rc=none"
        stdout = log.get("stdout")
        stderr = log.get("stderr")
        if not isinstance(stdout, str):
            stdout = ""
        if not isinstance(stderr, str):
            stderr = ""
        started_at = log.get("started_at")
        ended_at = log.get("ended_at")
        if not isinstance(started_at, (int, float)):
            started_at = start
        if not isinstance(ended_at, (int, float)):
            ended_at = end
    else:
        rc_text = "rc=none"
        stdout = ""
        stderr = ""
        started_at = start
        ended_at = end
    base = Path(log_dir)
    _write_private(base / "start", f"{float(started_at)}\n")
    _write_private(base / "end", f"{float(ended_at)}\n")
    _write_private(base / "rc.txt", rc_text + "\n")
    _write_private(base / "out.jsonl", _redact_text(stdout))
    _write_private(base / "err.txt", _redact_text(stderr))


def _write_log_dir_checked(
    root: str,
    run_id: str,
    node_id: str,
    log_dir,
    log,
    start: float,
    end: float,
    gate_line: str | None,
) -> None:
    if not isinstance(log_dir, str) or not log_dir:
        return
    try:
        _write_log_dir(log_dir, log, start, end)
        if gate_line is not None:
            _write_private(Path(log_dir) / "gate.txt", gate_line)
    except OSError:
        try:
            journal.append_error(
                root, {"error": "log_unwritable", "run": run_id, "node": node_id}
            )
        except OSError:
            pass
        print(f"trinity call: log dir not written: {log_dir}", file=sys.stderr)


def call(request: dict) -> dict:
    call_started = time.time()
    step = request.get("step") or ""
    label = request.get("label")
    if not _valid_label(step) or (label is not None and not _valid_label(label)):
        return _result(None, None, "bad_request", None)

    request_max_depth = _max_depth(request)
    if request_max_depth is None:
        return _result(None, None, "bad_request", None)

    prompt = _resolve_prompt(request)
    if prompt is None:
        return _result(None, None, "bad_request", None)

    root = journal.resolve_root()
    guard = journal.load_guard()
    is_root = guard is None

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

    if not getattr(adapter, "accepts_profile", lambda _profile: True)(profile):
        return _result(None, None, "bad_request", None)

    stall_limit_s = _stall_limit(request, profile)
    if stall_limit_s is None:
        return _result(None, None, "bad_request", None)
    time_limit_s = _time_limit(request)
    request_gate = request.get("gate")
    if request_gate is not None and request_gate not in profile_checks.GATES:
        return _result(None, None, "bad_request", None)
    gate = request_gate if request_gate is not None else profile.get("gate")
    if gate is None:
        gate = "none"
    effective_model = request.get("model") or profile.get("model")

    if is_root:
        run_id = _new_id("r-")
        parent = None
        depth = 0
        max_depth = request_max_depth
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
    captures_session = bool(getattr(adapter, "CAPTURES_SESSION", False))
    if captures_session:
        session_id = None if session_mode == "new" else session_mode
        session_record_mode = "new" if session_mode == "new" else "continue"
        session_source = "pending" if session_mode == "new" else "caller"
    else:
        session_id = _new_session_id() if session_mode == "new" else session_mode
        session_record_mode = session_mode
        session_source = "assigned"
    node_written = False

    log_dir = request.get("log_dir")
    if isinstance(log_dir, str) and log_dir:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            return _result(None, None, "bad_request", None)

    output = request.get("output")
    if isinstance(output, str) and output:
        real_root = os.path.realpath(root)
        real_output = os.path.realpath(output)
        if real_output == real_root or real_output.startswith(real_root + os.sep):
            return _result(None, None, "bad_request", None)

    journal_complete = True
    journal_error_logged = False

    def note_journal_unavailable() -> None:
        nonlocal journal_complete, journal_error_logged
        journal_complete = False
        if journal_error_logged:
            return
        journal_error_logged = True
        try:
            journal.append_error(
                root,
                {"error": "journal_unavailable", "run": run_id, "node": node_id},
            )
        except OSError:
            pass

    def unavailable_result() -> dict:
        note_journal_unavailable()
        result = _result(
            run_id, node_id if node_written else None, "journal_unavailable", None
        )
        result["journal_complete"] = False
        return result

    def append_after_start(record: dict) -> None:
        if not journal_complete:
            return
        try:
            journal.append(root, record)
        except TimeoutError:
            note_journal_unavailable()

    try:
        if is_root:
            journal.append(
                root,
                {
                    "kind": "run",
                    "run": run_id,
                    "event": "start",
                    "t": journal.utc_now(),
                },
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
                "model": effective_model,
                "stall_limit_s": stall_limit_s,
                "session": {
                    "id": session_id,
                    "mode": session_record_mode,
                    "source": session_source,
                },
                "t": journal.utc_now(),
            },
        )
        node_written = True
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
    except TimeoutError:
        return unavailable_result()

    gate_line = None

    def refuse(exit_class: str, check: dict | None, wall_s: float) -> dict:
        try:
            if isinstance(check, dict):
                journal.append(
                    root,
                    {
                        "kind": "check",
                        "run": run_id,
                        "node": node_id,
                        **check,
                        "t": journal.utc_now(),
                    },
                )
            journal.append(
                root,
                {
                    "kind": "state",
                    "run": run_id,
                    "node": node_id,
                    "state": state_for_exit_class(exit_class),
                    "exit_class": exit_class,
                    "output_kind": "none",
                    "wall_s": wall_s,
                    "t": journal.utc_now(),
                },
            )
            if is_root:
                journal.append(
                    root,
                    {
                        "kind": "run",
                        "run": run_id,
                        "event": "end",
                        "t": journal.utc_now(),
                    },
                )
        except TimeoutError:
            return unavailable_result()
        _write_log_dir_checked(
            root,
            run_id,
            node_id,
            log_dir,
            None,
            call_started,
            time.time(),
            gate_line,
        )
        return {
            "run": run_id,
            "node": node_id,
            "exit_class": exit_class,
            "session_id": None,
            "output_kind": "none",
            "output_ref": None,
            "transcript_ref": None,
            "usage": None,
            "ended_at": journal.utc_now(),
            "journal_complete": journal_complete,
        }

    preflight = getattr(adapter, "preflight", None)
    if preflight is not None:
        refusal = preflight(profile, model=effective_model)
        if isinstance(refusal, dict):
            return refuse("profile_refused", refusal.get("check"), 0)

    if gate != "none":
        gate_started = time.monotonic()
        gate_poll_s = memory_gate.poll_s()
        gate_deadline = (
            gate_started + time_limit_s if time_limit_s is not None else None
        )
        last_decision = None
        try:
            while True:
                try:
                    reading = memory_gate.read()
                except memory_gate.GateUnreadable:
                    gate_line = _gate_line(gate, None, "refused")
                    return refuse(
                        "check_failed",
                        _gate_check(gate, None, "refused"),
                        time.time() - call_started,
                    )
                decision = "go" if memory_gate.passes(gate, reading) else "wait"
                if (
                    decision == "go"
                    and gate_deadline is not None
                    and gate_deadline - time.monotonic() <= 0
                ):
                    decision = "wait"
                gate_line = _gate_line(gate, reading, decision)
                if decision != last_decision:
                    append_after_start(
                        _gate_record(run_id, node_id, gate, reading, decision)
                    )
                    last_decision = decision
                if decision == "go":
                    break
                now = time.monotonic()
                if gate_deadline is not None and gate_deadline - now <= 0:
                    gate_line = _gate_line(gate, reading, "stop")
                    return refuse(
                        "timeout",
                        _gate_check(gate, reading, "stop"),
                        time.time() - call_started,
                    )
                sleep_s = (
                    min(gate_poll_s, gate_deadline - now)
                    if gate_deadline is not None
                    else gate_poll_s
                )
                time.sleep(max(sleep_s, 0.0))
        except KeyboardInterrupt:
            return refuse("interrupted", None, time.time() - call_started)
        if time_limit_s is not None:
            time_limit_s -= time.monotonic() - gate_started
            if time_limit_s <= 0:
                gate_line = _gate_line(gate, reading, "stop")
                return refuse(
                    "timeout",
                    _gate_check(gate, reading, "stop"),
                    time.time() - call_started,
                )

    try:
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
    except TimeoutError:
        return unavailable_result()

    def record_heartbeat(source: str) -> None:
        append_after_start(
            {
                "kind": "heartbeat",
                "run": run_id,
                "node": node_id,
                "source": source,
                "t": journal.utc_now(),
            },
        )

    captured_report = {"done": False}

    def on_session(reported) -> None:
        if captured_report["done"]:
            return
        captured_report["done"] = True
        if session_mode != "new" and reported == session_id:
            return
        append_after_start(
            {
                "kind": "session",
                "run": run_id,
                "node": node_id,
                "id": reported,
                "source": "captured",
                "t": journal.utc_now(),
            },
        )

    outcome = adapter.run(
        profile,
        prompt=prompt,
        cwd=request.get("cwd") or os.getcwd(),
        session_id=session_id,
        run_id=run_id,
        node_id=node_id,
        depth=depth,
        max_depth=max_depth,
        root=root,
        heartbeat=record_heartbeat,
        poll_s=_heartbeat_poll_s(),
        time_s=time_limit_s,
        model=effective_model,
        on_session=on_session if captures_session else None,
        log_dir=request.get("log_dir"),
        output=request.get("output"),
    )

    exit_class = outcome.get("exit_class", "unknown")
    if exit_class == "timeout" and time_limit_s is not None:
        append_after_start(
            {
                "kind": "check",
                "run": run_id,
                "node": node_id,
                "check": "deadline",
                "limit_s": time_limit_s,
                "decision": "stop",
                "reason": "time limit reached",
                "t": journal.utc_now(),
            },
        )
    if (captures_session or exit_class == "harness_error") and not outcome.get(
        "session_id"
    ):
        append_after_start(
            {
                "kind": "session",
                "run": run_id,
                "node": node_id,
                "id": None,
                "source": "session_unknown",
                "t": journal.utc_now(),
            },
        )
    usage = _sanitize_usage(outcome.get("usage"))
    output_kind = outcome.get("output_kind", "none")
    output_ref = None
    answer = outcome.get("answer")
    output_path = request.get("output")
    if output_path and isinstance(answer, str):
        try:
            Path(output_path).write_text(answer, encoding="utf-8")
        except OSError:
            journal.append_error(
                root,
                {"error": "output_unwritable", "run": run_id, "node": node_id},
            )
            print(f"trinity call: output not written: {output_path}", file=sys.stderr)
        else:
            output_kind = "file"
            output_ref = output_path
    append_after_start(
        {
            "kind": "state",
            "run": run_id,
            "node": node_id,
            "state": state_for_exit_class(exit_class),
            "exit_class": exit_class,
            "output_kind": output_kind,
            "wall_s": outcome.get("wall_s", 0),
            **({"usage": usage} if usage else {}),
            "t": journal.utc_now(),
        },
    )
    if is_root:
        append_after_start(
            {"kind": "run", "run": run_id, "event": "end", "t": journal.utc_now()}
        )

    _write_log_dir_checked(
        root,
        run_id,
        node_id,
        log_dir,
        outcome.get("log"),
        call_started,
        time.time(),
        gate_line,
    )

    return {
        "run": run_id,
        "node": node_id,
        "exit_class": exit_class,
        "session_id": outcome.get("session_id"),
        "output_kind": output_kind,
        "output_ref": output_ref,
        "transcript_ref": None,
        "usage": usage,
        "ended_at": journal.utc_now(),
        "journal_complete": journal_complete,
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

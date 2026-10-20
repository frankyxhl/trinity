"""claude-code adapter: one call -> one `claude -p` invocation and back.

The adapter pre-assigns the session id (the harness takes `--session-id`), runs
the harness found on PATH, sets the recursion guard for the child, and reports
the exit class, session id and usage back to the core.

The core owns every journal line, heartbeat rows included (CHK-006): the
adapter only reports the heartbeat source it actually observed. The child
environment is built from an allow-list (ADP-006); the profile names a
credential wrapper command, which the adapter runs in place of the harness
found on PATH, so the adapter never reads the credential itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import selectors  # noqa: F401
import shutil
import signal
import subprocess  # noqa: F401
import time  # noqa: F401

from . import harness_proc, journal

ADAPTER = "claude-code"
WRAPPER_AUTH_MARKER = "trinity-claude-code: auth_error:"
CLAUDE_LOGIN_RESULT = "Not logged in · Please run /login"
HEARTBEAT_SOURCE = "stdout"
DEFAULT_POLL_S = 15.0
DEFAULT_STALL_LIMIT_S = 660.0
_DRAIN_GRACE_S = 0.5

_ENV_KEEP = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_COLLATE",
        "LC_MONETARY",
    }
)


def credential_wrapper(profile: dict) -> str | None:
    """The credential wrapper command this profile names, if any (PRF-001)."""
    source = profile.get("credential_source")
    if not isinstance(source, dict):
        return None
    wrapper = source.get("wrapper")
    return wrapper if isinstance(wrapper, str) and wrapper else None


def accepts_profile(profile: dict) -> bool:
    """A claude-code profile must name a credential wrapper (PRF-001)."""
    return credential_wrapper(profile) is not None


def run(
    profile: dict,
    *,
    prompt: str,
    cwd: str,
    session_id: str,
    run_id: str,
    node_id: str,
    depth: int,
    max_depth: int,
    root: str,
    heartbeat,
    poll_s: float = DEFAULT_POLL_S,
    time_s: float | None = None,
    model=None,
    on_session=None,
    log_dir=None,
    output=None,
) -> dict:
    wrapper = credential_wrapper(profile)
    if wrapper is None:
        return _outcome("unknown", None, None, 0)
    harness = shutil.which(wrapper)
    if harness is None:
        return _outcome("unknown", None, None, 0)

    argv = [
        harness,
        "-p",
        prompt,
        "--session-id",
        session_id,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    if model is None:
        model = profile.get("model")
    if model:
        argv += ["--model", str(model)]

    env = _build_env(
        {
            "run": run_id,
            "node": node_id,
            "depth": depth,
            "max_depth": max_depth,
            "journal_root": str(root),
        }
    )

    logged = harness_proc.run_harness(
        argv,
        cwd=cwd,
        env=env,
        heartbeat=heartbeat,
        heartbeat_source=HEARTBEAT_SOURCE,
        poll_s=poll_s,
        time_s=time_s,
        on_line=lambda _line: None,
        stdin=None,
    )
    wall_s = logged["wall_s"]
    rc = logged["rc"]
    out = logged["stdout"]
    stderr_text = logged["stderr"]

    if logged["interrupted"]:
        return {**_outcome("interrupted", None, None, wall_s), "log": logged}
    if logged["timed_out"]:
        result = _final_result(out)
        usage = result.get("usage") if result else None
        return {**_outcome("timeout", session_id, usage, wall_s), "log": logged}

    auth_hint = _wrapper_auth_hint(rc, stderr_text)
    result = _final_result(out)
    usage = result.get("usage") if result else None
    is_error = bool(result.get("is_error")) if result else True
    if auth_hint is None:
        if result is not None:
            auth_hint = _claude_json_auth_hint(result)

    reported = result.get("session_id") if result else None
    if auth_hint is not None:
        exit_class = "auth_error"
    elif rc == 0 and result is not None and not is_error:
        exit_class = "ok"
    else:
        exit_class = "unknown"

    session_out = session_id
    if exit_class == "ok" and reported != session_id:
        error = {
            "error": "session_mismatch",
            "run": run_id,
            "node": node_id,
            "assigned_fp": _fingerprint(session_id),
            "reported_fp": _fingerprint(reported),
        }
        if not _valid_session_shape(reported):
            error["reported_shape"] = "invalid"
        journal.append_error(root, error)
        exit_class = "harness_error"
        session_out = None
    outcome = _outcome(exit_class, session_out, usage, wall_s)
    if exit_class == "ok":
        outcome["answer"] = result.get("result")
    if auth_hint is not None:
        outcome["hint"] = auth_hint
    outcome["log"] = logged
    return outcome


def _poll_interval(value) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_POLL_S
    return interval if math.isfinite(interval) and interval > 0 else DEFAULT_POLL_S


def _finite_timeout(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return timeout if math.isfinite(timeout) and timeout > 0 else None


def _fingerprint(value) -> str | None:
    """One-way id fingerprint: first 12 hex of SHA-256, never the raw id."""
    if not isinstance(value, str):
        return None
    encoded = value.encode("utf-8", "surrogatepass")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _valid_session_shape(value) -> bool:
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 128
        and all(char.isalnum() or char in "-_" for char in value)
    )


def _build_env(guard: dict) -> dict:
    env: dict[str, str] = {}
    for name in os.environ:
        if name in _ENV_KEEP or name.startswith("LC_"):
            env[name] = os.environ[name]
    env["TRINITY_GUARD"] = json.dumps(guard)
    return env


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _final_result(out: str) -> dict | None:
    """The strict Claude JSON auth record: only the last non-empty stdout line."""
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        parsed = json.loads(lines[-1])
    except ValueError:
        return None
    if isinstance(parsed, dict) and parsed.get("type") == "result":
        return parsed
    return None


def _wrapper_auth_hint(returncode: int | None, stderr: str) -> str | None:
    if returncode == 0 or returncode is None:
        return None
    for line in stderr.splitlines():
        if line.startswith(WRAPPER_AUTH_MARKER):
            return line
    return None


def _claude_json_auth_hint(result: dict) -> str | None:
    if result.get("type") != "result" or result.get("is_error") is not True:
        return None
    if result.get("result") != CLAUDE_LOGIN_RESULT:
        return None
    config_dir = os.path.join(os.environ.get("HOME", ""), ".claude-trinity-claude-code")
    login_command = f"CLAUDE_CONFIG_DIR={shlex.quote(config_dir)} claude"
    return (
        f"Claude result: {CLAUDE_LOGIN_RESULT}; login with {login_command}, then /login"
    )


def _outcome(
    exit_class: str, session_id: str | None, usage: dict | None, wall_s: int
) -> dict:
    return {
        "adapter": ADAPTER,
        "exit_class": exit_class,
        "session_id": session_id,
        "output_kind": "none",
        "answer": None,
        "usage": usage if isinstance(usage, dict) else None,
        "wall_s": wall_s,
    }

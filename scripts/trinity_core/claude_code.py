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
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time

from . import journal

ADAPTER = "claude-code"
WRAPPER_AUTH_MARKER = "trinity-claude-code: auth_error:"
CLAUDE_LOGIN_RESULT = "Not logged in · Please run /login"
HEARTBEAT_SOURCE = "process_alive"
DEFAULT_POLL_S = 15.0

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
        "json",
    ]
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

    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    stop = threading.Event()
    thread = threading.Thread(
        target=_poll, args=(stop, proc, heartbeat, poll_s), daemon=True
    )
    thread.start()
    interrupted = False
    timed_out = False
    try:
        out, _err = proc.communicate(timeout=time_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(pgid)
        out, _err = proc.communicate()
    except KeyboardInterrupt:
        interrupted = True
        _kill_group(pgid)
        proc.communicate()
        out = ""
    finally:
        stop.set()
        thread.join()
    wall_s = int(time.monotonic() - started)

    if interrupted:
        return _outcome("interrupted", None, None, wall_s)
    if timed_out:
        result = _last_result(out)
        usage = result.get("usage") if result else None
        return _outcome("timeout", session_id, usage, wall_s)

    auth_hint = _wrapper_auth_hint(proc.returncode, _err)
    result = _last_result(out)
    usage = result.get("usage") if result else None
    is_error = bool(result.get("is_error")) if result else True
    if auth_hint is None and result is not None:
        auth_hint = _claude_json_auth_hint(result)

    reported = result.get("session_id") if result else None
    if auth_hint is not None:
        exit_class = "auth_error"
    elif proc.returncode == 0 and result is not None and not is_error:
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
    if auth_hint is not None:
        outcome["hint"] = auth_hint
    return outcome


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


def _poll(
    stop: threading.Event, proc: subprocess.Popen, heartbeat, poll_s: float
) -> None:
    while not stop.wait(poll_s):
        if proc.poll() is not None:
            return
        heartbeat(HEARTBEAT_SOURCE)


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _last_result(out: str) -> dict | None:
    for line in reversed(out.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
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
        "usage": usage if isinstance(usage, dict) else None,
        "wall_s": wall_s,
    }

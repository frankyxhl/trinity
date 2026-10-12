"""claude-code adapter: one call -> one `claude -p` invocation and back.

The adapter pre-assigns the session id (the harness takes `--session-id`), runs
the harness found on PATH, sets the recursion guard for the child, and reports
the exit class, session id and usage back to the core.

The core owns every journal line, heartbeat rows included (CHK-006): the
adapter only reports the heartbeat source it actually observed. The child
environment is built from an allow-list (ADP-006); the profile's credential is
forwarded by name only, never read.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time

from . import journal

ADAPTER = "claude-code"
HARNESS_CLI = "claude"
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
    harness = shutil.which(HARNESS_CLI)
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
        profile,
        {
            "run": run_id,
            "node": node_id,
            "depth": depth,
            "max_depth": max_depth,
            "journal_root": str(root),
        },
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
        _kill_group(proc)
        out, _err = proc.communicate()
    except KeyboardInterrupt:
        interrupted = True
        _kill_group(proc)
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

    result = _last_result(out)
    usage = result.get("usage") if result else None
    is_error = bool(result.get("is_error")) if result else True
    reported = result.get("session_id") if result else None
    if proc.returncode == 0 and result is not None and not is_error:
        exit_class = "ok"
    else:
        exit_class = "unknown"

    session_out = session_id
    if exit_class == "ok" and reported != session_id:
        journal.append_error(
            root,
            {"error": "session_mismatch", "assigned": session_id, "reported": reported},
        )
        exit_class = "harness_error"
        session_out = None
    return _outcome(exit_class, session_out, usage, wall_s)


def _build_env(profile: dict, guard: dict) -> dict:
    env: dict[str, str] = {
        name: value
        for name, value in os.environ.items()
        if name in _ENV_KEEP or name.startswith("LC_")
    }
    env["TRINITY_GUARD"] = json.dumps(guard)
    credential = (profile.get("credential_source") or {}).get("env")
    if credential and credential in os.environ:
        env[credential] = os.environ[credential]
    return env


def _poll(
    stop: threading.Event, proc: subprocess.Popen, heartbeat, poll_s: float
) -> None:
    while not stop.wait(poll_s):
        if proc.poll() is not None:
            return
        heartbeat(HEARTBEAT_SOURCE)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
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

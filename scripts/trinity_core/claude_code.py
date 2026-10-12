"""claude-code adapter: one call -> one `claude -p` invocation and back.

The adapter pre-assigns the session id (the harness takes `--session-id`), runs
the harness found on PATH, sets the recursion guard for the child, and reports
the exit class, session id and usage back to the core. It writes no journal
line itself except the heartbeat rows the core owns (CHK-006).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

from . import journal

ADAPTER = "claude-code"
HARNESS_CLI = "claude"
HEARTBEAT_POLL_S = 15


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
) -> dict:
    harness = shutil.which(HARNESS_CLI)
    if harness is None:
        return _outcome("unknown", session_id, None, 0)

    argv = [harness, "-p", prompt, "--session-id", session_id]
    model = profile.get("model")
    if model:
        argv += ["--model", str(model)]

    env = dict(os.environ)
    env["TRINITY_GUARD"] = json.dumps(
        {
            "run": run_id,
            "node": node_id,
            "depth": depth,
            "max_depth": max_depth,
            "journal_root": str(root),
        }
    )
    if depth + 1 > max_depth:
        env["TRINITY_DISABLE_DISPATCH"] = "1"
    else:
        env.pop("TRINITY_DISABLE_DISPATCH", None)

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
        target=_heartbeats, args=(stop, root, run_id, node_id, proc), daemon=True
    )
    thread.start()
    try:
        out, _err = proc.communicate()
    finally:
        stop.set()
        thread.join()
    wall_s = int(time.monotonic() - started)

    result = _last_result(out)
    usage = result.get("usage") if result else None
    is_error = bool(result.get("is_error")) if result else True
    exit_class = "ok" if proc.returncode == 0 and not is_error else "unknown"
    reported_id = result.get("session_id") if result else None
    return _outcome(exit_class, reported_id or session_id, usage, wall_s)


def _heartbeats(
    stop: threading.Event,
    root: str,
    run_id: str,
    node_id: str,
    proc: subprocess.Popen,
) -> None:
    while not stop.wait(HEARTBEAT_POLL_S):
        if proc.poll() is not None:
            return
        journal.append(
            root,
            {
                "kind": "heartbeat",
                "run": run_id,
                "node": node_id,
                "source": "transcript_growth",
                "t": journal.utc_now(),
            },
        )


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


def _outcome(exit_class: str, session_id: str, usage: dict | None, wall_s: int) -> dict:
    return {
        "adapter": ADAPTER,
        "exit_class": exit_class,
        "session_id": session_id,
        "output_kind": "none",
        "usage": usage if isinstance(usage, dict) else None,
        "wall_s": wall_s,
    }

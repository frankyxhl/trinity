from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess

from . import claude_code, harness_proc, journal, profile_checks

ADAPTER = "opencode"
CAPTURES_SESSION = True
HEARTBEAT_SOURCE = "stdout"

_SESSION_NOT_FOUND_MARKER = "Session not found"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def accepts_profile(profile: dict) -> bool:
    model = profile.get("model")
    if not profile_checks.non_empty_str(model) or "/" not in model:
        return False
    if not profile_checks.non_empty_str(profile.get("opencode_config")):
        return False
    variant = profile.get("variant")
    if variant is not None and not isinstance(variant, str):
        return False
    return (
        profile_checks.binary_ok(profile)
        and profile_checks.gate_ok(profile)
        and profile_checks.env_pass_ok(profile)
    )


def _config_path(profile: dict) -> str:
    return os.path.abspath(os.path.expanduser(profile.get("opencode_config") or ""))


def preflight(profile: dict, *, model=None):
    binary = shutil.which(profile.get("binary") or "opencode")
    if binary is None:
        return {"exit_class": "profile_refused", "check": None}
    config = _config_path(profile)
    if not os.path.isfile(config):
        return {"exit_class": "profile_refused", "check": None}
    return _models_refusal(binary, profile, model)


def _env(profile: dict, guard: dict | None = None) -> dict:
    env: dict[str, str] = {}
    for name in os.environ:
        if name in claude_code._ENV_KEEP or name.startswith("LC_"):
            env[name] = os.environ[name]
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    for name in profile.get("env_pass") or []:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    env["OPENCODE_CONFIG"] = _config_path(profile)
    if guard is not None:
        env["TRINITY_GUARD"] = json.dumps(guard)
    return env


def _models_refusal(binary: str, profile: dict, model):
    try:
        proc = subprocess.run(
            [binary, "models"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
            env=_env(profile),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"exit_class": "profile_refused", "check": None}
    if proc.returncode != 0:
        return {"exit_class": "profile_refused", "check": None}
    lines = [
        line.rstrip() for line in proc.stdout.decode("utf-8", "replace").splitlines()
    ]
    if model in lines:
        return None
    return {
        "exit_class": "profile_refused",
        "check": {"check": "model", "model": model, "decision": "refused"},
    }


def run(
    profile: dict,
    *,
    prompt: str,
    cwd: str,
    session_id: str | None,
    run_id: str,
    node_id: str,
    depth: int,
    max_depth: int,
    root: str,
    heartbeat,
    poll_s: float = claude_code.DEFAULT_POLL_S,
    time_s: float | None = None,
    model=None,
    on_session=None,
    log_dir=None,
    output=None,
) -> dict:
    binary = shutil.which(profile.get("binary") or "opencode")
    if binary is None:
        return _outcome("unknown", None, None, None, 0)
    argv = _argv(profile, prompt, model, cwd, session_id)
    env = _env(
        profile,
        guard={
            "run": run_id,
            "node": node_id,
            "depth": depth,
            "max_depth": max_depth,
            "journal_root": str(root),
        },
    )

    state = {
        "session_id": None,
        "reported": False,
        "answer_parts": [],
        "usage": {},
        "saw_step_finish": False,
        "last_reason": None,
        "error_markers": [],
        "saw_error": False,
        "permission_rejected": False,
    }

    def on_line(line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if not state["reported"]:
            reported_id = event.get("sessionID")
            if profile_checks.non_empty_str(reported_id):
                state["reported"] = True
                state["session_id"] = reported_id
                if on_session is not None:
                    on_session(reported_id)
        kind = event.get("type")
        part = event.get("part")
        if not isinstance(part, dict):
            part = {}
        if kind == "step_start":
            state["answer_parts"] = []
        elif kind == "text":
            text = part.get("text")
            if isinstance(text, str):
                state["answer_parts"].append(text)
        elif kind == "step_finish":
            state["saw_step_finish"] = True
            state["last_reason"] = part.get("reason")
            _accumulate_usage(state["usage"], part)
        elif kind == "error":
            state["saw_error"] = True
            state["error_markers"].append(_error_marker(event))
        elif kind == "tool_use":
            tool_state = part.get("state")
            if isinstance(tool_state, dict) and tool_state.get("status") == "error":
                tool_error = tool_state.get("error")
                if isinstance(tool_error, str):
                    lowered = tool_error.lower()
                    if "rejected" in lowered and "permission" in lowered:
                        state["permission_rejected"] = True

    result = harness_proc.run_harness(
        [binary, *argv],
        cwd=cwd,
        env=env,
        heartbeat=heartbeat,
        heartbeat_source=HEARTBEAT_SOURCE,
        poll_s=poll_s,
        time_s=time_s,
        on_line=on_line,
    )
    wall_s = result["wall_s"]
    rc = result["rc"]
    stderr = result["stderr"]
    if result["interrupted"]:
        exit_class = "interrupted"
    elif result["timed_out"]:
        exit_class = "timeout"
    elif rc != 0 and _SESSION_NOT_FOUND_MARKER in _ANSI_RE.sub("", stderr):
        exit_class = "session_not_found"
    elif state["saw_error"]:
        marker = "\n".join(state["error_markers"]).lower()
        if profile_checks.matches(marker, profile_checks.AUTH_MARKERS):
            exit_class = "auth_error"
        elif profile_checks.matches(marker, profile_checks.QUOTA_MARKERS):
            exit_class = "quota_exhausted"
        else:
            exit_class = "unknown"
    elif rc == 0 and state["last_reason"] == "stop":
        if not profile_checks.non_empty_str(state["session_id"]):
            state["session_id"] = None
            exit_class = "harness_error"
        else:
            failure = _readback_error(state["session_id"], model)
            if failure is not None:
                journal.append_error(
                    root, {"error": failure, "run": run_id, "node": node_id}
                )
            exit_class = "harness_error" if failure is not None else "ok"
    elif rc == 0 and state["permission_rejected"]:
        journal.append_error(
            root, {"error": "permission_rejected", "run": run_id, "node": node_id}
        )
        exit_class = "harness_error"
    elif rc == 0 and state["saw_step_finish"]:
        exit_class = "harness_error"
    else:
        exit_class = "unknown"
    usage = (
        dict(state["usage"]) if state["saw_step_finish"] and state["usage"] else None
    )
    answer = "".join(state["answer_parts"]) if state["answer_parts"] else None
    return {
        **_outcome(exit_class, state["session_id"], usage, answer, wall_s),
        "log": result,
    }


def _argv(profile: dict, prompt: str, model, cwd: str, session_id) -> list:
    argv = ["run", "--format", "json", "-m", str(model)]
    variant = profile.get("variant")
    if variant is not None:
        argv += ["--variant", variant]
    if session_id is not None:
        argv += ["-s", session_id]
    argv += ["--dir", cwd, prompt]
    return argv


def _accumulate_usage(usage: dict, part: dict) -> None:
    tokens = part.get("tokens")
    if isinstance(tokens, dict):
        _accumulate(usage, "input_tokens", tokens.get("input"))
        _accumulate(usage, "output_tokens", tokens.get("output"))
        _accumulate(usage, "tokens", tokens.get("total"))
        cache = tokens.get("cache")
        if isinstance(cache, dict):
            _accumulate(usage, "cache_read_input_tokens", cache.get("read"))
            _accumulate(usage, "cache_creation_input_tokens", cache.get("write"))
    _accumulate(usage, "cost_usd", part.get("cost"))


def _accumulate(usage: dict, key: str, value) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        usage[key] = usage.get(key, 0) + value


def _error_marker(event: dict) -> str:
    parts = []
    error = event.get("error")
    if isinstance(error, dict):
        name = error.get("name")
        if isinstance(name, str) and name:
            parts.append(name)
        data = error.get("data")
        if isinstance(data, dict):
            message = data.get("message")
            if isinstance(message, str) and message:
                parts.append(message)
    message = event.get("message")
    if isinstance(message, str) and message:
        parts.append(message)
    return " ".join(parts)


def _db_path() -> str:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return os.path.join(data_home, "opencode", "opencode.db")
    return os.path.expanduser("~/.local/share/opencode/opencode.db")


def _readback_error(session_id: str, model):
    path = _db_path()
    if not os.path.isfile(path):
        return "readback_missing"
    try:
        conn = sqlite3.connect(path, timeout=2)
        try:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute(
                "SELECT model FROM session WHERE id = ?", (session_id,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "readback_missing"
    if row is None:
        return "readback_missing"
    try:
        parsed = json.loads(row[0])
    except (ValueError, TypeError):
        return "readback_missing"
    if not isinstance(parsed, dict):
        return "readback_missing"
    provider_id = parsed.get("providerID")
    model_id = parsed.get("id")
    if not profile_checks.non_empty_str(
        provider_id
    ) or not profile_checks.non_empty_str(model_id):
        return "readback_missing"
    if f"{provider_id}/{model_id}" != model:
        return "model_mismatch"
    return None


def _outcome(
    exit_class: str,
    session_id: str | None,
    usage: dict | None,
    answer: str | None,
    wall_s: int,
) -> dict:
    return {
        "adapter": ADAPTER,
        "exit_class": exit_class,
        "session_id": session_id,
        "output_kind": "none",
        "usage": usage if isinstance(usage, dict) else None,
        "wall_s": wall_s,
        "answer": answer,
    }

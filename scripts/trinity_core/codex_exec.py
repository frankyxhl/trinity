from __future__ import annotations

import glob
import json
import os
import shutil
from pathlib import Path

from . import claude_code, harness_proc, journal, profile_checks

ADAPTER = "codex"
CAPTURES_SESSION = True
HEARTBEAT_SOURCE = "stdout"

_SANDBOXES = frozenset({"read-only", "workspace-write"})
_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh"})
_SESSION_NOT_FOUND_MARKER = "no rollout found for thread id"


def _event_message(event: dict) -> str | None:
    message = event.get("message")
    if isinstance(message, str) and message:
        return message
    error = event.get("error")
    if isinstance(error, dict):
        inner = error.get("message")
        if isinstance(inner, str) and inner:
            return inner
    return None


def _marker_text(state: dict, stderr: str, rc) -> str:
    parts = list(state["markers"])
    if rc != 0 and stderr:
        parts.append(stderr)
    return "\n".join(parts).lower()


def _last_turn_context(path) -> dict | None:
    context = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("type") == "turn_context":
                context = row
    return context


def _readback_error(codex_home, session_id, model, sandbox):
    try:
        matches = list(
            Path(codex_home).glob(
                f"sessions/**/rollout-*-{glob.escape(session_id)}.jsonl"
            )
        )
        if len(matches) != 1:
            return "readback_missing"
        context = _last_turn_context(matches[0])
        if context is None:
            return "readback_missing"
        payload = context.get("payload")
        if not isinstance(payload, dict) or payload.get("model") != model:
            return "model_mismatch"
        policy = payload.get("sandbox_policy")
        if not isinstance(policy, dict) or policy.get("type") != sandbox:
            return "sandbox_mismatch"
    except (OSError, UnicodeDecodeError):
        return "readback_missing"
    return None


def _codex_home(profile: dict) -> str:
    return os.path.abspath(os.path.expanduser(profile.get("codex_home") or ""))


def accepts_profile(profile: dict) -> bool:
    if not profile_checks.non_empty_str(profile.get("model")):
        return False
    sandbox = profile.get("sandbox")
    if not isinstance(sandbox, str) or sandbox not in _SANDBOXES:
        return False
    if not profile_checks.non_empty_str(profile.get("codex_home")):
        return False
    effort = profile.get("effort")
    if effort is not None and (not isinstance(effort, str) or effort not in _EFFORTS):
        return False
    return (
        profile_checks.binary_ok(profile)
        and profile_checks.gate_ok(profile)
        and profile_checks.env_pass_ok(profile)
    )


def preflight(profile: dict, *, model=None):
    codex_home = _codex_home(profile)
    if not os.path.isdir(codex_home):
        return {"exit_class": "profile_refused", "check": None}
    if shutil.which(profile.get("binary") or "codex") is None:
        return {"exit_class": "profile_refused", "check": None}
    return None


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
    binary = shutil.which(profile.get("binary") or "codex")
    if binary is None:
        return _outcome("unknown", None, None, None, 0)
    argv = _argv(profile, prompt, model, output, session_id)
    guard = {
        "run": run_id,
        "node": node_id,
        "depth": depth,
        "max_depth": max_depth,
        "journal_root": str(root),
    }
    env = claude_code._build_env(guard)
    for name in profile.get("env_pass") or []:
        if name in os.environ:
            env[name] = os.environ[name]
    env["CODEX_HOME"] = _codex_home(profile)
    env["TRINITY_GUARD"] = json.dumps(guard)
    codex_home = env["CODEX_HOME"]

    state = {
        "session_id": None,
        "reported": False,
        "answer": None,
        "usage": None,
        "last_event": None,
        "markers": [],
        "saw_error": False,
    }

    def on_line(line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "thread.started" and not state["reported"]:
            state["reported"] = True
            thread_id = event.get("thread_id")
            if profile_checks.non_empty_str(thread_id):
                if on_session is not None:
                    on_session(thread_id)
                state["session_id"] = thread_id
        state["last_event"] = kind
        if kind in ("error", "turn.failed"):
            message = _event_message(event)
            if message:
                state["markers"].append(message)
            if kind == "error":
                state["saw_error"] = True
        if kind == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                state["answer"] = item.get("text")
        elif kind == "turn.completed":
            state["usage"] = _usage(event.get("usage"))

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
    elif rc != 0 and _SESSION_NOT_FOUND_MARKER in stderr:
        exit_class = "session_not_found"
    else:
        marker = _marker_text(state, stderr, rc)
        if profile_checks.matches(marker, profile_checks.AUTH_MARKERS):
            exit_class = "auth_error"
        elif profile_checks.matches(marker, profile_checks.QUOTA_MARKERS):
            exit_class = "quota_exhausted"
        elif rc == 0 and state["last_event"] == "turn.completed":
            if not profile_checks.non_empty_str(state["session_id"]):
                state["session_id"] = None
                exit_class = "harness_error"
            else:
                failure = _readback_error(
                    codex_home,
                    state["session_id"],
                    model,
                    profile["sandbox"],
                )
                if failure is not None:
                    journal.append_error(
                        root, {"error": failure, "run": run_id, "node": node_id}
                    )
                exit_class = "harness_error" if failure is not None else "ok"
        elif rc == 0 and (state["last_event"] == "turn.failed" or state["saw_error"]):
            exit_class = "harness_error"
        else:
            exit_class = "unknown"
    return {
        **_outcome(
            exit_class, state["session_id"], state["usage"], state["answer"], wall_s
        ),
        "log": result,
    }


def _argv(profile: dict, prompt: str, model, output, session_id) -> list:
    effort = profile.get("effort")
    head = ["exec"]
    if session_id is None:
        head += ["-m", str(model)]
    else:
        head += ["-s", profile["sandbox"], "resume", "-m", str(model)]
    if effort is not None:
        head += ["-c", f'model_reasoning_effort="{effort}"']
    if session_id is None:
        head += ["-s", profile["sandbox"]]
    head += ["--skip-git-repo-check", "--json"]
    if output:
        head += ["-o", output]
    if session_id is None:
        return [*head, prompt]
    return [*head, session_id, prompt]


def _usage(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    mapping = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cached_input_tokens": "cache_read_input_tokens",
        "cache_write_input_tokens": "cache_creation_input_tokens",
    }
    usage = {}
    for source, target in mapping.items():
        value = raw.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[target] = value
    return usage or None


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

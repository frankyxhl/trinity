"""Pytest-BDD scenarios for /trinity user-facing flows.

This single file contains:
  1. Step definitions (@given / @when / @then) for the five .feature files
     under tests/features/.
  2. The pytest-bdd `scenarios()` collector call that binds those .feature
     files to pytest at collection time.

Per the slice C TRN-2024-CHG file-structure deviation: scenarios + step
defs live together here rather than in a separate `tests/step_defs/`
directory. Single-file approach eliminates the step-def-registration
question by construction (no `pytest_plugins` directive needed) and keeps
the BDD surface immediately discoverable for new contributors.

Step defs reuse `tmp_path` (per-scenario isolation), `monkeypatch` (env
+ cwd manipulation), and the JSON fixture helpers that the existing unit
tests in `test_session.py` and `test_codex_review_dispatch.py` already use.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION_PY = REPO_ROOT / "scripts" / "session.py"
INSTALL_PY = REPO_ROOT / "scripts" / "install.py"
DISCOVER_PY = REPO_ROOT / "scripts" / "discover.py"

# Make scripts.* importable as modules in the parent process.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Shared fixture: a per-scenario state bag.
# Each scenario gets its own; step defs read/write fields by name.
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx(tmp_path):
    return {
        "tmp_path": tmp_path,
        "project_dir": None,
        "home_dir": None,
        "config": None,
        "preset_name": None,
        "fanout": None,
        "preflight_ok": None,
        "heartbeat_output": None,
        "global_config_path": None,
    }


def _run(
    argv: list[str], cwd: Path | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run a subprocess, capture stdout+stderr, return the CompletedProcess."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=full_env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# session_lifecycle.feature
# ---------------------------------------------------------------------------


@given("a temporary project dir")
def _ctx_project_dir(ctx):
    pdir = ctx["tmp_path"] / "project"
    pdir.mkdir()
    ctx["project_dir"] = pdir


@given(
    parsers.parse(
        'a session entry "{key}" with session_id "{session_id}" and task "{task}"'
    )
)
def _seed_session(ctx, key: str, session_id: str, task: str):
    if ctx["project_dir"] is None:
        _ctx_project_dir(ctx)
    rc = _run(
        [
            sys.executable,
            str(SESSION_PY),
            "write",
            str(ctx["project_dir"]),
            key,
            session_id,
            task,
        ]
    )
    assert rc.returncode == 0, rc.stderr


@when(
    parsers.parse(
        'I write a session entry "{key}" with session_id "{session_id}" and task "{task}"'
    )
)
def _write_session(ctx, key: str, session_id: str, task: str):
    _seed_session(ctx, key, session_id, task)


@when(parsers.parse('I clear the session entry "{key}"'))
def _clear_session(ctx, key: str):
    rc = _run([sys.executable, str(SESSION_PY), "clear", str(ctx["project_dir"]), key])
    assert rc.returncode == 0, rc.stderr


def _read_session_file(project_dir: Path) -> dict:
    path = project_dir / ".claude" / "trinity.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@then(parsers.parse('the session file contains key "{key}"'))
def _assert_key_present(ctx, key: str):
    data = _read_session_file(ctx["project_dir"])
    assert key in data.get("sessions", {}), (
        f"key {key!r} missing from sessions: {list(data.get('sessions', {}).keys())}"
    )


@then(parsers.parse('the session file does not contain key "{key}"'))
def _assert_key_absent(ctx, key: str):
    data = _read_session_file(ctx["project_dir"])
    assert key not in data.get("sessions", {}), (
        f"key {key!r} unexpectedly present in sessions"
    )


@then(parsers.parse('the session entry "{key}" has session_id "{session_id}"'))
def _assert_session_id(ctx, key: str, session_id: str):
    data = _read_session_file(ctx["project_dir"])
    entry = data["sessions"][key]
    assert entry["session_id"] == session_id, (
        f"expected session_id={session_id!r}, got {entry.get('session_id')!r}"
    )


@then(parsers.parse('the session entry "{key}" has task_summary "{task}"'))
def _assert_task_summary(ctx, key: str, task: str):
    data = _read_session_file(ctx["project_dir"])
    entry = data["sessions"][key]
    assert entry["task_summary"] == task, (
        f"expected task_summary={task!r}, got {entry.get('task_summary')!r}"
    )


# ---------------------------------------------------------------------------
# review_preset_fanout.feature
# ---------------------------------------------------------------------------


@given(parsers.parse('required provider "{name}" with CLI "{cli}"'))
def _seed_required(ctx, name: str, cli: str):
    cfg = ctx["config"] or {
        "providers": {},
        "presets": {},
        "preset_aliases": {},
        "review": {},
    }
    cfg["providers"][name] = {"cli": cli, "installed": True}
    cfg["presets"]["p"] = {"providers": [name]}
    ctx["config"] = cfg


@given(
    parsers.parse(
        'the preset "{preset}" has optional provider "{name}" with CLI "{cli}"'
    )
)
def _seed_optional(ctx, preset: str, name: str, cli: str):
    cfg = ctx["config"]
    cfg["presets"][preset].setdefault("optional_providers", []).append(name)
    if cli != "(no config)":
        cfg["providers"][name] = {"cli": cli, "installed": True}


@given(parsers.parse('the preset "{preset}" has no optional providers'))
def _seed_no_optional(ctx, preset: str):
    cfg = ctx["config"]
    cfg["presets"][preset].pop("optional_providers", None)


@when(parsers.parse('I resolve preset "{preset}" against the config'))
def _resolve_preset(ctx, preset: str):
    from scripts import codex as codex_mod

    fanout, info, _warnings = codex_mod.resolve_preset_providers(
        ctx["config"], preset, "explicit"
    )
    ctx["fanout"] = fanout


@when("I run preflight on the resolved fan-out")
def _run_preflight(ctx):
    from scripts import codex as codex_mod

    health = codex_mod.provider_health_results(ctx["config"], ctx["fanout"], REPO_ROOT)
    ctx["preflight_ok"] = codex_mod.health_results_ok(health)


@then(parsers.parse('the fan-out is "{expected}"'))
def _assert_fanout(ctx, expected: str):
    expected_list = [p.strip() for p in expected.split(",") if p.strip()]
    assert ctx["fanout"] == expected_list, (
        f"fan-out mismatch: expected {expected_list}, got {ctx['fanout']}"
    )


@then(parsers.parse('preflight overall ok is "{ok}"'))
def _assert_preflight(ctx, ok: str):
    expected_bool = ok.strip().lower() == "true"
    assert ctx["preflight_ok"] is expected_bool, (
        f"expected preflight_ok={expected_bool}, got {ctx['preflight_ok']}"
    )


# ---------------------------------------------------------------------------
# provider_discovery.feature
# ---------------------------------------------------------------------------


@given("a temporary discovery setup")
def _setup_discovery(ctx):
    home = ctx["tmp_path"] / "home"
    (home / ".claude" / "agents").mkdir(parents=True)
    (home / ".claude" / "trinity.json").write_text(json.dumps({"providers": {}}))
    project = ctx["tmp_path"] / "project"
    project.mkdir()
    ctx["home_dir"] = home
    ctx["project_dir"] = project


@given(parsers.parse('a global config with provider "{name}" CLI "{cli}"'))
def _seed_global_config(ctx, name: str, cli: str):
    if ctx["home_dir"] is None:
        _setup_discovery(ctx)
    config_path = ctx["home_dir"] / ".claude" / "trinity.json"
    data = json.loads(config_path.read_text())
    data.setdefault("providers", {})[name] = {"cli": cli, "installed": True}
    config_path.write_text(json.dumps(data))


@given(parsers.parse('an agent file for provider "{name}"'))
def _seed_agent_file(ctx, name: str):
    if ctx["home_dir"] is None:
        _setup_discovery(ctx)
    agent_dir = ctx["home_dir"] / ".claude" / "agents"
    (agent_dir / f"trinity-{name}.md").write_text(f"# trinity-{name} worker agent\n")


@when("I run provider discovery")
def _run_discovery(ctx):
    rc = _run(
        [
            sys.executable,
            str(DISCOVER_PY),
            "list",
            "--global-config",
            str(ctx["home_dir"] / ".claude" / "trinity.json"),
            "--project-dir",
            str(ctx["project_dir"]),
        ],
        env={"HOME": str(ctx["home_dir"])},
    )
    assert rc.returncode == 0, f"discover failed: {rc.stderr}"
    ctx["discovery_output"] = rc.stdout


@then(parsers.parse('provider "{name}" status is "{status}"'))
def _assert_discovery_status(ctx, name: str, status: str):
    """discover.py list emits JSON: a list of {"name", "status", "cli", "agent"} objects."""
    providers = json.loads(ctx["discovery_output"])
    matching = [p for p in providers if p["name"] == name]
    assert matching, f"provider {name!r} not in discovery output: {providers}"
    actual = matching[0]["status"]
    assert actual == status, (
        f"provider {name!r}: expected status {status!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# session_heartbeat.feature
# ---------------------------------------------------------------------------


@given("a missing heartbeat output file path")
def _missing_output(ctx):
    ctx["heartbeat_output"] = ctx["tmp_path"] / "nonexistent.jsonl"


@given(
    parsers.parse(
        'an output file with an assistant message using tool "{tool}" with input summary "{summary}"'
    )
)
def _seed_output_file(ctx, tool: str, summary: str):
    path = ctx["tmp_path"] / "agent.jsonl"
    line = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": tool, "input": {"command": summary}}
            ]
        },
    }
    path.write_text(json.dumps(line) + "\n")
    ctx["heartbeat_output"] = path


@when("I run heartbeat against the output file")
def _run_heartbeat(ctx):
    rc = _run(
        [sys.executable, str(SESSION_PY), "heartbeat", str(ctx["heartbeat_output"])]
    )
    ctx["heartbeat_stdout"] = rc.stdout
    ctx["heartbeat_rc"] = rc.returncode


@then(parsers.parse('the heartbeat output indicates "{state}"'))
def _assert_heartbeat_state(ctx, state: str):
    out = ctx["heartbeat_stdout"]
    assert state.lower() in out.lower(), (
        f"expected state {state!r} in heartbeat output, got: {out!r}"
    )


@then(parsers.parse('the heartbeat output mentions "{text}"'))
def _assert_heartbeat_mentions(ctx, text: str):
    out = ctx["heartbeat_stdout"]
    assert text in out, f"expected {text!r} in heartbeat output, got: {out!r}"


# ---------------------------------------------------------------------------
# install_atomic_rollback.feature
# ---------------------------------------------------------------------------


@given("an empty global config")
def _empty_global_config(ctx):
    cfg_path = ctx["tmp_path"] / "trinity.json"
    cfg_path.write_text("{}")
    ctx["global_config_path"] = cfg_path


@when(parsers.parse('I register provider "{name}" with CLI "{cli}"'))
def _register_provider(ctx, name: str, cli: str):
    rc = _run(
        [
            sys.executable,
            str(INSTALL_PY),
            "register",
            name,
            "--cli",
            cli,
            "--global-config",
            str(ctx["global_config_path"]),
        ]
    )
    assert rc.returncode == 0, f"register failed: {rc.stderr}"


@when(parsers.parse('I unregister provider "{name}"'))
def _unregister_provider(ctx, name: str):
    rc = _run(
        [
            sys.executable,
            str(INSTALL_PY),
            "unregister",
            name,
            "--global-config",
            str(ctx["global_config_path"]),
        ]
    )
    # unregister of a non-existent provider is allowed to be a no-op (rc=0)
    # or surface a non-zero exit; both shapes are acceptable per CLI design.
    ctx["unregister_rc"] = rc.returncode


@then(parsers.parse('the global config contains provider "{name}"'))
def _assert_global_contains(ctx, name: str):
    data = json.loads(ctx["global_config_path"].read_text())
    assert name in data.get("providers", {}), (
        f"expected provider {name!r} in global config, got: {list(data.get('providers', {}).keys())}"
    )


@then(parsers.parse('the global config does not contain provider "{name}"'))
def _assert_global_does_not_contain(ctx, name: str):
    data = json.loads(ctx["global_config_path"].read_text())
    assert name not in data.get("providers", {}), (
        f"expected provider {name!r} absent from global config, got: {list(data.get('providers', {}).keys())}"
    )


# ---------------------------------------------------------------------------
# Bind every .feature in tests/features/ to pytest at collection time.
# pytest-bdd does NOT auto-collect raw .feature files; without this call,
# `pytest tests/` would discover zero scenarios. (Same defect class flagged
# in PR #44 round 4 — see TRN-2020-PRP §Slice C.)
# ---------------------------------------------------------------------------

scenarios(str(Path(__file__).parent / "features"))

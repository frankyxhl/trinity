from __future__ import annotations

import json
import shutil
import subprocess

from tests import one_support as one
from tests.test_one_options import _claude_root


def _json_dict_lines(stdout: str) -> int:
    count = 0
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            count += 1
    return count


def _hand_codex_profile(root, override) -> None:
    profile = {
        "name": one.PROFILE,
        "adapter": "codex",
        "provider": "codex",
        "billing": "subscription",
        "enabled": True,
        "model": one.MODEL,
        "sandbox": one.SANDBOX,
        "codex_home": str(root / "codex-home"),
    }
    profile.update(override)
    (root / "profiles.json").write_text(json.dumps({"profiles": [profile]}))


def _call_argv(ns) -> list:
    return [
        str(one.CLI),
        "call",
        "--profiles",
        str(ns.profiles),
        "--profile",
        one.PROFILE,
        "--step",
        "root",
        "--session",
        "new",
        "--prompt",
        one.PROMPT,
        "--cwd",
        str(ns.root / "work"),
    ]


def test_release_f1_claude_code_model_override_reaches_harness(tmp_path):
    ns = _claude_root(tmp_path)
    one.run_call(ns, args=("--model", "claude-opus-4-1"), timeout=30)
    capture = one.captures_of(ns.capture)[0]
    argv = capture.get("argv") or []
    position = argv.index("--model") if "--model" in argv else -1
    assert position != -1 and argv[position + 1] == "claude-opus-4-1", argv
    assert "claude-sonnet-4-5" not in argv, argv


def test_release_f3_env_pass_cannot_override_codex_home(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, env_pass=["CODEX_HOME"])
    one.run_call(
        ns,
        env_extra={"CODEX_HOME": str(tmp_path / "elsewhere")},
        timeout=30,
    )
    capture = one.captures_of(ns.capture)[0]
    env = capture.get("env") or {}
    assert env.get("CODEX_HOME") == str(ns.codex_home), env


def test_release_f3_env_pass_cannot_override_opencode_config(tmp_path):
    ns = one.make_opencode_root(tmp_path, env_pass=["OPENCODE_CONFIG"])
    one.run_oc_call(
        ns,
        env_extra={"OPENCODE_CONFIG": str(tmp_path / "elsewhere.json")},
        timeout=30,
    )
    rows = one.run_captures_of(ns.capture)
    assert rows, one.captures_of(ns.capture)
    env = rows[0].get("env") or {}
    assert env.get("OPENCODE_CONFIG") == str(ns.config), env


def test_release_f4_non_string_sandbox_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    _hand_codex_profile(ns.root, {"sandbox": ["read-only"]})
    proc = one.run_call(ns, timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert proc.returncode == 0, proc.returncode
    assert _json_dict_lines(proc.stdout) == 1, proc.stdout
    journal = ns.state / "journal.jsonl"
    assert not journal.exists(), journal.read_text()


def test_release_f4_non_string_effort_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    _hand_codex_profile(ns.root, {"effort": {"x": 1}})
    proc = one.run_call(ns, timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert proc.returncode == 0, proc.returncode
    assert _json_dict_lines(proc.stdout) == 1, proc.stdout
    journal = ns.state / "journal.jsonl"
    assert not journal.exists(), journal.read_text()


def test_release_f4_non_string_gate_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    _hand_codex_profile(ns.root, {"gate": ["light"]})
    proc = one.run_call(ns, timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert proc.returncode == 0, proc.returncode
    assert _json_dict_lines(proc.stdout) == 1, proc.stdout
    journal = ns.state / "journal.jsonl"
    assert not journal.exists(), journal.read_text()


def test_release_f7_relative_codex_home_resolves_against_caller_cwd(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home="rel-codex-home")
    relative = tmp_path / "rel-codex-home"
    relative.mkdir()
    proc = subprocess.run(
        _call_argv(ns),
        cwd=str(tmp_path),
        env=one.call_env(ns),
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    env = capture.get("env") or {}
    assert env.get("CODEX_HOME") == str(relative), env


def test_release_f7_relative_opencode_config_resolves_against_caller_cwd(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    shutil.copyfile(ns.config, tmp_path / "rel-oc.json")
    one.write_opencode_profiles(tmp_path, opencode_config="rel-oc.json")
    proc = subprocess.run(
        _call_argv(ns),
        cwd=str(tmp_path),
        env=one.call_env(ns, ns.env_extra),
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    rows = one.run_captures_of(ns.capture)
    assert rows, one.captures_of(ns.capture)
    env = rows[0].get("env") or {}
    assert env.get("OPENCODE_CONFIG") == str(tmp_path / "rel-oc.json"), env

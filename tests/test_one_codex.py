from __future__ import annotations

import json
import signal
import subprocess
import time
from pathlib import Path

from tests import one_support as one


def _journal_path(ns) -> Path:
    return ns.state / "journal.jsonl"


def test_one_001_missing_model_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, model=None, codex_home=ns.codex_home)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_001_missing_sandbox_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, sandbox=None, codex_home=ns.codex_home)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_001_missing_codex_home_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, codex_home=None)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_001_bad_sandbox_value_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, sandbox="danger-full-access", codex_home=ns.codex_home)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_001_bad_effort_value_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, effort="maximum", codex_home=ns.codex_home)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_001_tilde_codex_home_expands_to_home(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    tilde_home = ns.home / "tilde-home"
    tilde_home.mkdir()
    one.write_profiles(ns.root, codex_home="~/tilde-home")
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    env = capture.get("env") or {}
    assert Path(env.get("CODEX_HOME", "")) == tilde_home, env.get("CODEX_HOME")


def test_one_003_secret_shaped_env_pass_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path)
    for name in ("DEPLOY_API_KEY", "SERVICE_TOKEN", "AUTH_HEADER_VALUE"):
        one.write_profiles(ns.root, codex_home=ns.codex_home, env_pass=[name])
        proc = one.run_call(ns)
        result = one.result_of(proc)
        assert result.get("exit_class") == "bad_request", (name, result)
        assert not _journal_path(ns).exists(), f"{name} wrote a journal"


def test_one_020_new_session_node_holds_pending_session(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    records = one.records_of(ns.state)
    nodes = one.nodes_of(records)
    assert len(nodes) == 1, nodes
    assert nodes[0].get("session") == {
        "id": None,
        "mode": "new",
        "source": "pending",
    }, nodes[0].get("session")
    assert result.get("session_id") == one.THREAD_ID, result


def test_one_021_captured_thread_id_reaches_session_line_and_result(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("session_id") == one.THREAD_ID, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert len(lines) == 1, lines
    assert lines[0].get("id") == one.THREAD_ID, lines
    assert lines[0].get("source") == "captured", lines


def test_one_022_no_session_id_becomes_session_unknown_harness_error(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        skip_head=1,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX},
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    assert result.get("session_id") is None, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert len(lines) == 1, lines
    assert lines[0].get("id") is None, lines
    assert lines[0].get("source") == "session_unknown", lines


def test_one_023_continue_caller_session_and_resume_argv(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns, session=one.THREAD_ID)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    records = one.records_of(ns.state)
    nodes = one.nodes_of(records)
    assert nodes[0].get("session") == {
        "id": one.THREAD_ID,
        "mode": "continue",
        "source": "caller",
    }, nodes[0].get("session")
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv", [])[-2:] == [one.THREAD_ID, one.PROMPT], capture.get(
        "argv"
    )


def test_one_023_differing_reported_id_journaled_captured(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    caller_id = "0b8e6c01-22cd-4cc0-9a11-314c9f5a1d20"
    proc = one.run_call(ns, session=caller_id)
    result = one.result_of(proc)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert lines, records
    assert lines[-1].get("source") == "captured", lines[-1]
    assert lines[-1].get("id") == one.THREAD_ID, lines[-1]
    assert result.get("session_id") == one.THREAD_ID, result


def test_one_030_new_session_argv_exact(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "exec",
        "-m",
        one.MODEL,
        "-s",
        one.SANDBOX,
        "--skip-git-repo-check",
        "--json",
        one.PROMPT,
    ], capture.get("argv")


def test_one_030_effort_flag_sits_between_model_and_sandbox(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, effort="high")
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "exec",
        "-m",
        one.MODEL,
        "-c",
        'model_reasoning_effort="high"',
        "-s",
        one.SANDBOX,
        "--skip-git-repo-check",
        "--json",
        one.PROMPT,
    ], capture.get("argv")


def test_one_030_resume_argv_exact(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns, session=one.THREAD_ID)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "exec",
        "-s",
        one.SANDBOX,
        "resume",
        "-m",
        one.MODEL,
        "--skip-git-repo-check",
        "--json",
        one.THREAD_ID,
        one.PROMPT,
    ], capture.get("argv")


def test_one_030_output_flag_and_stdin_devnull_and_cwd(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    out = ns.root / "answer.txt"
    proc = one.run_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "exec",
        "-m",
        one.MODEL,
        "-s",
        one.SANDBOX,
        "--skip-git-repo-check",
        "--json",
        "-o",
        str(out),
        one.PROMPT,
    ], capture.get("argv")
    assert capture.get("stdin_is_devnull") is True, capture
    assert capture.get("cwd") == str(ns.root / "work"), capture


def test_one_031_child_env_allow_list_plus_codex_home_and_env_pass(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(
        ns.root, codex_home=ns.codex_home, env_pass=["TRINITY_ONESHOT_MARK"]
    )
    proc = one.run_call(
        ns,
        env_extra={
            "TRINITY_ONESHOT_MARK": "mark-value",
            "TRINITY_DECOY_TOKEN": "decoy-value",
        },
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    env = capture.get("env") or {}
    names = set(env)
    assert "CODEX_HOME" in names, sorted(names)
    assert Path(env.get("CODEX_HOME", "")) == ns.codex_home, env.get("CODEX_HOME")
    assert env.get("TRINITY_ONESHOT_MARK") == "mark-value", env.get(
        "TRINITY_ONESHOT_MARK"
    )
    assert "TRINITY_DECOY_TOKEN" not in names, sorted(names)
    allowed = (
        one.ALLOWED_ENV | one.PLATFORM_ENV | {"CODEX_HOME", "TRINITY_ONESHOT_MARK"}
    )
    leaked = [n for n in names if n not in allowed and not n.startswith("LC_")]
    assert leaked == [], sorted(leaked)


def test_one_032_final_answer_is_last_agent_message(tmp_path):
    extra = {
        "type": "item.completed",
        "item": {"id": "item_9", "type": "agent_message", "text": one.FINAL_MARK},
    }
    lines = (one.FIXTURES / "codex-new.jsonl").read_text().splitlines()
    fixture = tmp_path / "codex-extra-agent-message.jsonl"
    fixture.write_text("\n".join([*lines[:-1], json.dumps(extra), lines[-1]]) + "\n")
    ns = one.make_root(
        tmp_path,
        stdout_fixture=fixture,
        write_output=False,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX},
    )
    out = ns.root / "answer.txt"
    proc = one.run_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert out.exists(), "the -o file was not written"
    assert out.read_text() == one.FINAL_MARK, out.read_text()


def test_one_033_usage_maps_codex_turn_completed_fields(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    expected = {
        "input_tokens": 18947,
        "output_tokens": 8,
        "cache_read_input_tokens": 16128,
        "cache_creation_input_tokens": 0,
    }
    assert result.get("usage") == expected, result.get("usage")
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert states, records
    assert states[-1].get("usage") == expected, states[-1].get("usage")


def test_one_033_no_turn_completed_leaves_usage_absent(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        skip_tail=1,
        write_output=True,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX},
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("usage") is None, result
    assert result.get("session_id") == one.THREAD_ID, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert states, records
    assert states[-1].get("usage") is None, states[-1]


def test_one_034_bad_resume_stderr_is_session_not_found(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-bad-resume.jsonl",
        stderr_text=(one.FIXTURES / "codex-bad-resume.stderr.txt").read_text(),
        rc=1,
    )
    proc = one.run_call(ns, session=one.THREAD_ID)
    result = one.result_of(proc)
    assert result.get("exit_class") == "session_not_found", (result, proc.stderr)


def test_one_034_auth_marker_stderr_is_auth_error(tmp_path):
    ns = one.make_root(tmp_path, stderr_text="Error: 401 unauthorized\n", rc=1)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "auth_error", (result, proc.stderr)


def test_one_034_quota_marker_stderr_is_quota_exhausted(tmp_path):
    ns = one.make_root(tmp_path, stderr_text="Error: usage limit reached\n", rc=1)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "quota_exhausted", (result, proc.stderr)


def test_one_034_turn_failed_event_is_harness_error(tmp_path):
    failed = {"type": "turn.failed", "error": {"message": "provider exploded"}}
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        extra_event=failed,
        skip_tail=1,
        write_output=True,
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)


def test_one_034_nonzero_exit_without_markers_is_unknown(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        stderr_text="Error: something broke\n",
        rc=2,
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "unknown", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert lines and lines[-1].get("id") == one.THREAD_ID, lines


def test_one_034_ok_with_completed_turn_and_matching_rollout(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)


def test_one_034_time_limit_kills_harness_and_reports_timeout(tmp_path):
    pid_file = tmp_path / "harness.pid"
    child_pid_file = tmp_path / "harness-child.pid"
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        sleep_s=30,
        pid_file=pid_file,
        child_pid_file=child_pid_file,
    )
    proc = one.run_call(ns, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    assert pid_file.exists(), "the harness never wrote its pid file"
    assert child_pid_file.exists(), "the harness child never wrote its pid file"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (
        one.pid_is_live(pid_file) or one.pid_is_live(child_pid_file)
    ):
        time.sleep(0.1)
    assert not one.pid_is_live(pid_file), "the harness outlived its time limit"
    assert not one.pid_is_live(child_pid_file), (
        "the harness child outlived its time limit"
    )


def test_one_034_interrupt_reports_interrupted(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        sleep_s=30,
    )
    proc = subprocess.Popen(
        [
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
        ],
        cwd=str(one.REPO),
        env=one.call_env(ns),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while (
        time.monotonic() < deadline and not ns.capture.exists() and proc.poll() is None
    ):
        time.sleep(0.05)
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=20)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert states, records
    assert states[-1].get("exit_class") == "interrupted", states[-1]


def test_one_035_model_mismatch_is_harness_error_with_error_line(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
        rollout={"model": "other-model", "sandbox": one.SANDBOX},
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    run_id = one.run_id_of(records)
    entries = one.error_lines_of(ns.state)
    assert any(
        entry.get("error") == "model_mismatch"
        and entry.get("run") == run_id
        and entry.get("node") == node_id
        for entry in entries
    ), entries


def test_one_035_sandbox_mismatch_is_harness_error_with_error_line(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
        rollout={"model": one.MODEL, "sandbox": "workspace-write"},
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    run_id = one.run_id_of(records)
    entries = one.error_lines_of(ns.state)
    assert any(
        entry.get("error") == "sandbox_mismatch"
        and entry.get("run") == run_id
        and entry.get("node") == node_id
        for entry in entries
    ), entries


def test_one_035_missing_rollout_is_readback_missing(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    run_id = one.run_id_of(records)
    entries = one.error_lines_of(ns.state)
    assert any(
        entry.get("error") == "readback_missing"
        and entry.get("run") == run_id
        and entry.get("node") == node_id
        for entry in entries
    ), entries


def test_one_035_rollout_without_turn_context_is_readback_missing(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX, "no_turn_context": True},
    )
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    run_id = one.run_id_of(records)
    entries = one.error_lines_of(ns.state)
    assert any(
        entry.get("error") == "readback_missing"
        and entry.get("run") == run_id
        and entry.get("node") == node_id
        for entry in entries
    ), entries


def test_one_040_missing_codex_home_dir_is_profile_refused(tmp_path):
    ns = one.make_root(tmp_path, codex_home_created=False, **one.OK_FAKE)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert states[-1].get("exit_class") == "profile_refused", states[-1]
    assert not ns.capture.exists(), "the harness started despite preflight"


def test_one_040_binary_not_on_path_is_profile_refused(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, binary="no-such-codex-bin")
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert not ns.capture.exists(), "the harness started despite preflight"

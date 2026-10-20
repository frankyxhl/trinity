from __future__ import annotations

import signal
import subprocess
import time

from tests import one_support as one


def _journal_path(ns):
    return ns.state / "journal.jsonl"


def test_one_002_missing_model_is_bad_request(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    one.write_opencode_profiles(ns.root, model=None, opencode_config=ns.config)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_002_missing_opencode_config_is_bad_request(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    one.write_opencode_profiles(ns.root, opencode_config=None)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a refused profile wrote a journal"


def test_one_020_new_session_node_holds_pending_session(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    records = one.records_of(ns.state)
    nodes = one.nodes_of(records)
    assert len(nodes) == 1, nodes
    assert nodes[0].get("session") == {
        "id": None,
        "mode": "new",
        "source": "pending",
    }, nodes[0].get("session")


def test_one_021_captured_session_id_reaches_session_line_and_result(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("session_id") == one.OC_SESSION, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert len(lines) == 1, lines
    assert lines[0].get("id") == one.OC_SESSION, lines
    assert lines[0].get("source") == "captured", lines


def test_one_022_no_session_id_becomes_session_unknown_harness_error(tmp_path):
    ns = one.make_opencode_root(tmp_path, strip_session_id=True, seed_rows=None)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    assert result.get("session_id") is None, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert len(lines) == 1, lines
    assert lines[0].get("id") is None, lines
    assert lines[0].get("source") == "session_unknown", lines


def test_one_023_continue_caller_session_and_run_argv(tmp_path):
    ns = one.make_opencode_root(
        tmp_path, run_fixture=one.FIXTURES / "opencode-resume.jsonl"
    )
    proc = one.run_oc_call(ns, session=one.OC_SESSION)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    records = one.records_of(ns.state)
    nodes = one.nodes_of(records)
    assert nodes[0].get("session") == {
        "id": one.OC_SESSION,
        "mode": "continue",
        "source": "caller",
    }, nodes[0].get("session")
    argv = one.run_captures_of(ns.capture)[0].get("argv")
    assert argv[-5:-3] == ["-s", one.OC_SESSION], argv


def test_one_023_differing_reported_id_journaled_captured(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    caller_id = "ses_caller_00000000000000000001"
    proc = one.run_oc_call(ns, session=caller_id)
    result = one.result_of(proc)
    assert result.get("session_id") == one.OC_SESSION, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert lines, records
    assert lines[-1].get("source") == "captured", lines[-1]
    assert lines[-1].get("id") == one.OC_SESSION, lines[-1]


def test_one_041_model_not_in_models_output_is_refused_with_check_line(tmp_path):
    ns = one.make_opencode_root(tmp_path, model="opencode-go/no-such-model")
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    checks = [
        r for r in records if r.get("kind") == "check" and r.get("check") == "model"
    ]
    assert checks and checks[-1].get("decision") == "refused", records
    assert one.run_captures_of(ns.capture) == [], "the run started despite preflight"


def test_one_041_missing_config_file_is_profile_refused(tmp_path):
    ns = one.make_opencode_root(tmp_path, opencode_config=False)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert not ns.capture.exists() or one.run_captures_of(ns.capture) == [], (
        "the run started despite preflight"
    )


def test_one_041_binary_not_on_path_is_profile_refused(tmp_path):
    ns = one.make_opencode_root(tmp_path, binary="no-such-opencode-bin")
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert not ns.capture.exists(), "the harness started despite preflight"


def test_one_050_new_session_run_argv_exact(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.run_captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "run",
        "--format",
        "json",
        "-m",
        one.OC_MODEL,
        "--dir",
        str(ns.work),
        one.PROMPT,
    ], capture.get("argv")
    assert capture.get("stdin_is_devnull") is True, capture


def test_one_050_variant_flag_sits_after_model(tmp_path):
    ns = one.make_opencode_root(tmp_path, variant=one.OC_VARIANT)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.run_captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "run",
        "--format",
        "json",
        "-m",
        one.OC_MODEL,
        "--variant",
        one.OC_VARIANT,
        "--dir",
        str(ns.work),
        one.PROMPT,
    ], capture.get("argv")


def test_one_050_resume_argv_exact(tmp_path):
    ns = one.make_opencode_root(
        tmp_path, run_fixture=one.FIXTURES / "opencode-resume.jsonl"
    )
    proc = one.run_oc_call(ns, session=one.OC_SESSION)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.run_captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "run",
        "--format",
        "json",
        "-m",
        one.OC_MODEL,
        "-s",
        one.OC_SESSION,
        "--dir",
        str(ns.work),
        one.PROMPT,
    ], capture.get("argv")


def test_one_051_child_env_allow_list_plus_config_and_xdg(tmp_path):
    ns = one.make_opencode_root(tmp_path, env_pass=["TRINITY_ONESHOT_MARK"])
    proc = one.run_oc_call(
        ns,
        env_extra={
            "TRINITY_ONESHOT_MARK": "mark-value",
            "TRINITY_DECOY_TOKEN": "decoy-value",
        },
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.run_captures_of(ns.capture)[0]
    env = capture.get("env") or {}
    names = set(env)
    assert env.get("OPENCODE_CONFIG") == str(ns.config), env.get("OPENCODE_CONFIG")
    assert env.get("XDG_DATA_HOME") == str(ns.xdg_data), env.get("XDG_DATA_HOME")
    assert env.get("XDG_CONFIG_HOME") == str(ns.xdg_config), env.get("XDG_CONFIG_HOME")
    assert env.get("TRINITY_ONESHOT_MARK") == "mark-value", env.get(
        "TRINITY_ONESHOT_MARK"
    )
    assert "TRINITY_DECOY_TOKEN" not in names, sorted(names)
    allowed = (
        one.ALLOWED_ENV
        | one.PLATFORM_ENV
        | {
            "OPENCODE_CONFIG",
            "XDG_DATA_HOME",
            "XDG_CONFIG_HOME",
            "TRINITY_ONESHOT_MARK",
        }
    )
    leaked = [n for n in names if n not in allowed and not n.startswith("LC_")]
    assert leaked == [], sorted(leaked)


def test_one_052_output_file_gets_text_after_last_step_start(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    out = ns.root / "answer.txt"
    proc = one.run_oc_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert out.exists(), "the --output file was not written"
    assert out.read_text() == "PROBE-OK", out.read_text()


def test_one_052_concatenates_text_parts_after_last_step_start(tmp_path):
    extra = {
        "type": "text",
        "sessionID": one.OC_SESSION,
        "part": {"type": "text", "text": "\nMORE"},
    }
    ns = one.make_opencode_root(tmp_path, extra_event=extra)
    out = ns.root / "answer.txt"
    proc = one.run_oc_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert out.exists(), "the --output file was not written"
    assert out.read_text() == "PROBE-OK\nMORE", out.read_text()


def test_one_053_usage_sums_step_finish_fields(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    expected = {
        "input_tokens": 10032,
        "output_tokens": 5,
        "tokens": 11701,
        "cache_read_input_tokens": 1664,
        "cache_creation_input_tokens": 0,
        "cost_usd": 0.001512792,
    }
    assert result.get("usage") == expected, result.get("usage")
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert states, records
    assert states[-1].get("usage") == expected, states[-1].get("usage")


def test_one_053_no_step_finish_leaves_usage_absent(tmp_path):
    ns = one.make_opencode_root(tmp_path, skip_tail=1, seed_rows=None)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("usage") is None, result
    assert result.get("session_id") == one.OC_SESSION, result


def test_one_054_stop_finish_with_matching_db_is_ok(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)


def test_one_054_session_not_found_stderr_is_session_not_found(tmp_path):
    ns = one.make_opencode_root(
        tmp_path,
        run_fixture=None,
        stderr_text=(one.FIXTURES / "opencode-bad-session.stderr.txt").read_text(),
        rc=1,
    )
    proc = one.run_oc_call(ns, session="ses_unknown_0000000000000000001")
    result = one.result_of(proc)
    assert result.get("exit_class") == "session_not_found", (result, proc.stderr)


def test_one_054_error_event_without_marker_is_unknown(tmp_path):
    ns = one.make_opencode_root(
        tmp_path, run_fixture=one.FIXTURES / "opencode-bad-model.jsonl", rc=1
    )
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "unknown", (result, proc.stderr)
    assert result.get("session_id") == "ses_ea6b67225ffeQME2XU4FmlGOpP", result


def test_one_054_error_event_auth_marker_is_auth_error(tmp_path):
    extra = {
        "type": "error",
        "sessionID": one.OC_SESSION,
        "error": {"name": "AuthError", "data": {"message": "401 unauthorized"}},
    }
    ns = one.make_opencode_root(tmp_path, extra_event=extra)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "auth_error", (result, proc.stderr)


def test_one_054_error_event_quota_marker_is_quota_exhausted(tmp_path):
    extra = {
        "type": "error",
        "sessionID": one.OC_SESSION,
        "error": {
            "name": "RateLimitError",
            "data": {"message": "429 rate limit exceeded"},
        },
    }
    ns = one.make_opencode_root(tmp_path, extra_event=extra)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "quota_exhausted", (result, proc.stderr)


def test_one_054_permission_rejected_is_harness_error_with_error_line(tmp_path):
    ns = one.make_opencode_root(
        tmp_path,
        run_fixture=one.FIXTURES / "opencode-permission-rejected.jsonl",
        stderr_text=(
            one.FIXTURES / "opencode-permission-rejected.stderr.txt"
        ).read_text(),
        seed_rows=None,
    )
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    run_id = one.run_id_of(records)
    entries = one.error_lines_of(ns.state)
    assert any(
        entry.get("error") == "permission_rejected"
        and entry.get("run") == run_id
        and entry.get("node") == node_id
        for entry in entries
    ), entries


def test_one_054_tool_calls_finish_is_harness_error(tmp_path):
    extra = {
        "type": "step_finish",
        "sessionID": one.OC_SESSION,
        "part": {
            "type": "step-finish",
            "reason": "tool-calls",
            "tokens": {
                "total": 1,
                "input": 1,
                "output": 0,
                "cache": {"write": 0, "read": 0},
            },
            "cost": 0,
        },
    }
    ns = one.make_opencode_root(tmp_path, extra_event=extra, seed_rows=None)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "harness_error", (result, proc.stderr)


def test_one_054_no_step_finish_is_unknown(tmp_path):
    ns = one.make_opencode_root(tmp_path, skip_tail=1, seed_rows=None)
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "unknown", (result, proc.stderr)
    assert result.get("session_id") == one.OC_SESSION, result


def test_one_054_time_limit_reports_timeout(tmp_path):
    pid_file = tmp_path / "harness.pid"
    child_pid_file = tmp_path / "harness-child.pid"
    ns = one.make_opencode_root(
        tmp_path,
        sleep_s=30,
        seed_rows=None,
        pid_file=pid_file,
        child_pid_file=child_pid_file,
    )
    proc = one.run_oc_call(ns, args=("--time-s", "1"))
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


def test_one_054_interrupt_reports_interrupted(tmp_path):
    ns = one.make_opencode_root(tmp_path, sleep_s=30, seed_rows=None)
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
            str(ns.work),
        ],
        cwd=str(one.REPO),
        env=one.call_env(ns, ns.env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def run_started():
        if not ns.capture.exists():
            return 0
        return len(
            [
                line
                for line in ns.capture.read_text().splitlines()
                if '"argv": ["run"' in line
            ]
        )

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and run_started() < 1 and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=20)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert states, records
    assert states[-1].get("exit_class") == "interrupted", states[-1]


def test_one_055_matching_db_row_is_ok(tmp_path):
    ns = one.make_opencode_root(tmp_path, seed_rows="match")
    proc = one.run_oc_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)


def test_one_055_model_mismatch_is_harness_error_with_error_line(tmp_path):
    ns = one.make_opencode_root(tmp_path, seed_rows="mismatch")
    proc = one.run_oc_call(ns)
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


def test_one_055_missing_row_is_readback_missing(tmp_path):
    ns = one.make_opencode_root(tmp_path, seed_rows="other")
    proc = one.run_oc_call(ns)
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


def test_one_055_missing_database_is_readback_missing(tmp_path):
    ns = one.make_opencode_root(tmp_path, seed_rows=None)
    proc = one.run_oc_call(ns)
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

from __future__ import annotations

import json
import stat
import subprocess

import pytest

from tests import one_support as one

RESULT_KEYS = {
    "run",
    "node",
    "exit_class",
    "session_id",
    "output_kind",
    "output_ref",
    "transcript_ref",
    "usage",
    "ended_at",
    "journal_complete",
}

NONFINITE_TOKENS = {
    "NaN": float("nan"),
    "Infinity": float("inf"),
    "-Infinity": float("-inf"),
}


def _prompt_file_call(ns, *files):
    cmd = [
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
    ]
    for path in files:
        cmd.extend(["--prompt-file", str(path)])
    cmd.extend(["--cwd", str(ns.root / "work")])
    return subprocess.run(
        cmd,
        cwd=str(one.REPO),
        env=one.call_env(ns),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_release_f2_prompt_files_keep_crlf_bytes(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    f1 = tmp_path / "f1.txt"
    f1.write_bytes(b"a\r\nb\r")
    f2 = tmp_path / "f2.txt"
    f2.write_bytes(b"\r\nc")
    proc = _prompt_file_call(ns, f1, f2)
    rows = one.captures_of(ns.capture)
    assert rows[-1]["argv"][-1] == "a\r\nb\r\r\nc", (
        rows[-1]["argv"],
        proc.stdout,
        proc.stderr,
    )


@pytest.mark.parametrize(
    ("value", "key"),
    [
        (value, key)
        for value in ("NaN", "Infinity", "-Infinity")
        for key in ("level", "free_pct", "swap_mb", "load5")
    ],
)
def test_release_f5_nan_reading_is_refused(tmp_path, value, key):
    fields = {"level": 1, "free_pct": 90, "swap_mb": 0, "load5": 1}
    fields[key] = NONFINITE_TOKENS[value]
    readings = tmp_path / "readings.json"
    readings.write_text(json.dumps(fields))
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, gate="light")
    proc = one.run_call(ns, env_extra=one.gate_env(readings), timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "check_failed", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert [c.get("decision") for c in checks] == ["refused"], checks
    assert not ns.capture.exists(), "the harness ran despite a refused reading"


@pytest.mark.parametrize(
    "case",
    ["codex_auth", "codex_unknown", "opencode_unknown"],
)
def test_release_f6_missing_session_writes_session_unknown(tmp_path, case):
    if case == "opencode_unknown":
        ns = one.make_opencode_root(tmp_path, strip_session_id=True, rc=1)
        proc = one.run_oc_call(ns, timeout=30)
    else:
        ns = one.make_root(
            tmp_path,
            stdout_fixture=one.FIXTURES / "codex-new.jsonl",
            skip_head=1,
            stderr_text="error: 401 Unauthorized" if case == "codex_auth" else "",
            rc=1 if case == "codex_auth" else 2,
        )
        proc = one.run_call(ns, timeout=30)
    result = one.result_of(proc)
    if case == "codex_auth":
        assert result.get("exit_class") == "auth_error", (result, proc.stderr)
    elif case == "codex_unknown":
        assert result.get("exit_class") == "unknown", (result, proc.stderr)
    else:
        assert result.get("exit_class") != "ok", (result, proc.stderr)
    assert result.get("session_id") is None, result
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    lines = one.session_lines_of(records, node_id)
    assert len(lines) == 1, lines
    assert lines[0].get("source") == "session_unknown", lines
    assert lines[0].get("id") is None, lines


def test_release_f8_refused_gate_writes_gate_txt(tmp_path):
    readings = tmp_path / "readings.json"
    readings.write_text('{"level": 1, "free_pct": 90, "swap_mb": 0}')
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, gate="light")
    logs = tmp_path / "logs"
    proc = one.run_call(
        ns,
        args=("--log-dir", str(logs)),
        env_extra=one.gate_env(readings),
        timeout=30,
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "check_failed", (result, proc.stderr)
    gate_txt = logs / "gate.txt"
    assert gate_txt.exists(), f"gate.txt missing in {logs}"
    lines = gate_txt.read_text().splitlines()
    assert len(lines) == 1, lines
    line = lines[0]
    for field in ("gate=light", "level=na", "free=na", "swap_mb=na", "load5=na"):
        assert field in line, lines
    assert line.endswith("decision=refused"), lines


@pytest.mark.parametrize(
    "name",
    ["start", "end", "rc.txt", "out.jsonl", "err.txt", "gate.txt"],
)
def test_release_f12_log_file_symlink_is_not_followed(tmp_path, name):
    logs = tmp_path / "logs"
    logs.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("KEEP")
    victim_mode = stat.S_IMODE(victim.stat().st_mode)
    (logs / name).symlink_to(victim)
    if name == "gate.txt":
        readings = tmp_path / "readings.json"
        readings.write_text(
            json.dumps({"level": 1, "free_pct": 90, "swap_mb": 0, "load5": 1})
        )
        ns = one.make_root(tmp_path, **one.OK_FAKE)
        one.write_profiles(ns.root, codex_home=ns.codex_home, gate="light")
        proc = one.run_call(
            ns,
            args=("--log-dir", str(logs)),
            env_extra=one.gate_env(readings),
            timeout=30,
        )
    else:
        ns = one.make_root(tmp_path, **one.OK_FAKE)
        proc = one.run_call(ns, args=("--log-dir", str(logs)), timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert victim.read_text() == "KEEP", victim.read_text()
    assert stat.S_IMODE(victim.stat().st_mode) == victim_mode, (
        oct(stat.S_IMODE(victim.stat().st_mode)),
        oct(victim_mode),
    )
    rows = one.error_lines_of(ns.state)
    assert any(r.get("error") == "log_unwritable" for r in rows), rows


@pytest.mark.parametrize("name", ["journal.jsonl", "error.log"])
def test_release_f13_output_into_journal_is_bad_request(tmp_path, name):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns, args=("--output", str(ns.state / name)), timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not ns.capture.exists(), "the harness started on a bad request"
    assert not (ns.state / name).exists(), "the journal was written"


@pytest.mark.parametrize("name", ["journal.jsonl", "error.log"])
def test_release_f13_output_alias_into_journal_is_bad_request(tmp_path, name):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    ns.state.mkdir()
    alias = tmp_path / "alias.jsonl"
    alias.symlink_to(ns.state / name)
    proc = one.run_call(ns, args=("--output", str(alias)), timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not ns.capture.exists(), "the harness started on a bad request"


def test_release_f14_log_dir_is_a_file_is_bad_request(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.write_text("original")
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns, args=("--log-dir", str(log_dir)), timeout=30)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    out_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(out_lines) == 1, (proc.stdout, proc.stderr)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not ns.capture.exists(), "the harness started on a bad request"
    assert log_dir.read_text() == "original", log_dir.read_text()


def test_release_f14_log_write_failure_keeps_result(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "rc.txt").mkdir()
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(ns, args=("--log-dir", str(logs)), timeout=30)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert set(result) == RESULT_KEYS, sorted(result)
    rows = one.error_lines_of(ns.state)
    assert any(r.get("error") == "log_unwritable" for r in rows), rows
    stderr_lines = [line for line in proc.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) == 1, proc.stderr

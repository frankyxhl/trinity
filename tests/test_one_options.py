from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from tests import one_support as one

RESULT_TEXT = "CLAUDE-RESULT-TEXT"
USAGE = {"input_tokens": 100, "output_tokens": 5, "tokens": 105}
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
EXPECTED_RESULT = {
    "run": "<run>",
    "node": "<node>",
    "exit_class": "ok",
    "session_id": "<sid>",
    "output_kind": "none",
    "output_ref": None,
    "transcript_ref": None,
    "usage": USAGE,
    "ended_at": "<t>",
    "journal_complete": True,
}
EXPECTED_GUARD = {
    "run": "<run>",
    "node": "<node>",
    "depth": 0,
    "max_depth": 0,
    "journal_root": "<tmp>/state",
}
EXPECTED_JOURNAL = [
    {"v": 1, "kind": "run", "run": "<run>", "event": "start", "t": "<t>"},
    {
        "v": 1,
        "kind": "node",
        "run": "<run>",
        "node": "<node>",
        "parent": None,
        "step": "root",
        "round": 1,
        "label": "root",
        "depth": 0,
        "harness": "claude-code",
        "profile": "cx",
        "profile_reason": "named",
        "model": "claude-sonnet-4-5",
        "stall_limit_s": 660.0,
        "session": {"id": "<sid>", "mode": "new", "source": "assigned"},
        "t": "<t>",
    },
    {
        "v": 1,
        "kind": "state",
        "run": "<run>",
        "node": "<node>",
        "state": "queued",
        "t": "<t>",
    },
    {
        "v": 1,
        "kind": "state",
        "run": "<run>",
        "node": "<node>",
        "state": "running",
        "t": "<t>",
    },
    {
        "v": 1,
        "kind": "state",
        "run": "<run>",
        "node": "<node>",
        "state": "done",
        "exit_class": "ok",
        "output_kind": "none",
        "wall_s": "<wall>",
        "usage": {"input_tokens": 100, "output_tokens": 5, "tokens": 105},
        "t": "<t>",
    },
    {"v": 1, "kind": "run", "run": "<run>", "event": "end", "t": "<t>"},
]


def _normalize(value, tmp_path, generated):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in ("t", "ended_at"):
                out[key] = "<t>"
            elif key == "wall_s":
                out[key] = "<wall>"
            else:
                out[key] = _normalize(item, tmp_path, generated)
        return out
    if isinstance(value, list):
        return [_normalize(item, tmp_path, generated) for item in value]
    if isinstance(value, str):
        for placeholder, marker in generated.items():
            if marker and value == marker:
                return placeholder
        for placeholder, marker in generated.items():
            if marker and marker in value:
                value = value.replace(marker, placeholder)
        value = value.replace(str(tmp_path), "<tmp>")
        home = os.environ.get("HOME", "")
        if home:
            value = value.replace(home, "<home>")
        return value
    return value


def _journal_path(ns) -> Path:
    return ns.state / "journal.jsonl"


def run_raw(ns, *, prompt_args=(), args=(), env_extra=None, timeout=30):
    return subprocess.run(
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
            *prompt_args,
            "--cwd",
            str(ns.root / "work"),
            *args,
        ],
        cwd=str(one.REPO),
        env=one.call_env(ns, env_extra),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _secret() -> str:
    return "-".join(["sk", "A" * 24])


def _write_claude_wrapper(bin_dir: Path, capture: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    constants = "\n".join(
        [
            f"CAPTURE = {str(capture)!r}",
            f"RESULT_TEXT = {RESULT_TEXT!r}",
            f"USAGE = {USAGE!r}",
        ]
    )
    body = """
import json, os, stat, sys
from pathlib import Path

CAPTURE = Path(CAPTURE)

argv = sys.argv[1:]
try:
    stdin_devnull = (
        stat.S_ISCHR(os.fstat(0).st_mode)
        and os.fstat(0).st_rdev == os.stat("/dev/null").st_rdev
    )
except OSError:
    stdin_devnull = False
CAPTURE.parent.mkdir(parents=True, exist_ok=True)
with CAPTURE.open("a") as fh:
    fh.write(
        json.dumps(
            {
                "argv": argv,
                "env": dict(os.environ),
                "cwd": os.getcwd(),
                "stdin_is_devnull": stdin_devnull,
            }
        )
        + "\\n"
    )
session_id = None
for i, a in enumerate(argv):
    if a == "--session-id" and i + 1 < len(argv):
        session_id = argv[i + 1]
sys.stdout.write(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": session_id,
            "result": RESULT_TEXT,
            "usage": USAGE,
        }
    )
    + "\\n"
)
"""
    stub = bin_dir / "claude-code"
    stub.write_text("#!" + sys.executable + "\n" + constants + "\n" + body)
    stub.chmod(0o755)
    return stub


def _write_claude_profiles(root: Path) -> Path:
    profile = {
        "name": one.PROFILE,
        "adapter": "claude-code",
        "provider": "claude-code",
        "billing": "subscription",
        "model": "claude-sonnet-4-5",
        "credential_source": {"wrapper": "claude-code"},
        "transcript_retention": "30 days",
        "enabled": True,
    }
    path = root / "profiles.json"
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


def _claude_root(tmp_path: Path) -> SimpleNamespace:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "work").mkdir()
    capture = tmp_path / "capture" / "claude-code.jsonl"
    _write_claude_wrapper(tmp_path / "bin", capture)
    profiles = _write_claude_profiles(tmp_path)
    return SimpleNamespace(
        root=tmp_path,
        home=home,
        capture=capture,
        profiles=profiles,
        state=tmp_path / "state",
    )


def test_one_010_prompt_and_prompt_file_together_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("file text")
    proc = run_raw(
        ns, prompt_args=("--prompt", "inline", "--prompt-file", str(prompt_file))
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a rejected call wrote a journal"


def test_one_010_no_prompt_form_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = run_raw(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a rejected call wrote a journal"
    good = one.run_call(ns)
    good_result = one.result_of(good)
    assert good_result.get("exit_class") == "ok", (good_result, good.stderr)


def test_one_010_missing_prompt_file_is_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = run_raw(ns, prompt_args=("--prompt-file", str(tmp_path / "nope.txt")))
    result = one.result_of(proc)
    assert result.get("exit_class") == "bad_request", (result, proc.stderr)
    assert not _journal_path(ns).exists(), "a rejected call wrote a journal"
    present = tmp_path / "prompt.txt"
    present.write_text("file text")
    good = run_raw(ns, prompt_args=("--prompt-file", str(present)))
    good_result = one.result_of(good)
    assert good_result.get("exit_class") == "ok", (good_result, good.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv", [""])[-1] == "file text", capture.get("argv")


def test_one_010_prompt_files_join_in_order_as_bytes(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("héllo\n", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    proc = run_raw(
        ns, prompt_args=("--prompt-file", str(first), "--prompt-file", str(second))
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv", [""])[-1] == "héllo\nbeta", capture.get("argv")


def test_one_011_output_file_holds_final_answer(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    out = tmp_path / "answer.txt"
    proc = one.run_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert result.get("output_kind") == "file", result
    assert result.get("output_ref") == str(out), result
    assert out.exists(), "the output file was not written"
    assert out.read_text(encoding="utf-8") == "PROBE-OK"
    capture = one.captures_of(ns.capture)[0]
    argv = capture.get("argv") or []
    assert "-o" in argv and argv[argv.index("-o") + 1] == str(out), argv
    assert "PROBE-OK" not in _journal_path(ns).read_text(encoding="utf-8")


def test_one_011_no_final_answer_keeps_output_kind_none(tmp_path):
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        skip_tail=2,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX},
    )
    out = tmp_path / "answer.txt"
    proc = one.run_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "unknown", (result, proc.stderr)
    assert result.get("output_kind") == "none", result
    assert result.get("session_id") == one.THREAD_ID, result
    assert not out.exists(), "an output file exists without a final answer"


def test_one_011_claude_code_output_holds_result_text(tmp_path):
    ns = _claude_root(tmp_path)
    out = tmp_path / "claude-answer.txt"
    proc = one.run_call(ns, args=("--output", str(out)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert result.get("output_kind") == "file", result
    assert out.exists(), "the output file was not written"
    assert out.read_text(encoding="utf-8") == RESULT_TEXT


def test_one_012_log_dir_holds_redacted_files_mode_600(tmp_path):
    marker = _secret()
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
        rollout={"model": one.MODEL, "sandbox": one.SANDBOX},
        stderr_text="boom " + marker,
    )
    log_dir = tmp_path / "logs"
    proc = one.run_call(ns, args=("--log-dir", str(log_dir)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    for name in ("start", "end", "rc.txt", "out.jsonl", "err.txt"):
        path = log_dir / name
        assert path.exists(), f"missing {name} in the log dir"
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, (name, oct(mode))
    assert abs(float((log_dir / "start").read_text()) - time.time()) < 300
    assert abs(float((log_dir / "end").read_text()) - time.time()) < 300
    assert (log_dir / "rc.txt").read_text().strip() == "rc=0"
    out_lines = (log_dir / "out.jsonl").read_text().splitlines()
    assert out_lines, "out.jsonl is empty"
    assert json.loads(out_lines[0]).get("type") == "thread.started", out_lines[0]
    err = (log_dir / "err.txt").read_text(encoding="utf-8")
    assert "boom" in err, err
    assert marker not in err, "the secret survived redaction in err.txt"


def test_one_012_rc_none_when_no_harness_starts(tmp_path):
    ns = one.make_root(tmp_path, codex_home_created=False, **one.OK_FAKE)
    log_dir = tmp_path / "logs"
    proc = one.run_call(ns, args=("--log-dir", str(log_dir)))
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    rc = log_dir / "rc.txt"
    assert rc.exists(), "rc.txt missing from the log dir"
    assert rc.read_text().strip() == "rc=none", rc.read_text()
    assert not ns.capture.exists(), "the harness started despite preflight"


def test_one_012_gate_txt_records_latest_reading(tmp_path):
    readings = tmp_path / "readings.json"
    readings.write_text(
        json.dumps({"level": 1, "free_pct": 90, "swap_mb": 100, "load5": 1.5})
    )
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    log_dir = tmp_path / "logs"
    proc = one.run_call(
        ns, args=("--log-dir", str(log_dir)), env_extra=one.gate_env(readings)
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    gate_txt = log_dir / "gate.txt"
    assert gate_txt.exists(), "gate.txt missing from the log dir"
    mode = stat.S_IMODE(gate_txt.stat().st_mode)
    assert mode == 0o600, oct(mode)
    line = gate_txt.read_text().strip()
    assert re.fullmatch(
        r"gate=light level=1 free=\d+(\.\d+)? swap_mb=\d+(\.\d+)? "
        r"load5=\d+(\.\d+)? decision=go",
        line,
    ), line


def test_one_012_stdout_secret_is_redacted_in_out_jsonl(tmp_path):
    marker = _secret()
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        extra_event={"type": "note", "text": "boom " + marker},
    )
    log_dir = tmp_path / "logs"
    one.run_call(ns, args=("--log-dir", str(log_dir)))
    out = log_dir / "out.jsonl"
    assert out.exists(), "out.jsonl missing from the log dir"
    text = out.read_text(encoding="utf-8")
    assert "boom" in text, text
    assert marker not in text, "the secret survived redaction in out.jsonl"


def test_one_013_zero_and_negative_time_s_are_bad_request(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    for value in ("0", "-3"):
        proc = one.run_call(ns, args=(f"--time-s={value}",))
        result = one.result_of(proc)
        assert result.get("exit_class") == "bad_request", (value, result, proc.stderr)
        assert not _journal_path(ns).exists(), f"time-s {value} wrote a journal"


def test_one_013_time_s_bounds_the_call(tmp_path):
    pid_file = tmp_path / "harness.pid"
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        sleep_s=30,
        pid_file=pid_file,
    )
    proc = one.run_call(ns, args=("--time-s", "1"), timeout=20)
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    assert ns.capture.exists(), "the harness never started"


def test_one_014_gate_none_overrides_profile_gate(tmp_path):
    readings = tmp_path / "readings.json"
    readings.write_text(
        json.dumps({"level": 4, "free_pct": 1, "swap_mb": 9000, "load5": 99})
    )
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="heavy", codex_home=ns.codex_home)
    proc = one.run_call(ns, args=("--gate", "none"), env_extra=one.gate_env(readings))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert one.gate_checks(one.records_of(ns.state)) == [], "the gate still ran"
    assert ns.capture.exists(), "the harness never ran"


def test_one_014_gate_light_override_enables_gate(tmp_path):
    readings = tmp_path / "readings.json"
    readings.write_text(
        json.dumps({"level": 4, "free_pct": 90, "swap_mb": 0, "load5": 1})
    )
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = one.run_call(
        ns,
        args=("--gate", "light", "--time-s", "1"),
        env_extra=one.gate_env(readings),
    )
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started through a blocked gate"


def test_one_015_model_override_reaches_harness_and_node(tmp_path):
    new_model = "gpt-6.2-codex"
    ns = one.make_root(
        tmp_path,
        stdout_fixture=one.FIXTURES / "codex-new.jsonl",
        write_output=True,
        rollout={"model": new_model, "sandbox": one.SANDBOX},
    )
    proc = one.run_call(ns, args=("--model", new_model))
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    capture = one.captures_of(ns.capture)[0]
    argv = capture.get("argv") or []
    assert "-m" in argv and argv[argv.index("-m") + 1] == new_model, argv
    nodes = one.nodes_of(one.records_of(ns.state))
    assert nodes and nodes[0].get("model") == new_model, nodes


def test_one_015_opencode_model_override_is_checked(tmp_path):
    ns = one.make_opencode_root(tmp_path)
    proc = one.run_oc_call(ns, args=("--model", "opencode-go/no-such-model"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "profile_refused", (result, proc.stderr)
    records = one.records_of(ns.state)
    checks = [
        r for r in records if r.get("kind") == "check" and r.get("check") == "model"
    ]
    assert checks and checks[-1].get("decision") == "refused", checks
    assert not one.run_captures_of(ns.capture), "the harness ran a refused model"


def test_one_016_claude_code_without_new_options_unchanged(tmp_path):
    ns = _claude_root(tmp_path)
    proc = one.run_call(ns)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert result.get("journal_complete") is True, result
    assert set(result) == RESULT_KEYS, sorted(result)
    assert result.get("output_kind") == "none", result
    assert result.get("output_ref") is None, result
    sid = result.get("session_id")
    assert isinstance(sid, str) and len(sid) == 36, result
    generated = {
        "<run>": result.get("run"),
        "<node>": result.get("node"),
        "<sid>": sid,
    }
    assert all(isinstance(v, str) and v for v in generated.values()), result
    assert _normalize(result, tmp_path, generated) == EXPECTED_RESULT, _normalize(
        result, tmp_path, generated
    )
    capture = one.captures_of(ns.capture)[0]
    assert capture.get("argv") == [
        "-p",
        one.PROMPT,
        "--session-id",
        sid,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model",
        "claude-sonnet-4-5",
    ], capture.get("argv")
    env_used = one.call_env(ns)
    recorded = capture.get("env") or {}
    unexpected = sorted(
        n
        for n in recorded
        if n not in one.ALLOWED_ENV
        and n not in one.PLATFORM_ENV
        and not n.startswith("LC_")
    )
    assert unexpected == [], unexpected
    expected_names = {
        n for n in env_used if n in one.ALLOWED_ENV or n.startswith("LC_")
    } | {"TRINITY_GUARD"}
    assert set(recorded) - one.PLATFORM_ENV == expected_names, sorted(
        set(recorded) ^ expected_names
    )
    for name, value in recorded.items():
        if name == "TRINITY_GUARD":
            guard = _normalize(json.loads(value), tmp_path, generated)
            assert guard == EXPECTED_GUARD, (name, guard)
        elif name in one.PLATFORM_ENV:
            continue
        else:
            assert value == env_used.get(name), (name, value, env_used.get(name))
    records = [r for r in one.records_of(ns.state) if r.get("kind") != "heartbeat"]
    journal = _normalize(records, tmp_path, generated)
    pinned = json.dumps(EXPECTED_JOURNAL)
    assert "/Users/" not in pinned, pinned
    assert "/home/" not in pinned, pinned
    assert "/tmp/" not in pinned, pinned
    assert journal == EXPECTED_JOURNAL, json.dumps(journal, indent=1)
    assert RESULT_TEXT not in _journal_path(ns).read_text(encoding="utf-8")

"""Tests for TRN-2019 Codex review provider dispatch."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from scripts import codex
from tests.test_codex_adapter import CODEX_SCRIPT, commit_all, init_repo


def run_codex(args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(CODEX_SCRIPT)] + args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def simple_repo(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("before\n")
    commit_all(repo, "init")
    tracked.write_text("before\nafter\n")
    return repo


def write_provider(path, body):
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)


def write_sleep_provider(path, events, sleep_seconds=1.0, exit_code=0):
    write_provider(
        path,
        f"""
import json
import pathlib
import sys
import time

provider = pathlib.Path(sys.argv[0]).name
events = pathlib.Path({str(events)!r})
with events.open("a") as handle:
    handle.write(json.dumps({{"provider": provider, "event": "start", "time": time.monotonic()}}) + "\\n")
time.sleep({sleep_seconds})
print(f"provider={{provider}}")
print(f"stderr={{provider}}", file=sys.stderr)
with events.open("a") as handle:
    handle.write(json.dumps({{"provider": provider, "event": "end", "time": time.monotonic()}}) + "\\n")
raise SystemExit({exit_code})
""",
    )


def write_config(config, providers, *, max_parallel=None, default_providers=None):
    review = {
        "prompt_template": "Scope: {scope}\n\n{diff}\n\n{files}\n",
        "default_providers": default_providers or list(providers),
    }
    if max_parallel is not None:
        review["max_parallel_providers"] = max_parallel
    config.write_text(
        json.dumps(
            {
                "providers": {
                    name: {"cli": str(path), "timeout": 5}
                    for name, path in providers.items()
                },
                "review": review,
            }
        )
    )


def event_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def review_dir_from(result):
    return Path(result.stdout.strip().splitlines()[-1])


def test_review_runs_providers_in_parallel_and_preserves_result_order(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    deepseek = tmp_path / "deepseek"
    write_sleep_provider(glm, events, sleep_seconds=1.0)
    write_sleep_provider(deepseek, events, sleep_seconds=1.0)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm, "deepseek": deepseek})

    started = time.monotonic()
    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 2.5
    rows = event_rows(events)
    starts = {row["provider"]: row["time"] for row in rows if row["event"] == "start"}
    ends = {row["provider"]: row["time"] for row in rows if row["event"] == "end"}
    assert max(starts.values()) < min(ends.values())
    review_dir = review_dir_from(result)
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert [item["provider"] for item in metadata["results"]] == ["glm", "deepseek"]
    assert "trinity: starting provider glm timeout=5s" in result.stderr
    assert "trinity: starting provider deepseek timeout=5s" in result.stderr
    assert "trinity: writing metadata" in result.stderr
    # TRN-3028: completion line is printed without the `trinity: ` progress
    # prefix so callers can key off the documented "trinity review:" prefix.
    assert "\ntrinity review: " in "\n" + result.stderr
    assert "trinity: trinity review:" not in result.stderr


def test_cmd_review_starts_mcp_loopback_and_cleans_token(tmp_path, monkeypatch, capsys):
    repo = simple_repo(tmp_path)
    config = tmp_path / "codex.json"
    provider = tmp_path / "glm"
    write_provider(provider, "print('unused provider')\n")
    write_config(config, {"glm": provider})
    seen = {}

    def fake_run_providers(
        max_workers,
        providers,
        provider_configs,
        prompt_path,
        review_dir,
        root,
        **kwargs,
    ):
        seen["token"] = os.environ.get("TRINITY_MCP_TOKEN")
        seen["review_dir"] = str(review_dir)
        raw_path = review_dir / "raw" / "glm.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text("legacy pass\n")
        return [
            {
                "provider": "glm",
                "returncode": 0,
                "raw": "raw/glm.txt",
                "started_at": "2026-05-29T00:00:00Z",
                "finished_at": "2026-05-29T00:00:01Z",
            }
        ]

    monkeypatch.setattr(codex, "run_providers", fake_run_providers)
    os.environ["TRINITY_MCP_TOKEN"] = "ambient-stale-token"
    args = codex.build_parser().parse_args(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert codex.cmd_review(args) == 0
    review_dir = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert seen["review_dir"] == str(review_dir)
    assert isinstance(seen["token"], str)
    assert len(seen["token"]) == 32
    assert seen["token"] != "ambient-stale-token"
    assert "TRINITY_MCP_TOKEN" not in os.environ


def test_review_max_parallel_one_keeps_sequential_behavior(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    deepseek = tmp_path / "deepseek"
    write_sleep_provider(glm, events, sleep_seconds=0.4)
    write_sleep_provider(deepseek, events, sleep_seconds=0.4)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm, "deepseek": deepseek}, max_parallel=1)

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert result.returncode == 0, result.stderr
    rows = event_rows(events)
    starts = {row["provider"]: row["time"] for row in rows if row["event"] == "start"}
    ends = {row["provider"]: row["time"] for row in rows if row["event"] == "end"}
    assert starts["deepseek"] >= ends["glm"]
    raw = (review_dir_from(result) / "raw" / "glm.txt").read_text()
    assert "provider=glm" in raw
    assert "TRINITY-RAW-STDERR-BOUNDARY" in raw
    assert "stderr=glm" in raw


def test_review_collects_mixed_success_and_failure_in_provider_order(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    deepseek = tmp_path / "deepseek"
    write_sleep_provider(glm, events, sleep_seconds=0.4, exit_code=0)
    write_sleep_provider(deepseek, events, sleep_seconds=0.1, exit_code=3)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm, "deepseek": deepseek})

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert result.returncode == 1
    review_dir = review_dir_from(result)
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert [(item["provider"], item["returncode"]) for item in metadata["results"]] == [
        ("glm", 0),
        ("deepseek", 3),
    ]
    synthesis = (review_dir / "synthesis.md").read_text()
    assert "| deepseek | FAIL 3 | `raw/deepseek.txt` |" in synthesis
    assert synthesis.endswith("\n")
    assert not (review_dir / "incomplete.json").exists()


def test_review_rejects_invalid_max_parallel_values_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    deepseek = tmp_path / "deepseek"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    write_sleep_provider(deepseek, events, sleep_seconds=0.1)

    for index, value in enumerate([0, -1, True, "2", 3]):
        config = tmp_path / f"codex-{index}.json"
        write_config(config, {"glm": glm, "deepseek": deepseek}, max_parallel=value)
        out_dir = tmp_path / f"reviews-{index}"
        result = run_codex(
            [
                "review",
                "--root",
                str(repo),
                "--config",
                str(config),
                "--out-dir",
                str(out_dir),
            ]
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert "review.max_parallel_providers" in result.stderr
        assert not out_dir.exists()


def test_review_rejects_duplicate_explicit_providers_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm})
    out_dir = tmp_path / "reviews"

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm,glm",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "duplicate provider selected: glm" in result.stderr
    assert not out_dir.exists()


def test_review_rejects_duplicate_default_providers_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm}, default_providers=["glm", "glm"])
    out_dir = tmp_path / "reviews"

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "duplicate provider selected: glm" in result.stderr
    assert not out_dir.exists()


def test_review_prompt_includes_review_only_instruction_before_artifact(tmp_path):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm})

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert result.returncode == 0, result.stderr
    prompt = (review_dir_from(result) / "prompt.md").read_text()
    assert "## Review-Only Mode" in prompt
    assert "Do not run tests, shell commands" in prompt
    assert prompt.index("## Review-Only Mode") < prompt.index("diff --git")


def process_is_running(pid):
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "Z" not in result.stdout


def wait_until_not_running(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_running(pid):
            return True
        time.sleep(0.1)
    return not process_is_running(pid)


def wait_until_exists(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return path.exists()


def test_review_timeout_kills_provider_process_group_children(tmp_path):
    repo = simple_repo(tmp_path)
    child_pid = tmp_path / "child.pid"
    provider = tmp_path / "glm"
    write_provider(
        provider,
        f"""
import pathlib
import subprocess
import sys
import time

child_pid = pathlib.Path({str(child_pid)!r})
subprocess.Popen([
    sys.executable,
    "-c",
    "import pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(__import__('os').getpid())); time.sleep(30)",
    str(child_pid),
])
print("spawned child", flush=True)
time.sleep(30)
""",
    )
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(provider), "timeout": 1}},
                "review": {
                    "prompt_template": "{diff}\n\n{files}\n",
                    "default_providers": ["glm"],
                },
            }
        )
    )

    result = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert result.returncode == 1
    assert child_pid.exists()
    assert wait_until_not_running(int(child_pid.read_text()))
    review_dir = review_dir_from(result)
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["results"][0]["returncode"] == 124
    raw = (review_dir / "raw" / "glm.txt").read_text()
    assert "ERROR: timeout after 1s" in raw
    assert "spawned child" in raw
    assert not (review_dir / "incomplete.json").exists()


def test_review_sigint_writes_incomplete_json_and_cleans_up(tmp_path):
    repo = simple_repo(tmp_path)
    glm_done = tmp_path / "glm.done"
    deepseek_started = tmp_path / "deepseek.started"
    glm = tmp_path / "glm"
    deepseek = tmp_path / "deepseek"
    write_provider(
        glm,
        f"""
import pathlib

pathlib.Path({str(glm_done)!r}).write_text("done")
print("glm done", flush=True)
""",
    )
    write_provider(
        deepseek,
        f"""
import pathlib
import time

pathlib.Path({str(deepseek_started)!r}).write_text("started")
print("deepseek running", flush=True)
time.sleep(30)
""",
    )
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm, "deepseek": deepseek})
    proc = subprocess.Popen(
        [
            sys.executable,
            str(CODEX_SCRIPT),
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert wait_until_exists(glm_done)
    assert wait_until_exists(deepseek_started)
    # Brief settle delay so glm's process exit propagates to codex.py's
    # provider-running bookkeeping before SIGINT triggers cleanup. Without
    # this, on macOS CI runners under coverage instrumentation (TRN-2023
    # subprocess shim activates coverage in glm/deepseek child processes,
    # adding startup+exit overhead), glm can still appear in the running
    # snapshot at the moment SIGINT fires — a latent race the test hadn't
    # exercised until slice B's CI workflow began running it cross-platform.
    time.sleep(0.5)
    proc.send_signal(signal.SIGINT)
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise

    assert proc.returncode == 130, stderr
    review_dir = Path(stdout.strip().splitlines()[-1])
    incomplete = json.loads((review_dir / "incomplete.json").read_text())
    assert incomplete["status"] == "interrupted"
    assert incomplete["review_dir"] == str(review_dir)
    assert incomplete["providers_selected"] == ["glm", "deepseek"]
    assert incomplete["providers_started"] == ["glm", "deepseek"]
    assert incomplete["providers_running_at_cleanup"] == ["deepseek"]
    assert "glm" not in incomplete["cleanup"]
    assert "deepseek" in incomplete["cleanup"]
    # TRN-2018 M1: metadata.json is written at init (before run_providers),
    # so an interrupted review now leaves both files. metadata.json contains
    # the init-time state (status=running with provider_states); incomplete.json
    # overlays the interrupted-status verdict (read by _print_review_summary).
    assert (review_dir / "metadata.json").exists()
    init_meta = json.loads((review_dir / "metadata.json").read_text())
    assert init_meta["status"] == "running"
    assert set(init_meta["provider_states"].keys()) == {"glm", "deepseek"}


def test_review_sigint_before_dispatch_writes_incomplete_json(
    tmp_path, monkeypatch, capsys
):
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm})
    original_write_text = Path.write_text

    def interrupt_prompt_write(path, *args, **kwargs):
        if path.name == "prompt.md":
            raise KeyboardInterrupt
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(codex.Path, "write_text", interrupt_prompt_write)
    args = codex.build_parser().parse_args(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert codex.cmd_review(args) == 130
    review_dir = Path(capsys.readouterr().out.strip().splitlines()[-1])
    incomplete = json.loads((review_dir / "incomplete.json").read_text())
    assert incomplete["status"] == "interrupted"
    assert incomplete["providers_started"] == []
    assert incomplete["providers_running_at_cleanup"] == []
    assert incomplete["cleanup"] == {}
    assert not (review_dir / "metadata.json").exists()


def test_review_sigint_during_metadata_write_marks_incomplete(
    tmp_path, monkeypatch, capsys
):
    """TRN-2018 M1: metadata writes go through _review_metadata._write_atomic
    (os.replace), not Path.write_text. Interrupt during the post-run write
    is now achieved by patching finalize_metadata. The init-time
    metadata.json (written before run_providers starts) survives.
    """
    repo = simple_repo(tmp_path)
    events = tmp_path / "events.jsonl"
    glm = tmp_path / "glm"
    write_sleep_provider(glm, events, sleep_seconds=0.1)
    config = tmp_path / "codex.json"
    write_config(config, {"glm": glm})

    def interrupt_finalize(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(codex._rm, "finalize_metadata", interrupt_finalize)
    args = codex.build_parser().parse_args(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert codex.cmd_review(args) == 130
    review_dir = Path(capsys.readouterr().out.strip().splitlines()[-1])
    incomplete = json.loads((review_dir / "incomplete.json").read_text())
    assert incomplete["status"] == "interrupted"
    assert incomplete["providers_started"] == ["glm"]
    assert incomplete["providers_running_at_cleanup"] == []
    assert incomplete["cleanup"] == {}
    # M1: init_metadata wrote metadata.json before run_providers; finalize
    # was the interrupted step. The file persists with init-time state.
    assert (review_dir / "metadata.json").exists()
    init_meta = json.loads((review_dir / "metadata.json").read_text())
    assert init_meta["status"] == "running"
    # TRN-2018 R7: cmd_review reorders write_synthesis BEFORE
    # finalize_metadata so a concurrent status poll never sees
    # status=finished without synthesis.md. With finalize_metadata
    # monkeypatched to raise here, synthesis.md was already written
    # in the prior step. (Pre-R7 order had this assertion reversed.)
    assert (review_dir / "synthesis.md").exists()


def test_run_providers_does_not_start_queued_provider_after_failure(
    tmp_path, monkeypatch
):
    calls = []

    def fail_first_provider(provider, *args, **kwargs):
        calls.append(provider)
        if provider == "glm":
            raise RuntimeError("dispatch failed")
        return {
            "provider": provider,
            "returncode": 0,
            "raw": f"raw/{provider}.txt",
            "started_at": "2026-05-05T00:00:00",
            "finished_at": "2026-05-05T00:00:00",
        }

    monkeypatch.setattr(codex, "run_provider", fail_first_provider)

    try:
        codex.run_providers(
            1,
            ["glm", "deepseek"],
            {"glm": {}, "deepseek": {}},
            tmp_path / "prompt.md",
            tmp_path,
            tmp_path,
            mcp_port=None,
            mcp_token=None,
        )
    except codex.ReviewOrchestrationError as exc:
        assert str(exc) == "dispatch failed"
    else:
        raise AssertionError("expected ReviewOrchestrationError")

    assert calls == ["glm"]


# ---------------------------------------------------------------------------
# TRN-3024 Slice B: claude-code loopback MCP injection tests
# ---------------------------------------------------------------------------


def run_provider_with_captured_popen(
    tmp_path,
    monkeypatch,
    provider,
    provider_config,
    *,
    mcp_port=9999,
    mcp_token="test-token-1234567890abcdef",
):
    captured = {}
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("test prompt")
    monkeypatch.delenv("TRINITY_MCP_TOKEN", raising=False)

    class CapturingPopen:
        def __init__(
            self,
            cmd,
            *,
            cwd,
            stdout,
            stderr,
            text,
            start_new_session,
            env,
        ):
            _ = (stdout, stderr, text, start_new_session)
            self.pid = 12345
            self.returncode = 0
            captured["cmd"] = list(cmd)
            captured["cwd"] = cwd
            captured["env"] = dict(env)
            if "--mcp-config" in cmd:
                config_path = Path(cmd[cmd.index("--mcp-config") + 1])
                captured["mcp_config_path"] = config_path
                captured["mcp_config_exists_at_spawn"] = config_path.exists()
                captured["mcp_config"] = json.loads(config_path.read_text())

        def wait(self, timeout=None):
            _ = timeout
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(codex.subprocess, "Popen", CapturingPopen)
    monkeypatch.chdir(tmp_path)
    result = codex.run_provider(
        provider,
        provider_config,
        prompt_path,
        tmp_path,
        tmp_path,
        codex.ActiveProcessRegistry(),
        mcp_port=mcp_port,
        mcp_token=mcp_token,
    )
    return result, captured


def test_claude_code_mcp_config_generation(tmp_path):
    """Verify claude-code MCP config file content and permissions."""
    token = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    port = 9876
    config_path = codex._write_claude_code_mcp_config(tmp_path, port, token)

    assert config_path == tmp_path / "mcp_config" / "claude-code.json"
    assert config_path.exists()
    assert oct(config_path.stat().st_mode & 0o777) == "0o600"
    assert oct(config_path.parent.stat().st_mode & 0o777) == "0o700"

    config = json.loads(config_path.read_text())
    mcp = config["mcpServers"]["trinity"]
    assert mcp["type"] == "sse"
    assert mcp["url"] == f"http://127.0.0.1:{port}/sse"
    assert mcp["headers"]["Authorization"] == f"Bearer {token}"
    assert list(config["mcpServers"].keys()) == ["trinity"]
    assert len(config["mcpServers"]) == 1


def test_claude_code_mcp_config_created_restrictive_from_start(tmp_path, monkeypatch):
    """Config creation passes mode 0600 to os.open, avoiding write-then-chmod."""
    captured = {}
    real_open = codex.os.open

    def recording_open(path, flags, mode=0o777, *, dir_fd=None):
        captured["flags"] = flags
        captured["mode"] = mode
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(codex.os, "open", recording_open)
    codex._write_claude_code_mcp_config(tmp_path, 9876, "token")

    assert captured["mode"] == 0o600
    assert captured["flags"] & codex.os.O_CREAT
    assert captured["flags"] & codex.os.O_EXCL


def test_claude_code_mcp_injection_requires_explicit_provider_flag(
    tmp_path, monkeypatch
):
    """claude-code stays unchanged unless enable_loopback_mcp is true."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "claude-code",
        {"cli": "claude-code -p", "timeout": 5},
    )
    assert result["returncode"] == 0
    assert "--mcp-config" not in captured["cmd"]
    assert "--strict-mcp-config" not in captured["cmd"]
    assert "TRINITY_MCP_TOKEN" not in captured["env"]
    assert not (tmp_path / "mcp_config").exists()


def test_claude_code_mcp_injection_in_run_provider(tmp_path, monkeypatch):
    """Verify run_provider injects strict --mcp-config for enabled claude-code."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "claude-code",
        {"cli": "claude-code -p", "timeout": 5, "enable_loopback_mcp": True},
    )
    assert result["returncode"] == 0

    cmd = captured["cmd"]
    assert "--strict-mcp-config" in cmd
    assert "--mcp-config" in cmd
    assert cmd.index("--strict-mcp-config") < cmd.index("--mcp-config")
    assert cmd.index("--mcp-config") < cmd.index("-p")
    assert cmd[-2] == "-p"
    assert cmd[-1].startswith("Read the complete Trinity review prompt")
    assert captured["env"]["TRINITY_MCP_TOKEN"] == "test-token-1234567890abcdef"
    assert captured["mcp_config_exists_at_spawn"] is True
    config = captured["mcp_config"]
    assert config["mcpServers"]["trinity"]["url"] == "http://127.0.0.1:9999/sse"
    assert captured["mcp_config_path"].exists() is False


def test_claude_code_mcp_injection_skips_non_claude_code(tmp_path, monkeypatch):
    """Non-claude-code providers never get MCP injection, even if flagged."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "glm",
        {"cli": "glm", "timeout": 5, "enable_loopback_mcp": True},
    )
    assert result["returncode"] == 0
    assert "--mcp-config" not in captured["cmd"]
    assert "--strict-mcp-config" not in captured["cmd"]
    assert "TRINITY_MCP_TOKEN" not in captured["env"]
    assert not (tmp_path / "mcp_config").exists()


def test_claude_code_mcp_injection_skipped_when_disabled(tmp_path, monkeypatch):
    """Verify enabled claude-code runs without MCP when MCP params are missing."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "claude-code",
        {"cli": "claude-code -p", "timeout": 5, "enable_loopback_mcp": True},
        mcp_port=None,
        mcp_token=None,
    )
    assert result["returncode"] == 0
    assert "--mcp-config" not in captured["cmd"]
    assert "--strict-mcp-config" not in captured["cmd"]
    assert "TRINITY_MCP_TOKEN" not in captured["env"]
    assert not (tmp_path / "mcp_config").exists()


def test_claude_code_mcp_config_exposes_current_scope_tool(tmp_path):
    """Smoke test: start MCP server, generate config, then exercise a full
    tools/list MCP call through the SSE transport to prove trinity__current_scope
    is discoverable through the generated config shape."""
    token = "smoke-test-token-00000000000000"
    mcp_server, mcp_port = codex.start_server_blocking(
        review_dir=str(tmp_path),
        token=token,
    )
    try:
        config_path = codex._write_claude_code_mcp_config(tmp_path, mcp_port, token)
        config = json.loads(config_path.read_text())
        url = config["mcpServers"]["trinity"]["url"]
        assert f"http://127.0.0.1:{mcp_port}/sse" == url

        import asyncio
        import urllib.parse

        async def _do_tools_list():
            # 1. Open SSE connection and wait for the endpoint event.
            reader, writer = await asyncio.open_connection("127.0.0.1", mcp_port)
            req = (
                f"GET /sse HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{mcp_port}\r\n"
                f"Authorization: Bearer {token}\r\n"
                f"\r\n"
            )
            writer.write(req.encode())
            await writer.drain()

            # Read SSE response header block plus first endpoint event.
            sse_data = b""
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
                if not chunk:
                    break
                sse_data += chunk
                if b"event: endpoint" in sse_data and b"\n\n" in sse_data:
                    break

            header_text = sse_data.decode()
            assert header_text.startswith("HTTP/1.1 200"), (
                f"expected 200, got {header_text.split(chr(10))[0]}"
            )

            # Extract sessionId from endpoint event data.
            session_id = ""
            for line in header_text.splitlines():
                if line.startswith("data: "):
                    path_part = line[len("data: ") :].strip()
                    parsed = urllib.parse.urlparse(f"http://dummy{path_part}")
                    qs = urllib.parse.parse_qs(parsed.query)
                    session_id = qs.get("sessionId", [""])[0]
            assert session_id, (
                f"could not extract sessionId from SSE data:\n{header_text}"
            )

            # 2. POST tools/list to the messages endpoint on a separate connection.
            msg_req_body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                }
            )
            msg_req = (
                f"POST /messages?sessionId={session_id} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{mcp_port}\r\n"
                f"Authorization: Bearer {token}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(msg_req_body)}\r\n"
                f"\r\n"
                f"{msg_req_body}"
            )
            msg_reader, msg_writer = await asyncio.open_connection(
                "127.0.0.1", mcp_port
            )
            msg_writer.write(msg_req.encode())
            await msg_writer.drain()

            msg_resp = b""
            while True:
                chunk = await asyncio.wait_for(msg_reader.read(4096), timeout=5)
                if not chunk:
                    break
                msg_resp += chunk
                if b"\r\n\r\n" in msg_resp:
                    # For 202 Accepted there is no body; read the HTTP line only.
                    status_line, _rest = msg_resp.split(b"\r\n", 1)
                    if b"202" in status_line or b"\r\n\r\n" in msg_resp:
                        break
            msg_writer.close()
            assert b"202" in msg_resp or b"Accepted" in msg_resp, (
                f"expected 202, got {msg_resp.decode(errors='replace')[:200]}"
            )

            # 3. Read tools/list response from the SSE stream.
            tools_response = b""
            deadline = asyncio.get_event_loop().time() + 10
            while asyncio.get_event_loop().time() < deadline:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
                if not chunk:
                    break
                tools_response += chunk
                text = tools_response.decode(errors="replace")
                if '"result"' in text and '"tools"' in text:
                    break

            writer.close()

            # Parse the SSE event to extract the JSON-RPC response.
            sse_text = tools_response.decode(errors="replace")
            assert "event: message" in sse_text, (
                f"expected 'event: message' in SSE data:\n{sse_text[:500]}"
            )
            data_line = ""
            for line in sse_text.splitlines():
                if line.startswith("data: "):
                    data_line = line[len("data: ") :]
                    break
            assert data_line, f"no data line in SSE:\n{sse_text[:500]}"

            rpc_response = json.loads(data_line)
            assert rpc_response.get("id") == 1
            assert "result" in rpc_response, (
                f"no result key in response:\n{rpc_response}"
            )
            tool_names = [t["name"] for t in rpc_response["result"]["tools"]]
            assert "trinity__current_scope" in tool_names, (
                f"trinity__current_scope not found in tools: {tool_names}"
            )
            assert set(tool_names) == {
                "trinity__current_scope",
                "trinity__peer_findings_so_far",
                "trinity__prior_review_summary",
                "trinity__methodology_rule",
            }

        asyncio.run(_do_tools_list())
    finally:
        codex.stop_mcp_loopback_server(mcp_server)

# ---------------------------------------------------------------------------
# TRN-3024 Slice C: codex loopback MCP injection tests
# ---------------------------------------------------------------------------


def test_codex_mcp_injection_requires_explicit_provider_flag(
    tmp_path, monkeypatch
):
    """Codex stays unchanged unless enable_loopback_mcp is true."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "codex",
        {"cli": "codex exec --skip-git-repo-check -m gpt-5.5", "timeout": 5},
    )
    assert result["returncode"] == 0
    assert all("-c" not in part or not part.startswith("mcp_servers.")
               for part in captured["cmd"])
    assert "TRINITY_MCP_TOKEN" not in captured["env"]


def test_codex_mcp_injection_in_run_provider(tmp_path, monkeypatch):
    """Verify run_provider injects -c mcp_servers args for enabled codex."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "codex",
        {
            "cli": "codex exec --skip-git-repo-check -m gpt-5.5",
            "timeout": 5,
            "enable_loopback_mcp": True,
        },
    )
    assert result["returncode"] == 0

    cmd = captured["cmd"]
    # -c args for mcp_servers appear before the prompt (last element)
    mcp_args = [part for part in cmd if part.startswith("mcp_servers.")]
    assert len(mcp_args) == 3, f"expected 3 mcp_servers arg values, got {mcp_args}"

    types = [a for a in mcp_args if a.startswith("mcp_servers.trinity.type=")]
    urls = [a for a in mcp_args if a.startswith("mcp_servers.trinity.url=")]
    auths = [a for a in mcp_args if a.startswith("mcp_servers.trinity.headers.Authorization=")]

    assert len(types) == 1
    assert types[0] == "mcp_servers.trinity.type=sse"

    assert len(urls) == 1
    assert urls[0] == "mcp_servers.trinity.url=http://127.0.0.1:9999/sse"

    assert len(auths) == 1
    assert auths[0] == "mcp_servers.trinity.headers.Authorization=Bearer test-token-1234567890abcdef"

    # -c flags precede the -c values
    assert "-c" in cmd
    assert cmd[-1].startswith("Read the complete Trinity review prompt")
    assert captured["env"]["TRINITY_MCP_TOKEN"] == "test-token-1234567890abcdef"


def test_codex_mcp_injection_skipped_when_disabled(tmp_path, monkeypatch):
    """Enabled codex runs without MCP when MCP params are missing."""
    result, captured = run_provider_with_captured_popen(
        tmp_path,
        monkeypatch,
        "codex",
        {
            "cli": "codex exec --skip-git-repo-check -m gpt-5.5",
            "timeout": 5,
            "enable_loopback_mcp": True,
        },
        mcp_port=None,
        mcp_token=None,
    )
    assert result["returncode"] == 0
    assert all("-c" not in part or not part.startswith("mcp_servers.")
               for part in captured["cmd"])
    assert "TRINITY_MCP_TOKEN" not in captured["env"]


def test_codex_mcp_build_args_content():
    """_build_codex_mcp_args returns correctly shaped args."""
    args = codex._build_codex_mcp_args(7777, "secret-token-abc123")
    # Should be a flat list: -c, val, -c, val, -c, val
    assert args == [
        "-c",
        "mcp_servers.trinity.type=sse",
        "-c",
        "mcp_servers.trinity.url=http://127.0.0.1:7777/sse",
        "-c",
        "mcp_servers.trinity.headers.Authorization=Bearer secret-token-abc123",
    ]


def test_codex_mcp_insert_args_places_before_prompt():
    """_insert_codex_mcp_args inserts MCP args before the prompt element."""
    cmd = ["codex", "exec", "--skip-git-repo-check", "-m", "gpt-5.5", "the-prompt"]
    mcp_args = ["-c", "mcp_servers.trinity.type=sse"]
    result = codex._insert_codex_mcp_args(cmd, mcp_args)
    assert result == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "-m",
        "gpt-5.5",
        "-c",
        "mcp_servers.trinity.type=sse",
        "the-prompt",
    ]


def test_codex_mcp_enabled_requires_explicit_flag():
    """_codex_loopback_mcp_enabled returns True only for codex with flag."""
    assert codex._codex_loopback_mcp_enabled(
        "codex", {"enable_loopback_mcp": True}
    ) is True
    assert codex._codex_loopback_mcp_enabled(
        "codex", {}
    ) is False
    assert codex._codex_loopback_mcp_enabled(
        "codex", {"enable_loopback_mcp": False}
    ) is False
    assert codex._codex_loopback_mcp_enabled(
        "glm", {"enable_loopback_mcp": True}
    ) is False
    assert codex._codex_loopback_mcp_enabled(
        "claude-code", {"enable_loopback_mcp": True}
    ) is False
    assert codex._codex_loopback_mcp_enabled(
        "not-a-provider", {}
    ) is False

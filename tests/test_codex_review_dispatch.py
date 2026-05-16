"""Tests for TRN-2019 Codex review provider dispatch."""

import json
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
    assert elapsed < 1.8
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
    assert not (review_dir / "synthesis.md").exists()


def test_run_providers_does_not_start_queued_provider_after_failure(
    tmp_path, monkeypatch
):
    calls = []

    def fail_first_provider(provider, *_args):
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
        )
    except codex.ReviewOrchestrationError as exc:
        assert str(exc) == "dispatch failed"
    else:
        raise AssertionError("expected ReviewOrchestrationError")

    assert calls == ["glm"]

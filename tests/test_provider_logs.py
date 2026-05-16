"""TRN-2018 M1: incremental provider logs via Popen file-handle refactor.

Currently `run_provider` (scripts/codex.py:1701) uses
`Popen(stdout=PIPE, stderr=PIPE) + communicate(timeout=...)`, so
nothing is written to disk until communicate() returns. C.2 refactors
this to `Popen(stdout=open(path, 'w', buffering=1), stderr=...)` so
the logs/<p>.std{out,err}.log files appear and grow while the
provider runs.

These tests are RED before C.2 GREEN and prove:
1. logs/<p>.stdout.log exists during provider execution
2. timeout path preserves partial logs + returncode 124
3. command-not-found path creates empty log files + returncode 127
4. raw/<p>.txt format is unchanged (stdout-only and stdout+stderr cases)
5. ActiveProcessRegistry.remove is called on normal exit (preserves
   codex.py:1782 finally-block semantics)
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import codex as codex_mod  # noqa: E402
import _review_metadata as rm  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _init_review(tmp_path: Path, providers=("p",)) -> Path:
    """Set up a review_dir with raw/, logs/, and an init'd metadata.json
    so update_provider_state calls land instead of silently no-opping."""
    review_dir = tmp_path / "20260516-100000-test"
    (review_dir / "raw").mkdir(parents=True)
    (review_dir / "logs").mkdir()
    (tmp_path / "prompt.md").write_text("p")
    rm.init_metadata(
        review_dir,
        review_id=review_dir.name,
        review_dir_str=str(review_dir),
        providers=list(providers),
        preset=None,
        scope=".",
        root=str(tmp_path),
        input={"mode": "scope"},
    )
    return review_dir


def test_run_provider_creates_logs_files_before_completion(tmp_path):
    """The partial fixture emits one line, sleeps 1s, then emits another.
    During the sleep, logs/p.stdout.log should already contain line 1.
    Poll from the main thread while run_provider executes in a background
    thread."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_partial.sh"), "timeout": 10}
    registry = codex_mod.ActiveProcessRegistry()
    result_holder: dict = {}

    def run():
        result_holder["result"] = codex_mod.run_provider(
            "p",
            provider_config,
            tmp_path / "prompt.md",
            review_dir,
            tmp_path,
            registry,
        )

    t = threading.Thread(target=run)
    t.start()

    stdout_log = review_dir / "logs" / "p.stdout.log"
    deadline = time.time() + 1.5
    seen = False
    while time.time() < deadline and t.is_alive():
        if stdout_log.exists() and "partial output line 1" in stdout_log.read_text():
            seen = True
            break
        time.sleep(0.05)

    t.join(timeout=5)
    assert not t.is_alive(), "run_provider thread didn't finish"
    assert seen, "logs/p.stdout.log should contain partial output BEFORE provider exits"
    assert result_holder["result"]["returncode"] == 0


def test_run_provider_logs_persist_after_timeout(tmp_path):
    """Hang fixture sleeps 999s; provider_config sets timeout=2s. Expected:
    returncode 124, raw/p.txt contains the timeout banner, logs files
    exist on disk (may be empty or contain 'starting hang' depending on
    flush timing)."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_hang.sh"), "timeout": 2}
    registry = codex_mod.ActiveProcessRegistry()
    result = codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    assert result["returncode"] == 124
    raw = (review_dir / "raw" / "p.txt").read_text()
    assert "ERROR: timeout after 2s" in raw
    assert (review_dir / "logs" / "p.stdout.log").exists()
    assert (review_dir / "logs" / "p.stderr.log").exists()


def test_run_provider_logs_filenotfound_path(tmp_path):
    """Command points at a nonexistent path. Expected: returncode 127,
    raw/p.txt contains the command-not-found banner. Log files may
    exist (empty) or not — Popen() raises before the file handles open
    on some platforms, after on others. The contract is just "raw is
    written and returncode is 127", per the existing semantics at
    codex.py:1740-1751."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": "/nonexistent/trinity-test-cmd", "timeout": 5}
    registry = codex_mod.ActiveProcessRegistry()
    result = codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    assert result["returncode"] == 127
    raw = (review_dir / "raw" / "p.txt").read_text()
    assert "ERROR: command not found" in raw


def test_raw_txt_format_unchanged_stdout_only(tmp_path):
    """Quick fixture emits stdout only. raw/p.txt must contain the stdout
    bytes. The _STDERR_SENTINEL is always appended by raw_output() (see
    codex.py:1417) even when stderr is empty — the contract is that the
    sentinel is unique enough that no real provider output collides, and
    _strip_stderr_region (TRN-3022 coupling) relies on it being present
    as a boundary marker."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_quick.sh"), "timeout": 10}
    registry = codex_mod.ActiveProcessRegistry()
    codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    raw = (review_dir / "raw" / "p.txt").read_text()
    assert "quick provider stdout" in raw
    assert codex_mod._STDERR_SENTINEL in raw
    # stderr region after the sentinel is empty for stdout-only providers
    assert raw.endswith(codex_mod._STDERR_SENTINEL)


def test_raw_txt_format_unchanged_with_stderr(tmp_path):
    """stderr fixture emits to both. raw/p.txt is
    `<stdout>{_STDERR_SENTINEL}<stderr>` per codex.py:1417."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_stderr.sh"), "timeout": 10}
    registry = codex_mod.ActiveProcessRegistry()
    codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    raw = (review_dir / "raw" / "p.txt").read_text()
    assert "stdout line" in raw
    assert codex_mod._STDERR_SENTINEL in raw
    assert "stderr line" in raw
    # Order: stdout, then sentinel, then stderr.
    assert (
        raw.index("stdout line")
        < raw.index(codex_mod._STDERR_SENTINEL)
        < raw.index("stderr line")
    )


def test_run_provider_nonzero_rc_marks_state_failed(tmp_path):
    """R2 fix for codex P2 finding 3249xxxx: when a provider exits cleanly
    with rc != 0, run_provider must record provider_states.<p>.status as
    'failed' (not 'finished'), so finalize_metadata correctly surfaces the
    top-level status as 'failed' via the failed > timed_out > finished
    precedence."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_fail.sh"), "timeout": 10}
    registry = codex_mod.ActiveProcessRegistry()
    result = codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    assert result["returncode"] == 2
    import json

    state = json.loads((review_dir / "metadata.json").read_text())[
        "provider_states"
    ]["p"]
    assert state["status"] == "failed", (
        f"expected failed (rc=2 != 0); got {state['status']!r}"
    )
    assert state["returncode"] == 2


def test_active_process_registry_remove_called_on_normal_exit(tmp_path):
    """After run_provider returns, the registry snapshot must NOT contain
    the provider — preserves codex.py:1782's finally-block contract."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_quick.sh"), "timeout": 10}
    registry = codex_mod.ActiveProcessRegistry()
    codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    snap = registry.snapshot()
    assert all(item["provider"] != "p" for item in snap)


def test_active_process_registry_remove_called_on_timeout(tmp_path):
    """Same as above but for the timeout path — registry must be cleaned
    even when run_provider returns via the TimeoutExpired branch."""
    review_dir = _init_review(tmp_path)
    provider_config = {"cli": str(FIXTURES / "fake_provider_hang.sh"), "timeout": 2}
    registry = codex_mod.ActiveProcessRegistry()
    codex_mod.run_provider(
        "p",
        provider_config,
        tmp_path / "prompt.md",
        review_dir,
        tmp_path,
        registry,
    )
    snap = registry.snapshot()
    assert all(item["provider"] != "p" for item in snap)

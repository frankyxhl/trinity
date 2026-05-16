"""TRN-2018 M1: live review metadata helpers.

These tests target `scripts._review_metadata` — a new module introduced by
this CHG. The module owns:

- atomic metadata.json read/write with json-decode retry
- per-review-dir threading.Lock for read-modify-write under
  concurrent_futures.ThreadPoolExecutor (run_providers parallelism)
- init_metadata / update_provider_state / finalize_metadata helpers

Tests are written RED first. After scripts/_review_metadata.py exists
with the spec'd helpers, they should all pass.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _review_metadata as rm  # noqa: E402


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def _init(tmp_path, providers=("glm", "deepseek"), **overrides):
    review_dir = tmp_path / "20260516-120000-test"
    review_dir.mkdir(parents=True)
    kwargs = dict(
        review_id=review_dir.name,
        review_dir_str=str(review_dir),
        providers=list(providers),
        preset={"resolved": "fast-review"},
        scope=".",
        root=str(tmp_path),
        input={"mode": "scope"},
    )
    kwargs.update(overrides)
    rm.init_metadata(review_dir, **kwargs)
    return review_dir


def test_init_metadata_writes_file_before_provider_execution(tmp_path):
    review_dir = _init(tmp_path)
    assert (review_dir / "metadata.json").exists()


def test_init_metadata_contains_review_id_review_dir_status_running(tmp_path):
    review_dir = _init(tmp_path)
    data = json.loads((review_dir / "metadata.json").read_text())
    assert data["review_id"] == review_dir.name
    assert data["review_dir"] == str(review_dir)
    assert data["status"] == "running"


def test_init_metadata_all_providers_queued(tmp_path):
    review_dir = _init(tmp_path, providers=("glm", "deepseek", "codex"))
    data = json.loads((review_dir / "metadata.json").read_text())
    for p in ("glm", "deepseek", "codex"):
        assert data["provider_states"][p]["status"] == "queued"


def test_init_metadata_has_started_at_iso_finished_at_null(tmp_path):
    review_dir = _init(tmp_path)
    data = json.loads((review_dir / "metadata.json").read_text())
    # ISO seconds format: 2026-05-16T12:00:00
    assert isinstance(data["started_at"], str) and "T" in data["started_at"]
    assert data["finished_at"] is None


def test_init_metadata_results_is_empty_list(tmp_path):
    review_dir = _init(tmp_path)
    data = json.loads((review_dir / "metadata.json").read_text())
    assert data["results"] == []


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def test_update_provider_state_queued_to_running_writes_pid_started_at(tmp_path):
    review_dir = _init(tmp_path)
    rm.update_provider_state(
        review_dir, "glm", status="running", pid=12345, started_at="2026-05-16T12:00:01"
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    glm = data["provider_states"]["glm"]
    assert glm["status"] == "running"
    assert glm["pid"] == 12345
    assert glm["started_at"] == "2026-05-16T12:00:01"


def test_update_provider_state_running_to_finished_writes_returncode_finished_at(
    tmp_path,
):
    review_dir = _init(tmp_path)
    rm.update_provider_state(review_dir, "glm", status="running", pid=99)
    rm.update_provider_state(
        review_dir,
        "glm",
        status="finished",
        returncode=0,
        finished_at="2026-05-16T12:01:00",
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    glm = data["provider_states"]["glm"]
    assert glm["status"] == "finished"
    assert glm["returncode"] == 0
    assert glm["finished_at"] == "2026-05-16T12:01:00"
    # pid is preserved from the previous update
    assert glm["pid"] == 99


def test_update_provider_state_running_to_failed_preserves_partial_log_paths(tmp_path):
    review_dir = _init(tmp_path)
    rm.update_provider_state(
        review_dir,
        "glm",
        status="running",
        pid=99,
        stdout_path="logs/glm.stdout.log",
        stderr_path="logs/glm.stderr.log",
    )
    rm.update_provider_state(
        review_dir, "glm", status="failed", returncode=2, finished_at="t"
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    glm = data["provider_states"]["glm"]
    assert glm["status"] == "failed"
    assert glm["stdout_path"] == "logs/glm.stdout.log"
    assert glm["stderr_path"] == "logs/glm.stderr.log"


def test_update_provider_state_running_to_timed_out_writes_returncode_124(tmp_path):
    review_dir = _init(tmp_path)
    rm.update_provider_state(review_dir, "glm", status="running", pid=99)
    rm.update_provider_state(
        review_dir, "glm", status="timed_out", returncode=124, finished_at="t"
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    glm = data["provider_states"]["glm"]
    assert glm["status"] == "timed_out"
    assert glm["returncode"] == 124


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def _finalize_after_all(tmp_path, terminal_states):
    review_dir = _init(tmp_path, providers=tuple(terminal_states.keys()))
    results = []
    for provider, terminal in terminal_states.items():
        rc = {"finished": 0, "failed": 2, "timed_out": 124}[terminal]
        rm.update_provider_state(
            review_dir,
            provider,
            status=terminal,
            returncode=rc,
            finished_at=f"t-{provider}",
        )
        results.append(
            {
                "provider": provider,
                "returncode": rc,
                "raw": f"raw/{provider}.txt",
                "started_at": "t",
                "finished_at": f"t-{provider}",
            }
        )
    rm.finalize_metadata(review_dir, results)
    return review_dir


def test_finalize_metadata_all_finished_top_status_finished(tmp_path):
    review_dir = _finalize_after_all(
        tmp_path, {"glm": "finished", "deepseek": "finished"}
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    assert data["status"] == "finished"
    assert data["finished_at"] is not None
    assert len(data["results"]) == 2


def test_finalize_metadata_any_failed_top_status_failed(tmp_path):
    review_dir = _finalize_after_all(
        tmp_path, {"glm": "finished", "deepseek": "failed"}
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    assert data["status"] == "failed"


def test_finalize_metadata_any_timed_out_top_status_timed_out(tmp_path):
    review_dir = _finalize_after_all(
        tmp_path, {"glm": "finished", "deepseek": "timed_out"}
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    # Precedence per plan: failed > timed_out > finished. No 'failed' here, so timed_out.
    assert data["status"] == "timed_out"


# ---------------------------------------------------------------------------
# Atomic writes under contention
# ---------------------------------------------------------------------------


def test_update_provider_state_concurrent_writes_no_lost_update(tmp_path):
    """Two threads update different providers concurrently. Both updates land."""
    review_dir = _init(tmp_path, providers=("glm", "deepseek"))

    def write_glm():
        for i in range(20):
            rm.update_provider_state(review_dir, "glm", status="running", pid=i)

    def write_deepseek():
        for i in range(20):
            rm.update_provider_state(
                review_dir, "deepseek", status="running", pid=100 + i
            )

    t1 = threading.Thread(target=write_glm)
    t2 = threading.Thread(target=write_deepseek)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    data = json.loads((review_dir / "metadata.json").read_text())
    # Both providers ended up in running state with their last pid visible.
    # If RMW races silently, one provider's update_provider_state may have read
    # stale data and overwritten the other's progress.
    assert data["provider_states"]["glm"]["status"] == "running"
    assert data["provider_states"]["deepseek"]["status"] == "running"
    assert data["provider_states"]["glm"]["pid"] == 19
    assert data["provider_states"]["deepseek"]["pid"] == 119


# ---------------------------------------------------------------------------
# Backward compatibility (CHG §Backward compatibility)
# ---------------------------------------------------------------------------


def test_backwardcompat_providers_remains_list(tmp_path):
    review_dir = _init(tmp_path, providers=("glm", "deepseek"))
    data = json.loads((review_dir / "metadata.json").read_text())
    assert isinstance(data["providers"], list)
    assert data["providers"] == ["glm", "deepseek"]


def test_backwardcompat_results_finalized_entries_match_legacy_shape(tmp_path):
    """After finalize, each results[i] has exactly the legacy keys per
    scripts/codex.py:1732-1738 (run_provider's return dict)."""
    review_dir = _finalize_after_all(
        tmp_path, {"glm": "finished", "deepseek": "finished"}
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    legacy_keys = {"provider", "returncode", "raw", "started_at", "finished_at"}
    for entry in data["results"]:
        assert legacy_keys.issubset(entry.keys())


# ---------------------------------------------------------------------------
# append_result (R3 fix for codex R2 P2)
# ---------------------------------------------------------------------------


def test_append_result_appends_to_empty_results(tmp_path):
    review_dir = _init(tmp_path)
    rm.append_result(
        review_dir, {"provider": "glm", "returncode": 0, "raw": "raw/glm.txt"}
    )
    data = json.loads((review_dir / "metadata.json").read_text())
    assert len(data["results"]) == 1
    assert data["results"][0]["provider"] == "glm"


def test_append_result_preserves_prior_entries(tmp_path):
    review_dir = _init(tmp_path)
    rm.append_result(review_dir, {"provider": "glm", "returncode": 0})
    rm.append_result(review_dir, {"provider": "deepseek", "returncode": 2})
    data = json.loads((review_dir / "metadata.json").read_text())
    assert [r["provider"] for r in data["results"]] == ["glm", "deepseek"]


def test_append_result_no_op_when_metadata_missing(tmp_path):
    """Defensive: append_result silently no-ops when metadata.json absent.
    Mirrors update_provider_state for unit-test ergonomics."""
    review_dir = tmp_path / "bare"
    review_dir.mkdir()
    rm.append_result(review_dir, {"provider": "glm"})  # must not raise
    assert not (review_dir / "metadata.json").exists()


def test_finalize_overwrites_appended_results_with_canonical_order(tmp_path):
    """append_result + finalize: finalize replaces results with the
    canonical ordered list (matching `providers` order), so even if
    append_result wrote in completion-order, the final state matches
    the orchestrator's intent."""
    review_dir = _init(tmp_path, providers=("glm", "deepseek"))
    # Simulate provider completions in reverse order
    rm.append_result(
        review_dir,
        {
            "provider": "deepseek",
            "returncode": 0,
            "raw": "raw/deepseek.txt",
            "started_at": "t",
            "finished_at": "t",
        },
    )
    rm.append_result(
        review_dir,
        {
            "provider": "glm",
            "returncode": 0,
            "raw": "raw/glm.txt",
            "started_at": "t",
            "finished_at": "t",
        },
    )
    canonical = [
        {
            "provider": "glm",
            "returncode": 0,
            "raw": "raw/glm.txt",
            "started_at": "t",
            "finished_at": "t",
        },
        {
            "provider": "deepseek",
            "returncode": 0,
            "raw": "raw/deepseek.txt",
            "started_at": "t",
            "finished_at": "t",
        },
    ]
    rm.finalize_metadata(review_dir, canonical)
    data = json.loads((review_dir / "metadata.json").read_text())
    assert [r["provider"] for r in data["results"]] == ["glm", "deepseek"]


# ---------------------------------------------------------------------------
# Read-side resilience (DS-P2#3)
# ---------------------------------------------------------------------------


def test_read_metadata_retries_once_on_json_decode_error(tmp_path, monkeypatch):
    """Mock-based: read_text returns invalid JSON the first call, valid
    JSON the second. Asserts read_metadata's retry kicks in. Avoids the
    threading + sleep timing fragility of an end-to-end race simulation."""
    review_dir = tmp_path / "20260516-120000-x"
    review_dir.mkdir()
    metadata_path = review_dir / "metadata.json"
    metadata_path.write_text('{"status": "running"}')  # valid on disk

    original_read_text = Path.read_text
    calls = {"n": 0}

    def fake_read_text(self, *args, **kwargs):
        if self == metadata_path:
            calls["n"] += 1
            if calls["n"] == 1:
                return '{"status": "running"'  # truncated, invalid
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    data = rm.read_metadata(review_dir)
    assert data == {"status": "running"}
    assert calls["n"] >= 2, "expected retry after JSONDecodeError"


def test_read_metadata_raises_after_retry_exhausted(tmp_path):
    """If the file stays invalid past the retry window, read_metadata raises
    json.JSONDecodeError. The 100ms retry is for transient mid-writes, not
    indefinite tolerance."""
    review_dir = tmp_path / "20260516-120000-y"
    review_dir.mkdir()
    (review_dir / "metadata.json").write_text("not json at all")
    with pytest.raises(json.JSONDecodeError):
        rm.read_metadata(review_dir)

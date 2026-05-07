"""Tests for `trinity status [--latest]` (TRN-2028 / GitHub issue #35).

Each test sets up a fake `.trinity/reviews/` under tmp_path, populates it with
a metadata.json (and optionally synthesis.md / incomplete.json), invokes the
CLI as a subprocess, and asserts the rendered output.

The CLI is `python scripts/codex.py status --root <tmp_path>` so we can point
it at an isolated reviews directory without touching the project's real
`.trinity/reviews/`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CODEX_SCRIPT = REPO_ROOT / "scripts" / "codex.py"


def _run_status(root: Path, latest: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CODEX_SCRIPT), "status", "--root", str(root)]
    if latest:
        argv.append("--latest")
    return subprocess.run(argv, capture_output=True, text=True)


def _make_review(
    root: Path,
    name: str = "20260508-120000-rules",
    *,
    metadata: dict | None = None,
    write_synthesis: bool = True,
    incomplete: dict | None = None,
    metadata_text: str | None = None,
    raw_files: dict[str, str] | None = None,
) -> Path:
    """Materialize a fake review directory under <root>/.trinity/reviews/."""
    reviews_dir = root / ".trinity" / "reviews"
    review_dir = reviews_dir / name
    review_dir.mkdir(parents=True, exist_ok=True)
    if metadata_text is not None:
        (review_dir / "metadata.json").write_text(metadata_text)
    elif metadata is not None:
        (review_dir / "metadata.json").write_text(json.dumps(metadata))
    if write_synthesis:
        (review_dir / "synthesis.md").write_text("# synthesis\n")
    if incomplete is not None:
        (review_dir / "incomplete.json").write_text(json.dumps(incomplete))
    raw_dir = review_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for prov, body in (raw_files or {}).items():
        (raw_dir / f"{prov}.txt").write_text(body)
    return review_dir


def _basic_metadata(provider_returncodes: dict[str, int]) -> dict:
    return {
        "scope": "rules/",
        "root": "/fake",
        "providers": list(provider_returncodes.keys()),
        "preset": {
            "requested": "review",
            "resolved": "review",
            "source": "explicit",
            "task_type": "review",
            "skipped_optional_providers": [],
        },
        "input": {"mode": "working-tree", "scope": "rules/"},
        "results": [
            {
                "provider": prov,
                "returncode": rc,
                "raw": f"raw/{prov}.txt",
                "started_at": "2026-05-08T12:00:00",
                "finished_at": "2026-05-08T12:03:08",
            }
            for prov, rc in provider_returncodes.items()
        ],
    }


# ---------------------------------------------------------------------------
# T1: clean review dir → exits 0, "Status: completed", all providers rc=0.
# ---------------------------------------------------------------------------


def test_t1_clean_review_completed(tmp_path):
    _make_review(
        tmp_path,
        metadata=_basic_metadata({"glm": 0, "gemini": 0, "deepseek": 0}),
    )
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Status: completed" in out
    for prov in ("glm", "gemini", "deepseek"):
        assert prov in out
        assert "rc=0" in out
    assert "(timeout)" not in out


# ---------------------------------------------------------------------------
# T2: review with one rc=124 provider → "(timeout)" suffix on that line.
# ---------------------------------------------------------------------------


def test_t2_timeout_returncode_marks_provider(tmp_path):
    md = _basic_metadata({"glm": 0, "gemini": 124, "deepseek": 0})
    # Make gemini's elapsed obviously distinct
    md["results"][1]["finished_at"] = "2026-05-08T12:06:00"
    _make_review(tmp_path, metadata=md)
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "rc=124" in result.stdout
    assert "(timeout)" in result.stdout
    # Status is partial (non-zero rc, but no incomplete.json)
    assert "Status: partial" in result.stdout


# ---------------------------------------------------------------------------
# T3: review with incomplete.json → "Status: interrupted", surfaces .status.
# ---------------------------------------------------------------------------


def test_t3_incomplete_json_surfaces_status(tmp_path):
    md = _basic_metadata({"glm": 0, "deepseek": 0})
    _make_review(
        tmp_path,
        metadata=md,
        incomplete={"status": "interrupted", "review_dir": "fake"},
    )
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Incomplete: ✓ incomplete.json" in out
    assert "status=interrupted" in out
    assert "Status: interrupted" in out


# ---------------------------------------------------------------------------
# T4: review with no synthesis.md → "Synthesis: missing".
# ---------------------------------------------------------------------------


def test_t4_no_synthesis_marked_missing(tmp_path):
    _make_review(
        tmp_path,
        metadata=_basic_metadata({"glm": 0}),
        write_synthesis=False,
    )
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Synthesis: missing" in result.stdout


# ---------------------------------------------------------------------------
# T5: malformed metadata.json → exits rc=1 with clear error.
# ---------------------------------------------------------------------------


def test_t5_malformed_metadata_exits_nonzero(tmp_path):
    _make_review(tmp_path, metadata_text="{not valid json")
    result = _run_status(tmp_path)
    assert result.returncode == 1
    assert "malformed metadata" in result.stderr


# ---------------------------------------------------------------------------
# T6: empty .trinity/reviews/ → exits rc=1 with "no reviews".
# ---------------------------------------------------------------------------


def test_t6_empty_reviews_dir_exits_nonzero(tmp_path):
    (tmp_path / ".trinity" / "reviews").mkdir(parents=True)
    result = _run_status(tmp_path)
    assert result.returncode == 1
    assert "no reviews under" in result.stderr


# ---------------------------------------------------------------------------
# T7: missing .trinity/reviews/ entirely → exits rc=1 with "no reviews dir".
# ---------------------------------------------------------------------------


def test_t7_missing_reviews_dir_exits_nonzero(tmp_path):
    # tmp_path has no .trinity/ subdirectory at all.
    result = _run_status(tmp_path)
    assert result.returncode == 1
    assert "no reviews dir" in result.stderr


# ---------------------------------------------------------------------------
# T8: skipped optional providers → output lists each as "name (reason)".
# ---------------------------------------------------------------------------


def test_t8_skipped_optional_providers_rendered(tmp_path):
    md = _basic_metadata({"glm": 0, "deepseek": 0})
    md["preset"]["skipped_optional_providers"] = [
        {"provider": "codex", "reason": "missing config"},
        {"provider": "claude-code", "reason": "missing cli"},
    ]
    _make_review(tmp_path, metadata=md)
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Skipped optional:" in out
    assert "codex (missing config)" in out
    assert "claude-code (missing cli)" in out


# ---------------------------------------------------------------------------
# T9: in-progress review or partial-data per-provider entries (panel-added).
# ---------------------------------------------------------------------------


def test_t9a_in_progress_no_metadata(tmp_path):
    """Review dir exists but metadata.json hasn't been written yet."""
    review_dir = tmp_path / ".trinity" / "reviews" / "20260508-130000-foo"
    review_dir.mkdir(parents=True)
    # No metadata.json, no synthesis.md, no incomplete.json — bare dir.
    result = _run_status(tmp_path)
    assert result.returncode == 1
    assert "review in progress or no metadata" in result.stderr


def test_t9b_partial_data_per_provider_doesnt_crash(tmp_path):
    """A results[] entry missing started_at / finished_at / returncode keys
    should render '?' for those fields and not crash."""
    md = _basic_metadata({"glm": 0})
    # Strip per-provider keys to simulate a partial write.
    md["results"][0].pop("started_at")
    md["results"][0].pop("finished_at")
    md["results"][0].pop("returncode")
    _make_review(tmp_path, metadata=md)
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # The provider line itself must render ?-markers for rc and elapsed —
    # find the glm line specifically and assert on it (rather than any '?'
    # in the whole output, which could match Mode/Preset defaults).
    glm_lines = [
        line for line in out.splitlines() if "glm" in line and "elapsed" in line
    ]
    assert glm_lines, f"no glm provider line in output: {out!r}"
    glm_line = glm_lines[0]
    # The rc column AND the elapsed column must both render as bare '?'.
    # Regex on the glm line: name + marker + rc + 'elapsed' + duration.
    import re

    m = re.search(r"glm\s+✗\s+(\S+)\s+elapsed\s+(\S+)", glm_line)
    assert m, f"glm line didn't match expected shape: {glm_line!r}"
    rc_field, elapsed_field = m.group(1), m.group(2)
    assert rc_field == "?", f"expected rc='?', got {rc_field!r} in {glm_line!r}"
    assert elapsed_field == "?", (
        f"expected elapsed='?', got {elapsed_field!r} in {glm_line!r}"
    )


# ---------------------------------------------------------------------------
# T10 (panel-added — claude-code alignment regression):
# the provider name column must adapt to names longer than 10 chars
# (claude-code is 11 chars).
# ---------------------------------------------------------------------------


def test_t10_long_provider_name_aligns(tmp_path):
    md = _basic_metadata({"glm": 0, "claude-code": 0, "openrouter": 0, "deepseek": 0})
    _make_review(tmp_path, metadata=md)
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # Find each provider line; verify the marker character (✓/✗) appears at
    # the same column position across all four. If column width was hard-coded
    # to :10s, claude-code (11 chars) would push its marker right and break
    # alignment.
    provider_lines = [
        line
        for line in out.splitlines()
        if any(p in line for p in ("glm", "claude-code", "openrouter", "deepseek"))
        and "elapsed" in line
    ]
    assert len(provider_lines) == 4, (
        f"expected 4 provider lines, got {len(provider_lines)}: {provider_lines}"
    )
    marker_positions = [line.find("✓") for line in provider_lines]
    assert len(set(marker_positions)) == 1, (
        f"marker columns drifted: {list(zip(provider_lines, marker_positions))}"
    )


# ---------------------------------------------------------------------------
# T11 (panel-added — empty results semantics): zero providers ran → 'unknown'
# rather than 'completed'.
# ---------------------------------------------------------------------------


def test_t11_empty_results_renders_unknown(tmp_path):
    md = _basic_metadata({})  # no providers, results: []
    _make_review(tmp_path, metadata=md)
    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Status: unknown" in out
    assert "Status: completed" not in out
    assert "(no results in metadata)" in out

"""Unit tests for TRN-3028 synthesis summary helpers.

Covers:
- All four verdicts (ALL_PASS, NEEDS_FIXES, INCONCLUSIVE, LEGACY)
- Verdict precedence (INCONCLUSIVE > LEGACY > NEEDS_FIXES > ALL_PASS)
- Convergence: titles appearing across >=2 distinct providers
- Empty / whitespace titles ignored
- Mean score absent when no parsed scores
- _format_cli_summary line shape
- LEGACY mutually exclusive with NEEDS_FIXES (parsed FIX implies has_structured)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import codex as codex_mod  # noqa: E402

_compute_summary = codex_mod._compute_summary
_render_summary_block = codex_mod._render_summary_block
_format_cli_summary = codex_mod._format_cli_summary


def _result(provider, returncode=0):
    return {
        "provider": provider,
        "returncode": returncode,
        "raw": f"raw/{provider}.txt",
    }


def _parsed(decision="PASS", score=9.2, blocking=None, advisories=None, effective=None):
    p = {
        "decision": decision,
        "weighted_score": score,
        "blocking": blocking or [],
        "advisories": advisories or [],
    }
    p["effective_decision"] = effective or decision
    return p


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_all_pass_three_providers():
    results = [_result("a"), _result("b"), _result("c")]
    parsed = [_parsed(), _parsed(score=9.5), _parsed(score=9.0)]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "ALL_PASS"
    assert s["n_pass"] == 3
    assert s["n_fix"] == 0
    assert s["n_fail"] == 0
    assert s["total"] == 3
    assert s["mean_score"] is not None
    assert abs(s["mean_score"] - (9.2 + 9.5 + 9.0) / 3) < 1e-9


def test_needs_fixes_mixed():
    results = [_result("a"), _result("b")]
    parsed = [
        _parsed(),
        _parsed(
            decision="FIX",
            score=7.1,
            effective="FIX",
            blocking=[{"title": "bug", "evidence": "f:1"}],
        ),
    ]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "NEEDS_FIXES"
    assert s["n_pass"] == 1
    assert s["n_fix"] == 1
    assert s["n_blocking"] == 1


def test_inconclusive_one_failure():
    results = [_result("a"), _result("b", returncode=124), _result("c")]
    parsed = [_parsed(), None, _parsed()]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "INCONCLUSIVE"
    assert s["n_pass"] == 2
    assert s["n_fail"] == 1


def test_inconclusive_precedence_over_needs_fixes():
    results = [_result("a", returncode=1), _result("b")]
    parsed = [None, _parsed(decision="FIX", effective="FIX")]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "INCONCLUSIVE"


def test_legacy_no_structured():
    results = [_result("a"), _result("b")]
    parsed = [None, None]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "LEGACY"
    assert s["n_pass"] == 2
    assert s["mean_score"] is None


def test_legacy_excludes_needs_fixes():
    """LEGACY can't co-occur with FIX: any parsed FIX implies has_structured."""
    results = [_result("a"), _result("b")]
    parsed = [None, _parsed(decision="FIX", effective="FIX")]
    s = _compute_summary(results, parsed)
    assert s["verdict"] == "NEEDS_FIXES"
    assert s["verdict"] != "LEGACY"


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------


def test_convergence_two_providers_same_title():
    results = [_result("a"), _result("b")]
    parsed = [
        _parsed(blocking=[{"title": "Race condition", "evidence": "x:1"}]),
        _parsed(blocking=[{"title": "Race condition", "evidence": "y:2"}]),
    ]
    s = _compute_summary(results, parsed)
    assert s["convergence_count"] == 1


def test_convergence_three_providers_same_title():
    results = [_result("a"), _result("b"), _result("c")]
    parsed = [
        _parsed(blocking=[{"title": "Same bug", "evidence": "x:1"}]),
        _parsed(blocking=[{"title": "Same bug", "evidence": "y:2"}]),
        _parsed(blocking=[{"title": "Same bug", "evidence": "z:3"}]),
    ]
    s = _compute_summary(results, parsed)
    assert s["convergence_count"] == 1  # one distinct title


def test_convergence_same_title_one_provider_only():
    results = [_result("a"), _result("b")]
    parsed = [
        _parsed(
            blocking=[{"title": "Bug", "evidence": "x:1"}],
            advisories=[{"title": "Bug", "evidence": "x:2"}],
        ),
        _parsed(),
    ]
    s = _compute_summary(results, parsed)
    assert s["convergence_count"] == 0


def test_convergence_empty_titles_ignored():
    results = [_result("a"), _result("b")]
    parsed = [
        _parsed(blocking=[{"title": "", "evidence": "x:1"}]),
        _parsed(blocking=[{"title": "  ", "evidence": "y:2"}]),
    ]
    s = _compute_summary(results, parsed)
    assert s["convergence_count"] == 0


def test_convergence_blocking_and_advisory_match():
    results = [_result("a"), _result("b")]
    parsed = [
        _parsed(blocking=[{"title": "Same", "evidence": "x:1"}]),
        _parsed(advisories=[{"title": "Same", "evidence": "y:2"}]),
    ]
    s = _compute_summary(results, parsed)
    assert s["convergence_count"] == 1


# ---------------------------------------------------------------------------
# Mean score / counts
# ---------------------------------------------------------------------------


def test_mean_score_none_when_no_scores():
    results = [_result("a")]
    parsed = [None]
    s = _compute_summary(results, parsed)
    assert s["mean_score"] is None


def test_findings_counts():
    results = [_result("a")]
    parsed = [
        _parsed(
            blocking=[
                {"title": "B1", "evidence": "x:1"},
                {"title": "B2", "evidence": "x:2"},
            ],
            advisories=[{"title": "A1", "evidence": "x:3"}],
        )
    ]
    s = _compute_summary(results, parsed)
    assert s["n_blocking"] == 2
    assert s["n_advisories"] == 1


# ---------------------------------------------------------------------------
# CLI line format
# ---------------------------------------------------------------------------


def test_format_cli_summary_with_score():
    summary = {
        "verdict": "ALL_PASS",
        "n_pass": 3,
        "n_fix": 0,
        "n_fail": 0,
        "total": 3,
        "mean_score": 9.23,
        "n_blocking": 0,
        "n_advisories": 0,
        "convergence_count": 0,
    }
    line = _format_cli_summary(summary, Path("/tmp/x/synthesis.md"))
    assert line.startswith("trinity review: ALL_PASS — ")
    assert "3/3 PASS" in line
    assert "(mean 9.23)" in line
    assert "synthesis: /tmp/x/synthesis.md" in line


def test_format_cli_summary_without_score():
    summary = {
        "verdict": "LEGACY",
        "n_pass": 1,
        "n_fix": 0,
        "n_fail": 0,
        "total": 1,
        "mean_score": None,
        "n_blocking": 0,
        "n_advisories": 0,
        "convergence_count": 0,
    }
    line = _format_cli_summary(summary, Path("/tmp/y/synthesis.md"))
    assert "LEGACY" in line
    assert "mean" not in line


# ---------------------------------------------------------------------------
# Render block
# ---------------------------------------------------------------------------


def test_render_summary_block_legacy_uses_dashes():
    summary = {
        "verdict": "LEGACY",
        "n_pass": 2,
        "n_fix": 0,
        "n_fail": 0,
        "total": 2,
        "mean_score": None,
        "n_blocking": 0,
        "n_advisories": 0,
        "convergence_count": 0,
    }
    lines = _render_summary_block(summary)
    text = "\n".join(lines)
    assert "**Verdict**: LEGACY" in text
    assert "**Findings**: —" in text
    assert "**Convergence**: —" in text


def test_render_summary_block_all_pass_includes_findings_zero():
    summary = {
        "verdict": "ALL_PASS",
        "n_pass": 2,
        "n_fix": 0,
        "n_fail": 0,
        "total": 2,
        "mean_score": 9.1,
        "n_blocking": 0,
        "n_advisories": 0,
        "convergence_count": 0,
    }
    lines = _render_summary_block(summary)
    text = "\n".join(lines)
    assert "0 blocking · 0 advisories" in text
    assert "(mean score 9.10)" in text
    assert "**Convergence**: none" in text

"""Unit tests for TRN-3022 review result schema normalization.

Covers A1–A8i + edge cases:
- A1: parse returns dict on well-formed
- A2: parse returns None on malformed/missing/out-of-range/no-block
- A3: LAST block wins
- A4: forward-compat (unknown top-level + finding-level keys)
- A5: synthesis enriches Status column
- A6: Findings section only when >=1 structured
- A7: byte-identical legacy fallback
- A8: _review_schema_addendum("review") non-empty; "tdd"/None empty
- A8b: .agents/trinity.codex.json prompt_template UNCHANGED
- A8c: render_prompt(task_type="review") includes addendum; None/tdd do not
- A8d: stderr sentinel split
- A8d2: multi-line JSON regex (DOTALL)
- A8e: rc!=0 → FAIL <rc> regardless of structured
- A8e2: rc=124 + valid PASS → FAIL 124, parser returns dict but ignored
- A8f: effective_decision coercion (PASS+blocking, PASS+score<9)
- A8g: _safe_read_raw returns None on OSError/UnicodeDecodeError
- A8h: lazy-LLM literal placeholder rejected
- A8i: _REVIEW_PASS_THRESHOLD monkeypatch
- Numeric-bool rejection
- Markdown sanitization
- Raw-path resolution
- Findings ordering
- Empty-fix / empty-evidence rendering
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import codex as codex_mod  # noqa: E402

parse_structured_review = codex_mod.parse_structured_review
_validate_review_schema = codex_mod._validate_review_schema
_strip_stderr_region = codex_mod._strip_stderr_region
_safe_read_raw = codex_mod._safe_read_raw
_review_schema_addendum = codex_mod._review_schema_addendum
_render_findings_for = codex_mod._render_findings_for
write_synthesis = codex_mod.write_synthesis
render_prompt = codex_mod.render_prompt
_REVIEW_PASS_THRESHOLD = codex_mod._REVIEW_PASS_THRESHOLD
_STDERR_SENTINEL = codex_mod._STDERR_SENTINEL

# The §"Schema" valid example from the CHG (multi-line, real values).
SCHEMA_EXAMPLE = json.dumps(
    {
        "decision": "PASS",
        "weighted_score": 9.2,
        "blocking": [],
        "advisories": [
            {
                "title": "Late-binding closure in helper X",
                "evidence": "scripts/foo.py:142-148",
                "fix": "Capture loop var via default arg",
            }
        ],
        "confidence": 0.85,
    },
    indent=2,
)

WELL_FORMED_BLOCK = f"Review prose here.\n\n```json\n{SCHEMA_EXAMPLE}\n```"


def _make_result(provider, returncode=0, raw="raw/glm.txt"):
    return {
        "provider": provider,
        "returncode": returncode,
        "raw": raw,
        "started_at": "2026-01-01T00:00:00",
        "finished_at": "2026-01-01T00:01:00",
    }


# ---------------------------------------------------------------------------
# A1: well-formed parse
# ---------------------------------------------------------------------------


def test_a1_well_formed_returns_dict():
    result = parse_structured_review(WELL_FORMED_BLOCK)
    assert result is not None
    assert result["decision"] == "PASS"
    assert result["weighted_score"] == 9.2
    assert result["effective_decision"] == "PASS"
    assert result["advisories"][0]["title"] == "Late-binding closure in helper X"


# ---------------------------------------------------------------------------
# A2: malformed / missing / out-of-range / no-block
# ---------------------------------------------------------------------------


def test_a2_malformed_json_returns_none():
    text = "```json\n{not valid json}\n```"
    assert parse_structured_review(text) is None


def test_a2_missing_decision_returns_none():
    text = '```json\n{"weighted_score": 9.0, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_a2_missing_weighted_score_returns_none():
    text = '```json\n{"decision": "PASS", "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_a2_score_out_of_range_returns_none():
    text = '```json\n{"decision": "PASS", "weighted_score": 11.0, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_a2_negative_score_returns_none():
    text = '```json\n{"decision": "PASS", "weighted_score": -1.0, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_a2_no_block_returns_none():
    assert parse_structured_review("Just prose, no JSON block.") is None


def test_a2_blocking_null_returns_none():
    text = '```json\n{"decision": "PASS", "weighted_score": 9.0, "blocking": null, "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_a2_missing_title_in_finding_returns_none():
    text = '```json\n{"decision": "FIX", "weighted_score": 7.0, "blocking": [{"evidence": "f:1"}], "advisories": []}\n```'
    assert parse_structured_review(text) is None


# ---------------------------------------------------------------------------
# A3: LAST block wins
# ---------------------------------------------------------------------------


def test_a3_last_block_wins():
    first = json.dumps(
        {"decision": "FIX", "weighted_score": 5.0, "blocking": [], "advisories": []}
    )
    second = json.dumps(
        {"decision": "PASS", "weighted_score": 9.5, "blocking": [], "advisories": []}
    )
    text = f"```json\n{first}\n```\n\nSome prose\n\n```json\n{second}\n```"
    result = parse_structured_review(text)
    assert result is not None
    assert result["weighted_score"] == 9.5


# ---------------------------------------------------------------------------
# A4: forward-compat (unknown keys)
# ---------------------------------------------------------------------------


def test_a4_unknown_top_level_keys_ignored():
    text = (
        "```json\n"
        + json.dumps(
            {
                "decision": "PASS",
                "weighted_score": 9.0,
                "blocking": [],
                "advisories": [],
                "future_field": "ignored",
            }
        )
        + "\n```"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert "future_field" in result


def test_a4_unknown_finding_level_keys_ignored():
    text = (
        "```json\n"
        + json.dumps(
            {
                "decision": "FIX",
                "weighted_score": 7.0,
                "blocking": [{"title": "bug", "evidence": "f:1", "severity": "high"}],
                "advisories": [],
            }
        )
        + "\n```"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert result["blocking"][0]["severity"] == "high"


# ---------------------------------------------------------------------------
# A5: synthesis enriches Status column
# ---------------------------------------------------------------------------


def test_a5_enriched_pass_status(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(WELL_FORMED_BLOCK)
    results = [_make_result("glm", returncode=0, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "PASS (9.2)" in content


def test_a5_enriched_fix_status(tmp_path):
    fix_block = json.dumps(
        {
            "decision": "FIX",
            "weighted_score": 7.1,
            "blocking": [{"title": "bug", "evidence": "f:1"}],
            "advisories": [],
        }
    )
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(f"```json\n{fix_block}\n```")
    results = [_make_result("glm", returncode=0, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "FIX (7.1, 1 blocking)" in content


# ---------------------------------------------------------------------------
# A6: Findings section only when >=1 structured
# ---------------------------------------------------------------------------


def test_a6_findings_present_when_structured(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(WELL_FORMED_BLOCK)
    (raw_dir / "codex.txt").write_text("just prose")
    results = [
        _make_result("glm", returncode=0, raw="raw/glm.txt"),
        _make_result("codex", returncode=0, raw="raw/codex.txt"),
    ]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "## Findings" in content
    assert "### glm" in content
    # codex has no structured block → no findings subsection
    assert "### codex" not in content


def test_a6_no_findings_when_all_legacy(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text("just prose")
    results = [_make_result("glm", returncode=0, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "## Findings" not in content


# ---------------------------------------------------------------------------
# A7: byte-identical legacy fallback
# ---------------------------------------------------------------------------


def test_a7_byte_identical_legacy(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text("just prose")
    results = [_make_result("glm", returncode=0, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    expected_lines = [
        "# Trinity Review Synthesis",
        "",
        "Scope: spikes/test",
        "",
        "## Provider Status",
        "",
        "| Provider | Status | Raw Output |",
        "|----------|--------|------------|",
        "| glm | PASS | `raw/glm.txt` |",
        "",
        "## Notes",
        "",
        "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
        "",
    ]
    assert content == "\n".join(expected_lines) + "\n"


# ---------------------------------------------------------------------------
# A8: _review_schema_addendum task-type guard
# ---------------------------------------------------------------------------


def test_a8_review_returns_nonempty():
    text = _review_schema_addendum("review")
    assert text != ""
    assert "decision" in text
    assert "weighted_score" in text


def test_a8_tdd_returns_empty():
    assert _review_schema_addendum("tdd") == ""


def test_a8_none_returns_empty():
    assert _review_schema_addendum(None) == ""


# ---------------------------------------------------------------------------
# A8b: .agents/trinity.codex.json prompt_template UNCHANGED
# ---------------------------------------------------------------------------


def test_a8b_template_unchanged():
    config_path = ROOT / ".agents" / "trinity.codex.json"
    config = json.loads(config_path.read_text())
    template = config.get("review", {}).get("prompt_template", "")
    assert "Structured Output" not in template
    assert "decision" not in template


# ---------------------------------------------------------------------------
# A8c: render_prompt task_type gating
# ---------------------------------------------------------------------------


def test_a8c_review_includes_addendum():
    config = {"review": {"prompt_template": "{diff}\n{files}"}}
    review_input = {"diff": "diff content", "files": "file content"}
    prompt = render_prompt(
        config, ROOT, "spikes/test", review_input, task_type="review"
    )
    assert "Structured Output" in prompt


def test_a8c_none_excludes_addendum():
    config = {"review": {"prompt_template": "{diff}\n{files}"}}
    review_input = {"diff": "diff content", "files": "file content"}
    prompt = render_prompt(config, ROOT, "spikes/test", review_input, task_type=None)
    assert "Structured Output" not in prompt


def test_a8c_tdd_excludes_addendum():
    config = {"review": {"prompt_template": "{diff}\n{files}"}}
    review_input = {"diff": "diff content", "files": "file content"}
    prompt = render_prompt(config, ROOT, "spikes/test", review_input, task_type="tdd")
    assert "Structured Output" not in prompt


# ---------------------------------------------------------------------------
# A8d: stderr sentinel split
# ---------------------------------------------------------------------------


def test_a8d_stderr_block_ignored():
    stdout_json = json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.0,
            "blocking": [],
            "advisories": [],
        }
    )
    stderr_json = json.dumps(
        {
            "decision": "FIX",
            "weighted_score": 3.0,
            "blocking": [{"title": "stderr bug", "evidence": "f:1"}],
            "advisories": [],
        }
    )
    text = f"```json\n{stdout_json}\n```{_STDERR_SENTINEL}```json\n{stderr_json}\n```"
    result = parse_structured_review(text)
    assert result is not None
    assert result["weighted_score"] == 9.0


def test_a8d4_raw_output_always_appends_sentinel():
    """raw_output() must ALWAYS append the sentinel, even when stderr is
    empty, so _strip_stderr_region (which uses rfind) can rely on the
    sentinel being a real delimiter rather than possibly absent.
    """
    raw_output = codex_mod.raw_output
    assert raw_output("hello", "") == "hello" + _STDERR_SENTINEL
    assert raw_output("hello", None) == "hello" + _STDERR_SENTINEL
    assert raw_output("hello", "err") == "hello" + _STDERR_SENTINEL + "err"
    assert raw_output("", "err") == _STDERR_SENTINEL + "err"
    # No sentinel-in-stdout false-positive even with empty stderr:
    raw = raw_output("a```json\n{}\n```\nfoo bar baz", "")
    assert raw.endswith(_STDERR_SENTINEL), "appended sentinel must be at the END"


def test_a8d3_stdout_quoting_legacy_marker_does_not_truncate():
    """Stdout may contain the legacy '\\n[stderr]\\n' string (e.g., a
    reviewer quoting prior raw-output format). The actual sentinel is a
    unique hex-tagged marker, so legacy text in stdout cannot be confused
    with the boundary.
    """
    real_json = json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.5,
            "blocking": [],
            "advisories": [],
        }
    )
    text = (
        "Reviewer prose discussing the delimiter:\n[stderr]\nthen the actual\n"
        f"verdict block follows.\n\n```json\n{real_json}\n```"
        + _STDERR_SENTINEL
        + "actual stderr content here"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert result["weighted_score"] == 9.5


def test_a8d5_stderr_side_json_block_ignored():
    """Bot R9 scenario: stderr contains a fenced JSON block. The unique
    sentinel guarantees rfind() locks onto the appended boundary, so
    stderr-side blocks never enter the parse region.
    """
    stderr_json = json.dumps(
        {
            "decision": "FIX",
            "weighted_score": 3.0,
            "blocking": [{"title": "stderr-side noise", "evidence": "f:1"}],
            "advisories": [],
        }
    )
    # Stdout has no schema; stderr has a FIX verdict.
    raw_output = codex_mod.raw_output
    text = raw_output(
        "ordinary review prose with no fenced verdict",
        f"warning: deprecated\n```json\n{stderr_json}\n```",
    )
    result = parse_structured_review(text)
    assert result is None, "stderr-side JSON must be ignored"


def test_a8d6_sentinel_is_unique_marker():
    """The sentinel must be unique enough that ordinary provider output
    cannot collide with it (TRN-3022 R10 hardening).
    """
    assert "TRINITY-RAW-STDERR-BOUNDARY" in _STDERR_SENTINEL
    # Any legacy-format text must NOT be the sentinel:
    assert _STDERR_SENTINEL != "\n[stderr]\n"


# ---------------------------------------------------------------------------
# A8d2: multi-line JSON regex (DOTALL) — uses §"Schema" example
# ---------------------------------------------------------------------------


def test_a8d2_multiline_json_parsed():
    """All 4 panel reviewers caught the missing DOTALL flag in v2.
    This test would have caught it: the §"Schema" example is multi-line."""
    text = f"Some review text\n\n```json\n{SCHEMA_EXAMPLE}\n```\n"
    result = parse_structured_review(text)
    assert result is not None
    assert result["decision"] == "PASS"
    assert result["weighted_score"] == 9.2
    assert result["confidence"] == 0.85


# ---------------------------------------------------------------------------
# A8e: returncode precedence
# ---------------------------------------------------------------------------


def test_a8e_rc_nonzero_fail_regardless_of_structured(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(WELL_FORMED_BLOCK)
    results = [_make_result("glm", returncode=1, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "FAIL 1" in content
    assert "PASS (9.2)" not in content


def test_a8e_rc124_timeout_fail(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(WELL_FORMED_BLOCK)
    results = [_make_result("glm", returncode=124, raw="raw/glm.txt")]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    assert "FAIL 124" in content
    assert "## Findings" not in content


# ---------------------------------------------------------------------------
# A8e2: rc=124 + valid JSON → parser returns dict but caller ignores
# ---------------------------------------------------------------------------


def test_a8e2_parser_accepts_well_formed_pass_regardless_of_caller_rc():
    """Parser is rc-agnostic: it returns the dict even for timeout output.
    The caller (write_synthesis) decides whether to use it."""
    result = parse_structured_review(WELL_FORMED_BLOCK)
    assert result is not None
    assert result["decision"] == "PASS"


# ---------------------------------------------------------------------------
# A8f: effective_decision coercion
# ---------------------------------------------------------------------------


def test_a8f_pass_with_blocking_coerced_to_fix():
    text = (
        "```json\n"
        + json.dumps(
            {
                "decision": "PASS",
                "weighted_score": 9.5,
                "blocking": [{"title": "bug", "evidence": "f:1"}],
                "advisories": [],
            }
        )
        + "\n```"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert result["decision"] == "PASS"
    assert result["effective_decision"] == "FIX"


def test_a8f_pass_with_low_score_coerced_to_fix():
    text = (
        "```json\n"
        + json.dumps(
            {
                "decision": "PASS",
                "weighted_score": 8.5,
                "blocking": [],
                "advisories": [],
            }
        )
        + "\n```"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert result["decision"] == "PASS"
    assert result["effective_decision"] == "FIX"


# ---------------------------------------------------------------------------
# A8g: _safe_read_raw
# ---------------------------------------------------------------------------


def test_a8g_missing_file_returns_none(tmp_path):
    assert _safe_read_raw(tmp_path / "nonexistent.txt") is None


def test_a8g_unicode_decode_error_returns_none(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
    assert _safe_read_raw(bad) is None


def test_a8g_valid_file_returns_text(tmp_path):
    f = tmp_path / "good.txt"
    f.write_text("hello")
    assert _safe_read_raw(f) == "hello"


# ---------------------------------------------------------------------------
# A8h: lazy-LLM placeholder rejected
# ---------------------------------------------------------------------------


def test_a8h_literal_placeholder_rejected():
    text = '```json\n{"decision": "PASS" | "FIX", "weighted_score": 9.0, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


# ---------------------------------------------------------------------------
# A8i: _REVIEW_PASS_THRESHOLD monkeypatch
# ---------------------------------------------------------------------------


def test_a8i_threshold_monkeypatch(monkeypatch):
    """Both coercion and addendum must use the constant."""
    monkeypatch.setattr(codex_mod, "_REVIEW_PASS_THRESHOLD", 7.0)

    # Coercion: score 8.0 is now >= 7.0, so PASS stays PASS.
    text = (
        "```json\n"
        + json.dumps(
            {
                "decision": "PASS",
                "weighted_score": 8.0,
                "blocking": [],
                "advisories": [],
            }
        )
        + "\n```"
    )
    result = parse_structured_review(text)
    assert result is not None
    assert result["effective_decision"] == "PASS"

    # Addendum reflects new threshold.
    addendum = _review_schema_addendum("review")
    assert ">= 7.0" in addendum


# ---------------------------------------------------------------------------
# Numeric-bool rejection
# ---------------------------------------------------------------------------


def test_numeric_bool_weighted_score_rejected():
    text = '```json\n{"decision": "PASS", "weighted_score": true, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_numeric_bool_confidence_rejected():
    text = '```json\n{"decision": "PASS", "weighted_score": 9.0, "blocking": [], "advisories": [], "confidence": true}\n```'
    assert parse_structured_review(text) is None


def test_nan_weighted_score_rejected():
    text = '```json\n{"decision": "PASS", "weighted_score": NaN, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_infinity_weighted_score_rejected():
    text = '```json\n{"decision": "PASS", "weighted_score": Infinity, "blocking": [], "advisories": []}\n```'
    assert parse_structured_review(text) is None


def test_nan_confidence_rejected():
    text = '```json\n{"decision": "PASS", "weighted_score": 9.5, "blocking": [], "advisories": [], "confidence": NaN}\n```'
    assert parse_structured_review(text) is None


def test_addendum_score_range_uses_full_domain():
    """Score domain (0.0-10.0) is independent of PASS threshold (9.0)."""
    addendum = _review_schema_addendum("review")
    assert "0.0-10.0" in addendum
    assert "0.0-9.0" not in addendum


def test_addendum_concrete_example_is_valid_json():
    """The example block in the addendum must parse — providers may copy it."""
    addendum = _review_schema_addendum("review")
    import re

    blocks = re.findall(r"```json\n(.*?)\n```", addendum, re.DOTALL)
    assert blocks, "addendum must contain at least one ```json block"
    for block in blocks:
        data = json.loads(block)
        assert _validate_review_schema(data), (
            f"example block does not validate: {block}"
        )


def test_oversized_int_weighted_score_rejected_without_raising():
    """Huge ints would raise OverflowError in math.isfinite — must not propagate."""
    huge = "9" * 1000
    text = f'```json\n{{"decision": "PASS", "weighted_score": {huge}, "blocking": [], "advisories": []}}\n```'
    assert parse_structured_review(text) is None


def test_oversized_int_confidence_rejected_without_raising():
    huge = "9" * 1000
    text = f'```json\n{{"decision": "PASS", "weighted_score": 9.5, "blocking": [], "advisories": [], "confidence": {huge}}}\n```'
    assert parse_structured_review(text) is None


# ---------------------------------------------------------------------------
# Markdown sanitization
# ---------------------------------------------------------------------------


def test_markdown_newlines_stripped_in_title(tmp_path):
    parsed = {
        "effective_decision": "FIX",
        "weighted_score": 7.0,
        "blocking": [{"title": "bug\ninjection", "evidence": "f:1"}],
        "advisories": [],
    }
    lines = _render_findings_for(
        _make_result("glm", returncode=0),
        parsed,
    )
    joined = "\n".join(lines)
    assert "bug\ninjection" not in joined
    assert "bug injection" in joined


# ---------------------------------------------------------------------------
# Raw-path resolution
# ---------------------------------------------------------------------------


def test_raw_path_relative_to_review_dir(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text(WELL_FORMED_BLOCK)
    # result["raw"] is "raw/glm.txt" (relative to review_dir)
    raw_path = tmp_path / "raw" / "glm.txt"
    text = _safe_read_raw(raw_path)
    assert text is not None
    assert "decision" in text


# ---------------------------------------------------------------------------
# Findings ordering matches results iteration
# ---------------------------------------------------------------------------


def test_findings_ordering_matches_results(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for name in ("glm", "codex", "deepseek"):
        block = json.dumps(
            {
                "decision": "FIX",
                "weighted_score": 7.0,
                "blocking": [{"title": f"{name} bug", "evidence": "f:1"}],
                "advisories": [],
            }
        )
        (raw_dir / f"{name}.txt").write_text(f"```json\n{block}\n```")

    results = [
        _make_result("glm", returncode=0, raw="raw/glm.txt"),
        _make_result("codex", returncode=0, raw="raw/codex.txt"),
        _make_result("deepseek", returncode=0, raw="raw/deepseek.txt"),
    ]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    glm_pos = content.index("### glm")
    codex_pos = content.index("### codex")
    deepseek_pos = content.index("### deepseek")
    assert glm_pos < codex_pos < deepseek_pos


# ---------------------------------------------------------------------------
# Empty-fix / empty-evidence rendering
# ---------------------------------------------------------------------------


def test_empty_fix_omits_emdash():
    parsed = {
        "effective_decision": "FIX",
        "weighted_score": 7.0,
        "blocking": [{"title": "bug", "evidence": "f:1"}],
        "advisories": [],
    }
    lines = _render_findings_for(_make_result("glm"), parsed)
    # Only check finding bullet lines (skip headline with " — FIX")
    bullet_lines = [line for line in lines if line.startswith("- **")]
    assert len(bullet_lines) == 1
    # No " — " em-dash separator in the bullet (fix is absent).
    assert " — " not in bullet_lines[0]


def test_empty_evidence_renders_no_evidence_cited():
    parsed = {
        "effective_decision": "FIX",
        "weighted_score": 7.0,
        "blocking": [{"title": "cross-cutting", "evidence": ""}],
        "advisories": [],
    }
    lines = _render_findings_for(_make_result("glm"), parsed)
    joined = "\n".join(lines)
    assert "(no evidence cited)" in joined


# ---------------------------------------------------------------------------
# Fuzz test: never raises
# ---------------------------------------------------------------------------


def test_fuzz_random_bytes_never_raises():
    import os

    for _ in range(50):
        raw = os.urandom(256).decode("latin-1")
        # Must not raise.
        parse_structured_review(raw)


# ---------------------------------------------------------------------------
# Case-insensitive decision
# ---------------------------------------------------------------------------


def test_case_insensitive_decision():
    text = '```json\n{"decision": "pass", "weighted_score": 9.0, "blocking": [], "advisories": []}\n```'
    result = parse_structured_review(text)
    assert result is not None
    assert result["decision"] == "PASS"


# ---------------------------------------------------------------------------
# Fix 4: Multi-provider all-legacy A7 byte-identical
# ---------------------------------------------------------------------------


def test_a7_multi_provider_all_legacy_byte_identical(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "glm.txt").write_text("just prose from glm")
    (raw_dir / "codex.txt").write_text("just prose from codex")
    (raw_dir / "deepseek.txt").write_text("just prose from deepseek")
    results = [
        _make_result("glm", returncode=0, raw="raw/glm.txt"),
        _make_result("codex", returncode=0, raw="raw/codex.txt"),
        _make_result("deepseek", returncode=0, raw="raw/deepseek.txt"),
    ]
    write_synthesis(tmp_path, "spikes/test", results)
    content = (tmp_path / "synthesis.md").read_text()
    expected_lines = [
        "# Trinity Review Synthesis",
        "",
        "Scope: spikes/test",
        "",
        "## Provider Status",
        "",
        "| Provider | Status | Raw Output |",
        "|----------|--------|------------|",
        "| glm | PASS | `raw/glm.txt` |",
        "| codex | PASS | `raw/codex.txt` |",
        "| deepseek | PASS | `raw/deepseek.txt` |",
        "",
        "## Notes",
        "",
        "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
        "",
    ]
    assert content == "\n".join(expected_lines) + "\n"


# ---------------------------------------------------------------------------
# Fix 5: _validate_review_schema NaN/Inf rejection
# ---------------------------------------------------------------------------


def test_validate_review_schema_rejects_nan_weighted_score():
    data = {
        "decision": "PASS",
        "weighted_score": float("nan"),
        "blocking": [],
        "advisories": [],
    }
    assert _validate_review_schema(data) is False


def test_validate_review_schema_rejects_inf_weighted_score():
    data = {
        "decision": "PASS",
        "weighted_score": float("inf"),
        "blocking": [],
        "advisories": [],
    }
    assert _validate_review_schema(data) is False


# ---------------------------------------------------------------------------
# Fix 7: _review_schema_addendum accepts uppercase task_type
# ---------------------------------------------------------------------------


def test_review_schema_addendum_accepts_uppercase_task_type():
    text = _review_schema_addendum("REVIEW")
    assert text != ""
    assert "decision" in text

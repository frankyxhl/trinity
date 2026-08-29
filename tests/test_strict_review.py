"""Characterization tests for resolve_strict_review (TRN-3052).

Pins the five contract rows of the strict-review resolver: disabled path,
pair-mismatch, malformed id, unsupported combo, and the full happy-path
envelope consumed by write_synthesis.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _review  # noqa: E402


def _args(sop, rubric):
    return argparse.Namespace(sop=sop, rubric=rubric)


CHG_3052_ERROR_CASES = [
    (None, None, None),  # both missing → disabled
    ("", "", None),  # empty strings → disabled (bool("") is False)
    ("COR-1602", None, "must be used together"),  # one-side mismatch
    ("cor1602", "COR-1609", "must look like"),  # malformed id (no hyphen)
    ("COR-1602", "COR-1610", "unsupported strict review template"),  # unknown combo
]


@pytest.mark.parametrize("sop,rubric,expected", CHG_3052_ERROR_CASES)
def test_strict_review_error_paths(sop, rubric, expected):
    """None/error rows: None path, pair-mismatch, malformed id, unsupported combo."""
    if expected is None:
        assert _review.resolve_strict_review(_args(sop, rubric)) is None
    else:
        with pytest.raises(SystemExit, match=re.escape(expected)):
            _review.resolve_strict_review(_args(sop, rubric))


CHG_3052_HAPPY_CASES = [
    ("COR-1602", "COR-1609"),
    ("cor-1602", "cor-1609"),  # lowercase → normalized by normalize_review_doc_id
]


@pytest.mark.parametrize("sop,rubric", CHG_3052_HAPPY_CASES)
def test_strict_review_happy_path(sop, rubric):
    """Happy-path envelope: all fields match the sole registry entry."""
    result = _review.resolve_strict_review(_args(sop, rubric))
    assert result is not None
    assert result["enabled"] is True
    assert result["pass_threshold"] == 9.0
    assert result["pass_threshold"] == result["template"]["pass_threshold"]
    assert result["calibration"] == "COR-1611"
    # Equality, not identity: the envelope carries a list() copy of the schema.
    assert result["output_schema"] == _review.STRICT_REVIEW_OUTPUT_SCHEMA
    assert result["sop"] == "COR-1602"
    assert result["rubric"] == "COR-1609"
    assert len(result["template"]["criteria"]) == 5
    assert ">= 9.0" in result["template"]["decision_rule"]

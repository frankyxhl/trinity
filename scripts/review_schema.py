"""Structured review-result parsing helpers for Trinity synthesis."""

import json
import math
import re

try:
    from .provider_runtime import _STDERR_SENTINEL
except ImportError:
    from provider_runtime import _STDERR_SENTINEL


_REVIEW_PASS_THRESHOLD = 9.5


# ---------------------------------------------------------------------------
# TRN-3022: structured review result schema — parser + helpers
# ---------------------------------------------------------------------------

_SCHEMA_BLOCK_RE = re.compile(
    r"(?ims)^```json\s*$\n(.*?)\n^```\s*$",
)


def _strip_stderr_region(text):
    """Strip the stderr tail appended by raw_output().

    TRN-3022 coupling: the sentinel _STDERR_SENTINEL is a unique marker
    written by provider_runtime.raw_output(). It contains a random hex tag,
    so a colliding string in either stdout or stderr is astronomically
    unlikely. The pre-sentinel region (stdout) is scanned for structured
    blocks. If absent (custom raw-output writers), the full text is returned.
    """
    idx = text.rfind(_STDERR_SENTINEL)
    if idx == -1:
        return text
    return text[:idx]


def _safe_read_raw(path):
    """Read a raw provider file, returning text or None on failure.

    Catches OSError (file deleted/moved between run and synthesis) and
    UnicodeDecodeError (corrupt bytes). Returns None on failure — caller
    falls through to legacy rendering.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _validate_review_schema(data):
    """Validate a parsed JSON dict against the TRN-3022 review schema.

    Returns True if valid, False otherwise. Never raises.
    Checks: top-level dict, required fields, types, ranges, finding shapes.
    Unknown top-level and finding-level keys are ignored (forward-compat).
    Rejects numeric bools (isinstance(True, int) is True in Python).
    """
    if not isinstance(data, dict):
        return False

    # decision
    decision = data.get("decision")
    if not isinstance(decision, str) or decision.upper() not in ("PASS", "FIX"):
        return False

    # weighted_score — reject bools (True/False are int subclasses) and NaN/Inf.
    # math.isfinite() on huge ints raises OverflowError, so guard with isinstance(float).
    # Ints are always finite by definition; oversized ints fall through to range check.
    ws = data.get("weighted_score")
    if isinstance(ws, bool) or not isinstance(ws, (int, float)):
        return False
    if isinstance(ws, float) and not math.isfinite(ws):
        return False
    if ws < 0.0 or ws > 10.0:
        return False

    # blocking and advisories
    for key in ("blocking", "advisories"):
        val = data.get(key)
        if not isinstance(val, list):
            return False
        for item in val:
            if not isinstance(item, dict):
                return False
            if not isinstance(item.get("title"), str):
                return False
            if not isinstance(item.get("evidence"), str):
                return False
            # fix is optional; if present must be str
            fix = item.get("fix")
            if fix is not None and not isinstance(fix, str):
                return False

    # confidence (optional) — reject bools and NaN/Inf (same overflow guard as weighted_score).
    conf = data.get("confidence")
    if conf is not None:
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            return False
        if isinstance(conf, float) and not math.isfinite(conf):
            return False
        if conf < 0.0 or conf > 1.0:
            return False

    return True


def parse_structured_review(raw_text, pass_threshold=None):
    """Parse a structured review schema block from raw provider output.

    Returns a dict with schema fields + effective_decision, or None on any
    failure. Never raises — synthesis must work on malformed provider output.

    Steps:
      1. Strip stderr region via _strip_stderr_region.
      2. Find last fenced ```json block via regex (DOTALL).
      3. json.loads contents.
      4. Validate via _validate_review_schema.
      5. Coerce effective_decision if needed.
    """
    try:
        effective_threshold = (
            pass_threshold if pass_threshold is not None else _REVIEW_PASS_THRESHOLD
        )
        stdout_region = _strip_stderr_region(raw_text)

        matches = _SCHEMA_BLOCK_RE.findall(stdout_region)
        if not matches:
            return None

        last_block = matches[-1]
        data = json.loads(last_block)

        if not _validate_review_schema(data):
            return None

        # Normalize decision to uppercase.
        data["decision"] = data["decision"].upper()

        # Effective-decision coercion.
        if data["decision"] == "PASS" and (
            data["blocking"] or data["weighted_score"] < effective_threshold
        ):
            data["effective_decision"] = "FIX"
        else:
            data["effective_decision"] = data["decision"]

        return data
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _review_schema_addendum(task_type, strict_review=None, pass_threshold=None):
    """Return the structured-output prompt addendum for review task types.

    Returns empty string for non-review task types (tdd, prp, general, None).
    Addendum is appended at the end of the rendered prompt so providers emit
    the JSON block as the LAST thing in their output.
    """
    task_type = (task_type or "").lower()
    if task_type != "review":
        return ""

    threshold = (
        strict_review["pass_threshold"]
        if strict_review is not None
        else (pass_threshold if pass_threshold is not None else _REVIEW_PASS_THRESHOLD)
    )
    return (
        "\n## Required: Structured Output\n"
        "\n"
        "After your free-form review, emit EXACTLY ONE fenced JSON block at the END\n"
        'of your output. Required fields: `decision` ("PASS" or "FIX"),\n'
        "`weighted_score` (number 0.0-10.0), `blocking` (list, may be `[]`),\n"
        "`advisories` (list, may be `[]`). Optional: `confidence` (number 0.0-1.0).\n"
        "Each finding in blocking/advisories is an object with `title` (str),\n"
        '`evidence` (str, file:line, may be `""`), and optional `fix` (str).\n'
        "\n"
        "Concrete example — REPLACE values with your actual verdict; do NOT copy\n"
        "this block verbatim:\n"
        "\n"
        "```json\n"
        "{\n"
        '  "decision": "FIX",\n'
        '  "weighted_score": 7.5,\n'
        '  "blocking": [\n'
        "    {\n"
        '      "title": "Race condition in worker shutdown",\n'
        '      "evidence": "scripts/foo.py:142",\n'
        '      "fix": "Acquire lock before signaling done"\n'
        "    }\n"
        "  ],\n"
        '  "advisories": [],\n'
        '  "confidence": 0.85\n'
        "}\n"
        "```\n"
        "\n"
        "Rules:\n"
        f'- "decision" MUST be "PASS" only when "blocking" is empty AND "weighted_score" >= {threshold}.\n'
        '  (If you write PASS while "blocking" is non-empty or score < '
        f"{threshold}, Trinity will\n"
        "  display your provider as FIX — the consistency is enforced.)\n"
        '- "blocking" and "advisories" are required lists (use [] if empty, not null).\n'
        '- "evidence" is required per finding; use "" for cross-cutting issues.\n'
        "- This block must be the LAST fenced ```json block in your output. Trinity scans\n"
        "  for the last match. Earlier illustrative JSON in your prose is fine.\n"
    )

# CHG-3028: Richer Synthesis Summary

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #55)
**Priority:** Medium
**Change Type:** Direct CHG (issue scope: ~30-line CLI tweak)
**Targets:** `scripts/codex.py` (write_synthesis + cmd_review boundary)
**Closes:** #55
**Builds on:** TRN-3022 (structured review schema, just shipped in PR #69)

---

## What

Add an aggregate Summary block at the top of `synthesis.md` and emit a one-line stderr summary at the end of `trinity review`. Both consume the structured `parsed_per_provider` data TRN-3022 already collects in `write_synthesis()` — no new parsing, no LLM-side merging.

**Markdown block (top of synthesis.md):**

```
## Summary

- **Verdict**: ALL_PASS | NEEDS_FIXES | INCONCLUSIVE | LEGACY
- **Providers**: N/M PASS · K FIX · F FAIL (mean score X.XX)
- **Findings**: B blocking · A advisories total
- **Convergence**: T titles flagged by ≥2 providers (or "none")
```

**Stderr line on completion** (printed by cmd_review after write_synthesis):

```
trinity review: <verdict> — <providers-line> — synthesis: <path>
```

## Why

Issue #55: `synthesis.md` lists per-provider statuses but doesn't aggregate. Consumers (humans + LLM agents) re-parse raw files to extract verdict / convergence / risk-area calls. Multiple recent sessions (TRN-2020, TRN-2025, this session's TRN-3022 panel) showed Claude agents reading all 3-4 raw files to produce an aggregate by hand. That aggregate is more useful as Trinity's own output.

TRN-3022 (just shipped) made the data structured. This CHG renders it.

## Verdict semantics

| Verdict | Condition |
|---------|-----------|
| `ALL_PASS` | Every result rc=0 AND every parsed `effective_decision` is PASS |
| `NEEDS_FIXES` | At least one parsed `effective_decision` is FIX (no failures) |
| `INCONCLUSIVE` | At least one rc!=0 (timeout, crash, etc.) — review is incomplete |
| `LEGACY` | No provider emitted structured output (legacy fallback path) |

Precedence (top-to-bottom): `INCONCLUSIVE` > `LEGACY` > `NEEDS_FIXES` > `ALL_PASS`.

## Convergence rule

For each parsed provider, collect every `title` string from `blocking` + `advisories`. Group by exact title (case-sensitive, trimmed). Convergence count = number of titles that appear across ≥ 2 distinct providers.

Trade-off: exact-string match misses paraphrases ("Race condition" vs "Race in worker shutdown"), but cosine/embedding-based clustering would (a) require an LLM call, (b) be non-deterministic, (c) inflate the surface beyond a render-layer change. Exact-match is the right floor for v1; future iteration can add normalization.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `scripts/codex.py` write_synthesis | Add Summary block at TOP of synthesis.md (between scope line and `## Provider Status`). Both legacy and enriched paths render Summary; legacy verdict = `LEGACY`. |
| 2 | `scripts/codex.py` cmd_review | After `write_synthesis()`, print one-line stderr summary referencing the output path. |
| 3 | `tests/test_summary_render.py` (NEW) | ~10-15 unit tests covering all 4 verdicts + convergence + legacy fallback + empty results. |
| 4 | `CHANGELOG.md` | `[Unreleased] ### Added` entry. |
| 5 | `README.md` (optional) | Brief mention in "Run a review" section if space permits. |

## Acceptance Criteria

- **A1**: Summary block appears between scope line and Provider Status, in both legacy and enriched paths.
- **A2**: Verdict precedence correct (INCONCLUSIVE wins over NEEDS_FIXES; LEGACY only when no structured).
- **A3**: Provider counts equal `len(results)` in total; all-rc=0 + all-parsed-PASS → "N/N PASS · 0 FIX · 0 FAIL".
- **A4**: Mean score computed only over rc=0 providers with parsed scores; "—" when none.
- **A5**: Findings count = sum(len(blocking)+len(advisories)) across rc=0 parsed providers.
- **A6**: Convergence count = number of distinct titles appearing in ≥2 providers' findings.
- **A7**: Legacy path Summary block has Verdict=LEGACY and "—" for score/findings/convergence.
- **A8**: Stderr line printed after write_synthesis, format: `trinity review: <verdict> — <providers> — synthesis: <path>`.
- **A9**: Existing `test_a7_byte_identical_legacy` updated: legacy now includes Summary block (the test should assert against the new expected output, not the old).
- **A10**: Existing `test_a5_*`, `test_a6_*` tests unaffected (Summary block is additive at top).

## Implementation Order

1. Add `_compute_summary(results, parsed_per_provider) -> dict` helper near `_render_findings_for`.
2. Add `_render_summary_block(summary) -> list[str]` helper.
3. Modify `write_synthesis()` to call both and prepend the block.
4. Modify `cmd_review()` to print stderr line after `write_synthesis()`.
5. Update existing legacy/enriched tests to include the Summary block in expected output.
6. Add `tests/test_summary_render.py` with verdict + convergence + edge cases.
7. CHANGELOG entry.

## Out of Scope

- LLM-side narrative merging (issue #55 alternative #2)
- Slash-command parity (issue #55 alternative #4) — separate surface, separate CHG
- Title normalization / clustering for convergence (v2 problem if v1's exact-match proves insufficient)

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft, marked Approved (direct CHG path per issue scope) | Claude Code |

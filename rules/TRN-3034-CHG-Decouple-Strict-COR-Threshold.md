# CHG-3034: Decouple Strict COR Threshold (Per-Template Parameterization)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Proposed
**Date:** 2026-05-09
**Requested by:** chatgpt-codex-connector[bot] R2 review on PR #97 (comment `3212719959`); deferred per @frankyxhl chat decision (option (c)) on 2026-05-09
**Priority:** Medium
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #98
**Builds on:** TRN-3032 (which raised `_REVIEW_PASS_THRESHOLD` to 9.5 and exposed this latent design tension)

---

## What

Move `STRICT_REVIEW_DECISION_RULE` from a module-level constant into the per-template `STRICT_REVIEW_TEMPLATES` dict (Option A). Each template entry gains a `decision_rule` field, and the existing `pass_threshold` becomes load-bearing for parse-coercion (not just prompt rendering). The module-level `_REVIEW_PASS_THRESHOLD` remains as the **fast-review-tier default** — used when no strict template is in scope (i.e., panel reviews under TRN-1008 §4 / §8 fast-review tier per CHG-3032).

**Threading mechanism.** `parse_structured_review(raw_text, pass_threshold=None)` accepts an optional **float** kwarg defaulting to `_REVIEW_PASS_THRESHOLD` (the fast-review-tier value). Its single caller `write_synthesis` (`scripts/codex.py:~L2072`) extends its signature to accept `strict_review=None` (the **strict-template dict** populated by `strict_review_metadata()` at `~L1140-1147`); when in scope, `write_synthesis` extracts `strict_review["pass_threshold"]` and passes that float to `parse_structured_review`. Similarly, `_review_schema_addendum(task_type, strict_review=None)` is called from `render_prompt` (`~L1245`) which already has `strict_review` in scope; the addendum reads `strict_review["pass_threshold"]` when provided, else falls back to `_REVIEW_PASS_THRESHOLD`. No tuple reconstruction needed — `strict_review_metadata()` is the single populator and the dict is the single source of truth.

Option B (`parse_structured_review(text, threshold=N)` per-call kwarg without per-template constant) was rejected because the `STRICT_REVIEW_TEMPLATES` dict is the natural single source of truth for per-template metadata; co-locating `decision_rule` alongside the existing `pass_threshold` prevents future drift between the two. Option B would require every call site to look up and pass the threshold, increasing the surface area for bugs (a forgotten override silently falls back to the global). Option A keeps the parser self-sufficient — it (or its caller) looks up the template from `(sop, rubric)` once.

## Why

PR #97 R2 codex-bot finding (`3212719959`): under strict COR-1602/COR-1609 reviews, a 9.2/PASS verdict from a competent reviewer gets silently coerced to FIX in `parse_structured_review`'s effective-decision logic, because the function reads the global `_REVIEW_PASS_THRESHOLD` (9.5, set by CHG-3032 for the fast-review tier) instead of COR's own `pass_threshold` (9.0). Strict COR users would see false-FIX verdicts blocking PR merges or polluting synthesis tables.

PR #97 chose option (c) — accept the tension + document inline + defer to follow-up. The inline doc lives at `tests/test_codex_adapter.py:849-852`. This CHG is that explicit follow-up cleanup.

Strict COR reviews are rarely invoked in this repo today. The fix is design-cleanliness more than user-impact, but the latent bug is real for any future user who sets `--sop COR-1602 --rubric COR-1609`.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `scripts/codex.py` `STRICT_REVIEW_TEMPLATES` dict | Add `decision_rule` field to each template entry with prose matching that template's `pass_threshold` (COR-1602/COR-1609: `"PASS when weighted_average >= 9.0 and no blocking findings remain; otherwise FIX."`). |
| 2 | `scripts/codex.py` `strict_review_metadata()` (def L1140, read L1147) | Read `template["decision_rule"]` instead of module-level `STRICT_REVIEW_DECISION_RULE`. |
| 3 | `scripts/codex.py` `render_strict_review_instructions()` (def L1169, read L1215) | Append `template["decision_rule"]` for prompt rendering. |
| 4 | `scripts/codex.py` `parse_structured_review()` (def L1592, read L1623) + caller `write_synthesis` (L2072) | Signature: `parse_structured_review(raw_text, pass_threshold=None)` defaults to `_REVIEW_PASS_THRESHOLD`. Caller `write_synthesis` accepts `strict_review=None`; when strict template in scope, passes `strict_review["pass_threshold"]` directly. |
| 4b | `scripts/codex.py:2249` — main review flow's call site | Currently calls `write_synthesis(review_dir, args.scope, results)` without `strict_review`. After parameterization, must pass `strict_review=strict_review` (the variable is already in scope at L2190 in main flow). |
| 5 | `scripts/codex.py` `_review_schema_addendum()` (def L1634, read L1645) + caller `render_prompt` (L1245) | Signature: `_review_schema_addendum(task_type, strict_review=None)`. Caller `render_prompt` passes `strict_review` through. Uses template threshold when provided; else fast-review default. |
| 6 | `scripts/codex.py` module-level `STRICT_REVIEW_DECISION_RULE` | DELETE — replaced by per-template `decision_rule`. |
| 7 | `scripts/codex.py` module-level `_REVIEW_PASS_THRESHOLD` | KEEP at 9.5; clarify docstring/comment to "fast-review-tier default" (not "global"). |
| 8 | `tests/test_codex_adapter.py` L850-854 (`# Note:` block) + L855 (decision_rule string asserting `>= 9.5`) | Remove `# Note:` design-tension comment block (L850-854); change L855 assertion from `>= 9.5` to `>= 9.0` for COR template. |
| 9 | `tests/test_codex_adapter.py` (new test) | Add `test_strict_cor_reviewer_at_9.2_passes`: under COR template, `parse_structured_review` on a 9.2/PASS verdict returns `effective_decision="PASS"` (not FIX-coerced). |
| 9b | `tests/test_codex_adapter.py` (new test) | Add `test_fast_review_panel_at_9.4_coerces_to_FIX`: with no strict template in scope, `parse_structured_review` on a 9.4/PASS verdict returns `effective_decision='FIX'`. Regression guard for fast-review default. |
| 9c | `tests/test_codex_adapter.py` (new test) | `test_parse_structured_review_default_threshold` — backward-compat: parser with no kwarg uses `_REVIEW_PASS_THRESHOLD` default. |
| 9d | `tests/test_review_schema.py` (new test) | `test_review_schema_addendum_tier_aware` — addendum emits `>= 9.0` for strict template, `>= 9.5` for fast-review tier. |
| 10 | `tests/test_review_schema.py` — fixture sweep | Identify any fixtures that hardcode 9.5 threshold assumptions and parameterize per the active template (strict-template fixtures pass `strict_review={"pass_threshold": 9.0}`; fast-review fixtures keep current default behavior). Names of touched fixtures determined at implementation time; AC requires all existing tests still pass. |
| 11 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3034 entry via `af index --root .` regen. |
| 12 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry mentioning per-template decision-rule parameterization + fixes strict-COR coercion. |

## Acceptance Criteria

- [ ] Surface 1: `STRICT_REVIEW_TEMPLATES[("COR-1602","COR-1609")]` has `decision_rule` field with `>= 9.0` prose.
- [ ] Surface 2: `strict_review_metadata()` returns `decision_rule` from template (no global constant reference).
- [ ] Surface 3: `render_strict_review_instructions()` appends `template["decision_rule"]`.
- [ ] Surface 4: `parse_structured_review` signature accepts optional `pass_threshold` (defaults `_REVIEW_PASS_THRESHOLD`); caller `write_synthesis` passes template threshold when strict template in scope.
- [ ] Surface 4b: `scripts/codex.py:2249` caller updated to pass `strict_review=strict_review` (variable already in scope from L2190).
- [ ] Surface 5: `_review_schema_addendum(task_type, strict_review=None)` is tier-aware; caller `render_prompt` passes `strict_review` through.
- [ ] Surface 6: module-level `STRICT_REVIEW_DECISION_RULE` constant deleted.
- [ ] Surface 7: `_REVIEW_PASS_THRESHOLD` retained as fast-review-tier default (docstring clarified).
- [ ] Surface 8: `tests/test_codex_adapter.py` L850-854 `# Note:` block removed; L855 assertion changed from `>= 9.5` to `>= 9.0` for COR template.
- [ ] Surface 9: New test `test_strict_cor_reviewer_at_9.2_passes` exists and passes.
- [ ] Surface 9b: New test `test_fast_review_panel_at_9.4_coerces_to_FIX` exists and passes (regression guard for fast-review default).
- [ ] Surface 9c: `tests/test_codex_adapter.py` — new test `test_parse_structured_review_default_threshold` (backward-compat: no kwarg uses `_REVIEW_PASS_THRESHOLD`).
- [ ] Surface 9d: `tests/test_review_schema.py` — new test `test_review_schema_addendum_tier_aware` (addendum emits `>= 9.0` for strict template, `>= 9.5` for fast-review).
- [ ] Surface 10: `tests/test_review_schema.py` fixtures pass under tier-aware refactor.
- [ ] Surface 11: TRN-0000 index regenerated.
- [ ] Surface 12: CHANGELOG entry added.
- [ ] All existing tests pass (`make test` clean).
- [ ] `af validate --root .` clean.
- [ ] PR body documents design-tension closure (cross-link PR #97 + issue #98).
- [ ] PR body includes `Closes #98`.

## Migration / Backward-compat notes

Zero user-facing change for the fast-review tier (TRN-1008 §4/§8 panel reviews continue at 9.5 — the most common path). Strict COR-1602/COR-1609 users (rare) now correctly get the 9.0 gate matching the template metadata, instead of the silently-applied 9.5 from the global constant. No release-note breaking change. No config migration. No public API removal — `parse_structured_review` gains an optional kwarg with a backward-compatible default. For strict COR-1602/COR-1609 users specifically, verdicts in the 9.0–9.4 band now PASS where they previously FIX-coerced — this restores the documented `pass_threshold: 9.0` contract advertised by `STRICT_REVIEW_TEMPLATES` metadata. No known users in this repo rely on the latent 9.5 coercion (per `gh issue search 'strict COR'` history); change is safe.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial draft (Status: Proposed). Closes #98. Per-template Option A chosen over per-call Option B. | trinity-glm |
| 2026-05-09 | Plan-review R2: specified threading mechanism for parse_structured_review + _review_schema_addendum (deepseek P0); fixed line refs (glm/deepseek P1); added negative test for fast-review default; strengthened Option B rejection. | Claude Opus 4.7 |
| 2026-05-09 | Plan-review R3: added Surface 9c (2 backward-compat tests); switched threading to strict_review["pass_threshold"] (single dict access, no tuple reconstruction); enumerated hidden 13th surface at scripts/codex.py:2249 (main-flow caller); disambiguated kwarg types in threading paragraph. | Claude Opus 4.7 |
| 2026-05-09 | Plan-review R3: collapsed Threading paragraph from 13→5 sentences (compression); re-verified all Surface def-tag lines against current `scripts/codex.py` (L1140/L1169/L1592/L1634 all correct as drafted); split Surface 9c into 9c+9d (atomic per-file); added fixture-spec to Surface 10. | Claude Opus 4.7 |

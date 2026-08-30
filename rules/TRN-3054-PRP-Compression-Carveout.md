# PRP-3054: Compression-Scoring Carve-Out for Contract-Pinning Test Growth

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-08-30
**Last reviewed:** 2026-08-30
**Status:** Draft
**Requested by:** Issue #277 (TRN-3047 §11 retrospective F2, confirmed by @frankyxhl)
**Related:** TRN-1800 (weights), TRN-1008 (§4 threshold), TRN-3047 (§Plan Review adjudication record), issue #240 / PR #276

---

## What Is It?

An amendment to the review-scoring rules so that test code added to satisfy the panel's own contract-pinning findings stops counting against the compression dimension. TRN-1800's compression formula structurally caps small-refactor-plus-contract-tests CHGs below the §4 9.5 panel threshold — the rubric penalizes compliance with itself. This PRP analyzes the two remediation shapes named in #277 and recommends one.

## Problem

PR #276 (TRN-3047, `discover.py` argparse) is the motivating case, reproduced from TRN-3047 §Plan Review:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R2 | 9.55 PASS | 9.65 PASS | 9.25 FAIL (blocking: none; compression only) | ❌ |
| R3 | — carry | — carry | 9.45 FAIL (blocking: none ×2; compression structurally capped 8/10) | ❌ strict / ✅ adjudicated |

minimax held a sub-threshold score with an **empty blocking list two rounds running** and stated no honest CHG edit could close the gap: the net test-LoC growth **was the contract pinning the panel itself required** (R1 blocking findings demanded `--version` × subcommand pinning, `--bogus`/`-h` Changed rows, expanduser-default tests). The operator had to adjudicate PASS manually (2026-07-04, dissent recorded). glm hovered at 9.49 for the same class. Every future small-refactor-plus-contract-tests CHG re-creates this friction unless the rule changes.

## Options

### Option A — Compression carve-out for reviewer-demanded test growth (RECOMMENDED)

**Rule:** test lines added in direct response to a numbered R-round review finding are excluded from the compression-ratio calculation, provided the CHG cites the finding ID at the added test block (e.g., a `# pins R2-F3` comment or a Change-History row mapping test → finding).

**Mechanics (3 doc edits, no code):**
1. TRN-1800 §weights: append to the compression rows (both code and doc tables) — *"Carve-out: LoC added to pin a contract row demanded by a numbered review finding (cited by finding ID) is excluded from both numerator and denominator. The mapping must be verifiable by grep; reviewers audit it as part of Necessity. Zero-denominator rule: if the exclusion leaves `chars added = 0`, compression scores the maximum (10/10) — the CHG added nothing beyond reviewer-demanded pinning, which is the carve-out's intended limit case."*
2. TRN-1008 §4 prompt structure: add one sentence to the plan-review prompt spec — *"When scoring compression, exclude test LoC mapped (by cited finding ID) to findings your own panel demanded; audit the mapping, not the growth."*
3. TRN-1008 §4 "Triage findings" + TRN-3022 schema note: the orchestrator, when folding a round's findings into the CHG plan-review table, assigns each finding a deterministic ID `R<round>-F<index>` (order as listed in the verdict JSON) and records it in the fold row. The TRN-3022 structured schema gains an optional `id` field populated at fold time (schema-conforming reviewers who omit it still work — the ID is assigned downstream, never required from the model).

**Why it wins:** it removes the self-contradiction at the scoring layer, where it lives. Honest CHGs stop needing operator rescue. The 9.5 gate keeps its meaning (correctness dimensions unchanged). Gaming is bounded by the finding-ID citation requirement — a mapping that doesn't verify by grep is a Necessity/Scope finding, and unmapped growth still counts.

**Risks:** (a) over-claiming "contract pinning" for ordinary feature tests — mitigated by the citation + audit requirement and by reviewers being the same panel that issued the findings; (b) two more sentences in an already-long prompt — accepted; (c) drift between PKG COR-1800 and TRN-1800 — TRN-1800 already diverges deliberately (TRN-3039 alignment precedent).

### Option B — Codified adjudication rule for empty-blocking sub-threshold verdicts (REJECTED)

**Rule:** if a reviewer's weighted score is < 9.5 with `blocking == []` for two consecutive rounds and the deficit is compression-attributable, the orchestrator may record PASS with dissent, no operator needed.

**Why rejected:** it institutionalizes threshold bypass instead of fixing the scoring defect. "Compression-attributable" needs a definition that is itself a scoring rule (so it doesn't remove complexity, just relocates it). It preserves the recurring interruption (two rounds must still burn) and weakens the gate's audit trail — an auto-PASS below threshold is exactly what TRN-3036-era hardening tried to prevent. Option A makes B's trigger condition structurally rare.

## Recommendation

**Option A.** B's only advantage (no rubric edit) is outweighed by keeping the rubric wrong. B is recorded here so the rejection is citable if the carve-out proves gameable in practice.

## Scope

**In scope:** the three doc edits above (TRN-1800 weight-table appendices incl. the zero-denominator rule; TRN-1008 §4 prompt sentence + finding-ID assignment at fold time; TRN-3022 optional `id` field note); this PRP; CHANGELOG row; doc-index row.
**Out of scope:** changing the 9.5 threshold; rebalancing other weights; PKG COR-1800 alignment (separate CHG if wanted); codifying Option B.

## Acceptance Criteria

- [ ] TRN-1800 compression rows carry the carve-out sentence with the citation/audit requirement
- [ ] TRN-1008 §4 prompt spec carries the exclusion sentence
- [ ] A worked example exists showing PR #276's minimax R3 score computed under the new rule (mapping: R1 findings → pinned tests) reaching ≥ 9.5 on the compression dimension
- [ ] `af validate` clean

## Verification Plan

Doc-only: `af validate`; the worked example is arithmetic on the recorded R3 table.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-08-30 | Initial draft (Status: Draft). Both #277 options analyzed; Option A recommended, B rejected with rationale. Closes #277 when approved through the TRN-1008 loop. | pi (ryosaeba1985) |

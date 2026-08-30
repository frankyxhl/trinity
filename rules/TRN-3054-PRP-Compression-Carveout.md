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

**Rule:** test code that pins a contract row demanded by a review finding is excluded from the compression-ratio calculation — the same contract-pinning eligibility as the normative mechanics below; tests demanded for performance, internal structure, or ordinary feature behavior are NOT excluded — provided the CHG cites the finding ID at the added test block in the full canonical format (e.g., a `# pins P2-glm-F3` comment or a Change-History row mapping test → canonical finding ID). The carve-out applies at every scoring round — plan-review (§4) and code-review iterations (§8/§9) alike — so reviewer-demanded growth stays unpenalized wherever the panel re-scores. Measurement is phase-appropriate: during §4 rounds the CHG is pre-implementation, so compression — and the exclusion — is computed on the CHG's declared character budget: the plan's surface enumeration states per-block added/deleted/merged character estimates for every planned block (merged defaults to 0 for a block unless the plan explicitly declares a consolidation), and cited test blocks carry the finding-ID mapping. §4 reviewers score those declared numbers (deterministic — same plan, same score). The first post-implementation re-score (§8) recomputes on actual characters, with the shipped test blocks replacing the plan entries in the same mapping; any >10% divergence between declared and actual is itself a Scope-restraint finding.

**Mechanics (3 doc edits, no code):**
1. TRN-1800 §weights: append to the compression rows (both code and doc tables) — *"Carve-out: characters added to pin a contract row demanded by a review finding (cited by finding ID) are excluded from the denominator; the numerator is unchanged. Units are characters throughout, matching the base formula: exclude the full added characters of each cited block — wholly added lines count all their characters including delimiters and newlines; a partially changed line counts only the characters it adds. The mapping must be verifiable by grep; reviewers audit it as part of Necessity. Zero-denominator rule: if the exclusion leaves `chars added = 0`, compression scores the maximum (10/10) — the CHG added nothing beyond reviewer-demanded pinning, which is the carve-out's intended limit case."*
2. TRN-1008 §4 prompt structure AND §8 code-review prompt spec: add one sentence to both prompt specs — *"When scoring compression, exclude the characters of test blocks that pin a contract row your review process demanded (cited by finding ID); audit the mapping, not the growth."* — the same contract-pinning eligibility as the normative TRN-1800 rule; tests demanded for performance, internal structure, or ordinary feature behavior are NOT excluded. (§8's dispatch does not inherit §4's prompt, so the sentence must appear in both.)
3. TRN-1008 §4 "Triage findings" + §9 Triage + TRN-3022 schema note: the orchestrator assigns each finding a deterministic, globally-unique ID at every fold where a finding or advisory is ACCEPTED and recorded — the §4/§9 triage folds, the iterate-cycle folds for §8 code-review / bot findings, AND the convergent-advisory acceptance fold on passing rounds (TRN-1008 routes a PASS-with-advisories round straight to Approved with advisories fixed before phase 8; that acceptance fold is a fold site too, so advisory-demanded tests get the same canonical IDs). Each fold assigns `<phase><round>-<provider>-F<index>`, where phase is `P` for plan-review rounds and `I` for post-push iterate rounds (e.g. `P2-glm-F3`, `I1-codex-bot-F1`). The provider token is canonical: the short registry key — `glm`, `deepseek`, `minimax`, `gemini`, `codex`, `claude-code`, `openrouter` — never the `trinity-<key>` panel label; bot findings use `codex-bot`. A citation and its fold row therefore always match under grep. — provider from the finding's origin, index over that provider's findings in a fixed flattening order (blocking array first, then advisory array, each in listed order). The ID and its origin row are recorded in the fold row. The TRN-3022 structured schema gains an optional `id` field populated at fold time (schema-conforming reviewers who omit it still work — the ID is assigned downstream, never required from the model). Uniqueness and the grep audit are scoped to a single CHG's review record — a PR maps 1:1 to its CHG, so a citation resolves against that CHG's own plan-review table / triage record; within that scope, uniqueness is by construction: phase- and provider-scoped indices cannot collide (plan-review R1 and iterate R1 live in different phases) and the fixed flatten order removes within-provider ambiguity. A citation that must live outside its own PR carries the CHG number (`3054:P1-glm-F3`). For codex-bot findings — which arrive as GitHub artifacts (review summaries, inline review comments, issue comments), not ordered verdict arrays — the flattening source is the artifact tuple ordered (reviews by review id, then inline comments by comment id, then issue comments by comment id), with multiple findings inside one artifact ordered by appearance in its body; an edited sticky comment is snapshotted at triage time (a finding added by a later edit takes the next index in the NEXT triage round). Classification: P0/P1 badge = blocking-class, P2/P3 = advisory-class. Different triage runs therefore assign identical IDs to identical findings.

**Why it wins:** it removes the self-contradiction at the scoring layer, where it lives. Honest CHGs stop needing operator rescue. The 9.5 gate keeps its meaning (correctness dimensions unchanged). Gaming is bounded by the finding-ID citation requirement — a mapping that doesn't verify by grep is a Necessity/Scope finding, and unmapped growth still counts.

**Risks:** (a) over-claiming "contract pinning" for ordinary feature tests — mitigated by the citation + audit requirement and by reviewers being the same panel that issued the findings; (b) two more sentences in an already-long prompt — accepted; (c) drift between PKG COR-1800 and TRN-1800 — TRN-1800 already diverges deliberately (TRN-3039 alignment precedent).

### Option B — Codified adjudication rule for empty-blocking sub-threshold verdicts (REJECTED)

**Rule:** if a reviewer's weighted score is < 9.5 with `blocking == []` for two consecutive rounds and the deficit is compression-attributable, the orchestrator may record PASS with dissent, no operator needed.

**Why rejected:** it institutionalizes threshold bypass instead of fixing the scoring defect. "Compression-attributable" needs a definition that is itself a scoring rule (so it doesn't remove complexity, just relocates it). It preserves the recurring interruption (two rounds must still burn) and weakens the gate's audit trail — an auto-PASS below threshold is exactly what TRN-3036-era hardening tried to prevent. Option A makes B's trigger condition structurally rare.

## Recommendation

**Option A.** B's only advantage (no rubric edit) is outweighed by keeping the rubric wrong. B is recorded here so the rejection is citable if the carve-out proves gameable in practice.

## Scope

**In scope:** the three doc edits above — (1) TRN-1800 weight-table appendices incl. the character-unit definition and zero-denominator rule; (2) the exclusion sentence in BOTH prompt specs (TRN-1008 §4 plan-review AND §8 code-review); (3) finding-ID assignment at ALL THREE fold sites (TRN-1008 §4 plan-review triage, §9 iterate triage incl. the bot-artifact flattening rule, AND the convergent-advisory acceptance fold on passing rounds) plus the TRN-3022 optional `id` field note; this PRP; CHANGELOG row; doc-index row.
**Out of scope:** changing the 9.5 threshold; rebalancing other weights; PKG COR-1800 alignment (separate CHG if wanted); codifying Option B.

## Acceptance Criteria

- [ ] TRN-1800 compression rows carry the carve-out sentence with the citation/audit requirement, character-unit definition (wholly/partially added lines), and zero-denominator rule
- [ ] TRN-1008 §4 prompt spec carries the exclusion sentence
- [ ] TRN-1008 §4 AND §9 triage steps AND the passing-round advisory-acceptance fold assign `<phase><round>-<provider>-F<index>` IDs at fold time (all three observable in the amended docs), and TRN-3022's structured schema documents the optional `id` field populated at fold
- [ ] The exclusion sentence appears in BOTH the §4 plan-review prompt spec and the §8 code-review prompt spec
- [ ] A worked example exists showing PR #276's minimax R3 score computed under the new rule (mapping: R1 findings → pinned tests) reaching ≥ 9.5 on the compression dimension
- [ ] `af validate` clean

## Verification Plan

Doc-only: `af validate`; the worked example is arithmetic on the recorded R3 table.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-08-30 | Initial draft (Status: Draft). Both #277 options analyzed; Option A recommended, B rejected with rationale. Closes #277 when approved through the TRN-1008 loop. | pi (ryosaeba1985) |

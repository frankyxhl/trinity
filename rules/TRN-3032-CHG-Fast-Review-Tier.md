# CHG-3032: Fast-Review Tier (2-Provider Panel + ≥9.5 Gate)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Approved
**Date:** 2026-05-09
**Requested by:** @frankyxhl (chat direction post-#87 merge: "I want to only use fast-review model for this project. current is GLM + DeepSeek. I want to use these 2 only" + "the pass criteria is both review score is >= 9.5")
**Priority:** Medium
**Change Type:** Feature
**Targets:** `main`
**Closes:** #88
**Builds on:** TRN-1008 §4 (plan-review panel), §8 (code-review panel), §Failure Modes, §Guard Rails (replaces "Never accept 3-of-4 PASS" rule)
**Supersedes:** #86 (to be closed by this PR; bundled here per @frankyxhl direction — #86 proposed 3-provider code-review only; this CHG goes further with 2-provider both panels)

---

## What

§4 plan-review panel and §8 code-review panel: the current 4-provider list (trinity-gemini, trinity-codex, trinity-glm, trinity-deepseek) is reduced to 2 providers (trinity-glm, trinity-deepseek). The PASS gate is raised from "all-individual ≥9.0 AND blocking empty" to "both individual ≥9.5 AND blocking empty". The change is symmetric across both phases. Codex's contribution to code-review now comes exclusively from `chatgpt-codex-connector[bot]` post-push per the §8 polling spec; trinity-codex is no longer dispatched by the orchestrator. No bot equivalent for trinity-gemini exists at any phase — that signal is genuinely lost.

§Failure Modes "Reviewer / provider unavailability": the current "≥3 viable providers" tiering is replaced with a 2-provider availability rule: the panel requires BOTH providers; if either is unavailable, abort and surface to user; no fall-through to N-1 (because N-1 = 1 is not a panel).

§Guard Rails "Never accept 3-of-4 PASS as gate-met": replaced with count-free wording deferring to §4 spec per R17 SSOT: "any individual below the §4-specified threshold blocks the gate; dissent is not absorbable."

In addition to the four primary surfaces above, this CHG must also update §Why pt-3, §Steps preamble TOC, §4 gate-enforcement prose, §4 panel-result table, and §4 mermaid block — places that hardcode "4 providers" / "≥9.0" / "3-of-4" counts and would otherwise contradict the new §4 spec. These are tracked as Surfaces 10-12 below.

**Bootstrap decision.** The natural bootstrap reading is that this CHG's plan-review must run under the OLD 4-provider/≥9.0 rules (the rule cannot evaluate itself). However, @frankyxhl chose option (b) at pickup time — plan-review of THIS CHG runs under the new 2-provider/≥9.5 tier, matching established practice on PRs #93 and #96 where Frank pre-applied the new tier. Both readings are recorded here for audit-trail clarity. Subsequent CHGs use the new rules unconditionally.

## Why

Issue #88 §Problem-Goal: PR #87 (TRN-3029) reached PASS at R3 with mean 9.275 across 4 providers — but the same gate would have evaluated 6 review-runs (vs 12) with 2 providers, halving wall-clock and concurrent-agent overhead. PR #87 R3 means were gemini 9.9 / codex 9.2 / glm 9.0 / deepseek 9.0; under the proposed ≥9.5 rule, glm+deepseek (9.0/9.0) would NOT have PASSed — an R4 would have been required. That is the desired behaviour: the higher bar trades wall-clock for catch-rate, not the other way around. Frank's chat direction is concrete signal evidence; the PR-#87 data quantifies the tradeoff.

## Threshold rationale

The ≥9.5 individual bar compensates for the lost convergence-redundancy via three concrete mechanisms:

1. **All-voices-clear structure** (the load-bearing argument): both 2-provider and 4-provider gates require ALL voices to clear their bar. At 9.5 + 9.5 with 2 providers, every voice clears 9.5; at the prior 4-provider/≥9.0 gate, every voice cleared 9.0. The structural pattern is preserved; only the per-voice height changes. No reviewer's dissent is absorbable in either form.

2. **Frank's directive** (the requesting-stakeholder argument): @frankyxhl chose this configuration explicitly post-#87 merge with concrete reasoning ("only fast-review models for this project; pass criteria both ≥9.5"). Ship-blocked status not warranted on grounds of operator-overrule.

3. **Wall-clock / iteration tradeoff** (the cost-of-quality argument): PR #87 (TRN-3029) reached PASS at R3 with mean 9.275 with 4 providers — 12 review-runs across 3 rounds. Same gate at 2 providers = 6 review-runs per round; same R-count; half the wall-clock and half the concurrent-agent overhead. The new ≥9.5 bar is expected to require ≥1 more R-iteration on average (PR #87 R3 had 9.0/9.0 from glm/deepseek which would have been FIX under the new rule), accepting the tradeoff: more iterations × cheaper rounds.

Earlier draft framed this as "catch-rate equivalent to 4-provider/9.0" — that claim is unproven and depends on calibration data the project doesn't have. The three arguments above are structural / directive / cost — not catch-rate equivalence.

## Compression delta

The CHG itself is net-positive (~165 lines new file). Inside TRN-1008, the surface edits are net-zero or net-negative once deletion offsets are counted. Specifics across surfaces 1-12:

| Surface | Net effect on TRN-1008 |
|---------|------------------------|
| §4 panel-dispatch list (S1) | "4 providers (trinity-gemini + trinity-codex + trinity-glm + trinity-deepseek)" → "2 providers (trinity-glm + trinity-deepseek)" — ~25 chars deleted per occurrence × ≥3 occurrences ≈ 75 chars deleted |
| §8 panel-dispatch list (S2) | Same pattern as §4 ≈ 75 chars deleted; +1 short codex-bot deference line ≈ +60 chars |
| §Failure Modes ≥3-viable tiering (S3) | ~3-line "≥3 viable providers" tiering paragraph → 2-line "both providers required" rule ≈ net-zero / modest savings |
| §Guard Rails (S4) | "Never accept 3-of-4 PASS as gate-met. The dissenter's blockers must be addressed." → count-free deference to §4 ≈ net-zero (slightly shorter) |
| §Threat Model (S5) | +2-line 2-provider redundancy + bot-down note ≈ +120 chars |
| §Examples row (S6) | +1 row (placeholder columns at PR-open; outcome filled at merge per Surface 6a/6b split) ≈ +200 chars |
| §Change History row (S7) | +1 row ≈ +120 chars |
| §Why pt-3 (S10) | "3-of-4 PASS panel as 'good enough' instead of holding the all-individual-≥9.0 line" → count-free ("instead of holding the all-individual gate") ≈ ~40 chars deleted |
| §Steps preamble TOC (S10) | "4-provider panel, all-individual ≥9.0" → "2-provider fast-review tier, both individual ≥9.5" ≈ net-zero |
| §4 gate-enforcement prose (S11) | "weighted_score >= 9.0" → "weighted_score >= 9.5" ≈ net-zero (single char change × 2 occurrences) |
| §4 panel-result table (S11) | 4 rows mentioning "4 PASS" / "3 PASS + 1 FIX" / "8.95" → 2 rows referencing the 2-provider/9.5 spec ≈ ~150 chars deleted |
| §4 mermaid block (S12) | 4 leaf nodes (G1/G2/G3/G4) → 2 leaf nodes (G1[glm], G2[deepseek]); count-free dispatch + viability nodes ≈ ~50 chars deleted |

**Net within TRN-1008:** ~390 chars deleted, ~500 chars added (the +120 Threat Model + 200 Examples row + 120 Change History dominate the additions). Net additions ≈ +110 chars, justified by the necessity of explicit 2-provider redundancy / bot-down wording (per TRN-1800 doc-weight necessity dimension).

**Net for the project:** +165 lines (new CHG) + ~110 chars (TRN-1008 net positive). New CHG is 100% necessity-justified per TRN-1800 doc weights (Frank's directive + #88 quantified tradeoff). SOP delta is small-net-positive once redundancy/mitigation prose is counted.

## R-history

- **R1 plan-review** (2026-05-09): trinity-glm 9.175 / FIX (2 blockers + 6 advisories — A6 missing surfaces, B1 compression delta absent, B2 chicken-egg); trinity-deepseek 9.00 / FIX (1 blocker + 5 advisories — B1 unsubstantiated catch-rate claim, A2 chicken-egg convergent). Mean 9.09. R2 applies 9 fixes: (1) added Surfaces 10/11/12 for missing TRN-1008 sites (§Why pt-3, §Steps preamble, §4 gate-enforcement prose, §4 panel-result table, §4 mermaid count nodes); (2) new §Compression delta section quantifying per-surface deletions; (3) Surface 6 split into 6a (PR-open placeholder) + 6b (PR-merge fill) per TRN-3030/TRN-3031 precedent; (4) §Threshold rationale rewrite — drops unsubstantiated catch-rate equivalence claim; leads with structural / directive / cost; (5) UTC date command (`TZ=UTC git log -1 --date=iso-local --format=%cd`); (6) `Supersedes:` frontmatter validation; (7) #86 closure-note dedup folded into §What + frontmatter; (8) forward-looking framing ("(to be closed by this PR;…)"); (9) `chatgpt-codex-connector[bot]` exact-name verified via PR #93/#96 reviews API.
- **R2 plan-review** (2026-05-09): trinity-glm 9.50 / PASS (lands exactly on ≥9.5 gate; 4 sub-blocking advisories — none FIX-required); trinity-deepseek 9.57 / PASS (1 advisory — Surface 11 could split 11a/11b; non-blocking atomicity polish). Mean 9.535. **Gate MET** (both individual ≥9.5 + zero blocking). Note on panel independence: glm had session resumption across drafter / fixer / reviewer roles; deepseek had fresh per-round sessions. Deepseek's 9.57 (rigorous fresh-context signal) is the load-bearing verdict; glm 9.50 confirms but doesn't carry weight. Session-asymmetry flagged as a follow-up concern for orchestrator-discipline cluster (#91 / #92 / #94).

## Out of Scope

- Worker-dispatch default (issue #91 — different surface; orchestrator-discipline cluster, follow-up bundle).
- Comprehension-check pre-Phase-2 (issue #92 — different surface).
- Wait-state guard (issue #94 — different surface).
- SOP-1009 issue-filing conventions (issue #89 — different surface).
- The bootstrap question (resolved by operator option (b); see §What "Bootstrap decision").

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §4 plan-review panel | Provider list: 4 → 2 (trinity-glm + trinity-deepseek). PASS-gate threshold: "all-individual ≥9.0" → "both individual ≥9.5". §4 references threshold rationale (this CHG) as SSOT. |
| 2 | TRN-1008 §8 code-review panel | Provider list: 4 → 2 (same as Surface 1). Same ≥9.5 threshold. One-line note: codex's code-review contribution comes from `chatgpt-codex-connector[bot]` post-push per §8 polling spec; trinity-codex no longer orchestrator-dispatched. §8 references §4 for threshold rationale. |
| 3 | TRN-1008 §Failure Modes "Reviewer / provider unavailability" | Replace "≥3 viable providers" tiering with 2-provider availability rule: panel requires both providers; if either unavailable, abort + surface to user; no fall-through to N-1 (because N-1 = 1 is not a panel). |
| 4 | TRN-1008 §Guard Rails | Replace "Never accept 3-of-4 PASS as gate-met" with count-free deference to §4 spec per R17 SSOT ("any individual below the §4-specified threshold blocks the gate; dissent is not absorbable"). |
| 5 | TRN-1008 §Threat Model | Paragraph extended with 2-provider redundancy note + bot-down mitigation (`chatgpt-codex-connector[bot]` covers code-review codex contribution; if bot unavailable, treat as code-review-pending and don't merge until bot posts on current HEAD per §8 commit_id-anchored polling). |
| 6a | TRN-1008 §Examples (at PR-open) | Add row with plan-review numbers, lane, iterations filled; outcome columns marked TBD ("Code-review TBD at code-review time", "Outcome TBD at merge"). Placeholder pattern mirrors TRN-3030 (PR #93) and TRN-3031 (PR #96). |
| 6b | TRN-1008 §Examples (at PR-merge) | Outcome columns of the row added in 6a filled with actual merge result (follow-up commit on this PR or first post-merge maintenance commit, per the same TRN-3030/TRN-3031 pattern). |
| 7 | TRN-1008 §Change History | New row dated to commit timestamp (UTC; per R20 lesson — see Implementation Order step 10 for exact command). |
| 8 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3032 entry via `af index --root .` regen. |
| 9 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry mentioning the panel rule change + ≥9.5 gate + supersedes #86. |
| 10 | TRN-1008 §Why pt-3 + §Steps preamble TOC line ~56 | §Why pt-3 "3-of-4 PASS panel … all-individual-≥9.0 line" → count-free wording ("the all-individual-pass-gate line"). §Steps preamble TOC: "4. Plan-review ← 4-provider panel, all-individual ≥9.0" → "4. Plan-review ← 2-provider fast-review tier, both individual ≥9.5". Generic / count-free pattern per R17/R23 SSOT. |
| 11 | TRN-1008 §4 gate-enforcement prose + panel-result table (lines ~339, ~345-348) | Gate-enforcement prose "`weighted_score >= 9.0`" → "`weighted_score >= 9.5`" (both occurrences). Panel-result table: 4 rows ("4 PASS, every score ≥ 9.0…", "3 PASS + 1 FIX", "4 PASS but one reviewer at 8.95", "Reviewer emits PASS with score < 9.0") replaced with 2 rows generalised to the 2-provider/≥9.5 spec ("Both PASS, both scores ≥ 9.5, all blocking empty → Approved", "Either reviewer FIX or below 9.5 → not passed; iterate"); plus the malformed-verdict row updated to reference the §4 threshold rather than the literal 9.0. |
| 12 | TRN-1008 §4 mermaid block (lines ~278-303) | `B[Dispatch 4 in parallel]` → `B[Dispatch 2 in parallel]`. Leaf nodes `G1[gemini] / G2[codex] / G3[glm] / G4[deepseek]` → `G1[glm] / G2[deepseek]`. `N1{≥3 viable verdicts?}` → `N1{both viable verdicts?}`. Threshold node `K{"All viable individual ≥ 9.0…"}` → `K{"Both individual ≥ 9.5 AND all blocking empty?"}`. |

Atomicity note: each row is one ##-section (or one symmetric structural amendment within a single section) per CLD-1801 §2 surface taxonomy. Surfaces 10/11/12 are logically grouped because they all carry the same structural amendment — replacing hardcoded "4-provider/≥9.0" with the new 2-provider/≥9.5 spec — but operate on distinct ##-level sections (§Why, §Steps preamble, §4 prose, §4 table, §4 mermaid).

## Acceptance Criteria

- [ ] Surface 1: §4 plan-review panel updated to 2-provider (trinity-glm + trinity-deepseek) + ≥9.5 gate; threshold-rationale reference present; no hardcoded "4-provider" or "all-individual ≥9.0" text in §4 prose.
- [ ] Surface 2: §8 code-review panel updated to same 2-provider list + ≥9.5 gate; one-line `chatgpt-codex-connector[bot]` note present; §8 references §4 for threshold rationale.
- [ ] Surface 3: §Failure Modes "Reviewer / provider unavailability" replaces ≥3-viable tiering with 2-provider "both required" rule; no fall-through to N-1.
- [ ] Surface 4: §Guard Rails replaces "Never accept 3-of-4 PASS as gate-met" with count-free wording deferring to §4 per R17 SSOT.
- [ ] Surface 5: §Threat Model paragraph extended with 2-provider redundancy note + bot-down mitigation prose.
- [ ] Surface 6a: §Examples row added at PR-open with plan-review + lane + iterations filled and outcome columns marked TBD (mirrors TRN-3030 / TRN-3031 placeholder pattern).
- [ ] Surface 6b: §Examples row outcome columns filled at PR-merge (follow-up commit on this PR, or first post-merge maintenance commit).
- [ ] Surface 7: §Change History row dated to commit timestamp (UTC; produced via `TZ=UTC git log -1 --date=iso-local --format=%cd` per R20 lesson).
- [ ] Surface 8: `rules/TRN-0000-REF-Document-Index.md` regenerated; TRN-3032 indexed.
- [ ] Surface 9: CHANGELOG `[Unreleased] ### Changed` entry for fast-review tier + ≥9.5 gate + supersedes #86.
- [ ] Surface 10: §Why pt-3 + §Steps preamble TOC line use count-free wording (no "3-of-4", no "4-provider", no "≥9.0").
- [ ] Surface 11: §4 gate-enforcement prose uses ≥9.5 (both occurrences); panel-result table reduced to 2-row 2-provider form referencing the §4 threshold (not literal 9.0).
- [ ] Surface 12: §4 mermaid block uses count-free dispatch / 2 leaf nodes (`glm`, `deepseek`) / count-free or "both" viability node / ≥9.5 threshold node.
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate met under operator-chosen option (b) — 2-provider / ≥9.5 panel rules.
- [ ] Code-review gate met under same 2-provider / ≥9.5 panel rules.
- [ ] PR body documents the bootstrap decision explicitly (option (b) chosen; the natural bootstrap reading was option (a)).
- [ ] PR body links #86 closure (close #86 with a comment pointing to this PR).
- [ ] PR body includes `Closes #88`.
- [ ] #86 closed with comment pointing to this PR's ship.

## Implementation Order

1. (Already done) Branch `codex/trn-3032-fast-review-tier` cut from `origin/main` per TRN-1008 §2.
2. (Dispatch to worker per #91 worker-default) Draft this CHG with Status: Proposed.
3. (Orchestrator-direct) `af validate --root .` to confirm CHG ACID-compliance before plan-review.
4. (Orchestrator-direct) Plan-review panel R1 under operator-chosen 2-provider / ≥9.5 rules (option (b)). Iterate to gate.
5. (Orchestrator-direct) On gate-met: flip Status: Proposed → Approved on this CHG; commit the flip.
6. (Dispatch to worker) Apply Surface 1 (TRN-1008 §4 plan-review panel — provider list, threshold).
7. (Dispatch to worker) Apply Surface 2 (TRN-1008 §8 code-review panel — provider list, threshold, codex-bot note).
8. (Dispatch to worker) Apply Surfaces 3-4 (§Failure Modes "Reviewer / provider unavailability" + §Guard Rails count-free wording).
9. (Dispatch to worker) Apply Surface 5 (§Threat Model 2-provider redundancy + bot-down mitigation).
10. (Dispatch to worker) Apply Surfaces 10-12 (§Why pt-3 + §Steps preamble TOC, §4 gate-enforcement prose + panel-result table, §4 mermaid block — all count-free / 2-provider / ≥9.5 amendments).
11. (Dispatch to worker) Apply Surface 6a (§Examples row with TBD outcome columns) + Surface 7 (§Change History row dated to commit timestamp via `TZ=UTC git log -1 --date=iso-local --format=%cd`).
12. (Orchestrator-direct) Apply Surfaces 8-9 (`af index --root .` regen + CHANGELOG entry).
13. (Orchestrator-direct) `af validate --root .` clean. Commit; push to `fork`.
14. (Orchestrator-direct) Open PR with `Closes #88`, supersedes-#86 in commit-message context, bootstrap-decision rationale. Code-review per §8 rules NEW. Iterate to gate. Close #86 with comment pointing here. Handoff to Frank.
15. (Post-merge) Apply Surface 6b — fill §Examples row outcome columns (follow-up commit on this PR, or first post-merge maintenance commit, per TRN-3030 / TRN-3031 pattern).

## Reference Implementation

```
# BEFORE → AFTER: three blocks showing the normative spec changes.

# (1) §4 panel-dispatch instruction
# BEFORE:
#   Dispatch all 4 in parallel via the `Agent` tool.
#   PASS gate: all-individual ≥9.0 AND blocking empty.
# AFTER:
#   Dispatch the fast-review panel in parallel (trinity-glm, trinity-deepseek).
#   PASS gate: both individual ≥9.5 AND blocking empty.
#
# (2) §Failure Modes "Reviewer / provider unavailability"
# BEFORE:
#   The panel must have ≥3 viable providers to enforce the gate meaningfully —
#   proceed with N-1 only if N-1 ≥ 3 AND the failed provider wasn't the prior
#   round's dissenter; otherwise abort the panel and surface the outage to the
#   user. Below 3 viable: the convergence signal collapses; do NOT proceed
#   with 2-of-2.
# AFTER:
#   Panel requires both providers (trinity-glm, trinity-deepseek). If either is
#   unavailable, abort and surface outage to user; do not fall through to N-1
#   (single-provider review is not a panel). Retry once per provider; if still
#   unavailable after retry, surface immediately.
#
# (3) §Guard Rails
# BEFORE:
#   Never accept 3-of-4 PASS as gate-met. The dissenter's blockers must be
#   addressed.
# AFTER:
#   Any individual below the §4-specified threshold blocks the gate; dissent is
#   not absorbable. (Threshold and provider count are §4-spec-defined per
#   R17 SSOT.)
```

No ScheduleWakeup example needed — this CHG does not change wake patterns.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial draft (Status: Proposed). Closes #88. Supersedes #86. Plan-review of this CHG runs under operator-chosen option (b) — new 2-provider/≥9.5 tier. | trinity-glm |
| 2026-05-09 | R2 fixes from R1 panel (glm 9.175 / deepseek 9.00, mean 9.09, both FIX): added Surfaces 10-12 covering §Why pt-3, §Steps preamble TOC, §4 gate-enforcement prose, §4 panel-result table, §4 mermaid block (glm A6 — completeness blocker); added §Compression delta subsection enumerating per-surface deletion offsets (glm B1); split Surface 6 into 6a/6b (PR-open placeholder + PR-merge fill, mirroring TRN-3030/TRN-3031 pattern; glm B2 + deepseek A2); rewrote §Threshold rationale around three concrete arguments (structural / directive / cost) — dropped unproven catch-rate-equivalence claim (deepseek B1); UTC-anchored §Change History timestamp command in Surface 7 + Implementation Order step 11 (glm A1); folded #86 closure-note into §What body and frontmatter Supersedes — removed duplicated standalone section (deepseek A1); changed frontmatter Supersedes to "to be closed by this PR" — #86 currently OPEN (deepseek A4); verified `chatgpt-codex-connector[bot]` identity via `gh api repos/frankyxhl/trinity/pulls/{93,96}/reviews` — string is correct (deepseek A5). | trinity-glm |

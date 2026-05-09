# CHG-3031: Merge-Watch Active-Work Cancellation + Longer Cap

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Approved
**Date:** 2026-05-09
**Requested by:** chatgpt-codex-connector[bot] (R7 review on PR #93 commit 8f3790c) + @frankyxhl (deferral decision)
**Priority:** Medium-high
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #95
**Builds on:** TRN-3030 (PR #93, just merged) — fixes two correctness bugs in the §10 merge-watch loop introduced by TRN-3030 R7

---

## What

The §10 merge-watch wake's `prompt=` MUST embed the watched-branch name as a token (e.g., `merge-watch wake N of 24 for branch codex/foo`). On wake, the orchestrator runs `git rev-parse --abbrev-ref HEAD` and compares the result to the stored token. Match → proceed with the `gh pr view --json mergedAt` poll. Mismatch (a user-directed pick intervened and switched to a different branch) → wake is a no-op. Do NOT auto-switch-and-pull; the operator decides when to resume merge-watch via manual re-arm or the next §1 phase-1 entry on `main`. This mirrors the §1 cancellation pattern from TRN-3030 R3-R5, adapted for the merge-watch context where the orchestrator is legitimately on a feature branch.

The merge-watch cap is extended. Defect 2 migration: current TRN-1008 §Failure Modes case (b) uses `merge-watch wake N of 12` (12 × 270s = 54min, post-#93 merge). Proposed: `merge-watch wake N of 24` (24 × 1800s = 12h). Both cadence (270s → 1800s) and counter cap (12 → 24) change. Default option (a): 1800s × 24 = 12h, intentionally 2× §1 idle-retry max-stop (6h, 12 × 1800s @ TRN-1008 §Failure Modes case (b)) because branch-protected merges typically take longer than idle-with-retry's "no-work-pending" wait. The 1800s cadence is symmetric with §1; the count (24 vs 12) and total duration (12h vs 6h) intentionally differ. Plan-review must choose between three options and document the rationale in the PR body:

| Option | Cap | Cadence | Tradeoff |
|--------|-----|---------|----------|
| (a) | 24 wakes / 12h | 1800s throughout | Simple; cadence-symmetric with §1; loses cache-warm on first few wakes |
| (b) | 12 + 24 wakes / ~12.9h | 270s × 12 → 1800s × 24 | Preserves cache-warm early; counter logic more complex |
| (c) | 12 wakes / 54min | 270s | Manual resume after async/branch-protected merges |

The cache-warm-loss tradeoff for option (a) is acceptable because operator-availability latency (hours) dominates cache-miss cost (single seconds).

## Why

Codex-bot review on PR #93 commit 8f3790c found two correctness bugs in the §10 merge-watch loop that TRN-3030 R7 introduced (issue #95 §Problem-Goal). **P1** (comment `3212386563`): a merge-watch wake that fires while the orchestrator is on a different feature branch (user-directed pick intervened) will auto-switch-to-main-and-pull, destroying the in-flight work — the watched-branch token comparison closes this race. **P2** (comment `3212386565`): the 12-wake × 270s = 54 min cap is too short for async/branch-protected merges that can take 8-12h; the cap fires silently and abandons the watch — extending the cap to 12h resolves this. Both findings acknowledged via replies `3212407016` + `3212407071`. This is the first CHG iterating on a TRN-3030-introduced bug — a real-world test of the new merge-watch lifecycle. Tightly scoped: both defects live in TRN-1008 §10.

## R-history

- **R1 plan-review** (2026-05-09): trinity-glm 8.05 / FIX (1 blocker [symmetry-claim factual error] + 3 advisories); trinity-deepseek 8.60 / FIX (1 blocker [Closes #95 vs unmet RefImpl-update expectation] + 4 advisories). Mean 8.325; gate ≥9.5 + zero blocking. Both providers converged on need for factual precision and explicit handling of issue-#95 expectations. R2 applies 6 fixes: (1) symmetry-claim corrected to cadence-only (count/duration intentionally 2× §1, not symmetric); (2) explicit justification added for retaining `Closes #95` despite TRN-3030 RefImpl untouched (CHGs are historical records, not living spec); (3) counter migration `N of 12` → `N of 24` made explicit at 4 locations including Surface 3 AC; (4) Surface 4 hedge resolved to NEW §Failure Modes case (f); (5) Surface 5 §Examples row reframed from hypothetical to actual-PR retrospective per TRN-3030 pattern; (6) Defect 2 options compressed to a 3-row table + atomicity-justification note added to Surfaces preamble.
- **R2 plan-review** (2026-05-09): trinity-glm 9.23 / FIX (2 advisories: post-RefImpl prose redundancy + `<name>` vs `<BRANCH_NAME>` placeholder inconsistency); trinity-deepseek 9.50 / PASS (1 advisory: option (b) total math `~12.5h` vs correct `~12.9h`). Mean 9.365; glm 0.27 short of 9.5 gate; deepseek at threshold. R3 applies 3 surgical trim/correction fixes: (1) collapsed post-RefImpl rationale paragraph to a single-line cross-reference (eliminates near-duplication of §What and RefImpl comment block); (2) standardized Surface 1 placeholder `<name>` → `<BRANCH_NAME>` for consistency with AC Surface 1 and RefImpl block; (3) corrected option (b) total `~12.5h` → `~12.9h` (12 × 270s + 24 × 1800s = 46440s = 12.9h).

## Out of Scope

- Other §1 / §11 paths — this CHG only touches the §10 merge-watch loop.
- Panel rule changes (issue #88 — different surface: §4 + §8).
- Worker-default rule (issue #91 — different surface).
- Comprehension-check phase (issue #92 — different surface).
- Wait-state guard (issue #94 — different surface; #94's closure-checklist applies to this CHG's PR).

## Surfaces

Surfaces are split by content kind (e.g., mermaid/code vs prose; mechanism-extension vs new-case) when they share a heading; each split has distinct ACs.

| # | Surface | Change |
|---|---------|--------|
| 1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §10 merge-watch loop | Wake `prompt=` embeds watched-branch token (e.g., `merge-watch wake N of 24 for branch <BRANCH_NAME>`) AND **migrates count token from `N of 12` (just shipped via #93) to `N of 24` to reflect the new cap**; on wake, compare `git rev-parse --abbrev-ref HEAD` to stored token; mismatch → wake is no-op (do NOT auto-switch-and-pull; operator decides when to resume). |
| 2 | TRN-1008 §10 prose | Explicitly state the watched-branch comparison rule. The merge-watch's exemption from the universal "must be on main" guard applies ONLY when current branch matches the stored watched-branch token; ANY other branch is the cancellation signal. |
| 3 | TRN-1008 §Failure Modes case (b) max-consecutive | **Migrate the count token from `N of 12` (just shipped via #93) to `N of 24`** and cadence from 270s to 1800s; extend with merge-watch counter pattern; cap per plan-review-decided option (default (a) 1800s × 24 = 12h; cadence-symmetric with §1 idle-retry, but count (24) and duration (12h) are intentionally 2× §1's count (12) and duration (6h)). |
| 4 | TRN-1008 §Failure Modes — NEW **case (f) 'Active-work cancellation for merge-watch'** | Describes the watched-branch token comparison rule: on each merge-watch wake, the orchestrator runs `git rev-parse --abbrev-ref HEAD` and compares to the stored token; mismatch → wake is no-op (operator decides resume). Cross-references the §1 cancellation pattern per R17 SSOT (do not restate the check count). |
| 5 | TRN-1008 §Examples | Add new row when this CHG's PR ships, documenting the PR (issue #95, lane, plan-review/code-review iterations, outcome) — this PR is itself the first instance of the new merge-watch rule. Mirrors TRN-3030's surface which added a row for PR #93 itself. No hypothetical scenario; the row is concrete retrospective data. |
| 6 | TRN-1008 §Change History | New row dated to commit timestamp. |
| 7 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3031 entry via `af index --root .` regen. |
| 8 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry mentioning the merge-watch active-work-cancel guard + longer cap (12h default). |

Note: TRN-3030 stays untouched as a historical CHG record; this CHG modifies the live SOP (TRN-1008) only.

**Note on issue #95 TRN-3030 RefImpl update expectation**: Issue #95's Expected Outcome listed "TRN-3030 Reference Implementation: 3rd ScheduleWakeup example (merge-watch) updated for both defects". This CHG explicitly does NOT update TRN-3030 — CHGs are historical records of the change at the time it shipped, not living spec. The normative merge-watch specification lives in TRN-1008 §10 (the live SOP), which this CHG amends. Future readers reconstructing what shipped in TRN-3030 see the original (now-superseded) example; future readers needing the current spec read TRN-1008 §10. This is the standard pattern across all post-merge corrections (e.g., CHG-3029's later corrections live in subsequent CHGs, not retroactive edits to CHG-3029). `Closes #95` is therefore retained: this CHG resolves the underlying defects, and the RefImpl-update line item is reframed (not silently dropped).

## Acceptance Criteria

- [ ] Surface 1: §10 merge-watch `ScheduleWakeup` `prompt=` embeds `merge-watch wake N of 24 for branch <BRANCH_NAME>` token; on wake, orchestrator compares `git rev-parse --abbrev-ref HEAD` to stored token; mismatch → no-op (no auto-switch-and-pull).
- [ ] Surface 2: §10 prose states the watched-branch comparison rule explicitly; notes that the "must be on main" guard exemption applies only when current branch matches the watched-branch token.
- [ ] Surface 3: §Failure Modes case (b) extended with merge-watch counter pattern (`merge-watch wake N of 24` token, 12h cap, surface message on N==24); no leftover `N of 12` text remains in TRN-1008 §Failure Modes case (b) after the migration.
- [ ] Surface 4: §Failure Modes gains **NEW case (f) 'Active-work cancellation for merge-watch'**; cross-references §1's cancellation pattern per R17 SSOT without restating the check count.
- [ ] Surface 5: §Examples row added documenting this CHG's own PR (real retrospective entry; not hypothetical). Row populated with PR #, issue #95, lane, plan-review/code-review iterations, outcome at handoff time.
- [ ] Surface 6: §Change History row dated to commit timestamp (per R20 lesson: UTC, anchored to `git log --format=%ai`).
- [ ] Surface 7: `rules/TRN-0000-REF-Document-Index.md` regenerated; TRN-3031 indexed.
- [ ] Surface 8: CHANGELOG `[Unreleased] ### Changed` entry for merge-watch active-work-cancel guard + longer cap.
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate met under TRN-1008 §4 rules in force at pickup time. (Note: #88 fast-review tier may or may not be merged at pickup; surface to plan-review R1 whether Frank is pre-applying fast-review again.)
- [ ] Code-review gate met under TRN-1008 §8 rules in force at pickup time.
- [ ] PR body documents which Defect 2 option was chosen (a/b/c) with plan-review rationale.
- [ ] PR body links back to PR #93 R7 comments (`3212386563` + `3212386565`) as the source findings.
- [ ] PR body includes `Closes #95`.
- [ ] Self-test in PR body: dry-run merge-watch wake with a tracer prompt to verify the watched-branch comparison fires correctly (lighter than full PR cycle; ~2 minutes live observation).

## Implementation Order

1. (Already done) Branch `codex/trn-3031-merge-watch-cancel-cap` cut from `origin/main` per TRN-1008 §2.
2. (Dispatch to worker per #91 worker-default) Draft this CHG with Status: Proposed.
3. (Orchestrator-direct) `af validate --root .` to confirm CHG ACID-compliance before plan-review.
4. (Orchestrator-direct) Plan-review panel R1 under TRN-1008 §4 rules in force. Decide Defect 2 option (a/b/c). Iterate to gate.
5. (Orchestrator-direct) On gate-met: flip Status: Proposed → Approved on this CHG; commit the flip.
6. (Dispatch to worker) Apply Surfaces 1-2 (TRN-1008 §10 merge-watch `ScheduleWakeup` watched-branch token + §10 prose watched-branch comparison rule).
7. (Dispatch to worker) Apply Surfaces 3-4 (§Failure Modes case (b) merge-watch counter extension + active-work-cancellation sub-section).
8. (Dispatch to worker) Apply Surface 5 (§Examples row).
9. (Dispatch to worker) Apply Surface 6 (§Change History row dated to commit timestamp).
10. (Orchestrator-direct) Apply Surfaces 7-8 (`af index --root .` regen + CHANGELOG entry).
11. (Orchestrator-direct) `af validate --root .` clean. Commit; push to `fork`.
12. (Orchestrator-direct) Open PR with `Closes #95`, Defect 2 choice rationale, self-test result. Code-review per §8 rules in force. Iterate to gate. Handoff to Frank.

## Reference Implementation

```
# Surface 1 — §10 merge-watch invocation (UPDATED for TRN-3031).
# Two-guard cancellation: (1) stop-marker FIRST per §Failure Modes case (c);
# (2) watched-branch comparison SECOND per §Failure Modes new sub-section
# (active-work cancellation). The watched-branch token is embedded in the
# prompt at arming time and compared on each wake.
# Cap: option (a) plan-review default — 1800s × 24 = 12h. Cadence (1800s)
# symmetric with §1 idle-with-retry; count (24) and duration (12h) are
# intentionally 2× §1's (12 wakes / 6h) — branch-protected async merges
# run longer than idle-with-retry's no-work-pending wait. Plan-review may
# select (b) two-tier or (c) keep-and-surface; this RefImpl tracks (a).
ScheduleWakeup(
  delaySeconds=1800,
  reason="TRN-1008 §10 merge-watch — polling PR #<N> mergedAt on branch <BRANCH_NAME>",
  prompt="TRN-1008 §10 merge-watch wake — merge-watch wake 1 of 24 for branch <BRANCH_NAME> on PR #<N>. FIRST: if -e $(git rev-parse --git-path trinity-loop-stopped), wake is no-op (user-stop active per §Failure Modes case (c)). SECOND: run `git rev-parse --abbrev-ref HEAD`; if not <BRANCH_NAME>, user-directed pick intervened — wake is no-op (do NOT auto-switch-and-pull; operator decides when to resume merge-watch via manual re-arm OR next §1 phase 1 entry on main). If branch matches: gh pr view <N> --json mergedAt -q .mergedAt. If non-null (merged): git switch main && git pull --ff-only origin main; arm §11 loop-restart wake. If null (still pending): arm next merge-watch wake with prompt containing `merge-watch wake <N+1> of 24 for branch <BRANCH_NAME>` unless N==24 (surface to user: merge-watch timed out on PR #N after 12h)."
)
```

Option (a) rationale and cache-warm tradeoff per §What and RefImpl comment block above. Plan-review may overrule with option (b) or (c).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial draft (Status: Proposed). Closes #95. Defect 2 default option (a) 1800s × 24 = 12h pending plan-review confirmation. | trinity-glm |
| 2026-05-09 | R2 fix pass after R1 plan-review (glm 8.05 / deepseek 8.60, both FIX). Applied 6 convergent + reviewer-specific fixes; details in §R-history above. CHG re-dispatched for R2 panel. | trinity-glm |
| 2026-05-09 | R3 trim pass after R2 plan-review (glm 9.23 / FIX, deepseek 9.50 / PASS). Applied 3 surgical fixes: post-RefImpl prose collapse + `<name>` → `<BRANCH_NAME>` placeholder standardization + option (b) math `~12.5h` → `~12.9h`. CHG re-dispatched for R3 panel. | trinity-glm |

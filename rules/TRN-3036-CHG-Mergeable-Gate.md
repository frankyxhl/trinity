# CHG-3036: Mergeable Gate (Decouple Auto-Pick From Actual Merge)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Proposed
**Date:** 2026-05-09
**Requested by:** @frankyxhl chat directive 2026-05-09 ("那我现在想改成 mergable 就能 autopick 下一个任务...")
**Priority:** Medium-High
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #106
**Builds on:** TRN-3031 (PR #96) — extends §10 merge-watch with a parallel mergeable-handoff trigger; TRN-3030 (§11 loop-restart). §10 watched-branch token + active-work cancellation from TRN-3031 are preserved unchanged in the merge-watch path; this CHG ADDS a parallel trigger.

---

## What

Split TRN-1008 §10 Handoff into two concurrent triggers: (1) **mergeable-handoff trigger** (NEW) — fires immediately when the "PR is mergeable" multi-signal predicate is satisfied (CI green + bot 👍 + panel gate met + no open blockers — the same predicate §10 already uses to declare handoff to the user); declares mergeable to user and arms §11 wake (60s) WITHOUT waiting for `mergedAt`. (2) **merge-watch** (UNCHANGED from TRN-3031) — continues polling `gh pr view N --json mergedAt`; on actual merge fires cleanup (`git switch main && git pull --ff-only origin main`). The two triggers run in parallel: mergeable-handoff arms §11 once on first-mergeable; merge-watch continues independently until merge or 12h cap. §11 entry precondition becomes dual-state: **State A** (current — on `main` with `origin/main` pulled, post-merge cleanup) or **State B** (NEW — on prior PR's branch with PR mergeable, branching next issue off `origin/main`). Under State B, the prior PR IS the in-flight unmerged dependency. The existing §1 phase-1 scope-rank tree includes a `Depends on unmerged PR?` check (mermaid node C → Z2) — this is the load-bearing safety net for State B. If the next issue's body declares any dependency on the prior PR (via `Depends-on:` link or implicit issue-thread reference), the dependency check rejects pickup until prior PR merges. Branch-base policy + dependency check together close the State B safety surface. §1 gains a one-line note that auto-pick can fire under either state. §Failure Modes gains a "Mergeable-but-revoked" subsection. §Steps preamble TOC updated.

**Branch-base policy**: next-issue branch always = `origin/main` regardless of §11 entry state. Under State B, the prior PR's source changes are not yet on `origin/main`; if the new issue's surfaces overlap the prior PR's, the new branch will need rebase post-merge. Accepted tradeoff — Phase 2 branch hygiene already pulls `origin/main`; under State B that pull may be stale relative to prior PR's HEAD, but that is strictly safer than branching off an unmerged PR HEAD (avoids inheriting unreviewed code).

**Concurrent-PR cap (orchestrator-side guard)**: at §1 phase-1 entry (after rocket-eligibility scan, before §1.5 comprehension check), the orchestrator runs:
```bash
# `$REPO` is the §1-config repo identifier (default: frankyxhl/trinity); honors PKG-promotion.
# `$AGENT_GH_LOGIN` is the agent's gh-CLI identity that AUTHORS PRs (default: ryosaeba1985 per §2);
# distinct from `$TRUSTED_REACTOR` (rocket-consent signal, default: frankyxhl).
open_count=$(gh pr list --repo "$REPO" --author "$AGENT_GH_LOGIN" --state open --json number -q 'length')
if [ $? -ne 0 ] || [ -z "$open_count" ]; then
  # gh failure (network / auth / rate-limit) — fail closed.
  exit_to_idle_with_message "concurrent-PR cap query failed; idling conservatively (gh non-zero or empty count)"
fi
if [ "$open_count" -ge 2 ]; then
  # Cap reached — idle wake until merges reduce in-flight count
  exit_to_idle_with_message "concurrent-PR cap N≤2 reached; idle until ≥1 merge"
fi
```
The cap value (N=2: prior PR awaiting merge + current pick) is a §1 phase-1 guard, not a hardcoded constant — future evolve cycles may revisit. Document the rationale: rebase-cost amplification grows with N, claim-comment collision risk grows quadratically, reviewer cognitive load grows linearly.

## Why

PR cadence cost (~30% loop idle): across recent #89 → #98 → #103 → #104 sequence, every transition incurred 30–90 min idle waiting on operator's merge click. Panel + bot already converged on quality before merge — the merge click is operator timing, not a quality signal. Strict serialization wastes the autonomous loop's value by ~30%. Explicit user directive 2026-05-09.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | TRN-1008 §10 Handoff prose (~L579-587) | Split current "merge-watch loop" into TWO concurrent triggers: (a) NEW **mergeable-handoff trigger** — fires immediately when "PR is mergeable" predicate satisfied (CI green + bot 👍 + panel gate + no open blockers); declares mergeable to user; arms §11 wake (60s) WITHOUT waiting for `mergedAt`. (b) **merge-watch** (UNCHANGED — preserves TRN-3031 watched-branch token + cap + active-work cancellation): continues polling `gh pr view N --json mergedAt`; on actual merge fires cleanup `git switch main && git pull --ff-only origin main`. The two triggers run in parallel: mergeable-handoff arms §11 once on first mergeable; merge-watch continues independently until merge or 12h cap. |
| 2 | TRN-1008 §11 Loop restart entry precondition (~L591) | Replace single load-bearing precondition with TWO accepted entry states: **State A** (current) — on `main` with `origin/main` pulled (post-merge cleanup complete; picked from §10 merge-watch). **State B** (NEW) — on prior PR's feature branch with PR in `mergeable` state (mergeable-handoff trigger fired). Both states route into §11's wake-then-re-enter-phase-1 logic. State B's branch-base policy: next-issue branch = `origin/main` (NOT prior PR's branch HEAD); §2 branch hygiene's `git fetch origin main && git switch -c codex/<slug> origin/main` is unchanged. **§11 State-B git-branch guard**: at wake time, `git rev-parse --abbrev-ref HEAD` is compared to **three** accepted states: (a) `main` (State A — merge happened, cleanup ran); (b) prior PR's watched branch (State B — operator hasn't merged yet, orchestrator hasn't moved on); (c) any `codex/*` branch matching `^codex/` prefix (State B — orchestrator already started next issue's branch). All three accept the wake; any other branch → wake is no-op (mirrors §10 merge-watch case (f) cancellation guard). |
| 3 | TRN-1008 §1 Phase 1 (~L67-77) | One-line note: "Auto-pick can fire under either §11 entry state — State A (post-merge on main) or State B (mergeable-handoff on prior PR branch); see §11." |
| 4 | TRN-1008 §2 Branch hygiene (~L245-285) | One-line addition flagging rebase-risk: "Under §11 State B (mergeable-handoff), the prior PR's source changes are not yet on `origin/main`; if the new issue's surfaces overlap, the new branch will need a rebase post-merge. Accepted cost — surfaces are typically orthogonal in the rocket queue." |
| 5 | TRN-1008 §Failure Modes — NEW subsection "Mergeable-but-revoked" (insert after case (f), ~L703) | Describes the failure mode: PR was declared mergeable (bot 👍 + panel + CI all green), §11 fired in State B, next issue picked up; subsequently mergeable revoked. **Revocation triggers**: any of the 4 mergeable-predicate signals can flip back to non-clean post-handoff: (i) CI fails on a new commit, (ii) bot 👍 retracted (codex re-finds issue on a forced-push), (iii) panel re-score below gate (a new commit re-triggers panel review), (iv) blocker label re-applied. Recovery is identical for all four — the merge-watch path independently polls `mergedAt`; the prior PR remains unmerged until all signals re-align. **Recovery flow**: merge-watch wake is armed independently at the moment of mergeable-handoff and continues polling `mergedAt` regardless. No explicit re-routing required. The TRN-3031 case (f) watched-branch cancellation guard handles the case where the orchestrator has moved on (next-issue branch active) — merge-watch wake fires as no-op until manual re-arm OR the next §1 phase-1 entry on main eventually catches up. **60s arm-window edge case**: if mergeable revoked during the 60s window between §11-arm and §11-fire, the wake proceeds (was armed on a valid first-mergeable signal). Residual risk accepted because: (a) 60s < typical CI / bot re-review latency; (b) next-issue branch is `origin/main`-based, not inheriting prior PR's code; (c) the concurrent-PR cap (Surface 1 orchestrator-side guard) already prevents cascading on revocation chains. |
| 6 | TRN-1008 §Steps preamble TOC (~L62-65) | Phase 10 row → "'mergeable' = orchestrator done (declares mergeable + arms §11 in State B); merge-watch continues for actual merge". Phase 11 row gains "(State A or State B)" qualifier. |
| 7 | TRN-1008 §Change History | New row dated 2026-05-09 UTC summarizing the §10 split + §11 dual-entry + Failure Modes addition. |
| 8 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3036 entry via `af index --root .` regen. |
| 9 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry: "TRN-1008 §10/§11: auto-pick now fires when prior PR is mergeable (CI + bot + panel + no blockers), not when actually merged. Recovers ~30% loop idle time." |
| 10 | TRN-1008 §1 Phase 1 (~L67-77) — concurrent-PR cap guard | Add orchestrator-side hard-cap check at §1 phase-1 entry (after rocket-eligibility scan, before §1.5 comprehension check): query `gh pr list --repo "$REPO" --author "$AGENT_GH_LOGIN" --state open --json number -q 'length'`; if ≥2, exit-to-idle with structured message "concurrent-PR cap N≤2 reached; idle until ≥1 merge". Filters by `$AGENT_GH_LOGIN` (agent identity, default `ryosaeba1985`), NOT `$TRUSTED_REACTOR` — `gh pr list --author` filters by PR author; agent PRs are authored by `ryosaeba1985` per §2 identity-gate, not by the rocket-consent reactor. Cap value parameterized as a §1 phase-1 guard (not hardcoded constant) — future evolve cycles may revisit. Rationale: rebase-cost amplification grows with N; claim-comment collision risk grows quadratically; reviewer cognitive load grows linearly. |

**Atomicity note**: multi-section CHG bundled by correlated behavior change — precedent: TRN-3031, TRN-3033. Per TRN-1800 atomicity dimension, this satisfies "one coherent design change" even though it touches multiple §-sections. Surfaces 1, 2, 4 are within `## Steps` heading sections of the same multi-section doc TRN-1008 — each gets its own row. Surface 5 is a NEW subsection of §Failure Modes (separate row). Surface 3 and Surface 10 are both within §1 but cover distinct entry-point edits (dual-state note vs concurrent-PR cap guard) — separate rows. All TRN-1008 surfaces share the same atomicity unit (one §-heading-edit per surface).

## Mermaid impact

§1 mermaid does NOT depict §10/§11 transitions (terminates at `EXEC[Proceed]`). The §10/§11 dual-path is pure prose. **No mermaid edits required.** Plan-review may recommend adding a §10/§11 mermaid as future cleanup; out-of-scope here.

## Acceptance Criteria

- [ ] Surface 1: §10 prose documents BOTH concurrent triggers (mergeable-handoff NEW + merge-watch UNCHANGED) with explicit interaction description.
- [ ] Surface 2: §11 entry precondition documents State A and State B with explicit branch-base policy.
- [ ] Surface 3: §1 Phase 1 has one-line dual-state note.
- [ ] Surface 4: §2 Branch hygiene has rebase-risk note.
- [ ] Surface 5: §Failure Modes has new "Mergeable-but-revoked" subsection.
- [ ] Surface 6: §Steps preamble TOC reflects dual-trigger §10 + dual-state §11.
- [ ] Surface 7: §Change History row appended (UTC timestamp per R20 lesson).
- [ ] Surface 8: TRN-0000 index regenerated.
- [ ] Surface 9: CHANGELOG entry added.
- [ ] Surface 10: §1 phase-1 entry guards on N<2 in-flight authored PRs; idles with structured message when cap reached.
- [ ] §11 State-B guard accepts {main, prior-PR-branch, codex/*-branch} states; rejects all others as no-op.
- [ ] Regression test for State-B-then-revoked path: simulate (a) mergeable-handoff fires, (b) §11 wake arms, (c) bot revokes 👍 within 60s arm-window, (d) §11 fires anyway on stale signal — verify next-issue starts with origin/main as base (not prior PR's branch HEAD), and prior PR's merge-watch continues independently.
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate: fast-review tier ≥9.5 + zero blocking.
- [ ] Code-review gate: fast-review tier ≥9.5 + zero blocking.
- [ ] PR body: `Closes #106`, documents mermaid yes/no rationale, documents concurrent-PR cap.

## Reference Implementation

**Mergeable-handoff trigger** (§10):

```python
def declare_mergeable_and_arm_handoff(pr_number, watched_branch):
    """Called when all 4 mergeable signals satisfied: CI green, bot 👍, panel ≥9.5, no open blockers."""
    # 1. Surface mergeable declaration to user
    surface(f"PR #{pr_number} is mergeable; awaiting your merge click. Proceeding to next issue per §11 State B.")
    # 2. Arm §11 loop-restart wake (60s post-handoff burst — same cadence as State A)
    ScheduleWakeup(
        delaySeconds=60,
        reason=f"§11 loop-restart from mergeable-handoff PR #{pr_number}",
        # The wake prompt encodes the FULL §11 State-B guard (NOT just the simple regex),
        # because branch (c) acceptance has THREE conjunctive conditions per TRN-1008 §11
        # State-B guard prose: regex match + open PR for branch + that PR's own mergeable
        # predicate. A regex-only check bypasses (b) and (c) and re-introduces the
        # abandoned-mid-iteration-PR failure mode.
        prompt=f"§11 wake from mergeable-handoff (PR #{pr_number}, watched-branch {watched_branch}). "
               f"FIRST: if -e $(git rev-parse --git-path trinity-loop-stopped), no-op. "
               f"SECOND: run §11 State-B guard from TRN-1008 (3-branch acceptance check): "
               f"  branch={{git rev-parse --abbrev-ref HEAD}}; "
               f"  if branch == 'main' OR branch == '{watched_branch}' → accept; "
               f"  elif branch matches /^codex\\// AND `gh pr list --head $branch --state open --json number -q 'length'` >= 1 "
               f"      AND that PR's own §10 mergeable predicate is satisfied (CI green + bot 👍 + panel ≥9.5 + no blockers) → accept; "
               f"  else no-op (orchestrator must resume in-flight work, not start new issue). "
               f"THIRD: on accept, enter §1 phase-1 (next-issue auto-pick); on no-op, exit cleanly."
    )
    # 3. Merge-watch wake remains independently armed (continues polling mergedAt regardless)
```

Coexistence with merge-watch: both wakes are armed; mergeable-handoff fires first (60s) and triggers next-issue pickup; merge-watch fires later (when operator merges) and runs cleanup as no-op via watched-branch guard if orchestrator has moved on.

## Migration / Backward-compat

Zero impact on existing in-flight PRs at the time of merge: the new mergeable-handoff path is purely ADDITIVE — old strict-serial behavior remains valid as State A. PRs already mid-merge-watch when this CHG ships continue under the existing TRN-3031 contract; §11 still accepts State A as canonical entry. No release-note breaking change. No config migration. Operators who prefer strict-serial may simply not push next issues' rockets until prior merges land — the gate stays closed under State A in that case.

**Concurrent in-flight PR count**: the new path enables N=2+ PRs simultaneously open. Hard cap N≤2 enforced via orchestrator-side guard at §1 phase-1 entry (Surface 10) — operator-rocket cadence is no longer the primary mechanism. Rocket-gate on the next issue remains independent of any in-flight PR's status, but the orchestrator-side cap fires BEFORE rocket-gate work begins; if `gh pr list --repo "$REPO" --author "$AGENT_GH_LOGIN" --state open` returns ≥2 (or fails, in which case it fails closed), phase-1 exits to idle with structured message. Filter by `$AGENT_GH_LOGIN` (PR author identity), not `$TRUSTED_REACTOR` (rocket-consent signal). Future evolve cycles may revisit the cap value via PRP/CHG.

## Threat Model assessment

No new attack surface. Specifically:
- **Prompt-injection**: rocket-gate on the next issue runs `verify_rocket_eligibility` independently — does not consult prior PR's status. Mergeable-handoff does not relax any consent-signal check.
- **Half-trusted PR**: the prior PR's "mergeable" predicate is the SAME multi-signal predicate §10 already uses to declare handoff to user — no looser standard introduced.
- **Race window**: mergeable-handoff fires once on first-mergeable; if subsequently revoked (bot 👍 retracted), the in-flight next issue continues but the prior PR returns to merge-watch. No window opens where un-consented work proceeds.
- **Branch-base**: next-issue branch = `origin/main` (NOT prior PR's HEAD) — the new issue's branch never inherits unreviewed code from the prior PR, even under State B. This is strictly safer than branching off prior PR's branch.

Accepted residual: under State B, the prior PR's source changes are not on `origin/main` yet; if the new issue's surfaces overlap, rebase cost applies. This is workflow cost, not an attack.

**Force-push residual (accepted)**: branch-protection rules on `frankyxhl/trinity` prevent force-push to main, BUT not necessarily to feature branches. If force-push is allowed on a prior PR's feature branch, an attacker could inject post-mergeable-handoff commits, causing the prior PR to merge with tainted code. Under State B, the next issue is safe (branch-base = `origin/main`, not the tainted prior PR). The prior PR's contamination matches the pre-CHG threat surface (force-push could always taint between mergeable declaration and merge click). Mitigation is at the GitHub branch-protection layer, not this CHG.

## Implementation Order

1. (Already done) Branch `codex/trn-mergeable-gate` cut from `origin/main` per TRN-1008 §2.
2. (This CHG draft) Status: Proposed; ready for plan-review.
3. (Orchestrator-direct) `af validate --root .` to confirm CHG ACID-compliance before plan-review.
4. (Orchestrator-direct) Plan-review panel R1 under TRN-1008 §4 fast-review tier. Decide concurrent-PR cap (recommended N≤2). Decide mermaid yes/no. Iterate to gate.
5. (Orchestrator-direct) On gate-met: flip Status: Proposed → Approved on this CHG; commit.
6. (Dispatch to worker per #91) Apply Surfaces 1–7 (TRN-1008 §10/§11/§1/§2/§Failure Modes/§Steps preamble TOC/§Change History edits).
7. (Orchestrator-direct) Apply Surfaces 8–9 (`af index --root .` regen + CHANGELOG entry).
8. (Orchestrator-direct) `af validate --root .` clean. Commit; push to `fork`.
9. (Orchestrator-direct) Open PR with `Closes #106`, plan-review choices documented. Code-review per §8 fast-review tier. Iterate to gate. Handoff to Frank.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial draft (Status: Proposed). Closes #106. Concurrent-PR cap default N≤2 pending plan-review. Mermaid decision deferred to plan-review. | trinity-glm |
| 2026-05-09 | Plan-review R1: added orchestrator-side concurrent-PR cap mechanism (Fix-1); rewrote mergeable-but-revoked recovery prose + generalized revocation triggers + 60s arm-window edge case (Fix-2); §11 State-B guard accepts 3-branch states (Fix-3); §Reference Implementation pseudocode (Fix-4); §1 mermaid dependency-check cross-ref (Fix-5); regression-AC for revocation path (Fix-7); force-push threat residual (Fix-8); atomicity citation corrected to TRN-1800 (Fix-9). | Claude Opus 4.7 |

# CHG-3030: Self-Driving Loop (idle-with-retry + Phase 11 loop-restart)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Approved
**Date:** 2026-05-09
**Requested by:** @frankyxhl
**Priority:** Medium
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #90
**Builds on:** TRN-1008 §1 (rocket-gate + bypass clause SSOT per R17), §8 (canonical `ScheduleWakeup` invocation pattern per R11)

---

## What

**Phase 1 self-drives via idle-with-retry.** Today's TRN-1008 §1 ends idle paths at the terminal `Z_GATE_B → idle silently / do not invent work` node, and recurrence depends on an external trigger (`/loop 10m` cron, manual re-invocation, or fresh chat input). This CHG amends §1 so that on idle, phase 1 arms a 1800s `ScheduleWakeup` and re-runs itself on wake. Mirrors the canonical pattern in §8 (R11 history note): named params `delaySeconds`, `reason`, `prompt`. A live-chat user-directed pick during the wait pre-empts the wake (per the §1 normative bypass clause, unchanged). 1800s matches §8's existing "no work pending" cadence guidance for amortising cache-miss across longer waits.

**Loop restart becomes an explicit phase.** A new §11 "Loop restart" appears at the end of the SOP, immediately after §10 Handoff. It fires a 60s `ScheduleWakeup` (§8 minimum; do not go below) whose prompt re-enters phase 1, replacing §10's informal `Move to phase 1 (auto-pick next issue)` line with an executable step. The new §11 is also advertised in TRN-1008's §Steps preamble (the "loop has N phases" line bumps from 10 → 11, with a new TOC bullet for §11). Combined with §1's idle-with-retry, the SOP self-perpetuates: pick → ship → handoff → §11 wake → phase 1 → next 🚀'd issue OR idle+retry. The external `/loop 10m` cron becomes redundant; operator-stop is one-liner (just don't re-invoke `/loop`).

## Why

The cron-driven recurrence is fragile and invisible. During #85 the cron was stopped manually mid-flight ("stop/start at state-transitions" pattern); after #87 merged it had to be re-armed by hand and the SOP did not self-heal. On 2026-05-09 the bypass clause was misread as a pick directive after a routine "continue the loop" message, exposing how dependent the SOP is on out-of-band recurrence prompting. Baking recurrence into §1 + §11 removes a class of "loop stopped without operator noticing" bugs and makes the cycle visible in the §1 mermaid graph.

## R-history

- **R1 plan-review** (2026-05-09): trinity-glm 7.85 / FIX (3 blockers + 5 advisories + 1 self-critique missing-surface); trinity-deepseek 7.85 / FIX (1 blocker + 3 advisories). Both providers converged at 7.85 from different angles. R2 applies 10 convergent + reviewer-specific fixes: idle cadence 600s → 1800s; phantom §11 cross-refs corrected to §8; Reference Implementation code-fence cleaned (no `bash` tag, no shell escapes); mermaid wake re-entry corrected from `V` to `A` (full phase-1 scan); pre-empt encoded as separate branch + prose note (mermaid lacks edge-annotation primitive); new Surface 11 covers TRN-1008 §Steps preamble phase-count bump; SOP-side comment about future #83 retrospective insertion ordering; Surface 6 cites concurrent-orchestrator claim-comment debounce; AC#15 self-test downgraded to dry-run tracer; CHANGELOG entry gains plain-language sentence; Surface 9 atomicity split between TRN-3030 regen and TRN-3029 catch-up acknowledgement.
- **R2 plan-review** (2026-05-09): trinity-glm 9.10 / FIX (3 advisories); trinity-deepseek 9.39 / FIX (4 advisories). Both providers said FIX-on-cosmetics — one editor pass closes the gap to PASS. R3 applies 5 surgical trim/tighten edits: (1) Surface 6(b) "suggested" → "MUST be" (aligns with normative AC checkbox); (2) Surface 4 + AC#4 + §What "~60s" → "60s delay (§8 minimum; do not go below)" (commits to §8's hard floor; tightened Reference Implementation rationale to match); (3) trimmed redundant R2 Change History row that duplicated this R-history (R-history stays canonical); (4) Surface 6(e) quotes verbatim from TRN-1008 §Failure Modes "Concurrent orchestrators" subsection so wording cannot drift; (5) new AC line documenting the issue #90 cadence deviation (600s → 1800s) with §8 citation and operator-visible impact note.

## Out of Scope

- Phase 11 = retrospective hook + COR-1200 wiring (issue #83 — different surface). Per orchestrator + Frank sequencing decision on 2026-05-09: #83 was NOT rocket-approved, so this CHG claims §11 for **loop-restart**. If #83 ships later, it inserts as a subsequent phase (re-numbering the retrospective hook); this CHG's §11 stays put. NOTE: the natural retrospective-then-loop-restart order is for retrospective to fire BEFORE the wake — see SOP-side comment in the new §11 body for renumber guidance.
- 2-provider fast-review tier + ≥9.5 PASS gate (issue #88 — different surface: §4 + §8). Plan-review of THIS CHG runs under whichever rules are in force at pickup.
- `/loop` slash command implementation. The command itself is untouched; it simply becomes optional after this CHG.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1 mermaid block | `Z_GATE_B` is no longer terminal. New edge `Z_GATE_B → WAIT[wait 1800s (ScheduleWakeup)] → A` (full phase-1 re-run from candidate scan, not gate-only). The wake re-runs `scripts/scan_rocket_issues.sh` so newly-rocketed/labeled issues are picked up. Pre-empt: a separate `WAIT` outgoing branch labelled `live chat input` leads to `USER_PICK[user-directed pick path]`, mirroring §1's existing bypass-clause behaviour. Annotated as a prose note adjacent to the graph (mermaid lacks an edge-annotation primitive). |
| 2 | TRN-1008 §1 prose | New subsection **"Idle-with-retry behavior"** naming `ScheduleWakeup`, the 1800s default cadence, cache-cost cross-reference to §8, pre-empt semantics (live chat input cancels the wake per §1 normative bypass clause, unchanged), pointer to §Failure Modes for stop conditions. |
| 3 | TRN-1008 §Guard Rails | Existing rule **"For autonomous picks, never invent work when no candidate is rocket-eligible"** extended count-free (per R17 SSOT) to **"idle ≠ exit; idle = wait+retry until interrupted or stopped per §Failure Modes"**. No restate of the check count. |
| 4 | TRN-1008 NEW **§11 "Loop restart"** | Explicit step at the end of the SOP. After §10 Handoff completes, fire `ScheduleWakeup` with a 60s delay (§8 minimum; do not go below) whose prompt re-enters phase 1. Mirrors §8 R11 named-param pattern. **Inline SOP comment**: "If a future retrospective phase is added (e.g., per issue #83), it inserts BEFORE this §11 step; renumber accordingly." |
| 5 | TRN-1008 §10 ending | Replace the line `Move to phase 1 (auto-pick next issue)` with a pointer: `Proceed to §11 Loop restart`. |
| 6 | TRN-1008 §Failure Modes | New subsection **"ScheduleWakeup unavailable / loop stop conditions"** covering 5 cases: (a) tool-failure fallback to manual operator re-run, (b) max-consecutive-idle stop MUST be 12 wakes / 6 hours @ 1800s → surface to user, (c) user `stop`/`pause`/`hold` chat input → exit cleanly without a wake, (d) session termination → wakes die with the session (existing tool semantics, document explicitly), (e) cron + idle-retry concurrency → relies on existing §Failure Modes "Concurrent orchestrators": > "Each orchestrator posts `🤖 Auto-pick claim: <id> at <ISO-8601>` on the tracking issue at branch-creation time, after re-polling for an existing claim within the last 10 min." No new mechanism needed. |
| 7 | TRN-1008 §Examples | New row showing the loop-back pattern: rocket-eligible → pick → ship → handoff → §11 wake → phase 1 re-fires → next 🚀'd issue picked OR idle+retry. |
| 8 | TRN-1008 §Change History | New row dated to commit timestamp referencing this CHG. |
| 9 | `rules/TRN-0000-REF-Document-Index.md` | 9a. Add TRN-3030 entry via `af index --root .` regen. 9b. **Pre-existing-defect catch-up**: TRN-3029 (just shipped) was missed from the index when CHG-3029 merged — the same `af index` regen catches it up. Acknowledge as a ratified catch, not a silent bundle. (Optionally split into a separate trivia commit; orchestrator's call.) |
| 10 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry: "TRN-1008 §1 / new §11 — phase 1 self-drives via ScheduleWakeup idle+retry; explicit loop-back step at end of SOP. External `/loop 10m` cron now optional. **After a PR is handed off, the orchestrator automatically resumes picking without waiting for a cron tick.**" |
| 11 | TRN-1008 §Steps preamble (line ~50) | "The loop has 10 phases" → "The loop has 11 phases"; add row to the TOC bullet list for §11 "Loop restart". |

## Acceptance Criteria

- [ ] Surface 1: §1 mermaid graph updated; `Z_GATE_B` cycles back to phase-1 entry (`A`, not `V`) via a `wait 1800s (ScheduleWakeup)` edge so the candidate scan re-runs; user chat input encoded as a separate `WAIT → USER_PICK` branch with adjacent prose note (mermaid edge-annotation workaround); no other graph nodes changed.
- [ ] Surface 2: §1 has a new "Idle-with-retry behavior" subsection naming `ScheduleWakeup`, the 1800s default, cache-cost cross-ref to §8, pre-empt semantics, and a pointer to §Failure Modes for stop conditions.
- [ ] Surface 3: §Guard Rails "never invent work" rule extended count-free per R17 SSOT to cover idle = wait+retry; no restate of the check count.
- [ ] Surface 4: NEW §11 "Loop restart" exists with explicit `ScheduleWakeup` invocation, 60s delay (§8 minimum; do not go below), prompt re-entering phase 1; uses §8 R11 named-param shape (`delaySeconds`, `reason`, `prompt`); contains inline comment about future #83 retrospective inserting BEFORE §11 with renumber.
- [ ] Surface 5: §10 ending references §11 (the `Move to phase 1` line is replaced with a pointer, not duplicated).
- [ ] Surface 6: §Failure Modes new subsection covers tool-failure fallback, max-consecutive-idle stop (12 / 6h @ 1800s), user-stop chat input, session-termination semantics, and cron + idle-retry concurrency relying on existing claim-comment 10-min debounce.
- [ ] Surface 7: §Examples row showing handoff → §11 wake → phase 1 → next pick OR idle+retry.
- [ ] Surface 8: §Change History row dated to commit timestamp (per R20 lesson — UTC, anchored to `git log --format=%ai`).
- [ ] Surface 9: `rules/TRN-0000-REF-Document-Index.md` regenerated; both TRN-3029 and TRN-3030 indexed. PR body explicitly notes the TRN-3029 index catch-up as a pre-existing-defect ratification (not silent).
- [ ] Surface 10: CHANGELOG `[Unreleased] ### Changed` entry mentioning the cron-replacement, with plain-language sentence about post-handoff auto-resume.
- [ ] Surface 11: TRN-1008 §Steps preamble phase-count bumps from 10 → 11 with a new TOC bullet for §11 "Loop restart".
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate met under TRN-1008 §4 rules in force at pickup time.
- [ ] Code-review gate met under TRN-1008 §8 rules in force at pickup time.
- [ ] PR body includes `Closes #90`, notes `/loop 10m` cron is now optional, AND documents the Phase-11-vs-#83 sequencing decision (this CHG claims §11 for loop-restart since #83 was not rocket-approved).
- [ ] PR body explicitly notes the cadence revision from issue #90's proposed 600s to 1800s, citing §8's "no work pending: 1800-3600s" rule. Operator-visible impact: first idle wake is 30min, not 10min.
- [ ] PR body documents a dry-run self-test: orchestrator calls `ScheduleWakeup(delaySeconds=60, reason='TRN-3030 self-test', prompt='TEST §11 wake fired')`; observes the wake re-enters phase 1 with that prompt; spot-checks the loop-back path without committing to a full PR cycle. Live observation in PR body, ~2 minutes.

## Implementation Order

1. (Already done) Branch `codex/trn-3030-self-driving-loop` cut from `origin/main` per TRN-1008 §2.
2. (This step — orchestrator-direct) Draft `rules/TRN-3030-CHG-Self-Driving-Loop.md` with Status: Proposed.
3. (Orchestrator-direct) Run `af validate --root .` to confirm CHG ACID-compliance before plan-review.
4. (Orchestrator-direct) Plan-review panel R1 under TRN-1008 §4 rules in force. Iterate to gate.
5. (Orchestrator-direct) On gate-met: flip Status: Proposed → Approved on this CHG; commit the flip.
6. (Dispatch to worker) Apply Surfaces 1-3 + 11 (TRN-1008 §1 mermaid + prose subsection + §Guard Rails + §Steps preamble phase-count bump). Worker dispatched per TRN-1008 §5; orchestrator spot-checks per §Guard Rails "Never trust worker reports without spot-checking".
7. (Dispatch to worker) Apply Surfaces 4-5 (NEW §11 + §10 pointer line replacement).
8. (Dispatch to worker) Apply Surfaces 6-7 (§Failure Modes new subsection + §Examples row).
9. (Dispatch to worker) Apply Surface 8 (§Change History row dated to commit timestamp).
10. (Orchestrator-direct) Apply Surfaces 9-10 (`af index --root .` regen + CHANGELOG entry).
11. (Orchestrator-direct) `af validate --root .` clean. Commit; push to `fork`.
12. (Orchestrator-direct) Open PR with `Closes #90`, sequencing note, self-test result. Code-review per §8 rules in force. Iterate to gate. Handoff to Frank.

## Reference Implementation

```
# Surface 2 — §1 idle-with-retry invocation (fired when verify_rocket_eligibility
# returns no eligible candidate AND no live-chat user-directed pick is pending):
ScheduleWakeup(
  delaySeconds=1800,
  reason="TRN-1008 §1 idle-with-retry — no rocket-eligible candidate this tick",
  prompt="TRN-1008 §1 phase-1 re-fire. Re-run scripts/scan_rocket_issues.sh | while read N; do verify_rocket_eligibility "$N" || continue; done. If a candidate is now eligible, proceed to scope-rank tree. If still idle, arm next 1800s wake unless §Failure Modes stop condition reached (12 consecutive idle wakes / user stop / session termination / ScheduleWakeup tool failure). Pre-empt: any live-chat user instruction cancels the wake per §1 normative bypass clause."
)

# Surface 4 — NEW §11 Loop restart invocation (fired at the end of the SOP,
# immediately after §10 Handoff completes):
ScheduleWakeup(
  delaySeconds=60,
  reason="TRN-1008 §11 loop restart — re-enter phase 1 after handoff",
  prompt="TRN-1008 §11 loop restart. Prior PR is mergeable and handed off to Frank per §10. Re-enter phase 1: run scripts/scan_rocket_issues.sh | while read N; do verify_rocket_eligibility "$N" || continue; done. If a candidate is rocket-eligible, proceed to scope-rank tree. If idle, arm §1 idle-with-retry (1800s wake). Pre-empt: any live-chat user instruction cancels the wake per §1 normative bypass clause."
)
```

Cadence rationale: 60s for §11 (post-handoff burst — operator may 🚀 a queued issue immediately after merge; short delay catches it without burning ticks; §8's "Never < 60s" hard minimum applies); 1800s for §1 idle-with-retry (well past 5-min cache TTL — the cache-miss cost is amortised against operator-availability latency, per §8 cadence guidance). 60s is a hard floor (§8); 1800s may be tuned upward per operator availability without changing the SOP shape.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial draft (Status: Proposed). Closes #90. Phase-11-vs-#83 sequencing: this CHG claims §11 for loop-restart since #83 was not rocket-approved. | Claude Opus 4.7 |
| 2026-05-09 | R2 fix pass after R1 plan-review (glm 7.85 / deepseek 7.85, both FIX). Applied 10 convergent + reviewer-specific fixes; details in §R-history above. CHG re-dispatched for R3. | Claude Opus 4.7 |
| 2026-05-09 | R3 trim+tighten pass after R2 plan-review (glm 9.10 / deepseek 9.39, both FIX-on-cosmetics). 5 surgical edits; details in §R-history above. | Claude Opus 4.7 |

# CHG-3037: Wake-Prompt § References (Replace Inline Guard Pseudocode With SOP § Pointers)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-10
**Last reviewed:** 2026-05-10
**Status:** Proposed
**Date:** 2026-05-10
**Requested by:** @frankyxhl issue #112 (filed after PR #109 R4 caught wake-prompt drift in TRN-3036 §Reference Implementation)
**Priority:** Medium
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #112
**Builds on:** TRN-3036 (PR #109) — replaces inline State-B guard pseudocode in §Reference Implementation with a § reference; TRN-3030 (§1 idle-retry, §11 loop-restart) and TRN-3031 (§10 merge-watch) — call sites whose prompts are refactored in §10/§11/§1 prose.

---

## What

Refactor every `ScheduleWakeup(...)` call in TRN-1008 §1 / §10 / §11 (and the pseudocode echo in TRN-3036 §Reference Implementation) so each `prompt=` parameter carries a concise §-reference + the call-site's variable bindings (PR/branch/counter), NOT a re-statement of the SOP's guard logic. The woken orchestrator's duty is to read the referenced § section verbatim and execute it; the prompt no longer encodes FIRST/SECOND/THIRD pseudocode, regex, or the multi-condition State-B guard inline.

Add a new TRN-1008 §Guard Rails entry — **Wake-procedure duty** — codifying the orchestrator's obligation: on every wake, before any side-effecting action, read the referenced § section literally (`Read` tool on `rules/TRN-1008-...md`) and follow its prose. Do NOT synthesize behaviour from the prompt text alone. The prompt is a procedure CALL; the § section is the procedure body. SSOT.

**Example (§11 State-B from TRN-3036 RefImpl)**:

- BEFORE: `prompt="§11 wake from mergeable-handoff (PR #N, watched-branch <B>). FIRST: if -e $(git rev-parse --git-path trinity-loop-stopped), no-op. SECOND: run §11 State-B guard from TRN-1008 (3-branch acceptance check): branch={...}; if branch == 'main' OR branch == '<B>' → accept; elif branch matches /^codex\\// AND `gh pr list --head $branch --state open` >= 1 AND that PR's own §10 mergeable predicate is satisfied → accept; else no-op. THIRD: on accept, enter §1 phase-1; on no-op, exit cleanly."`
- AFTER: `prompt="On wake, execute TRN-1008 §11 State-B guard literally per the §Guard Rails 'Wake-procedure duty' rule (read §11 prose, do not synthesize from this prompt). Bindings: PR=#<N>; watched_branch=<B>. On accept, enter §1 phase-1; on no-op, exit cleanly."`

The prompt no longer duplicates the 3-branch / open-PR / own-mergeable logic; it points at §11 prose, which is the SSOT.

## Why

PR #109 R4 (codex-bot comment [3214106551](https://github.com/frankyxhl/trinity/pull/109#discussion_r3214106551)) caught a real drift bug: TRN-3036 §Reference Implementation's pseudocode `prompt=` only encoded `^codex/` regex match for State-B, missing the open-PR + own-mergeable conjunctive checks that R3 had added to TRN-1008 §11 prose. Nothing mechanically tied the two — the prompt was a stale copy. R4 fixed that single instance, but the structural defect remains across every other wake site: the prose in §1 / §10 / §11 carries the normative guard, while every `prompt=` re-states a snapshot of that guard. Any future tightening (the same pattern as R10–R17 on TRN-1008's own history of duplicated rules drifting independently) silently stales every prompt copy until the next codex-bot pass catches each one individually.

Replacing inline pseudocode with a § reference + the new Wake-procedure-duty guard rail makes drift impossible by construction: the prompt has nothing to drift FROM. SSOT moves to the SOP prose; wakes inherit the latest semantics for free.

## Surfaces

**Placeholder convention**: angle-bracket tokens like `<N>`, `<BRANCH_NAME>`, `<PR_NUMBER>` are runtime-substituted values (set at `ScheduleWakeup(prompt=...)` arm time via Python f-string interpolation). The orchestrator at wake time sees the substituted concrete value, not the placeholder.

| # | Surface | Change |
|---|---------|--------|
| 1 | TRN-1008 §1 "Idle-with-retry behavior" prose (~L172) — the idle-retry `ScheduleWakeup` invocation | Replace inline FIRST/SECOND/THIRD pseudocode in `prompt=` with `"Execute TRN-1008 §1 idle-with-retry guard (stop-marker check + on-main check) per §Guard Rails 'Wake-procedure duty'. Bindings: idle wake <N> of 12."` Counter tokens are **preserved as bindings** (rather than verbatim phrases) — the binding `idle wake <N> of 12` carries the count via runtime substitution of `<N>` per the placeholder convention preamble; the referenced § documents the increment-on-wake mechanism. The rendered string at wake time is `idle wake 1 of 12`, `idle wake 2 of 12`, etc., matching §Failure Modes (b)'s required phrase shape — see Surface 7 amendment for the dual-form rule. |
| 2 | TRN-1008 §10 (A) Mergeable-handoff prose (~L619) — the `ScheduleWakeup(60)` invocation | Replace inline FIRST/SECOND/THIRD + State-B guard pseudocode with `"Execute TRN-1008 §11 State-B guard literally per §Guard Rails 'Wake-procedure duty'. Bindings: PR=#<N>; watched_branch=<B>."` Drops the ~3-line inline regex + open-PR + own-mergeable copy. |
| 3 | TRN-1008 §10 (B) Merge-watch prose (~L624) — the `ScheduleWakeup(1800)` invocation | Replace inline FIRST/SECOND/THIRD + watched-branch + mergedAt-poll pseudocode with `"Execute TRN-1008 §10 (B) merge-watch wake procedure per §Guard Rails 'Wake-procedure duty'. Bindings: PR=#<N>; watched_branch=<B>; merge_watch_count=<N> of 24."` Counter tokens preserved as bindings (see Surface 1 note). |
| 4 | TRN-1008 §11 Loop-restart prose (~L641) — the `ScheduleWakeup(60)` invocation | Replace inline FIRST/SECOND/THIRD pseudocode with `"Execute TRN-1008 §11 loop-restart wake procedure (State-A or State-B guard per §11 entry-precondition prose) per §Guard Rails 'Wake-procedure duty'. Bindings: prior_PR=#<N>; entry_state=<A or B>."` |
| 5 | TRN-1008 §Guard Rails — NEW entry **Wake-procedure duty** | "On every `ScheduleWakeup` fire, the orchestrator MUST, **before any side-effecting action**, `Read` the referenced § section literally and execute it. The stop-marker FIRST guard inside the referenced § applies as the first step of execution. The orchestrator's `Read` target is determined by the §-pointer in the wake prompt (e.g., `TRN-1008 §11 State-B guard`). When the pointer cites a SOP other than TRN-1008 (e.g., a future TRN-30XX with its own wake protocol), the duty applies to that SOP's prose. Do NOT synthesize the wake's behaviour from the prompt text alone. The prompt is a procedure CALL with binding parameters (PR/branch/counter); the § section is the procedure body. Rationale: prompts are immutable strings captured at arm-time; SOP § prose is the live SSOT. Inline pseudocode in prompts goes stale silently every time §-prose tightens (e.g., the §11 State-B 3-condition guard regression caught in PR #109 R4). Inserted between the existing 'Wait-state guard' and end-of-list." |
| 6 | TRN-3036 §Reference Implementation pseudocode (~L94-111) | Update the `declare_mergeable_and_arm_handoff` pseudocode `prompt=f"..."` to use the reference-style prompt (matches Surface 2). Drops the ~7-line inline State-B guard. Comment block above the call (`# The wake prompt encodes the FULL §11 State-B guard (NOT just the simple regex)...`) updated to: `# The wake prompt is a § REFERENCE per CHG-3037 — the SOP §11 State-B guard is the live source of truth; the prompt carries only the binding parameters.` |
| 7 | TRN-1008 §Failure Modes (b) ~L747 — counter mechanism amendment | Append clause: **Note (CHG-3037)**: When using **ref-style** prompts (per §Guard Rails "Wake-procedure duty"), the counter binding takes the form `idle wake <N> of 12` (with `<N>` runtime-substituted via f-string interpolation per the placeholder convention preamble) embedded in the prompt's binding-variable section (alongside `<BRANCH_NAME>` etc.) — not as a literal phrase requirement. The rendered string at wake time is `idle wake 1 of 12`, `idle wake 2 of 12`, etc., matching the literal phrase shape (b) mandates. The orchestrator's Wake-procedure-duty `Read` of the referenced § (here §1 idle-with-retry prose, which itself documents the increment-on-wake mechanism) is the authoritative procedure. Inline-style prompts (legacy) continue to require the literal phrase verbatim per the rule above. |
| 8 | TRN-1008 §Failure Modes (c) ~L751 — stop-marker FIRST guard amendment | Append clause: **Note (CHG-3037)**: For **ref-style** prompts (per §Guard Rails "Wake-procedure duty"), the FIRST guard is satisfied by the referenced § section's prose, which itself documents the stop-marker FIRST step. The Wake-procedure-duty rule's `Read`-then-execute obligation guarantees the orchestrator runs the stop-marker check before any side-effecting action. Inline-style prompts (legacy) continue to require the literal `FIRST:` clause verbatim per the rule above. |
| 9 | TRN-1008 §Change History | New row dated 2026-05-10 UTC summarizing wake-prompt refactor + Wake-procedure-duty guard rail. |
| 10 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3037 entry via `af index --root .` regen. |
| 11 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry: "TRN-1008 §1/§10/§11 + TRN-3036 RefImpl: ScheduleWakeup `prompt=` parameters now carry concise § references + bindings, not inline guard pseudocode. New §Guard Rails 'Wake-procedure duty' rule. Closes #112." |

**Atomicity note**: multi-section CHG bundled by single coherent design change (one structural pattern applied symmetrically to every wake call site + its load-bearing guard rule + the §Failure Modes counter-clauses that the refactor amends). Per TRN-1800 atomicity dimension and CLD-1802 surface taxonomy (symmetric multi-file refactor → the *class* is the surface), Surfaces 1–4 form a symmetric class (same structural edit: replace inline pseudocode with § ref + bindings) — listed individually for explicit before/after invariants per CLD-1802. Surface 5 is the load-bearing guard rule that makes the refactor safe; Surface 6 mirrors the refactor in TRN-3036's pseudocode echo; Surfaces 7–8 reconcile §Failure Modes (b)/(c) literal-phrase requirements with the new ref-style surface form. Precedent: TRN-3031, TRN-3033, TRN-3036 (all multi-section).

## Audit Note (out-of-scope, recorded for historical fidelity)

Inline `ScheduleWakeup` examples in **TRN-3030 §Reference Implementation** (L103, L113, L121) and **TRN-3031 §Reference Implementation** (L113) are historical CHG records — per TRN-3031's own precedent ("CHGs are historical records of the change at the time it shipped, not living spec"), they are NOT updated by this CHG. Future readers reconstructing what shipped read the original; future readers needing the current spec read TRN-1008 §1 / §10 / §11 (which Surfaces 1–4 update). TRN-3036 §Reference Implementation IS updated (Surface 6) because it ships in the same PR as the §11 State-B guard prose it pseudocodes — the two are co-current, not historical/superseded. **TRN-3032 §Reference Implementation** explicitly states "No ScheduleWakeup example needed" — no edit required. **TRN-3033 §Wait-state guard** mentions `ScheduleWakeup` only as a noun (no prompt-text example) — no edit required.

## Acceptance Criteria

- [ ] Surface 1: TRN-1008 §1 idle-retry `ScheduleWakeup` `prompt=` uses § reference + idle-counter binding; no FIRST/SECOND/THIRD inline pseudocode.
- [ ] Surface 2: TRN-1008 §10 (A) mergeable-handoff `ScheduleWakeup` `prompt=` uses § reference + PR/branch bindings; no inline State-B guard pseudocode.
- [ ] Surface 3: TRN-1008 §10 (B) merge-watch `ScheduleWakeup` `prompt=` uses § reference + PR/branch/merge-watch-counter bindings; no inline mergedAt-poll pseudocode.
- [ ] Surface 4: TRN-1008 §11 loop-restart `ScheduleWakeup` `prompt=` uses § reference + entry-state binding; no inline pseudocode.
- [ ] Surface 5: TRN-1008 §Guard Rails has new "Wake-procedure duty" entry codifying read-before-execute on every wake.
- [ ] Surface 6: TRN-3036 §Reference Implementation pseudocode uses § reference style (mirrors Surface 2); RefImpl comment block updated.
- [ ] Surface 7: TRN-1008 §Failure Modes (b) ~L747 amended with CHG-3037 note clarifying counter binding form for ref-style prompts (legacy literal-phrase requirement preserved for inline-style).
- [ ] Surface 8: TRN-1008 §Failure Modes (c) ~L751 amended with CHG-3037 note clarifying stop-marker FIRST guard satisfaction via referenced § prose for ref-style prompts (legacy literal `FIRST:` clause preserved for inline-style).
- [ ] Surface 9: TRN-1008 §Change History row appended (UTC 2026-05-10).
- [ ] Surface 10: TRN-0000 index regenerated via `af index --root .`.
- [ ] Surface 11: CHANGELOG `[Unreleased] ### Changed` entry added.
- [ ] Counter tokens are **preserved as bindings** (rather than verbatim phrases) — the binding variable carries the count (Surface 1 idle-counter; Surface 3 merge-watch-counter); the referenced § documents the increment-on-wake mechanism. Equivalent semantics; different surface form per the SSOT principle. Surface 7 amends §Failure Modes (b) accordingly.
- [ ] Stop-marker semantics preserved: §Failure Modes (c) requires every wake's `prompt=` include the stop-marker FIRST guard; for ref-style prompts this is satisfied by the §-referenced procedure (the §1/§10/§11 prose itself documents the stop-marker FIRST step) per Surface 8's amendment to §Failure Modes (c) — verify no §-prose regression.
- [ ] Audit row in §Audit Note explicitly records TRN-3030 / TRN-3031 RefImpl as historical (out-of-scope).
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate: fast-review tier ≥9.5 + zero blocking.
- [ ] Code-review gate: fast-review tier ≥9.5 + zero blocking.
- [ ] PR body: `Closes #112`; cross-links PR #109 R4 (`3214106551`) as the discovery signal; documents historical-RefImpl audit decision.

## Migration / Backward-compat

**Zero state migration.** `ScheduleWakeup` jobs are session-only and ephemeral (per §Failure Modes (d) — wakes die with the Claude session). Wakes already armed in-flight at the time this CHG ships continue to fire correctly under their old inline-pseudocode prompts (the orchestrator's old code path for "execute prompt verbatim" still works against literal prompts). Newly-armed wakes use the new § reference style. There is no in-flight wake that survives across the merge boundary because the merge itself drops the running session's wakes if the operator restarts; if the operator does not restart, in-flight wakes fire under the conversation that armed them (which is still running the pre-CHG behaviour). No coordination, no fallback, no dual-format reader required.

**Operator-facing**: zero. The wake fires, the orchestrator reads the §, executes prose. Indistinguishable from the prior behaviour at the user level except (a) the § prose is now the live source of truth (so any prose tightening since arm-time is automatically applied — strictly safer), and (b) prompt strings are shorter (~3-7 lines per wake → ~1-2 lines), which marginally reduces session-context cost.

## Threat Model assessment

**No new attack surface.** Specifically:

- **Prompt-injection**: § references are inert text — they encode pointer + binding, no executable logic. The orchestrator's `Read`-then-execute step on the referenced § is a routine SOP-compliance read against `rules/TRN-1008-...md`, a path under the repo's own version control. No external string is dereferenced.
- **§-pointer tampering**: a malicious actor with write access to `rules/TRN-1008-...md` could modify §11 State-B guard prose to weaken the guard, and newly-armed wakes would inherit the weakened guard automatically. This is the SAME attack surface as today (the prose is already the SSOT for human readers and code-review panel reviewers); the wake-time `Read` does not introduce a new privilege. Mitigation lives at the GitHub branch-protection layer (the SOP edit ships via PR + plan-review + code-review panel + bot review per TRN-1008's own loop).
- **SOP-compliance failure**: if a future orchestrator implementation forgets to read the referenced § on wake and instead synthesizes from prompt text, the wake misbehaves silently. This is a SOP-compliance class issue, not a security hole. Surface 5's Wake-procedure-duty rule + §-prose acceptance criteria + plan-review panel are the existing controls; making the duty explicit (vs implicit today) strictly tightens compliance, never loosens it.

**Stop-marker redundancy note**: In the old (inline) design, the stop-marker check was duplicated in every prompt string (defense-in-depth). In the new (ref-style) design, it is enforced through the Wake-procedure-duty rule's `Read`-then-execute obligation on § prose (SSOT). The redundancy reduction is intentional — duplicated rules are the defect class this CHG closes (§Why, PR #109 R4). Compensating controls: (a) the Wake-procedure-duty rule itself; (b) plan-review panel verification that every referenced § section correctly documents the stop-marker FIRST step; (c) §Failure Modes (c) as the normative stop-marker contract. A future orchestrator that violates the duty rule and synthesizes from prompt text would also miss every other § guard, not just the stop-marker — the stop-marker is not uniquely vulnerable.

Accepted residual: TRN-3030/TRN-3031 historical RefImpl pseudocode remains unchanged per §Audit Note. Future reader confusion ("which inline-prompt example is current?") is mitigated by the CHG-as-historical-record convention and by Surface 9's §Change History row pointing at TRN-1008 §1/§10/§11 as the live spec.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-10 | Initial draft (Status: Proposed). Closes #112. Six TRN-1008/TRN-3036 surfaces enumerated; TRN-3030/TRN-3031 RefImpl flagged as historical (out-of-scope per §Audit Note). | trinity-glm |
| 2026-05-10 | Plan-review R1: added Surfaces for §Failure Modes (b)/(c) amendments (counter binding + stop-marker exception clauses for ref-style); disambiguated "preserved verbatim" → "preserved as bindings"; tightened Wake-procedure-duty ordering ("before any side-effecting action"); defined placeholder convention; added Threat Model stop-marker redundancy note; promoted §-pointer SOP-routing parenthetical. | Claude Opus 4.7 |

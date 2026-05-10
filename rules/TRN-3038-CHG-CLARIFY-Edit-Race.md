# CHG-3038: CLARIFY Edit-Race vs §1 Rocket-Gate Body-Edit Invalidation (Comment-Based CLARIFY)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-10
**Last reviewed:** 2026-05-10
**Status:** Proposed
**Date:** 2026-05-10
**Requested by:** chatgpt-codex-connector[bot] R6 review on PR #99 commit `155f0f9` (comment `3212948899`); deferred per @frankyxhl chat decision on 2026-05-09.
**Priority:** Medium
**Change Type:** Refactor (SOP amendment)
**Targets:** `main`
**Closes:** #100
**Builds on:** TRN-3033 (CHG that introduced §1.5 comprehension check); coexists with the §1 rocket-gate timeline-events check 3 (R12/R13/R14/R26 evolution that hardened body-edit invalidation).

---

## What

Resolve the design conflict between §1 rocket-gate check 3 (invalidates the gate on any post-rocket `edited`/`renamed`/`closed`/`reopened`/`transferred`/`unlocked` timeline event) and §1.5 CLARIFY outcome prose ("re-evaluate on body edits or next phase-1 tick") by adopting **option (b) comment-based CLARIFY**: the operator responds to a CLARIFY comment by posting a NEW issue comment (NOT by editing the issue body). The orchestrator re-evaluates the candidate on the next phase-1 tick, reading the comment thread to determine whether scope is now clear.

Concretely:

- **§1.5 CLARIFY outcome bullet (line 235)** — Replace "re-evaluate on body edits or next phase-1 tick" with normative comment-based prose: the CLARIFY comment instructs the operator to **reply via a new issue comment** (NOT a body edit); the orchestrator re-evaluates on the next phase-1 tick by reading the comment thread (most-recent operator comment after the orchestrator's CLARIFY comment carries the clarification text). Body edits remain invalidating per §1 check 3 — operators who edit the body must un-🚀 + re-🚀 to reset consent (legacy "option (a)" workaround preserved as fallback, not the recommended path).
- **§1.5 Re-evaluation flow paragraph (line 264)** — Rewrite to specify: on next phase-1 tick (idle-with-retry wake, §11 loop-restart, or chat input), `verify_rocket_eligibility` re-runs against the **unmodified** issue body (which still passes check 3 because no body edit occurred), and on PASS the orchestrator routes the candidate through §1.5 again. The §1.5 re-run reads the comment thread via `gh api repos/$REPO/issues/$N/comments --paginate`, identifies the operator's most-recent reply after the orchestrator's CLARIFY comment, and re-runs the 6-point rubric using the original body augmented with the operator's clarification text. Outcome → PROCEED (scope now clear), CLARIFY again (still unclear; new question or re-ask), or REJECT (operator declined / cap exhausted per §1.5 round-counter).
- **§1 rocket-gate prose (around line 153 and the §Threat Model paragraph at line 690)** — Add an explicit sentence after the "self-contained" paragraph stating that `commented` is **NOT** in the invalidating-events list (currently implicit — only `edited`/`renamed`/`closed`/`reopened`/`transferred`/`unlocked` invalidate). Note that the comment-based CLARIFY workflow (per §1.5) **relies on this exemption**: comments preserve consent because they are an additive conversation surface, not a content-mutation surface. §Threat Model paragraph appended with the comment-vs-body-edit defense reasoning (already partially documented; this CHG makes the §1.5 dependency explicit).
- **§1 mermaid `CLAR_OUT` node (line 115)** — Update label from `Post comment; defer; preserve blueprint-ready label; re-eval on next phase-1 tick` to `Post comment (asks operator to reply via new comment, NOT body edit); defer; preserve blueprint-ready label; re-eval on next phase-1 tick reads comment thread`.
- **§1.5 CLARIFY comment template (lines 240-251)** — Append a normative final line: `**Reply via a new comment on this issue** (do NOT edit the issue body — that would invalidate the rocket-gate consent per §1 check 3 and require un-🚀 + re-🚀). The orchestrator re-reads the comment thread on the next phase-1 tick.`

### Rejected alternative — option (a) strict re-rocket

Discarded in favour of (b). Option (a) would amend §1.5 to require the operator to un-🚀 + re-🚀 after every body edit (and CLARIFY rounds would route through body edits as today). Pros: 1-2 line SOP change; preserves "edits invalidate consent" rocket-gate semantics with no carve-out. Cons: operator-friction multiplies linearly with CLARIFY round count (3-round cap × 1 manual rocket-cycle each = up to 3 rocket-cycles per issue); rocket-cycle is a bespoke ritual not native to GitHub's conversation flow; comment-based dialogue is the canonical surface for "I have a question about your work item". Net: option (b) ships the same correctness with materially better UX, at the cost of one structural §1.5 prose rewrite + one explicit §1 sentence documenting the existing comment-exemption. Plan-review may override and pick (a) if simplicity dominates UX in the panel's judgement.

## Why

PR #99 R6 codex-bot comment `3212948899` identified a real correctness gap: §1.5 says "re-evaluate on body edits", but §1 check 3 (R12/R13/R14/R26 evolution) invalidates the gate on any post-rocket `edited` event. CLARIFY-marked issues that get edited (the natural fix path the SOP documents) are silently skipped on every subsequent phase-1 tick until the operator manually un-🚀 + re-🚀 — a user-visible failure of the just-shipped CLARIFY workflow.

The two rules were composed without noticing the conflict because they were authored in different CHGs (§1 check 3 evolved through R12/R13/R14/R26; §1.5 was added by CHG-3033). Comment-based CLARIFY resolves the conflict by routing clarifications through the surface §1 already exempts (`commented` not in invalidator list) instead of the surface §1 fail-closes on (`edited`).

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | TRN-1008 §1.5 CLARIFY outcome bullet (~L235) | Replace "re-evaluate on body edits or next phase-1 tick" with comment-based normative prose: operator replies via new comment; body edits remain invalidating per §1 check 3 (legacy fallback only). |
| 2 | TRN-1008 §1.5 Re-evaluation flow paragraph (~L264) | Rewrite to specify comment-thread read on next-tick re-eval. The orchestrator runs `gh api repos/$REPO/issues/$N/comments --paginate` and identifies the operator's most-recent reply via this anchor logic: (i) find the orchestrator's most-recent CLARIFY comment by filtering `user.login == $AGENT_GH_LOGIN` AND body starts with `Comprehension check — CLARIFY (§1.5):` (the canonical CLARIFY comment template header); (ii) the operator's clarification = most-recent comment AFTER that anchor whose `user.login` is **in the trusted set** `{$TRUSTED_REACTOR}` — same trusted-reactor identity that grants rocket consent per check 2. Restricting CLARIFY-reply authorship to the consent-granting principal prevents hostile non-trusted commenters from injecting clarification text. Comments from any other login (bots, other contributors, agent self-replies) are ignored for re-eval. The 6-point rubric re-runs on (original body + operator clarification text). Outcomes: PROCEED / CLARIFY again / REJECT. **Clarification-comment TOCTOU pin (PROCEED path)**: when §1.5 PROCEEDs based on a `$TRUSTED_REACTOR` clarification comment, the orchestrator MUST record the chosen comment's `id` AND `updated_at` at PROCEED time. Before each subsequent side-effecting git op (branch creation per §2, push, PR open) AND on every `RV` re-verify, the orchestrator MUST re-fetch the comment via `gh api repos/$REPO/issues/comments/<id>` and compare `updated_at` to the pinned value. If `updated_at` has changed (operator edited the clarification post-PROCEED), abort the in-flight work and re-run §1.5 against the new comment text. Without this pin, the body-edit TOCTOU class (closed by §1 check 3 timeline-events) reopens on the comment surface — comment `id` (immutable) + `updated_at` (changes on edit) form the same pin pattern §1 uses for the issue-body `rocket_created` timestamp. |
| 3 | TRN-1008 §1.5 CLARIFY comment template (~L240-251) | Append normative final line instructing operator to reply via comment (not body edit), with explicit warning about §1 check 3 invalidation. |
| 4 | TRN-1008 §1 rocket-gate prose (~L153, after the "self-contained" sentence) | Add explicit sentence: `commented` events are NOT in the invalidating-events list (only `edited`/`renamed`/`closed`/`reopened`/`transferred`/`unlocked` invalidate). The §1.5 comment-based CLARIFY workflow relies on this exemption. |
| 5 | TRN-1008 §1 mermaid `CLAR_OUT` node (~L115) | Update label to reflect comment-based flow: `Post comment (asks operator to reply via new comment, NOT body edit); defer; preserve blueprint-ready label; re-eval on next phase-1 tick reads comment thread`. |
| 6 | TRN-1008 §Threat Model paragraph (~L690) | Append clause: comment-based CLARIFY (per §1.5) does NOT introduce a new attack surface — comment authors do not grant consent (rocket reactions on the issue body remain the sole consent signal per check 2); §1.5 PROCEED outcome triggers branch creation + worker dispatch only, both of which are subsequently rocket-gated and panel-reviewed. Hostile commenters can attempt to spoof clarification text, but the orchestrator's PROCEED routing depends on the rubric's cross-section consistency check (still applied to the original body, which is the consent-anchored surface), not on comment authorship. Accepted residual: comment-spam DoS is no worse than today's body-edit-spam path. |
| 7 | TRN-1008 §Change History | New row dated 2026-05-10 UTC summarizing comment-based CLARIFY adoption + §1 commented-exemption documentation. |
| 8 | `rules/TRN-0000-REF-Document-Index.md` | Add TRN-3038 entry via `af index --root .` regen. |
| 9 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry: "TRN-1008 §1.5: CLARIFY outcome now uses comment-based dialogue (operator replies via new comment, not body edit) to avoid §1 rocket-gate body-edit invalidation. Closes #100." |

**Atomicity note**: multi-section CHG bundled by single coherent design change (one structural pattern — route CLARIFY clarifications through the comment surface §1 already exempts). Per CLD-1802 surface taxonomy, Surfaces 1–6 form a cross-class set unified by the comment-based CLARIFY contract; each is a distinct §-section per CLD-1802's "multi-section doc → each `##` heading is a surface" rule but they ship together because partial application would re-create the §1/§1.5 conflict in a new shape. Precedent: TRN-3033 (multi-section), TRN-3037 (multi-section).

**Compression note**: net-positive growth (~+10-15 lines on TRN-1008 prose: ~120 char outcome bullet rewrite + ~400 char re-eval paragraph rewrite + ~200 char §1 commented-exemption sentence + ~150 char comment-template normative line + ~300 char Threat Model clause + ~50 char mermaid label update). Justified by bugfix necessity — the deletions (~120 char on the broken outcome-bullet wording + ~400 char on the broken re-eval paragraph) plus additions yield a net-zero-to-slightly-positive prose delta with corrected semantics. Net-positive for a security-correctness fix is acceptable per TRN-1800 doc weights when the alternative is a silent failure mode. No deletion offset opportunity elsewhere — the surrounding §1 / §1.5 prose is load-bearing.

## Acceptance Criteria

- [ ] Surface 1: §1.5 CLARIFY outcome bullet specifies comment-based reply mechanism; legacy body-edit fallback documented as un-🚀 + re-🚀.
- [ ] Surface 2: §1.5 Re-evaluation flow paragraph specifies comment-thread read on next-tick re-eval; outcome paths (PROCEED / CLARIFY again / REJECT) enumerated.
- [ ] Surface 3: §1.5 CLARIFY comment template appended with normative "reply via new comment" line.
- [ ] Surface 4: §1 rocket-gate prose explicitly documents `commented` exemption + §1.5 dependency.
- [ ] Surface 5: §1 mermaid `CLAR_OUT` node label updated.
- [ ] Surface 6: §Threat Model paragraph extended with comment-based CLARIFY defense reasoning.
- [ ] Surface 7: §Change History row appended (UTC 2026-05-10).
- [ ] Surface 8: TRN-0000 index regenerated via `af index --root .`.
- [ ] Surface 9: CHANGELOG `[Unreleased] ### Changed` entry added.
- [ ] Round-counter (§1.5 ~L266) preserved; comment-based CLARIFY rounds increment the same counter; cap-exhaustion path unchanged.
- [ ] §1 invalidator list (check 3 row, ~L149) UNCHANGED — the fix is documenting the existing `commented` exemption, not adding it. No new event types added/removed from the invalidator set.
- [ ] PR body: `Closes #100`; cross-links PR #99 R6 (`3212948899`) as the discovery signal.
- [ ] `af validate --root .` clean.
- [ ] Plan-review gate: fast-review tier ≥9.5 + zero blocking.
- [ ] Code-review gate: fast-review tier ≥9.5 + zero blocking.

## Migration / Backward-compat

**Zero state migration.** Existing CLARIFY'd issues are in one of two states at merge time: (a) operator already body-edited (rocket-gate already invalidated; legacy fallback applies — operator un-🚀 + re-🚀 to resume; behaviour unchanged from pre-CHG); (b) operator has not yet responded (orchestrator's NEW CLARIFY comment template will instruct comment-based reply on the NEXT round, since round-counter is preserved). No in-flight CLARIFY round breaks across the merge boundary.

**Operator-facing**: minor surface change. Operators who reply via comment (the new recommended path) experience materially smoother UX: single comment reply per round, no rocket-cycle ritual. Operators who continue to body-edit (the legacy path) experience identical behaviour to pre-CHG (gate invalidates; manual un-🚀 + re-🚀 required). The §1.5 CLARIFY comment template (Surface 3) makes the recommended path explicit, so most operators will follow it.

## Threat Model assessment

**No new attack surface.** Specifically:

- **Comment authorship spoofing**: comments can come from anyone with issue read access; the orchestrator's §1.5 re-run reads the operator's most-recent comment after the CLARIFY comment **filtered to the trusted set `{$TRUSTED_REACTOR}`** (the same trusted-reactor identity that grants rocket consent per check 2; see Surface 2 anchor logic step (ii)). Comments from any non-trusted login (untrusted contributors on public issues, bots, agent self-replies) are ignored for re-eval purposes. A non-trusted hostile commenter therefore CANNOT inject clarification text into the §1.5 rubric at all — they can post comments, but the anchor logic skips past them. **Primary defense is authorship filtering at the anchor step, not downstream gates.** A trusted hostile-clarification scenario (i.e., `$TRUSTED_REACTOR` themselves attempting to inject misleading clarification) is not a meaningful attack — the trusted-reactor identity is the consent-granting principal; a hostile principal can already revoke/grant rockets directly. Defense-in-depth (still relevant if the trusted-set filter is somehow bypassed in implementation): §1.5 PROCEED outcome only triggers (a) branch creation on `main` (rocket-gated separately on every git op per §1 `RV` re-verify), and (b) worker dispatch (output is panel-reviewed before PR open). The rubric's cross-section consistency point (point 2) anchors against the original body (consent-anchored via check 2 rocket reaction); comment text CAN influence rubric points 1 (scope clarity) and 4 (latent ambiguity) — that is the design intent, since clarification text legitimately resolves those — but cannot fabricate cross-section agreement (point 2), which still requires a body edit (which would re-trigger the consent gate).
- **Clarification-comment edit-race (TOCTOU)**: even with trusted-set authorship restriction, a `$TRUSTED_REACTOR` could edit their own clarification comment AFTER §1.5 PROCEEDs but BEFORE the orchestrator's first side-effecting git op (branch creation, push, PR open). The orchestrator would otherwise continue using stale clarification text — the same TOCTOU class §1 check 3 closes for issue-body edits, shifted to the comment surface. **Defense**: Surface 2's spec MANDATES the orchestrator record the chosen comment's `id` + `updated_at` at PROCEED time and re-validate (`gh api repos/$REPO/issues/comments/<id>`, compare `updated_at`) before each side-effecting git op AND on every `RV` re-verify; mismatch → abort and re-run §1.5 against new comment text. This mirrors §1's `rocket_created` timestamp pin pattern but on the comment surface. Without the pin, trusted-set authorship restriction alone is necessary-but-insufficient — it controls WHO can clarify but not WHEN-IT-CAN-BE-MUTATED.
- **Consent semantics**: rocket reactions remain the sole consent signal (check 2). Comments do not grant or revoke consent — the comment-based CLARIFY workflow is a clarification dialogue, not a consent path. The §1 invalidator list is unchanged; only the documentation of the existing `commented` exemption is added.
- **Comment-spam DoS**: an attacker posting many comments cannot weaponize this surface beyond today's body-edit-spam path (already accepted residual). The orchestrator reads the most-recent comment after the CLARIFY anchor; spam volume does not change rubric outcomes, only API call cost (paginated; bounded by GitHub's per-issue comment limit).

**Accepted residual**: operators who ignore the new normative "reply via comment" instruction and body-edit anyway will see legacy fail-closed behaviour (gate invalidates; manual rocket-cycle required). This is not a regression — it is the pre-CHG behaviour preserved as fallback. Surface 3's comment-template warning + Surface 5's mermaid label update are the operator-facing controls that minimize the residual.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-10 | Initial draft (Status: Proposed). Closes #100. Six TRN-1008 surfaces enumerated; option (b) comment-based CLARIFY recommended; option (a) strict re-rocket documented as rejected alternative for plan-review override. | trinity-glm |

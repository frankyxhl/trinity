# CHG-3044: TRN-1008 SOP Amendment - Review Completion Gate

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-20
**Last reviewed:** 2026-05-20
**Status:** Approved
**Date:** 2026-05-20
**Requested by:** @frankyxhl after PR #128 review-polling miss
**Priority:** Medium
**Change Type:** SOP amendment / process hardening
**Targets:** `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md`, `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md`, `CHANGELOG.md`, `rules/TRN-0000-REF-Document-Index.md`

---

## What

Amend TRN-1008 so a PR is not treated as complete, mergeable, or ready for handoff until the orchestrator has passed an explicit **Review Completion Gate** on the current head SHA.

The gate requires four current-head signals:

1. CI checks are terminal and green, or explicitly not applicable because a pure-docs PR was skipped by workflow `paths-ignore` and no required checks are configured.
2. Trinity code-review panel is complete on the current head and passes the required tier.
3. GitHub review state has been read with paginated thread-aware data, not only flat PR metadata.
4. Required bot/human review state is either clean on the current head or explicitly reported as blocked/waiting.

If the latest bot review is stale, `reviewDecision` remains `REVIEW_REQUIRED`, or any unresolved non-outdated review thread remains, the orchestrator must not say "done". It must continue polling when a poll mechanism is available, or report a bounded blocked state with the exact missing signal and the write action needed to unblock it.

## Why

PR #128 exposed a completion-gate hole. The local work, CI, and Trinity re-dispatch were clean, but GitHub still had unresolved Codex review threads and no Codex review for the latest head (`cc5cd21`). I stopped after the local/provider signals and reported the PR as effectively done, then only later polled the GitHub review state when prompted.

The existing TRN-1008 §8 says to poll CI, bot review, and the code-review panel, but it does not make thread-aware current-head review state a final exit condition. It also does not define the blocked state when no new bot review appears for the current head. That lets an orchestrator confuse "I ran my checks" with "the PR review state is clean".

## Failure Example

Observed on PR #128:

- Current head: `cc5cd21`
- CI: Ubuntu and macOS passed
- Trinity code-review re-dispatch: GLM + DeepSeek passed
- Latest Codex review: still anchored to older commit `bac779b`
- Current-head GitHub review event: `iterwheel-clearance`
- Unresolved review threads: `scripts/build_codex_skill.sh:61` and `scripts/build_codex_skill.sh:90`
- PR state: `reviewDecision=REVIEW_REQUIRED`, `mergeStateStatus=BLOCKED`

Correct SOP outcome: `BLOCKED - CI and Trinity are green, but GitHub review state is not clean on current head; continue polling or request/authorize the needed GitHub write action.`

Incorrect outcome: `done` or `mergeable`.

## Out of Scope

- No automation that resolves GitHub threads, posts comments, or requests Codex review without explicit user authorization.
- No change to the Trinity provider tier or score threshold.
- No change to branch protection or GitHub repository settings.
- No replacement for TRN-1007 PR-readiness checks.
- No requirement that Codex always produce a fresh review immediately after every push. Absence of a current-head bot review is a WAIT/BLOCKED state, not a local failure.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| S1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §7 | Extend the post-push closure checklist so an R-push cannot be called complete unless the orchestrator has either armed a poll wake or run the bounded no-wakeup fallback for the current head SHA. Item 4 is explicitly either/or so runtimes without `ScheduleWakeup` are supported. |
| S2 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §8 | Add the Review Completion Gate with states `CLEAN`, `WAIT`, and `BLOCKED`; require paginated thread-aware GitHub review reads via GraphQL reviewThreads or the GitHub plugin helper, plus current-head review anchoring. |
| S3 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §8 mermaid / polling prose | Update the "Bot reviewed this commit?" node so stale reviews do not satisfy the condition; unresolved current/non-outdated threads route to triage or blocked reporting. |
| S4 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §10 | Replace the informal mergeable predicate with "Review Completion Gate == CLEAN and no blocker labels." |
| S5 | `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md` Bot polling row | Clarify that `chatgpt-codex-connector[bot]` is the normative bot actor, while GitHub API reads may expose the login without the `[bot]` suffix; matching must be explicit and current-head anchored. |
| S6 | `CHANGELOG.md` | Add an Unreleased changed entry for the TRN-1008 review-completion gate. |
| S7 | `rules/TRN-0000-REF-Document-Index.md` | Regenerate the document index so TRN-3044 appears. |

## Acceptance Criteria

- [ ] TRN-1008 defines a Review Completion Gate with exactly three terminal classifications: `CLEAN`, `WAIT`, `BLOCKED`.
- [ ] `CLEAN` requires CI green on the current head (or `CI=N/A (paths-ignore)` for pure-docs skipped CI with no required checks), Trinity code-review panel pass on the current head, no unresolved non-outdated review threads, and current-head GitHub review evidence that is not stale-only.
- [ ] `WAIT` covers pending CI, pending panel review, or no current-head bot review inside the active polling window.
- [ ] `BLOCKED` covers failed CI, failed panel review, `reviewDecision=REVIEW_REQUIRED` with unresolved current review threads, stale-only bot reviews after the bounded polling window, or any current bot finding that has not been triaged.
- [ ] TRN-1008 says stale reviews/comments from older commits do not satisfy "bot reviewed this commit".
- [ ] TRN-1008 says paginated review and thread-aware state are required; flat `gh pr view` data alone is insufficient when review-thread resolution matters.
- [ ] TRN-1008 says `reviewDecision=null` or an absent `reviewDecision` field does not block `CLEAN` by itself when required reviews are not configured.
- [ ] TRN-1008 says the GitHub review portion of the gate is clean when `reviewDecision=APPROVED`, no unresolved non-outdated threads exist, and no current bot findings exist, even if no new advisory text was posted.
- [ ] TRN-1008 says the orchestrator must not say "done", "complete", or "mergeable" while the gate is `WAIT` or `BLOCKED`.
- [ ] TRN-1008 includes a no-wakeup fallback scenario: when `ScheduleWakeup` is unavailable, run a bounded poll of at least 3 cycles separated by at least 60 seconds, then report `WAIT` or `BLOCKED` with the exact missing signal.
- [ ] TRN-1008 says pure-docs skipped CI only counts as `CI=N/A (paths-ignore)` when no required checks are configured and local doc validation passed.
- [ ] TRN-1008 preserves GitHub write safety: do not resolve threads, reply to comments, or post `@codex review` unless the user explicitly authorizes that write action.
- [ ] TRN-1209 bot-polling row clarifies API login matching for `chatgpt-codex-connector[bot]`.
- [ ] CHANGELOG includes this SOP hardening.
- [ ] `af validate --root .` passes.

## Reference Procedure

The SOP amendment should include a command shape equivalent to:

```bash
HEAD=$(gh pr view "$PR" --repo "$REPO" --json headRefOid -q .headRefOid)
gh pr checks "$PR" --repo "$REPO" --required
gh api graphql \
  -f owner="${REPO%/*}" \
  -f name="${REPO#*/}" \
  -F number="$PR" \
  -f query='query($owner:String!, $name:String!, $number:Int!, $reviewsCursor:String = null, $threadsCursor:String = null) {
    repository(owner:$owner, name:$name) {
      pullRequest(number:$number) {
        headRefOid
        mergeStateStatus
        reviewDecision
        reviews(first: 100, after: $reviewsCursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            author { login }
            state
            submittedAt
            commit { oid }
          }
        }
        reviewThreads(first: 100, after: $threadsCursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            isResolved
            isOutdated
            path
            line
            comments(last: 3) {
              nodes {
                author { login }
                createdAt
                body
              }
            }
          }
        }
      }
    }
  }'
```

Interpretation rules:

- A review with `commit.oid != headRefOid` is stale for current-head gating.
- The reference query is one page. Repeat it with `reviewsCursor=<endCursor>` and `threadsCursor=<endCursor>` until both `reviews.pageInfo.hasNextPage` and `reviewThreads.pageInfo.hasNextPage` are false; review and unresolved-thread counts are invalid until all pages are read. Both cursor variables default to `null` for the first call.
- An unresolved thread with `isOutdated == false` blocks `CLEAN`, even when local code already contains the fix.
- A current-head clearance comment can explain a resolved thread, but auxiliary clearance bots are not a substitute for the normative bot actor unless TRN-1209 says so.
- If no current-head bot review appears after the polling budget, report the missing current-head review as `BLOCKED` or `WAIT` according to user context; do not silently stop.

## Implementation Order

1. Amend TRN-1008 §8 with the Review Completion Gate definition, command shape, and `CLEAN` / `WAIT` / `BLOCKED` state machine.
2. Amend TRN-1008 §7 so each R-push must either arm a wake or run the no-wakeup fallback before completion is claimed; do not make `ScheduleWakeup` mandatory in no-wakeup runtimes.
3. Amend TRN-1008 §10 so handoff requires the Review Completion Gate to be `CLEAN`.
4. Amend TRN-1209 bot-polling notes for API login matching and current-head anchoring.
5. Add CHANGELOG entry.
6. Run `af index --root .` and `af validate --root .`.
7. Run plan-review on this doc-only SOP CHG using the COR-1609 CHG review rubric before marking `Approved`.

## Risks / Rollback

Risk: the new gate can make the loop more conservative when GitHub's bot review is delayed or when old unresolved threads remain attached to the current diff. That is intentional. The prior behavior hid the state from the user; the new behavior surfaces it as `WAIT` or `BLOCKED`.

Residual risk: GitHub review-thread metadata can lag after force-push or clearance-bot actions. The SOP should prefer explicit reporting over optimistic inference. If the code is fixed but GitHub still shows an unresolved current thread, the correct state is blocked on GitHub review state or on an authorized write action, not clean.

Rollback is a revert of the SOP/REF/CHANGELOG edits. No code, data, or external GitHub state is migrated.

## Plan Review

- GLM: PASS 9.575
- DeepSeek: PASS 9.3
- MiniMax: PASS 9.5

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-19 | Initial proposed CHG after PR #128 polling miss. | Codex |
| 2026-05-20 | R2: implemented surfaces in TRN-1008, TRN-1209, CHANGELOG, and TRN-0000; aligned `CLEAN` wording with GitHub review-state evidence rather than requiring a fresh Codex text review when GitHub already marks review state clean. | Codex |
| 2026-05-20 | R3: plan-review passed 3/3 (GLM, DeepSeek, MiniMax); marked Approved and applied advisory clarifications. | Codex |
| 2026-05-20 | R4: self-application fix — pure-docs PRs intentionally skipped by `paths-ignore` record `CI=N/A (paths-ignore)` instead of waiting forever when no required checks are configured. | Codex |
| 2026-05-20 | R5: codex-bot P2 fix — Review Completion Gate now requires paginating all reviewThreads pages before declaring `CLEAN`. | Codex |
| 2026-05-20 | R6: codex-bot P2 fix — §7 item 4 now allows either `ScheduleWakeup` or the bounded no-wakeup fallback, avoiding deadlock in no-wakeup runtimes. | Codex |
| 2026-05-20 | R7: codex-bot P2 fix — §8 entry-gate now accepts either an armed wake or a completed bounded no-wakeup poll for the current head. | Codex |
| 2026-05-20 | R8: plan-review advisory fix — paginate reviews as well as reviewThreads, default cursors to null for the first call, document `reviewDecision=null`, and add explicit ACs for no-wakeup and docs-only CI paths. | Codex |
| 2026-05-20 | R9: codex-bot P2 fix — make the post-push poll handoff conditional on wakeup availability and use `gh pr checks --required` for required-CI gate evaluation. | Codex |

# CHG-2015: PR Base Head Review Mode

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** In Progress
**Date:** 2026-05-04
**Requested by:** Frank
**Implementer:** Codex
**Priority:** High
**Change Type:** Normal
**Related:** TRN-1200, TRN-2011, TRN-2013, TRN-2014

---

## What

Add a committed-branch review mode to Codex-native Trinity review:

```bash
trinity review --pr 20
trinity review --base main --head HEAD
```

This mode must collect the actual PR/base-head patch and full snapshots of
changed files instead of relying only on local uncommitted working-tree changes.

---

## Why

During PR #20 COR-1602 review, the generic `trinity review` path saw no diff
because the PR changes were already committed. This produced misleading reviewer
feedback. Trinity needs a first-class mode for reviewing committed branches and
GitHub PRs.

---

## Impact Analysis

- **Systems affected:** `scripts/codex.py`, `bin/trinity`, README,
  Codex adapter tests, review metadata schema, and `.trinity/reviews/` prompt
  content.
- **Systems intentionally preserved:** current working-tree review behavior,
  `--providers`, `--scope`, raw outputs, synthesis layout, and Claude Code
  Trinity behavior.
- **Downtime required:** No.
- **Rollback plan:** remove `--pr`, `--base`, and `--head` support plus tests
  and docs. Working-tree review remains the fallback behavior.

---

## Implementation Plan

1. RED: add tests for `--base main --head HEAD` collecting `git diff
   main...HEAD` and snapshots for changed files.
2. RED: add tests for `--pr <number>` using mocked `gh pr diff` /
   `gh pr view` output, including failure when `gh` is unavailable or
   unauthenticated.
3. RED: add tests proving working-tree review still collects tracked and
   untracked local changes when no PR/base-head options are supplied.
4. GREEN: add review input mode resolution:
   explicit `--pr` wins, then explicit `--base/--head`, then current
   working-tree mode.
5. GREEN: write review metadata with input mode, base, head, PR number, changed
   files, and snapshot source.
6. GREEN: ensure large diffs still use the prompt-file handoff.
7. REFACTOR: split diff collection into small helpers for working tree,
   base/head, and PR modes.
8. Docs: add examples and explain when to use each mode.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- mocked GitHub PR diff tests
- local git base/head fixture tests
- `make test`
- `make lint`
- `af validate --root .`
- `trinity review --base main --head HEAD --providers <fake-providers>`

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-04 | Added RED tests for `--base/--head`, `--pr`, and GitHub CLI failure handling | RED confirmed against prior adapter |
| 2026-05-04 | Implemented review input mode resolution for working-tree, base/head, and PR modes | Focused Codex adapter tests pass |
| 2026-05-04 | Added metadata for review input mode, base/head, PR number, changed paths, and snapshot source | Prompt and metadata assertions pass |
| 2026-05-04 | Updated README, Codex skill docs, plugin skill docs, and CHANGELOG | Documentation now covers dirty, committed-branch, and PR review modes |
| 2026-05-04 | Reviewed committed branch with `trinity review --base main --head HEAD --providers glm,deepseek` | GLM PASS, DeepSeek PASS |
| 2026-05-04 | Added follow-up tests for partial `--base/--head` usage and unavailable PR head snapshots | Focused tests and lint pass |

---

## Triage Evidence

Trinity improvement triage on 2026-05-04:

- GLM: CREATE_CHG, highest review-quality impact
- DeepSeek: CREATE_CHG, immediate Trinity-scope follow-up after provider health

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial CHG for PR/base-head review mode | Codex |

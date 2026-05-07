# CHG-2017: PR Update Helper

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Date:** 2026-05-04
**Requested by:** Frank
**Implementer:** Codex
**Priority:** Low
**Change Type:** Normal
**Related:** TRN-1200, TRN-2013, COR-1101, COR-1500, COR-1612, COR-1615

---

## What

Add a small helper for the recurring amended-PR update flow used during CHG
review rounds: validate, amend or commit, force-push with lease when needed, and
post a concise PR comment with review/validation evidence.

Candidate interface:

```bash
make pr-update PR=20 MESSAGE="Address COR-1602 review"
```

The helper should also support dry-run preview and explicit mode selection:

```bash
make pr-update PR=20 MESSAGE="Address COR-1602 review" DRY_RUN=1
make pr-update PR=20 MESSAGE="Address COR-1602 review" MODE=commit
make pr-update PR=20 MESSAGE="Post validation evidence" MODE=comment-only
```

---

## Why

During PR #20, the same workflow repeated manually: amend the CHG commit,
force-push to the fork branch, and comment with COR-1602 results. This is
low-risk to document or automate, but lower priority than provider health and
PR-diff review support.

---

## Impact Analysis

- **Systems affected:** Makefile, `dev/`, README/developer docs, and tests
  for command construction.
- **Systems intentionally preserved:** normal manual Git/GitHub workflow,
  draft PR defaults, and branch safety.
- **Downtime required:** No.
- **Safety model:** refuse unstaged or untracked files, missing upstream
  branches, and commit/amend modes with no staged changes. Use
  `--force-with-lease` only for amend mode, and always push to an explicit
  upstream refspec.
- **Rollback plan:** remove helper target/script/docs/tests. Manual git and
  `gh pr comment` remain available.

---

## Implementation Plan

1. RED: add tests for helper dry-run output with fake `git` and `gh`.
2. RED: add safety tests: refuses dirty unrelated files, refuses missing PR
   number, refuses branch without upstream, and uses `--force-with-lease` only
   after an amend.
3. GREEN: add helper as a script plus Makefile target with dry-run support.
4. GREEN: require explicit file staging or clean scope before commit/amend.
5. GREEN: post PR comment from a template that includes validation and review
   evidence.
6. Docs: document manual fallback and when not to use the helper.

---

## Testing / Verification

Expected evidence before marking complete:

- focused fake-git/fake-gh tests
- dry-run preview of validation, commit/amend, push, and PR comment commands
- `make test`
- `make lint`
- `af validate --root .`
- dry-run command output inspected before any real push/comment use

---

## Triage Evidence

Trinity improvement triage on 2026-05-04:

- GLM: CREATE_CHG due low implementation cost
- DeepSeek: CREATE_CHG but low urgency; implement after higher-priority review
  reliability work

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-05 | Revised CHG with concrete Makefile/script interface, dry-run mode, safety model, and COR-1615/COR-1612 relationship | Codex |
| 2026-05-04 | Initial CHG for PR update helper | Codex |
| 2026-05-08 | Status reconciled to Completed; merged in PR #28 at `56ab7cb` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

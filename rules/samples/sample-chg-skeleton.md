# <CHG-ID>: <Short Title>

**Applies to:** `<project-slug>` — `<scope description>`
**Last updated:** <YYYY-MM-DD>
**Last reviewed:** <YYYY-MM-DD>
**Status:** Proposed
**Date:** <YYYY-MM-DD>
**Requested by:** <requester>
**Priority:** <High | Medium | Low>
**Change Type:** <Feature | Bug Fix | Refactor | Doc | SOP | CHG>
**Targets:** <target-branch, usually `main`>
**Closes:** #<issue-number>
**Builds on:** <prior-TRN-ID, if applicable>

---

## What

<One paragraph describing what changes. Be concrete: which files, which functions, which behaviours.>

## Why

<One paragraph explaining why this change matters. Cite session evidence, failed CI runs, PR-review findings, or user reports. Reference the issue or prior PR that motivated this work.>

## Out of Scope

- <Bullet list of things explicitly deferred. Name follow-up CHGs by their TRN-ID where possible.>
- <Each deferred item should be actionable on its own.>

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `<path/to/file.ext>` | <brief description of what changes in this file> |
| 2 | `<path/to/another.ext>` | <brief description> |
| 3 | `<path/to/test_file.ext>` | <brief description of test additions/modifications> |

<One row per file or symmetric class per CLD-1802. Include test files as their own surface rows.>

## Acceptance Criteria

- **A1:** <Observable, testable criterion. e.g. "Running `pytest tests/test_foo.py` passes with 0 failures.">
- **A2:** <Observable, testable criterion. e.g. "New helper `bar()` accepts `<pattern>` and returns `<type>` — validated by ≥3 test cases.">
- **A3:** <Observable, testable criterion. e.g. "`ruff check <changed-paths>` reports 0 errors.">
- **A4:** <Observable, testable criterion. e.g. "CHANGELOG.md updated with entry under Unreleased.">

## Implementation Order

1. <Step 1 — e.g. "Add helper function `bar()` to `scripts/foo.py`.">
2. <Step 2 — e.g. "Update call sites in `scripts/baz.py` to use new helper.">
3. <Step 3 — e.g. "Add test cases to `tests/test_foo.py` covering A1–A3.">
4. <Step 4 — e.g. "Run full verification: pytest, ruff check, ruff format --check, af validate.">
5. <Step 5 — e.g. "Update CHANGELOG.md.">
6. <Step 6 — e.g. "Commit with message following project convention.">

## Change History

| Date | Change | By |
|------|--------|----|
| <YYYY-MM-DD> | Initial draft (Status: Proposed) | <author> |

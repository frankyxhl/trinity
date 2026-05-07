# CHG-2016: COR-1602 Strict Review Mode

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Date:** 2026-05-04
**Requested by:** Frank
**Implementer:** Codex
**Priority:** Medium
**Change Type:** Normal
**Related:** TRN-1200, TRN-2011, TRN-2013, TRN-2015, COR-1101, COR-1500, COR-1602, COR-1609, COR-1613, COR-1615, COR-1612

---

## What

Add a strict COR review mode to Codex-native Trinity review, for example:

```bash
trinity review --sop COR-1602 --rubric COR-1609 --pr 20
```

The mode should generate a rubric-specific prompt and require reviewers to
return findings, decision matrix, weighted average, and PASS/FIX.

This change covers prompt construction, command-line ergonomics, review
metadata, and documentation. It does not introduce automated parsing or
machine-scoring of reviewer outputs.

---

## Why

COR-1602 review of PR #20 required hand-built prompts and manual reviewer
coordination. This is repeatable enough to automate once TRN-2015 provides a
reliable PR/base-head review input mode.

---

## Impact Analysis

- **Systems affected:** `scripts/codex.py`, `.agents/trinity.codex.json`,
  README, tests, and review prompt templates.
- **Systems intentionally preserved:** default review prompt, provider
  execution, raw outputs, and synthesis layout.
- **Downtime required:** No.
- **Dependencies:** Should follow TRN-2015 so strict reviews can target actual
  PR/base-head diffs, not only uncommitted working-tree changes.
- **Review workflow:** use COR-1602 with COR-1613 decision tracking before PR.
  After PR creation, use COR-1615 for GitHub App review bot polling and
  COR-1612 for fetched PR findings.
- **Rollback plan:** remove `--sop`, `--rubric`, strict templates, tests, and
  docs. Default `trinity review` remains unchanged.

---

## Implementation Plan

1. Protect unrelated in-progress CHGs before branching for TRN-2016.
2. RED: add tests for `--sop COR-1602 --rubric COR-1609` prompt generation.
3. RED: add tests for unsupported SOP/rubric combinations and missing rubric
   docs or templates.
4. RED: add tests proving strict mode records SOP, rubric, PASS threshold, and
   expected output schema in review metadata.
5. RED: add compatibility tests for `--providers`, `--preset`,
   `--base/--head`, and `--pr`; default review behavior must remain unchanged.
6. GREEN: add a small registry of supported review templates, starting with
   COR-1602 + COR-1609.
7. GREEN: include required scoring instructions, PASS threshold, COR-1611
   calibration guidance, and expected output sections in the generated prompt.
8. GREEN: preserve existing provider dispatch, raw output, timeout, and
   synthesis behavior.
9. REFACTOR: keep prompt template assembly separate from provider dispatch.
10. Docs: add examples for CHG review, branch review, and PR review.
11. Review gate: run Trinity fast-review/deep-review on the CHG and
    implementation; revise blockers before opening the PR.
12. PR gate: after opening the PR, follow COR-1615 for any GitHub App review
    bot pass and route actionable findings through COR-1612.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- prompt snapshot/substring tests for COR-1602 + COR-1609
- `make test`
- `make lint`
- `af validate --root .`
- mocked `trinity review --sop COR-1602 --rubric COR-1609 --base main --head HEAD`
- Trinity review evidence from `glm` and `deepseek` at minimum, using the
  configured fast-review preset unless a deeper pass is requested.
- PR-stage COR-1615 evidence: current `headRefOid` recorded, one bot review
  request per head when needed, current-head review result matched, and
  COR-1612 used for actionable findings.

---

## Triage Evidence

Trinity improvement triage on 2026-05-04:

- GLM: CREATE_CHG
- DeepSeek: CREATE_CHG, borderline but worth tracking after PR review mode

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-05 | Revised plan to add TDD, Trinity review gate, and COR-1615 PR bot review loop | Codex |
| 2026-05-04 | Initial CHG for COR-1602 strict review mode | Codex |
| 2026-05-08 | Status reconciled to Completed; merged in PR #26 at `71750fac` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

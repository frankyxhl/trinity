# CHG-2014: Provider Health Checks and DeepSeek Review Config

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** In Progress
**Date:** 2026-05-04
**Requested by:** Frank
**Implementer:** Codex
**Priority:** High
**Change Type:** Normal
**Related:** TRN-1200, TRN-2011, TRN-2013

---

## What

Add provider health checks for Codex-native `trinity review`, and fix the
DeepSeek review path so it uses a locally valid Trinity wrapper or a validated
model command.

---

## Why

During TRN-2013 review, DeepSeek failed through the Codex config path because
`droid exec --model deepseek-v4-pro[1m]` was not accepted by the local `droid`
CLI. The installed Trinity DeepSeek wrapper worked. Review orchestration should
surface this before a long review run, not after partial reviewer output.

---

## Impact Analysis

- **Systems affected:** `.agents/trinity.codex.json`, `scripts/codex.py`,
  `make install-codex`, README, Codex adapter tests, and local
  `~/.codex/trinity.json` after install.
- **Systems intentionally preserved:** Claude Code provider agents,
  `make install`, existing `trinity review --providers ...` syntax, raw output
  and synthesis file layout.
- **Downtime required:** No.
- **Rollback plan:** restore prior DeepSeek CLI config and remove provider
  health-check code/tests/docs. Existing review calls continue to run providers
  directly.

---

## Implementation Plan

1. RED: add tests for provider health validation with fake CLIs:
   missing command, empty `cli`, non-executable wrapper, invalid timeout, and
   healthy provider.
2. RED: add regression test proving configured DeepSeek review path is locally
   valid without requiring a real DeepSeek network call.
3. GREEN: add a health-check function in `scripts/codex.py` that validates
   command existence, config shape, timeout, and optional smoke metadata before
   dispatch.
4. GREEN: update Codex default DeepSeek config to use the installed Trinity
   wrapper path when available, or a droid model ID accepted by local/provider
   health checks.
5. GREEN: add `trinity doctor` or `trinity review --check-providers` if the
   implementation needs an explicit health-only command.
6. REFACTOR: keep health validation independent from review execution so tests
   do not need real provider calls.
7. Docs: document provider health checks, expected failures, and repair steps.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- focused fake-provider health tests
- `make test`
- `make lint`
- `af validate --root .`
- `make install-codex`
- `trinity review --providers glm,deepseek --scope <small-file>` with mocked or
  low-risk provider calls

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-04 | Added RED tests for provider health failures, healthy providers, review preflight, and Codex DeepSeek wrapper install | RED confirmed against prior adapter |
| 2026-05-04 | Implemented `trinity doctor`, `trinity review --check-providers`, and pre-dispatch health validation | Focused Codex adapter tests pass |
| 2026-05-04 | Updated Codex DeepSeek default to `~/.codex/skills/trinity/bin/deepseek -p` and install target to copy the wrapper | Installed config can be health-checked without network calls |
| 2026-05-04 | Addressed Trinity review note by aligning `doctor` relative CLI resolution with git-root review semantics while preserving non-git health checks | Added regression coverage and reran full verification |

---

## Triage Evidence

Trinity improvement triage on 2026-05-04:

- GLM: CREATE_CHG
- DeepSeek: CREATE_CHG, highest score among candidates

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial CHG for provider health checks and DeepSeek review config | Codex |

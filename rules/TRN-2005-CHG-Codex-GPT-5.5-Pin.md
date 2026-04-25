# CHG-2005: Pin trinity-codex to gpt-5.5

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-04-26
**Status:** In Progress
**Requested by:** Frank
**Priority:** Low
**Change Type:** Standard
**Implementer:** Claude Opus 4.7

---

## What

Pin the `trinity-codex` provider to OpenAI's newly released `gpt-5.5` model by appending `-m gpt-5.5` to every `codex exec` invocation, and update agent-facing prose from "GPT-5.4" to "GPT-5.5".

| File | Action |
|------|--------|
| `providers/codex.delta.md` | Update — `-m gpt-5.5` flag + GPT-5.4 → GPT-5.5 prose (3 occurrences) |
| `providers/codex.md` | Regenerated via `make build` |
| `Makefile` | Update — `make install` registers codex CLI with `-m gpt-5.5` |
| `install.sh` | Update — remote install registers codex CLI with `-m gpt-5.5` |
| `~/.claude/trinity.json` | Updated locally by `make install` (out-of-tree) |
| `CHANGELOG.md` | Add 1.6.0 entry |
| `rules/TRN-0000` | Add TRN-2005 to document index |

---

## Why

`gpt-5.5` shipped in codex-cli 0.125 and is a meaningful capability uplift over the prior default. Without an explicit `-m` flag, the worker inherits whatever the user's `~/.codex/config.toml` default is — non-deterministic across machines. Pinning gives every Trinity dispatch the same baseline regardless of local config.

---

## Impact Analysis

- **Systems affected:** `trinity-codex` worker only (other providers untouched)
- **Behavior change:** all `codex exec` calls now invoke `gpt-5.5`; users who had a different local default will see different outputs
- **Downtime:** none
- **Rollback:** revert the four source files + reinstall (or hand-edit `~/.claude/trinity.json` to remove `-m gpt-5.5`)
- **Compatibility:** requires codex-cli ≥ 0.125 (gpt-5.5 availability). Older codex-cli will fail with "unknown model" — documented in CHANGELOG Notes

---

## Implementation Plan

1. Edit `providers/codex.delta.md`: append `-m gpt-5.5` to both `codex exec` and `codex exec resume` snippets, the closing rules line, and update GPT-5.4 → GPT-5.5 in the description block + body sentence
2. Edit `Makefile` and `install.sh`: include `-m gpt-5.5` in the codex `register` CLI string
3. `make build` — regenerate `providers/codex.md`
4. `make install` — overwrite `~/.claude/agents/trinity-codex.md` and re-register codex in `~/.claude/trinity.json`
5. Smoke test: `codex exec -m gpt-5.5 --skip-git-repo-check "say hello"` returns successfully
6. Per TRN-1003: commit feature code, update CHANGELOG, run `make bump VERSION=1.6.0`
7. Per TRN-1004: `make release` cuts v1.6.0

---

## Approval

- [x] Standard change — single-flag CLI update on a single provider, smoke-tested locally before commit

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-04-26 | Source edits + `make build` + `make install` | trinity.json shows `-m gpt-5.5`; agent file shows GPT-5.5 prose |
| 2026-04-26 | Smoke test `codex exec -m gpt-5.5` | Returned response from gpt-5.5 (codex-cli 0.125) |
| 2026-04-26 | CHG written, TRN-0000 updated | Ready for commit + bump |

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-04-26 | Initial version | Claude Opus 4.7 |

# CHG-2012: Claude Code Provider

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Date:** 2026-05-04
**Last updated:** 2026-05-06
**Last reviewed:** 2026-05-06
**Status:** Proposed
**Requested by:** Frank
**Implementer:** Codex
**Priority:** Medium
**Change Type:** Normal
**Related:** TRN-1000, TRN-1005, TRN-1006, TRN-2004, TRN-2011

---

## What

Add Claude Code as a first-class Trinity provider. The canonical provider key is
`claude-code`, and the installed worker agent is
`~/.claude/agents/trinity-claude-code.md`.

The registered CLI is:

```sh
$HOME/.claude/skills/trinity/bin/claude-code -p
```

The wrapper is mandatory. It must isolate Claude Code state and apply a
mechanical recursion guard before invoking `claude`.

## Model and Effort Policy

Default model and effort must be explicit:

- **Default model:** `sonnet`
- **Default effort:** `high`
- **Allowed effort values:** `low`, `medium`, `high`, `xhigh`, `max`
- **Override mechanism:** support `TRINITY_CLAUDE_CODE_MODEL` and
  `TRINITY_CLAUDE_CODE_EFFORT` environment variables in the wrapper. Provider
  instructions may also parse `EFFORT=<level>` from the task prompt and export
  `TRINITY_CLAUDE_CODE_EFFORT` before calling the wrapper.

Rationale: Claude Code accepts model aliases such as `sonnet`, and the Sonnet
alias tracks the current recommended Sonnet model for coding work. Official
Claude Code effort guidance lists `low`, `medium`, `high`, `xhigh`, and `max`
as CLI-level effort options, but Sonnet's supported default is `high`; reserve
`max` for explicit one-off overrides.

---

## Why

Trinity can already delegate to Codex, Gemini, GLM, OpenRouter, and DeepSeek.
Adding Claude Code as a peer provider lets users compare Claude Code output
against those providers from the same `/trinity` workflow, especially for review,
design critique, and compatibility checks.

Because the orchestrator can also be Claude Code, this provider must be added
with explicit recursion and compatibility guard rails instead of being treated as
just another external CLI.

---

## Impact Analysis

- **Systems affected:** provider composition under `providers/`, built provider
  artifacts, `scripts/build_providers.sh`, root `SKILL.md`, `make install`,
  `install.sh`, provider discovery, install tests, provider build tests, README,
  CHANGELOG, VERSION metadata, and user-level `~/.claude/trinity.json` after
  install.
- **Systems intentionally preserved:** root `SKILL.md` dispatch contract,
  existing `glm`, `codex`, `gemini`, `openrouter`, and `deepseek` provider
  behavior, Codex-native `trinity review`, and `.claude/` ignore behavior.
- **Downtime required:** No.
- **Main risks:** nested Claude Code calls can recursively invoke Trinity, reuse
  the orchestrator's Claude Code state, or require interactive permissions in a
  background worker.
- **Required mitigations:** the wrapper must set
  `TRINITY_DISABLE_DISPATCH=1`, `CLAUDE_CONFIG_DIR="${HOME}/.claude-trinity-claude-code"`,
  and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` before calling `claude`.
  Root `SKILL.md` must check `TRINITY_DISABLE_DISPATCH=1` during startup and
  refuse `/trinity` dispatch in that process. The wrapper must also pass
  `--disable-slash-commands` to the nested `claude` call.
- **Rollback plan:** remove `providers/claude-code.delta.md`, generated
  `providers/claude-code.md`, any `providers/bin/claude-code` wrapper, install
  registrations, tests/docs updates, and unregister `claude-code` from
  `~/.claude/trinity.json`.

---

## Implementation Plan

1. RED: add tests before implementation.
2. Add `tests/test_discover.py` coverage proving hyphenated provider names like
   `claude-code` are discovered from config plus
   `trinity-claude-code.md`.
3. Add `tests/test_config.py` coverage proving provider config merge preserves
   hyphenated provider keys.
4. Add provider build tests so `claude-code` participates in deterministic
   `make build` / `make verify-built` checks, has `name:
   trinity-claude-code`, has no stale `@include`, and contains the expected
   Claude Code CLI signature.
5. Add install tests for both local `make install` and remote `install.sh`:
   copy `providers/claude-code.md` to
   `~/.claude/agents/trinity-claude-code.md`, register provider key
   `claude-code`, preserve existing providers, and install
   `providers/bin/claude-code`.
6. Add a mocked wrapper/CLI test that stubs `claude` and verifies the wrapper:
   sets `TRINITY_DISABLE_DISPATCH=1`, sets isolated `CLAUDE_CONFIG_DIR`, sets
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, passes
   `--disable-slash-commands`, passes `--model sonnet --effort high`
   by default, accepts `TRINITY_CLAUDE_CODE_MODEL` and
   `TRINITY_CLAUDE_CODE_EFFORT=max` overrides, rejects invalid effort values,
   preserves `-p`/`--resume` argv, and does not require a real Claude Code
   network call.
7. Add root `SKILL.md` coverage, or an equivalent textual regression test,
   proving the startup check refuses dispatch when
   `TRINITY_DISABLE_DISPATCH=1`.
8. GREEN: create `providers/bin/claude-code` as a POSIX wrapper. It should call:
   ```sh
   MODEL="${TRINITY_CLAUDE_CODE_MODEL:-sonnet}"
   EFFORT="${TRINITY_CLAUDE_CODE_EFFORT:-high}"
   exec claude --permission-mode bypassPermissions --disable-slash-commands --model "$MODEL" --effort "$EFFORT" "$@"
   ```
   with the required environment variables from Impact Analysis.
9. GREEN: create `providers/claude-code.delta.md` using the TRN-2004 shared
   partial pattern, then regenerate `providers/claude-code.md`.
10. Update hardcoded provider inventories:
    `scripts/build_providers.sh` `DELTAS`, `tests/test_build_providers.sh`
    `PROVIDERS` and provider-family arrays, `tests/test_install_sh.sh`
    provider loops and expected files, `Makefile` copy/chmod/register lines,
    and `install.sh` download/chmod/register lines.
11. Register provider key `claude-code` in `Makefile` and `install.sh` with CLI
    `$HOME/.claude/skills/trinity/bin/claude-code -p`.
12. Add provider instructions that restate the mechanical recursion guard and
    forbid nested `/trinity` delegation from Claude Code provider sessions.
13. Docs and release metadata: update README install/status examples, provider
    list, adding-provider notes, CHANGELOG, and bump target version to `3.1.0`
    during implementation.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_discover.py -q`
- `.venv/bin/pytest tests/test_config.py -q`
- focused wrapper test for `providers/bin/claude-code` with a fake `claude`
  executable
- model/effort regression evidence showing default `sonnet` + `high`,
  accepted `max` override, and rejected invalid effort override
- regression evidence that root `SKILL.md` refuses `/trinity` dispatch when
  `TRINITY_DISABLE_DISPATCH=1`
- `bash tests/test_build_providers.sh`
- `bash tests/test_install_sh.sh`
- `make build`
- `make verify-built`
- `make test`
- `make lint`
- `af validate --root .`
- fake-home `make install` smoke showing `claude-code` in
  `~/.claude/trinity.json` and
  `~/.claude/agents/trinity-claude-code.md`
- Claude Code compatibility smoke: existing `/trinity status` path still lists
  old providers, and adding `claude-code` does not break root `SKILL.md`
  startup/version checks

Real `claude-code` provider smoke should use a small prompt only after the mock
tests pass, because it may consume Claude Code quota.

---

## Approval

- [x] Approved for implementation
- [x] Implemented
- [x] Verified locally
- [x] PR opened

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-04 | Created CHG draft with canonical provider name and TDD plan | Proposed |
| 2026-05-04 | Reviewed with Trinity GLM, Gemini, and DeepSeek | REQUEST_CHANGES: require mechanical recursion guard, Claude config isolation, explicit CLI signature, hardcoded provider inventory, and version-bump guidance |
| 2026-05-04 | Checked official Claude Code CLI and Anthropic effort docs | Initially proposed `claude-opus-4-7` + `xhigh`; allow `max` as explicit override |
| 2026-05-06 | Rechecked Claude Code model/effort docs and user preference | Revised default to `sonnet` + `high`; keep explicit `max` override |
| 2026-05-06 | Implemented provider files, wrapper, install registration, recursion guard, docs, and TDD coverage | Focused tests, `make test`, `make lint`, `make verify-built`, fake-home `make install`, and `af validate --root .` pass |
| 2026-05-06 | Ran real Claude Code wrapper smoke on local CLI | Blocked by local auth: `Not logged in · Please run /login` |
| 2026-05-06 | Reviewed implementation with Trinity fast-review (GLM + DeepSeek) | PASS from both; addressed DeepSeek advisory by making the nested dispatch guard exit non-zero |
| 2026-05-06 | Re-reviewed final head with Trinity fast-review (GLM + DeepSeek) | PASS from both; addressed advisory docs clarifications before PR |
| 2026-05-06 | Updated GLM to `glm-5.1 --reasoning-effort high` and re-reviewed with Trinity fast-review | PASS from GLM-5.1/high and DeepSeek |
| 2026-05-06 | Opened PR #34 | Ready for GitHub review |

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial CHG for Claude Code provider | Codex |
| 2026-05-04 | Revised after Trinity provider review | Codex |
| 2026-05-04 | Added explicit model and effort policy | Codex |
| 2026-05-06 | Revised default model/effort to Claude Code `sonnet` + `high` | Codex |

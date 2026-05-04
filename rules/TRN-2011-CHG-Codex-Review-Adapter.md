# CHG-2011: Codex Review Adapter

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Date:** 2026-05-04
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** In Progress
**PRP:** TRN-2010
**Implementer:** Codex

---

## What

Implement the approved TRN-2010 Codex review adapter: Codex-specific config, `trinity review` CLI wrapper, Codex install target, tests, and documentation.

---

## Why

Codex needs a direct Trinity review path that does not depend on Claude Code's Agent runtime or worker-agent files. The existing Claude Code path must remain unchanged and regression-tested.

---

## Impact Analysis

- **Systems affected:** repo-local Codex skill packaging, local Codex installation under `~/.codex`, `~/.local/bin/trinity`, README, tests, and rules docs.
- **Systems intentionally preserved:** root Claude Code `SKILL.md`, `install.sh`, `make install`, `~/.claude/agents`, and `~/.claude/trinity.json` behavior.
- **Downtime required:** No.
- **Rollback plan:** Remove `bin/trinity`, `scripts/codex.py`, `.agents/trinity.codex.json`, `make install-codex`, and related tests/docs. Locally, remove `~/.local/bin/trinity`, `~/.codex/skills/trinity`, and `~/.codex/trinity.json` if desired.

---

## Implementation Plan

1. RED: add tests for Codex config shape, `review` prompt collection, raw output/synthesis files, `make install-codex`, and Claude compatibility.
2. GREEN: add Codex config, CLI script, wrapper, install target, and ignore generated review output.
3. REFACTOR: keep wrapper small, deterministic, and stdlib-only.
4. Docs: update README and Codex skill with command/config/install notes.
5. Verification: `make test`, `make lint`, `af validate --root .`, `make install-codex` smoke, and Claude install/version smoke.
6. Delivery: commit, push feature branch, and open draft PR.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- `make test`
- `make lint`
- `af validate --root .`
- `HOME=<temp> make install-codex` creates only Codex files.
- `make install` and `python3 ~/.claude/skills/trinity/scripts/session.py --version` still pass.

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-04 | Added RED tests for Codex adapter and Claude compatibility | RED confirmed: missing config, wrapper script, and install target |
| 2026-05-04 | Implemented Codex config, `scripts/codex.py`, `bin/trinity`, and `make install-codex` | Focused Codex tests pass |
| 2026-05-04 | Ran full repo verification | `make test`, `make lint`, and `af validate --root .` pass |
| 2026-05-04 | Installed adapters on this machine | `make install-codex`, `trinity --version`, `make install`, and Claude `session.py --version` pass |
| 2026-05-04 | Addressed PR #16 review comment about argv length | Provider calls now pass a short prompt-file handoff; large-diff regression test added |

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial change record for TRN-2010 implementation | Codex |

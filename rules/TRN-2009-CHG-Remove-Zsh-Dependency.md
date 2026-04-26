# CHG-2009: Remove Zsh Dependency from Trinity Providers

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-04-26
**Last updated:** 2026-04-26
**Last reviewed:** 2026-04-26
**Status:** In Progress
**PRP:** TRN-2008 (Approved — Round 2: Codex 8.9/PASS, Gemini 9.8/PASS, GLM 8.8/PASS, DeepSeek 10/PASS)
**Implementer:** Claude Opus 4.7

---

## Summary

Replace the two `.zshrc`-defined wrapper functions (`deepseek_cy`, `openrouter_cy`) — registered today as the dispatch CLI for `deepseek` and `openrouter` providers — with portable POSIX shell scripts shipped in the trinity repo. After this change, a fresh user can install trinity (`install.sh` or `make install`) and use every registered provider with **no shell-rc edits**.

See PRP TRN-2008 for full design rationale, alternatives considered, and 4-model strict-review resolution.

---

## Deliverables

| File | Action |
|------|--------|
| `providers/bin/deepseek` | New — POSIX sh wrapper (~50 lines) |
| `providers/bin/openrouter` | New — POSIX sh wrapper (~45 lines) |
| `providers/deepseek.delta.md` | Edit — simplify `run_deepseek` Setup to 1-line wrapper call; clean frontmatter description |
| `providers/openrouter.delta.md` | Edit — same shape for openrouter |
| `providers/deepseek.md` | Regenerate via `make build` (do NOT edit directly) |
| `providers/openrouter.md` | Regenerate via `make build` (do NOT edit directly) |
| `install.sh` | Edit — `mkdir -p .../bin/`; download + `chmod +x` both bin scripts; register absolute paths |
| `Makefile` | Edit — `install` target mirrors install.sh wiring |
| `tests/test_anthropic_compat_wrappers.py` | New — pytest suite covering T1–T14 from PRP |
| `README.md` | Edit — note `~/.secrets/<provider>_api_key` (mode 600) or `<PROVIDER>_API_KEY` env var |
| `rules/TRN-0000-REF-Document-Index.md` | Update — add TRN-2008 (PRP) and TRN-2009 (CHG) rows |

**No changes to:** `glm`, `codex`, `gemini` provider registrations; `trinity.json` schema; `discover.py`; `install.py`; `session.py`; `SKILL.md`.

---

## Migration

**For existing users with `~/.claude/trinity.json` containing `"cli": "deepseek_cy -p"` or `"cli": "openrouter_cy -p"`:**

Re-run the installer:

```bash
# remote
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash

# or local
cd <trinity-clone> && make install
```

The installer's `register` calls (`scripts/install.py`) overwrite the two `cli` strings to absolute-path form. Other providers (glm/codex/gemini) and any project-scoped configs are untouched.

**To remove the now-dead zsh functions** (optional cleanup): delete the `deepseek_cy` and `openrouter_cy` definitions from `~/.zshrc` (or whichever shell-rc holds them). They are no longer reached.

**To remove a provider entirely** (out of scope for this CHG, but documented for completeness):

```bash
python3 ~/.claude/skills/trinity/scripts/install.py unregister deepseek
```

---

## Execution Log

Workflow: TDD per COR-1500 — write failing tests first, then implement until green.

| Step | Status | Notes |
|------|--------|-------|
| Phase 6.1 — Write `tests/test_anthropic_compat_wrappers.py` (17 tests, all failing initially) | ✅ | RED confirmed — 17/17 fail with FileNotFoundError before bin scripts exist |
| Phase 6.2 — Write `providers/bin/deepseek` and `providers/bin/openrouter` (POSIX sh) | ✅ | GREEN — 17/17 pytest pass; both files +x, `#!/bin/sh` shebang |
| Phase 6.3 — Edit `providers/deepseek.delta.md` and `providers/openrouter.delta.md` | ✅ | `run_<provider>` simplified to 1-line wrapper call; frontmatter description cleaned |
| Phase 6.4 — Run `make build` to regenerate `providers/<name>.md`; verify `make verify-built` passes | ✅ | Both regenerated; verify-built OK; no `command -v _cy` lines remain |
| Phase 6.5 — Edit `install.sh` (mkdir + download + chmod + register absolute paths) | ✅ | T9 + T11 in `tests/test_install_sh.sh` cover the new behavior; both pass |
| Phase 6.6 — Edit `Makefile` `install` target for parity | ✅ | Same wiring (`mkdir -p .../bin`, copy + chmod, register absolute paths via `$(HOME)`) |
| Phase 6.7 — Edit `README.md` (key file note in Quick Start) | ✅ | Step 2 expanded with env-var / key-file precedence + perm requirement; legacy `*_cy` snippet replaced with absolute-path example |
| Phase 7 — `make test` green | ✅ | pytest 63/63 + shell 10/10 + release-workflow 53/53; verify-built OK |
| Phase 8 — `make lint` clean | ✅ | ruff check + ruff format --check both clean |
| Pause — report to user before mutating `~/.claude/trinity.json` or pushing | in_progress | |
| User confirmation — proceed with commit + push + PR | blocked on user | |
| `git commit` + `git push` + `gh pr create` | pending | |

---

## Test Strategy

Per PRP TRN-2008 §Test Cases, T1–T14:

- **T1–T7**: wrapper scripts behavior (env precedence, perm check, missing-key, exec semantics) — pytest with PATH-injected Python `claude` stub recording argv+env to a temp file.
- **T8**: `--resume <id> -p <prompt>` argv ordering (verifies the worker's resume contract still produces correct argv).
- **T9–T12**: `install.sh` and `make install` register absolute paths; idempotent; legacy `deepseek_cy -p` migration overwrites correctly.
- **T13**: stat-fails-on-exotic-fs (both BSD and GNU `stat` return non-zero) → `unknown` branch refuses with stderr.
- **T14**: `make build` from edited `.delta.md` produces `.md` that passes `make verify-built` and contains the new 1-line wrapper.

---

## Risk Realized / Mitigations Applied

| Risk (from PRP) | Realized? | How handled |
|-----------------|-----------|-------------|
| Generated `.md` edits would fail `make verify-built` | (TBD during impl) | §4 of PRP and Step 6.3 explicitly direct edits at `.delta.md` source |
| `stat -f` (BSD) vs `-c` (GNU) split | (TBD during impl) | Wrapper script tries both, then `\|\| echo unknown` terminator with explicit case branch |
| Concurrent install corrupts `trinity.json` | Already mitigated | `install.py` uses `fcntl.flock` (existing test `test_concurrent_register_no_corruption`) |

---

## Out of Scope

- Python `trinity-exec` dispatcher (rejected alternative B in PRP)
- `shape` discriminator in `trinity.json` schema
- `openai-compat` shape
- Moving provider config into agent .md frontmatter (deferred alternative D)
- Changes to `glm`, `codex`, `gemini` registrations
- Windows support
- `DEEPSEEK_API_KEY_FILE` / non-default key path support

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-04-26 | Initial draft after PRP TRN-2008 approval (Round 2 PASS from all four reviewers) | Claude Opus 4.7 |

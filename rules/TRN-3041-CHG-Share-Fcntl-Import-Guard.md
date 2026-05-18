# CHG-3041: Share fcntl Import Guard

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-18
**Last reviewed:** 2026-05-18
**Status:** Approved
**Date:** 2026-05-17
**Requested by:** @frankyxhl via issue #78
**Priority:** Low
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #78
**Builds on:** #77 / PR #122 (`scripts/_version.py` shared-helper pattern)

---

## What

Extract the duplicated POSIX `fcntl` availability guard from
`scripts/session.py` and `scripts/install.py` into a shared helper module,
`scripts/_compat.py`. The two callers will import the guarded `fcntl` module
from that helper and continue to exit with the same unsupported-platform
message when `fcntl` is unavailable.

## Why

The same platform guard currently lives in two scripts. That is small, but it
is a real drift surface: any future platform-support change would need to touch
both files in lockstep. #77 just established the local pattern for tiny shared
script helpers (`scripts/_version.py` with dual package/direct import support);
this change applies the same pattern to the `fcntl` guard.

## Out of Scope

- Adding Windows support or a non-`fcntl` fallback.
- Changing lock semantics in `scripts/session.py` or `scripts/install.py`.
- Refactoring unrelated script compatibility helpers.
- Bundling any other #40 cleanup issue.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `scripts/_compat.py` | New shared compatibility module. Exposes `fcntl` after guarded import; on `ImportError`, prints the existing unsupported-platform message to stderr and exits 1. |
| 2 | `scripts/session.py` | Remove inline `try: import fcntl` guard; import `fcntl` from `_compat` with the same dual package/direct import style used for `_version`. No behavioral change to any session locking call site (`_read_pointer`, `cmd_write`, `cmd_clear`). |
| 3 | `scripts/install.py` | Remove inline `try: import fcntl` guard; import `fcntl` from `_compat` with the same dual package/direct import style used for `_version`. No behavioral change to `atomic_update` locking. |
| 4 | `tests/test_compat.py` | New focused tests for `_compat`: normal import exposes a module with `flock`, and a simulated missing-`fcntl` import exits 1 with the existing message. |
| 5 | Existing script tests | Existing `tests/test_session.py` and `tests/test_install.py` continue to exercise the lock-using paths unchanged. No fixture contract changes expected. |
| 6 | `install.sh` + `tests/test_install_sh.sh` | Curl-style installer downloads `scripts/_compat.py`; shell install happy-path manifest asserts the helper is installed before `scripts/install.py` runs. |
| 7 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry describing the shared guard and referencing #78. |
| 8 | `rules/TRN-0000-REF-Document-Index.md` | Regenerated with TRN-3041 entry via `af index --root .`. |

## Acceptance Criteria

- [ ] `scripts/_compat.py` exists and is the single source for the guarded
  `fcntl` import.
- [ ] `scripts/session.py` and `scripts/install.py` no longer contain an
  inlined `try: import fcntl` / `except ImportError` block.
- [ ] Missing `fcntl` still exits 1 and emits
  `trinity-scripts: unsupported platform (fcntl not available). Windows is not supported.`
- [ ] `tests/test_compat.py` covers both normal import and simulated missing
  `fcntl`, including the exact unsupported-platform stderr string. The
  simulation should be subprocess-based and explicit about the import hook or
  path manipulation used to force `ImportError`.
- [ ] `scripts/session.py` and `scripts/install.py` import `fcntl` at module
  scope from `_compat`, so existing `fcntl.flock` / `LOCK_*` call sites remain
  ordinary module-level references.
- [ ] `install.sh` downloads `scripts/_compat.py` before invoking
  `scripts/install.py`; `tests/test_install_sh.sh` asserts the helper is
  present in the installed scripts directory.
- [ ] `pytest tests/test_compat.py tests/test_session.py tests/test_install.py -q`
  passes.
- [ ] `bash tests/test_install_sh.sh` passes.
- [ ] `.venv/bin/ruff check scripts/_compat.py scripts/session.py scripts/install.py tests/test_compat.py`
  passes.
- [ ] `.venv/bin/ruff format --check scripts/_compat.py scripts/session.py scripts/install.py tests/test_compat.py`
  passes.
- [ ] `make verify-built` passes.
- [ ] `af validate --root .` passes.
- [ ] PR body includes `Closes #78`.

## Implementation Order

1. Add `scripts/_compat.py` with a guarded module-level `fcntl` export.
2. Replace the two inline guards with dual-mode imports:
   `from ._compat import fcntl` / `from _compat import fcntl`.
3. Add focused `_compat` tests, including a subprocess-based simulated
   `ImportError` so the test does not depend on the host platform lacking
   `fcntl`.
4. Run the focused pytest target and lint/format checks.
5. Add `_compat.py` to the curl installer download list and shell install
   manifest.
6. Regenerate `rules/TRN-0000-REF-Document-Index.md`.
7. Add the changelog entry.
8. Run `make verify-built` and `af validate --root .`.

## Plan Review

TRN-1008 phase 4 gate met on 2026-05-18:

| Reviewer | Score | Decision | Blocking |
|----------|-------|----------|----------|
| trinity-glm | 9.50 | PASS | [] |
| trinity-deepseek | 9.55 | PASS | [] |

Advisories applied before implementation:

- DeepSeek: make the missing-`fcntl` test simulation mechanism explicit.
- DeepSeek: ensure both callers keep `fcntl` as a module-level import from
  `_compat` so existing lock call sites remain unchanged.

## Implementation Verification

Local verification after worker implementation and orchestrator cleanup:

- `pytest tests/test_compat.py tests/test_session.py tests/test_install.py -q`
  → 31 passed.
- `bash tests/test_install_sh.sh` → passed after R2 installer-manifest fix.
- `.venv/bin/ruff check scripts/_compat.py scripts/session.py scripts/install.py tests/test_compat.py`
  → passed.
- `.venv/bin/ruff format --check scripts/_compat.py scripts/session.py scripts/install.py tests/test_compat.py`
  → passed.
- `make verify-built` → passed.

## Migration / Backward-compat

No user-facing behavior change. POSIX hosts import the same stdlib `fcntl`
module. Unsupported platforms still fail fast with the same message and exit
code. The helper is private to `scripts/` and does not create a public API.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-17 | Initial draft (Status: Proposed). Closes #78. | Codex |
| 2026-05-18 | Plan-review gate met (glm 9.50 / deepseek 9.55); applied DeepSeek advisories to AC. | Codex |
| 2026-05-18 | Worker implementation completed; local focused verification passed. | trinity-glm + Codex |
| 2026-05-18 | R2 bot/CI fix: add `_compat.py` to curl installer download list and install manifest. | Codex |

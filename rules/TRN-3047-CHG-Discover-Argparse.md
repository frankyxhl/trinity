# CHG-3047: Replace discover.py Manual Flag Parser with argparse

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #240 (source: ponytail over-engineering audit 2026-06-23)
**Priority:** Low
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #240
**Builds on:** `scripts/codex.py` argparse pattern (`ArgumentParser(prog=..., allow_abbrev=False)` + subparsers)

---

## What

Replace the hand-rolled `while i < len(args)` flag parser in
`scripts/discover.py main()` (lines 141–157) with stdlib `argparse`, matching
the pattern already used by `scripts/codex.py`. The two flags
(`--global-config`, `--project-dir`) move to a `list` subparser with their
current defaults.

## Why

`codex.py` already parses with argparse; `discover.py` hand-rolls the same
job in 17 lines that must be maintained separately (flag-value pairing,
unknown-argument handling, defaults). Stdlib does it. Flagged by the ponytail
over-engineering audit; filed as #240.

## Out of Scope

- `scripts/install.py`'s three hand-rolled arg loops (#239, separate issue).
- Any change to `cmd_list` / `scan_agent_dirs` / `get_merged_config` logic.
- Adding new flags, commands, or help text beyond what argparse generates.

## Behavioral Contract

**Preserved (documented CLI surface — existing tests must pass unmodified):**

| Invocation | Behavior (unchanged) |
|---|---|
| `discover.py` (no args) | module docstring to stderr, exit 1 |
| `discover.py --version` | version (semver only, no usage line) to stdout, exit 0 |
| `discover.py --version list` | version to stdout, exit 0 — `--version` short-circuits before subcommand dispatch (see Invariants) |
| `discover.py list [--global-config P] [--project-dir D]` | JSON provider rows to stdout; defaults `~/.claude/trinity.json` (expanduser) / `os.getcwd()` |

**Changed (undocumented error/help surface — every row pinned by a NEW test, declared here for the panel):**

| Invocation | Before | After |
|---|---|---|
| `discover.py --bogus` (top-level unknown flag) | `unknown command '--bogus'` to stderr, exit 1 | argparse error to stderr, exit 2 |
| `discover.py list --bogus` | `unknown argument '--bogus'` to stderr, exit 1 | argparse error to stderr, exit 2 |
| `discover.py list --version` | `unknown argument '--version'` to stderr, exit 1 | argparse "unrecognized arguments" to stderr, exit 2 (`--version` is top-level only) |
| `discover.py bogus-cmd` | `unknown command 'bogus-cmd'` to stderr, exit 1 | argparse invalid-choice error to stderr, exit 2 |
| `discover.py list --global-config` (missing value) | treated as unknown argument, exit 1 | argparse "expected one argument", exit 2 |
| `discover.py -h` / `--help`, `discover.py list -h` | `unknown command`/`unknown argument`, exit 1 | argparse help to stdout, exit 0 (behavior ADDITION — kept deliberately; `add_help` default matches the `codex.py` precedent, and free help text is the point of argparse) |

No test or caller pins the old error text or exit-1 codes (verified: `tests/test_discover.py`, `tests/test_bdd_scenarios.py`, `tests/test_trinity_zc.py` only exercise the documented surface). Exit 2 on usage errors is the argparse/POSIX convention `codex.py` already exposes.

**Invariants:**

- `allow_abbrev=False` — the current parser does exact-match only; argparse's
  default prefix abbreviation (`--global` → `--global-config`) would be a
  silent behavior ADDITION and is disabled.
- **Version-check-before-dispatch** — `main()` MUST branch on `args.version`
  and return BEFORE dispatching `args.command`, otherwise
  `discover.py --version list` silently regresses from print-version/exit-0
  to running `list`. Mirrors `codex.py`'s ordering.
- Empty-argv docstring dump stays a manual pre-parse check (argparse would
  otherwise exit 2 with its own usage line).

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/discover.py` | `import argparse`; `main()` rewritten: empty-argv guard kept, then `ArgumentParser(prog="discover.py", allow_abbrev=False)` with `--version` (store_true) and a `list` subparser carrying the two flags with current defaults. Manual `while` loop deleted. The parser MUST be constructed inside `main()` (not module level) so the `expanduser`/`getcwd` defaults bind per-invocation and honor patched `HOME` in subprocess tests. Est. −17/+15 lines. | trinity-glm |
| 2 | `tests/test_discover.py` | New tests pinning the full contract above. The five exit-2 error cases (top-level `--bogus`; `list --bogus`; `list --version`; `bogus-cmd`; missing flag value) and the no-abbreviation case (`list --global`) MUST be a single `pytest.mark.parametrize` test (one body, six param rows) asserting exit 2, message on STDERR, and stderr mentions the offending token — compactness is a review dimension, not style. Plus individual tests: `-h` and `list -h` → help on STDOUT, exit 0; `--version` → stdout equals the semver EXACTLY (`out == version`, catching a stray argparse usage line), exit 0; `--version list` → version on stdout AND no JSON emitted (proves dispatch short-circuited), exit 0; no-args → docstring on stderr, exit 1 (unchanged); default `--global-config` path (`list --project-dir X` with patched `HOME`, no explicit flag) — assert the resolved config path string contains the patched `HOME` (catches import-time expanduser binding). Reuse the existing run helper at line 21. Est. ~50 LoC total via parametrization. | trinity-deepseek |
| 3 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry referencing #240. | trinity-glm |
| 4 | `rules/TRN-0000-REF-Document-Index.md` | Regenerated via `af index --root .`. | orchestrator |

Write sets are disjoint per TRN-1008 §5 (glm: scripts/ + CHANGELOG; deepseek: tests/).

## Acceptance Criteria

- [ ] `scripts/discover.py` contains no manual `while i < len(args)` loop;
  flags parsed via argparse with `allow_abbrev=False`.
- [ ] `main()` checks `args.version` before subcommand dispatch
  (version-check-before-dispatch invariant).
- [ ] Documented CLI surface preserved per §Behavioral Contract; existing
  tests pass **unmodified**.
- [ ] New tests pin every §Behavioral Contract Changed-table row (exit-2
  cases on stderr, `-h`/`--help` exit-0 on stdout, abbreviation rejection),
  both preserved version paths, the no-args exit-1 path, and the default
  expanduser config path.
- [ ] `pytest tests/test_discover.py tests/test_bdd_scenarios.py -q` passes.
- [ ] Full `pytest -q` passes.
- [ ] `.venv/bin/ruff check scripts/discover.py tests/test_discover.py` and
  `.venv/bin/ruff format --check` on the same files pass.
- [ ] `af validate --root .` passes.
- [ ] PR body includes `Closes #240`.

## Implementation Order

1. trinity-deepseek: write the new contract tests (fail against current code
   where behavior changes, pass where preserved) — TDD per COR-1500.
2. trinity-glm: rewrite `main()` per Surface 1.
3. Orchestrator: run AC verification commands; regenerate index; CHANGELOG
   check.

Commit order: the RED commit (step 1, new tests failing on changed rows)
lands before the GREEN commit (step 2); do not squash them together, so the
RED evidence survives in history.

## Migration / Backward-compat

Documented CLI surface unchanged. Out-of-repo scripted callers of the error
paths (none found in-repo) should note: usage errors now exit **2** instead
of 1 with argparse-formatted messages on stderr, and `-h`/`--help` now print
help and exit 0 instead of erroring. `#239` (install.py argparse) should
follow the same `--version`-dispatch and `allow_abbrev=False` choices for
cross-script consistency.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 9.3 FAIL | 8.55 FAIL | 8.8 FAIL | ❌ |
| R2 (2026-07-04) | 9.55 PASS | 9.65 PASS | 9.25 FAIL (blocking: none; compression only) | ❌ |
| R3 (2026-07-04) | — (R2 carry) | — (R2 carry) | 9.45 FAIL (blocking: none ×2; compression structurally capped at 8/10) | ❌ strict / ✅ adjudicated |

**Adjudication (2026-07-04, operator frankyxhl):** minimax held 9.45 with an
empty blocking list for the second consecutive round and stated no honest CHG
edit can close the gap (the net test-LoC growth is the contract pinning the
panel itself required). Quorum (glm 9.55 / deepseek 9.65) exceeded threshold
with no correctness changes since. Operator adjudicated PASS with dissent
recorded; per minimax's own R3 advisory, this table is reproduced in the PR
body so the 0.05 hover is visible at merge time.

R1 blocking findings folded (converged across reviewers): `--version` ×
subcommand interaction pinned both directions + version-check-before-dispatch
invariant; top-level `--bogus` Changed row; `-h`/`--help` auto-injection
declared as deliberate addition + pinned; default expanduser path test.
Advisories folded: stderr-stream assertions, RED/GREEN commit order, explicit
exit 1→2 note in §Migration, #239 consistency note. Advisory skipped:
empty-string flag value test (boundary with no failure mode distinct from the
explicit-path tests; reviewer marked it low-risk).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #240. | Claude Code (orchestrator) |
| 2026-07-04 | R1 panel fixes: contract table +3 rows (top-level `--bogus`, `list --version`, `-h`/`--help`), version-check-before-dispatch invariant, Surface 2 test list expanded, RED/GREEN commit order, §Migration exit-code note. | Claude Code (orchestrator) |
| 2026-07-04 | R2 fixes (minimax compression finding + deepseek/minimax assertion-depth advisories): Surface 2 error cases collapsed to one parametrized test (~50 LoC est., was ~80-100); `--version` exact-match assertion; `--version list` no-JSON assertion; default-path patched-HOME containment assertion; Surface 1 parser-inside-main() constraint. | Claude Code (orchestrator) |

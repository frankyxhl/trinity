# CHG-2026: Scope Coverage Shim Activation to `make coverage` Only

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #58)
**Priority:** Medium
**Change Type:** Standard
**Closes:** #58

---

## What

Move the activation of the subprocess-coverage shim out of `tests/conftest.py` (where it runs unconditionally on every `pytest tests/` invocation) and into `Makefile`'s `coverage:` target (where it's actually wanted). Concretely:

1. **`tests/conftest.py`** — gate the `PYTHONPATH` mutation on `os.environ.get("COVERAGE_PROCESS_START")` already being set. Drop the `os.environ.setdefault("COVERAGE_PROCESS_START", ...)` line; setting that env var becomes the Makefile's job. Update the module docstring to reflect the new contract (no-op when env unset; PYTHONPATH-prepend when set).
2. **`Makefile`** — the `coverage:` target sets `COVERAGE_PROCESS_START=$(CURDIR)/.coveragerc` via **inline assignment on the same recipe line** as `coverage run`. (Make spawns a fresh subshell per recipe line; `export VAR=…` on a previous line would not persist. The Makefile does not enable `.ONESHELL`. Inline `VAR=val cmd` is the canonical form.)
3. **`tests/sitecustomize.py`** — docstring update only. The runtime behavior is unchanged (`coverage.process_startup()` stays a no-op when env unset). But its current docstring (lines 9-10) asserts "the conftest.py at the same directory sets COVERAGE_PROCESS_START" — false post-CHG. Update the docstring to state that the Makefile's `coverage:` target is now the producer of `COVERAGE_PROCESS_START`, and conftest only ensures `PYTHONPATH` propagation.

### Proposed diffs (embedded in CHG to prevent subshell mistakes during code-review)

**`tests/conftest.py`** — full rewrite:

```python
"""Test-runner setup: optionally enable coverage tracking inside subprocesses.

Subprocess-coverage tracking is OPT-IN, controlled by `COVERAGE_PROCESS_START`:

- When `COVERAGE_PROCESS_START` is set in the env (set by `Makefile`'s
  `coverage:` target via inline `VAR=val cmd`, or by a developer
  invoking pytest directly with the env var prefix), this conftest
  prepends `tests/` to `PYTHONPATH` so child Python processes
  auto-import `tests/sitecustomize.py`, which calls
  `coverage.process_startup()`.

- When `COVERAGE_PROCESS_START` is unset (the default during plain
  `make test` and direct `pytest tests/` invocation), this conftest
  is a no-op. No PYTHONPATH mutation, no `.coverage.*` files written
  by subprocesses.

Note on ambient env: a developer who has `COVERAGE_PROCESS_START`
exported globally in their shell will trigger the gate even on plain
`make test`. This is by design (the env var IS the opt-in switch),
but worth noting if `.coverage.*` files appear unexpectedly.

`coverage.process_startup()` is a no-op unless `COVERAGE_PROCESS_START`
or `COVERAGE_PROCESS_CONFIG` is set (verified against coverage.py
control.py:1437). So accidental imports of sitecustomize stay harmless.
"""

import os
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()

if os.environ.get("COVERAGE_PROCESS_START"):
    _existing_pp = os.environ.get("PYTHONPATH", "")
    _parts = _existing_pp.split(os.pathsep) if _existing_pp else []
    if str(_TESTS_DIR) not in _parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(_TESTS_DIR), *_parts])
```

The `_PROJECT_ROOT / ".coveragerc"` existence check is dropped — the env var IS the gate now; if it points to a missing file `coverage.process_startup()` raises a `ConfigError` which is loud-and-correct rather than silent-and-wrong.

**`Makefile`** — `coverage:` target:

```makefile
coverage:       ## Measure line coverage with subprocess tracking (TRN-2023, fail-under 80%)
	.venv/bin/coverage erase
	COVERAGE_PROCESS_START=$(CURDIR)/.coveragerc .venv/bin/coverage run -m pytest tests/ -q
	.venv/bin/coverage combine
	.venv/bin/coverage report --include='scripts/*,dev/*' --fail-under=80
```

The env var is set via **inline assignment on the same recipe line** as `coverage run`, scoped to that single command invocation. Per-line subshell isolation in Make means this is the only correct form unless `.ONESHELL` is enabled.

**`tests/sitecustomize.py`** — docstring update only:

```python
"""Auto-start coverage in any Python child process that has tests/ on PYTHONPATH.

When PYTHONPATH includes tests/, Python imports `sitecustomize` at startup;
this module then activates coverage based on the COVERAGE_PROCESS_START
env var. The combination lets pytest-cov see lines executed inside
subprocesses spawned via subprocess.run (the dominant test pattern).

Producer of COVERAGE_PROCESS_START: `Makefile`'s `coverage:` target sets
it via inline `VAR=val cmd` form (see Makefile `coverage:` target for
the canonical incantation including `--include` and `--fail-under`
flags). A developer can also set it directly to opt in via the same
pattern: `COVERAGE_PROCESS_START=$(pwd)/.coveragerc .venv/bin/coverage
run -m pytest tests/ -q && .venv/bin/coverage combine && .venv/bin/coverage report`.

Reader of COVERAGE_PROCESS_START: `tests/conftest.py` reads it as the
gate; child processes pass it via env inheritance to
`coverage.process_startup()` here.

`coverage.process_startup()` is a no-op when neither
`COVERAGE_PROCESS_START` nor `COVERAGE_PROCESS_CONFIG` is set, so this
module stays harmless on accidental imports.
"""

import coverage

coverage.process_startup()
```

## Why

`tests/conftest.py` currently sets `COVERAGE_PROCESS_START` unconditionally at pytest collection time. Every Python subprocess spawned by the test suite (and the test suite spawns many — `subprocess.run([..., scripts/codex.py, ...])`-style is the dominant test pattern) imports `tests/sitecustomize.py` and starts a coverage instrumentation session. For `make test` (the developer's tight feedback loop) this is wasted work:

- ~5–10s of subprocess startup/shutdown overhead per `make test` cycle on macOS (data point from the TRN-2020 contract panel review)
- `.coverage.HOSTNAME.PID.RANDOM` files accumulate in the workspace (gitignored, but visually noisy; require manual `coverage erase`)
- Coverage data is collected and discarded — `make test` doesn't run `coverage report`

The shim was added in TRN-2023 to fix the 27%-vs-83% reporting gap when running `coverage run -m pytest` directly — that's `make coverage`'s job, not `make test`'s.

Issue #58 documents this explicitly. Trinity panel scored leaving as-is at 6.62 ("defer; ship if friction"); friction has now surfaced (this issue) so we ship.

## Impact

### Files touched (atomicity)

Per CLD-1801 §2, this is a **cross-class candidate** with three surfaces — two Python files, one Makefile target. All three are tightly coupled (the Makefile sets the env var that conftest reads, sitecustomize is the indirect consumer in spawned subprocesses), so they ship in one PR but each edit is minimal to its declared surface.

| Surface | Edit |
|---------|------|
| `tests/conftest.py` | Drop `os.environ.setdefault(...)` and the `.coveragerc.exists()` guard. Gate `PYTHONPATH` prepend on `os.environ.get("COVERAGE_PROCESS_START")`. Rewrite docstring per the embedded diff. |
| `tests/sitecustomize.py` | Docstring update only (no code change). Document that the Makefile is the producer post-CHG. |
| `Makefile` `coverage:` target | Add inline `COVERAGE_PROCESS_START=$(CURDIR)/.coveragerc` prefix on the `coverage run` line. |

Total expected change: ~30 lines (mostly docstring rewrites). Code delta is net negative (-1 line in conftest body, +30 chars in Makefile).

### CI impact

`.github/workflows/test.yml` calls `make test` (line 59) THEN `make coverage` (line 61) in the same job. After this change:
- `make test` step: subprocesses uninstrumented, no `.coverage.*` artifacts left over to confuse the subsequent `make coverage` step. (Pre-fix: `make coverage`'s `coverage erase` step cleaned up `make test`'s leftovers; post-fix: there are no leftovers to clean. Same outcome via different path.)
- `make coverage` step: erases (`coverage erase`), runs with env var set, combines, reports — unchanged outcome (TOTAL ≥80% preserved).

`.github/workflows/release.yml` (line 157) calls only `make test` — beneficial impact (no wasted instrumentation during release validation).

`Makefile`'s `release-prep:` target (line ~126) invokes `make test` — also benefits, no change required.

`scripts/pr-update.sh` validates `make test` — also benefits.


### Backwards compatibility

- A developer running `pytest tests/` directly **without** setting `COVERAGE_PROCESS_START` will no longer get subprocess coverage. **Intended behavior change** per #58.
- A developer who explicitly wants coverage from a direct invocation has **two paths**, neither equivalent to plain `pytest --cov`:
  - **Recommended**: `make coverage` (full signal: erase → run → combine → report).
  - **Manual equivalent**: `COVERAGE_PROCESS_START=$(pwd)/.coveragerc .venv/bin/coverage run -m pytest tests/ -q && .venv/bin/coverage combine && .venv/bin/coverage report`. Note: bare `pytest --cov=scripts tests/` is **NOT** a substitute — pytest-cov 7.x removed its own subprocess-measurement support and defers to `coverage.process_startup()`. Without `coverage run` as the parent, you only get the parent process's coverage (the original 27% problem).

### Rollback

Revert this PR's commit. The change is contained to two Python files and one Makefile target. `.coveragerc` is unchanged.

## Acceptance Criteria

| # | Check | How |
|---|-------|-----|
| A1 | `make coverage` reports `TOTAL` line coverage ≥ 80% | `make coverage` exits 0 with `--fail-under=80` |
| A2 | `make coverage` reports the same per-module coverage as before, within ±1pp | **Baseline capture**: before opening PR, on `main`, run `make coverage` and save output to `tmp/coverage-baseline.txt` (gitignored). On the PR branch, run `make coverage` and `diff` against the baseline. Attach diff to PR body. |
| A3 | After `coverage erase` then `make test`, no new coverage data files in workspace | `.venv/bin/coverage erase && make test && find . \( -name '.coverage' -o -name '.coverage.*' \) -not -path './.git/*' -not -path './.venv/*'` returns zero entries. **The glob is split** to avoid matching `./.coveragerc` (the tracked config file in repo root); `-name '.coverage*'` would false-positive on it. |
| A4 | Direct `pytest tests/` invocation with no coverage env vars: no coverage data files written | Manual: `.venv/bin/coverage erase && unset COVERAGE_PROCESS_START COVERAGE_PROCESS_CONFIG && .venv/bin/pytest tests/test_codex_adapter.py -q && find . \( -name '.coverage' -o -name '.coverage.*' \) -not -path './.git/*' -not -path './.venv/*'` returns zero entries. Both env vars unset for symmetry with §Writer schema (either triggers `coverage.process_startup()`). |
| A5 | All existing tests pass on both ubuntu-latest and macos-latest | CI green |

## Out of Scope

- **Renaming or restructuring `tests/sitecustomize.py`** — only the docstring updates; runtime behavior unchanged.
- **Adding a `TRINITY_TRACK_COVERAGE` sentinel env var** — explicitly rejected in #58 alternatives ("redundant with the existing mechanism").
- **Refactoring tests away from `subprocess.run`** — explicitly rejected in TRN-2020-PRP (preserves v2.0.0 incident-class regression evidence).
- **Modifying `.coveragerc`** — out of scope.
- **Pinning `coverage` / `pytest-cov` versions in `Makefile setup:` for baseline reproducibility** — orthogonal concern, defer.

## Authority

Standalone single-slice CHG, not part of any execution contract — same shape as TRN-2025 / TRN-2028. Operator defaults: identity `ryosaeba1985` for GitHub-visible writes, branch `codex/trn-2026-coverage-shim-scope`, plan-review and code-review via 4-provider Trinity panel (glm + gemini + deepseek + codex) with ≥9.0 PASS gate **for every individual provider** (mean alone is insufficient — PR #60 demonstrated mean ≥9 with one outlier at 8.7 still let a real bug through).

### Code-review prompt addendum (5-step methodology rule from PR #60)

PR #60 surfaced 7 consecutive caller-flow / sibling-code / unverified-invariant findings that the 4-provider panel chain missed. The methodology rule queued at PR #60's CHG change-history is now live and embedded in this CHG's plan-review and code-review dispatches:

1. **Trace caller flows** of any function the diff consumes data from
2. **Read writer schemas** of any data the diff parses
3. **Compare to sibling registration sites** for any new subcommand / feature / config key
4. **When fixing value-handling in helper X**, grep for the same hard-code/pattern in sibling helpers consuming the same data source
5. **Comments asserting invariants** (e.g., "fixed-width prefix → lex == chrono") MUST be verified against the writer that produces the data — *and against the readers that depend on the invariant being true*

Specifically for THIS CHG, applying the rule:

- (1) caller flow: `make coverage` → inline `VAR=val coverage run -m pytest` → pytest collects conftest → conftest reads env → mutates PYTHONPATH → child `subprocess.run(...)` inherits env → child Python imports `sitecustomize` → `coverage.process_startup()` reads env. Any link broken = subprocess coverage broken.
- (2) writer schema: `coverage.process_startup()` (verified against `coverage/control.py:1437`) is a no-op when neither `COVERAGE_PROCESS_START` nor `COVERAGE_PROCESS_CONFIG` is set. Safe to leave `sitecustomize.py` runtime unchanged.
- (3) sibling sites: `make test`, `make coverage`, `release.yml`, `test.yml`, `Makefile release-prep:`, `scripts/pr-update.sh` — all 6 caller paths verified above.
- (4) value-handling siblings: `git grep COVERAGE_PROCESS_START` returns only `tests/conftest.py`, `tests/sitecustomize.py`, `rules/TRN-202[03]*.md` (historical docs). Post-CHG: Makefile becomes the unique writer; conftest is the sole reader (sitecustomize calls `coverage.process_startup()` which reads env directly inside `coverage` package). No siblings to grep.
- (5) comment-stated invariants:
  - **Invariant A** ("conftest is no-op when `COVERAGE_PROCESS_START` is unset") — verified by acceptance criterion A3 (empirical: `make test` writes zero `.coverage*` files).
  - **Invariant B** ("sitecustomize is harmless on accidental imports") — verified by reading coverage.py source (`process_startup()` returns early when neither env var is set).
  - **Invariant C** (the previous `tests/sitecustomize.py:9-10` claim that "conftest sets COVERAGE_PROCESS_START") — **becomes false post-CHG**; updated docstring restates the producer correctly. (This was the exact step-5 violation codex caught in plan-review round 1 — keeping it logged here as a worked example of why the rule matters.)

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3, with PR #60's 5-step methodology rule embedded in the code-review prompt addendum | Claude Opus 4.7 |
| 2026-05-08 | **Status**: Proposed → Approved (plan + code-review gate met). Code-review round 1 (4-provider panel, branch `codex/trn-2026-coverage-shim-scope`, 3 files / 116-line diff): codex 9.64 PASS, gemini 9.75 PASS, glm 9.525 PASS, deepseek 9.50 PASS — **all 4 individually PASS at ≥9.0** (mean 9.60), zero blocking. Adopted: gemini's cosmetic advisory (conftest docstring line citation refined from `control.py:1437` to `control.py process_startup() — early-return gate at the function top` — robust to coverage.py version drift). All 4 acceptance criteria pre-verified locally on the implementation branch (A1 TOTAL 83% ≥80%, A2 zero drift vs main baseline, A3 `make test` zero `.coverage*` files, A4 direct pytest with both env vars unset zero `.coverage*` files, A5 deferred to CI). Codex independently verified `coverage/control.py` writer-schema invariant; gemini verified gate logic at L1482-1490; glm verified all 9 sibling caller paths; deepseek verified all 4 invariants A/B/C/D against actual code. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 2 (4-provider panel re-dispatch): glm 9.45 PASS (was 9.2), gemini 10.0 PASS (was 10.0), deepseek 9.30 PASS (was 9.15), **codex 8.9 FAIL** (was 8.75) — round-1 blocking B1/B2/B3 confirmed resolved, but **codex caught new B4**: A3/A4 glob `.coverage*` matches `./.coveragerc` (tracked config file in repo root), so the "zero entries" check would spuriously fail on a clean tree. Adopted in round 3: A3/A4 glob split into `\( -name '.coverage' -o -name '.coverage.*' \)` to exclude the config file. Also adopted glm round-2 advisories (sitecustomize docstring incantation aligned to `.venv/bin/coverage` for consistency; reference Makefile flags rather than re-listing them) and codex round-2 advisory (A4 also `unset COVERAGE_PROCESS_CONFIG` for symmetry with the §Writer schema two-env-var trigger). Skipped deepseek's "automate A2 baseline via in-repo file + CI diff" — fair point but disproportionate to the change; noted as future enhancement. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 1 (4-provider panel): scores glm 9.2 PASS, gemini 10.0 PASS, deepseek 9.15 PASS, **codex 8.75 FAIL**. Codex's 3 blocking findings adopted: B1 — direct `pytest --cov` workaround in §Backwards-Compat was wrong (not equivalent to `make coverage`); now documents both paths with the canonical `coverage run + combine + report` incantation. B2 — `tests/sitecustomize.py` docstring lines 9-10 (asserting conftest produces COVERAGE_PROCESS_START) becomes false post-CHG; added sitecustomize as a third surface in the Impact table with docstring-only update; this is the **exact step-5 invariant violation** the methodology rule is meant to catch — keeping it logged as a worked example. B3 — A3 polluted by stale `.coverage*` files; reworded to require `coverage erase` first. Also folded in advisory tightenings: gemini's embedded-diff request (proposed code blocks now in §What); gemini's CI ordering invariant note; gemini's A2 baseline-capture mechanics; glm's `.coveragerc.exists()` guard disposition (dropped — env var IS the gate); glm's `COVERAGE_PROCESS_CONFIG` mention; deepseek's terminology harmonization ("inline assignment" not "exports"); deepseek's `find -maxdepth 2` removal; deepseek's ambient-env footgun note. Authority section also tightened: explicit "all 4 providers PASS individually at ≥9.0" rule (PR #60 lesson — mean alone is insufficient). | Claude Opus 4.7 |

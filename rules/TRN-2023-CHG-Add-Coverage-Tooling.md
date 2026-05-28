# CHG-2023: Add Coverage Tooling

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Date:** 2026-05-07
**Requested by:** Frank (via GitHub issue #41 plan B + TRN-2020-PRP slice B)
**Implementer:** Claude Opus 4.7
**Priority:** Medium
**Change Type:** Normal
**Related:** TRN-2020 (parent PRP), TRN-2021 (execution contract), TRN-2022 (slice A), TRN-1801, COR-1614, COR-1616, COR-1500

---

## What

Slice B of the TRN-2020 / TRN-2021 multi-phase test-improvement contract. Wires line-coverage measurement into the test stack with subprocess tracking, adds a `make coverage` target with a `--fail-under=80` gate, and introduces the project's first PR-triggered CI workflow on Linux + macOS.

---

## Why

Three concrete gaps from the parent PRP:

1. **No coverage signal today.** `make setup` installs only `pytest` + `ruff`. There is no `pytest-cov`, no `.coveragerc`, no codecov upload. A naive `pytest --cov=scripts --cov=dev` reports ~27% line coverage because the Python tests invoke their target modules as subprocesses (`subprocess.run([...session.py, ...])`); coverage in the parent process can't see child execution. With a `COVERAGE_PROCESS_START` + `sitecustomize` shim the real number is **83%** (1533 statements, 264 missed).
2. **TRN-1801 evolve cycle has no coverage signal.** Without coverage tooling wired in, evolve cycles cannot use coverage delta as a candidate-evaluation axis.
3. **CI is tag-only today.** `.github/workflows/release.yml` fires on `push: tags: v*.*.*`. There is no `pull_request`-triggered CI, so the v2.0.0-class macOS-passes-Linux-fails parity bug class can ship into a PR and only surface at release. Slice A (TRN-2022) explicitly noted this gap; slice B closes it.

---

## Impact and Risk

**Impact:**
- Adds two test-infra dependencies (`pytest-cov`, `coverage[toml]`) to `make setup`.
- Adds 3 new files (`.coveragerc`, `tests/sitecustomize_shim.py`, `.github/workflows/test.yml`) and creates a new `tests/conftest.py`.
- Adds a new `make coverage` Make target.
- Wall-clock impact on `make test`: zero (coverage tooling only activates under `make coverage`).
- Wall-clock impact on PR CI: ~3–5 min per OS leg (ubuntu-latest + macos-latest in matrix). For a public repo on GitHub Free tier, this is unmetered.

**Risk:** Low to medium.

- **Subprocess tracking is fragile.** The `COVERAGE_PROCESS_START` env var must reach Python child processes spawned via `subprocess.run`. The `tests/conftest.py` will set it explicitly; the `tests/sitecustomize_shim.py` auto-loads in any Python process that has `tests/` on `PYTHONPATH`. If the env var leaks into unrelated child processes (e.g., a `subprocess.run(["which", "git"])`), coverage logs benign `.coverage.*` data files; mitigated by `parallel = True` + `coverage erase` at start of `make coverage`.
- **Coverage threshold drift.** Today's measured baseline is 83%. Setting `--fail-under=80` leaves 3% headroom. If a PR adds untested code, the threshold bites; if a PR makes a justified coverage drop (e.g., delete tested code, restructure), the threshold needs to move. This is normal coverage-gate hygiene, not a slice B risk.
- **CI workflow is permanent infra.** Once merged, every PR runs the matrix; reverting requires another PR. Mitigated by keeping the workflow narrow (run existing `make test` + `make coverage`, no new commands, no secrets, no deploy steps).
- **macOS runner availability.** GitHub macOS runners are sometimes capacity-constrained during peak hours. Mitigated by setting `fail-fast: false` in the matrix so an ubuntu pass + macOS queue isn't blocked indefinitely.

---

## Implementation Plan

Five file changes, one commit:

1. **`Makefile`** — extend the `setup:` target to install `pytest-cov` and `coverage[toml]` alongside the existing `pytest` + `ruff`. Add a new `coverage:` target that runs `coverage erase && coverage run -m pytest tests/ -q && coverage combine && coverage report --include='scripts/*,dev/*' --fail-under=80`. Note: the runner is `coverage run -m pytest`, not bare `pytest`, so the pytest parent process is also measured. Tests that import a module and call its functions directly (`tests/test_codex_review_dispatch.py` calls `codex.cmd_review()`) execute in the parent; under bare pytest the subprocess shim only measures children, leaving parent-process execution silently uncounted.

2. **`.coveragerc`** (new) — project-root config:
   ```ini
   [run]
   parallel = True
   source = scripts,dev
   sigterm = True

   [report]
   exclude_also =
       if __name__ == .__main__.:
       raise NotImplementedError
   ```
   `parallel = True` lets each subprocess write its own data file. `sigterm = True` flushes coverage on graceful shutdown (matters for `cmd_review` which installs SIGTERM handlers).

3. **`tests/sitecustomize_shim.py`** (new) — three lines:
   ```python
   import coverage
   coverage.process_startup()
   ```
   When a Python child process boots with `tests/` in `PYTHONPATH`, Python auto-imports `sitecustomize` at startup; this shim then activates coverage based on `COVERAGE_PROCESS_START`.

4. **`tests/conftest.py`** (new) — set up the env var + `PYTHONPATH` injection for child processes:
   ```python
   import os
   import sys
   from pathlib import Path

   _TESTS_DIR = str(Path(__file__).parent.resolve())
   os.environ.setdefault("COVERAGE_PROCESS_START",
                         str(Path(__file__).parent.parent / ".coveragerc"))
   _existing_pp = os.environ.get("PYTHONPATH", "")
   if _TESTS_DIR not in _existing_pp.split(os.pathsep):
       os.environ["PYTHONPATH"] = (
           _TESTS_DIR + (os.pathsep + _existing_pp if _existing_pp else "")
       )
   ```
   This avoids the venv-`site-packages`-write hack used during the baseline measurement.

5. **`.github/workflows/test.yml`** (new) — PR-triggered CI:
   ```yaml
   name: Test
   on:
     push:
       branches: [main]
     pull_request:
   permissions:
     contents: read
   jobs:
     test:
       strategy:
         fail-fast: false
         matrix:
           os: [ubuntu-latest, macos-latest]
       runs-on: ${{ matrix.os }}
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.11'
         - run: make setup
         - run: make test
         - run: make coverage
   ```

---

## Test / BDD / Coverage Expectations

- `make coverage` exits 0 with `coverage report` showing TOTAL ≥ 80% and per-module numbers within ±2% of the baseline (codex.py 82%, session.py 81%, install.py 75%, config.py 88%, discover.py 88%).
- The new `.coveragerc`, `conftest.py`, and `sitecustomize_shim.py` MUST NOT change `make test` pass/fail counts. Existing 141 pytest + 113 + 105 + 10 + 2 shell cases stay green.
- The CI workflow runs `make setup && make test && make coverage` on both `ubuntu-latest` and `macos-latest` and exits 0 on both.

---

## Acceptance

- `make coverage` on `main` post-merge reports TOTAL ≥ 80% line coverage on `scripts/`.

- `make test` continues to produce the same pass count as before slice B.
- A PR opened against `main` post-merge shows two passing checks (Test (ubuntu-latest), Test (macos-latest)) within ~5 min.
- TRN-1801 evolve cycles can now read `make coverage` output as a candidate-evaluation signal.
- `af validate --root .` reports 0 issues.

---

## Validation Commands

```bash
make verify-built          # passes (no providers/_base/ changes)
make test                  # existing 141 + 113 + 105 + 10 + 2 PASS, no regressions
make coverage              # exits 0, TOTAL ≥ 80% on scripts/

make lint                  # ruff clean
af validate --root .       # 0 issues
```

CI verification (post-merge, on next PR):
- Open any small PR against `main`. Verify "Test (ubuntu-latest)" and "Test (macos-latest)" both turn green within ~5 min.

Executed locally on `codex/trn-2023-coverage`:

```
$ make verify-built
build_providers --check: OK (committed matches generated)

$ make test          # all gates still PASS, no regressions from conftest/sitecustomize
... (existing 141 pytest + 113 + 105 + 10 + 2 shell PASS) ...

$ make coverage
.venv/bin/coverage erase
.venv/bin/coverage run -m pytest tests/ -q
.venv/bin/coverage combine     (combines parent + ~70 subprocess .coverage.* parallel data files)
.venv/bin/coverage report --include='scripts/*' --fail-under=80

Name                  Stmts   Miss  Cover
-----------------------------------------
scripts/__init__.py       1      0   100%
scripts/codex.py        844    151    82%
scripts/config.py        82     10    88%
scripts/discover.py      91     11    88%
scripts/install.py      126     32    75%
scripts/session.py      169     33    80%
-----------------------------------------
TOTAL                  1313    237    82%

$ make lint
All checks passed!     (19 files already formatted)

$ af validate --root .
104 documents checked, 0 issues found.
```

Per-module numbers within ±2% of the baseline measurement on `2766115`. TOTAL = 82%, comfortably above the 80% gate.

---

## Out of Scope

- Codecov / Coveralls remote upload (local + CI gate is sufficient v1; promote later if multi-contributor visibility becomes useful).
- Mutation testing (`mutmut`, `cosmic-ray`).
- Property-based testing (`hypothesis`).
- Shell-test coverage (`kcov` is Linux-only, `bashcov` adds Ruby — neither fits the zero-dep posture).
- Refactoring tests away from `subprocess.run` to import-then-call (would invalidate v2.0.0 incident-class regression evidence; the subprocess pattern is preserved with the shim).
- Windows runner in the CI matrix (no Windows users today; can add as follow-on if requested).
- Multiple Python version matrix (today's setup.py / scripts target 3.11+; broader matrix is a separate proposal).

---

## Authority

This CHG is subordinate to TRN-2021-PLN §4 (slice B definition). Operator defaults from TRN-2021-PLN §2 apply: branch `codex/trn-2023-coverage`, identity `ryosaeba1985`, plan-review skipped (parent PRP review covered strategy), code-review delegated to PR review loop. The `.github/workflows/test.yml` inclusion was explicitly authorized by the operator on 2026-05-07 in response to the slice B CI question raised post-slice-A merge.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft of slice B delivery contract; CI workflow inclusion confirmed by operator | Claude Opus 4.7 |
| 2026-05-07 | PR #45 round 1 P2 from Codex bot: bare `pytest tests/ -q` doesn't measure the pytest parent process, so tests that import modules and call functions directly (`test_codex_review_dispatch.py` calling `codex.cmd_review()`) are silently omitted from coverage. Fix: change runner to `coverage run -m pytest`. Re-measured baseline TOTAL 82% → 83%; codex.py 81% → 82% (the directly-called functions now visible to coverage). | Claude Opus 4.7 |
| 2026-05-08 | Status reconciled to Completed; merged in PR #45 at `0143d07` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

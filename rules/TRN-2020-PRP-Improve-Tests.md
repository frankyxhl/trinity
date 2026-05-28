# PRP-2020: Improve Tests

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-07
**Last reviewed:** 2026-05-07
**Status:** Implemented
**Reviewed by:** Trinity panel review on 2026-05-07 (`.trinity/reviews/20260507-180721-rules/`): glm PASS, deepseek PASS with 7 advisory findings (F1 skipped — `af index` tool behavior; F2+F3 folded into slice A scope; F4+F5 adopted; F6+F7 skipped with rationale), gemini timeout (no opinion). 2-of-3 PASS, no blockers; approved for execution per COR-1614 contract TRN-2021.
**Implemented:** All three slices merged on 2026-05-07. Slice A `5b0a666` (PR #44, 6 review rounds, 7 P2 findings resolved). Slice B `cfe6e08` (PR #45, 1 review round, 1 P2 finding resolved — coverage methodology). Slice C `1e28392` (PR #46, 2 review rounds, 1 P1 + 1 race-fix resolved). Acceptance criteria all met: `make test` invokes `tests/test_install_sh.sh`, `make coverage` reports 83% TOTAL on `main`, `pytest tests/test_bdd_scenarios.py` collects 13 scenarios.
**Related:** TRN-1000, TRN-1001, TRN-1002, TRN-1801, TRN-2021, GitHub issue #41

---

## What Is It?

Three targeted improvements to the Trinity test infrastructure, delivered as one COR-1614 multi-phase execution contract:

1. Wire `tests/test_install_sh.sh` into `make test` so the install-path smoke test runs every cycle.
2. Add line-coverage measurement with subprocess tracking, plus a `make coverage` target.
3. Add a `pytest-bdd` scenario layer for `/trinity` user-narrative flows.

The PRP is the authority document. The execution contract (TRN-2021-PLN) authorizes the three slices to run continuously without re-asking settled scope. Each slice ships as its own CHG and PR.

---

## Problem

Three concrete gaps surfaced when surveying the test infrastructure on `2766115` (release-prep commit on `codex/release-v3.2.0`):

**Install-path smoke test orphaned.** `tests/test_install_sh.sh` exists with ~10 hermetic cases (local `python3 -m http.server` against `mktemp -d` HOME, no network, no real `~/.claude/` impact). It catches the v2.0.0-class macOS-passes-Linux-fails parity bugs that TRN-1801 evolve cycles exist to prevent. The file was last touched in `d1e4464` (claude-code provider, May 2026). It is not referenced by `Makefile`'s `test` target. No comment in commit history explains the exclusion — it appears to be an oversight when the claude-code provider landed.

**No coverage measurement.** `make setup` installs only `pytest` + `ruff`. There is no `pytest-cov`, no `.coveragerc`, no `make coverage` target, and no codecov upload. A naive one-shot run of `pytest --cov=scripts --cov=dev` reports ~27% line coverage because the Python tests invoke their target modules as **subprocesses** (`subprocess.run([...session.py, "read", ...])`) — coverage in the parent process cannot see child execution. With a `COVERAGE_PROCESS_START` + `sitecustomize.py` shim, the real number is 83% across `scripts/` and `dev/` (1533 statements, 264 missed). Without coverage tooling wired in, TRN-1801 evolve cycles have no coverage signal to use as a regression guard.

**No scenario-shaped coverage of `/trinity` flows.** Tests are unit-shaped: each `test_*.py` maps 1:1 to a source module. Several user-facing flows have no scenario-shaped coverage — single dispatch, review preset fan-out (with the optional/preflight A/B/C/D boundary that PR #42 just exercised), plan-mode auto-decompose, heartbeat + timeout transitions, install atomic rollback. Reviewers (panel and human) consistently ask "what does this do for the user," and the answer today is "stitch SKILL.md prose with `test_codex_review_dispatch.py` mocks and infer." This is the surface where a BDD layer earns its keep.

---

## Scope

**In scope (v1):**

- Slice A: `Makefile` change to invoke `bash tests/test_install_sh.sh` from the `test` target, plus `TRN-1800-REF-Evolution-Philosophy.md` §Behavior Baseline correction (pytest count `63+` → `141+`, `test_install_sh.sh` listing becomes accurate post-merge — folds in panel review findings F2+F3). Documented in TRN-2022-CHG.
- Slice B: `pytest-cov` + `coverage[toml]` added to `make setup`; commit `.coveragerc` (parallel mode, sigterm handler); commit `tests/conftest.py` extension + `tests/sitecustomize_shim.py` for subprocess tracking; add `make coverage` target with `--fail-under=80`. Optionally a new `.github/workflows/test.yml` for PR-triggered CI on Linux + macOS. Documented in TRN-2023-CHG.
- Slice C: `pytest-bdd` added to `make setup`; new `tests/features/` and `tests/step_defs/` directories; five seed scenarios (single dispatch, preset fan-out, plan auto-decompose, heartbeat/timeout, install rollback); shared step definitions reusing existing fixtures. Documented in TRN-2024-CHG.

**Out of scope (v1):**

- Refactoring existing tests to import-then-call instead of `subprocess.run` (would invalidate the v2.0.0 incident-class regression evidence — keep the subprocess pattern, add the shim instead).
- Coverage of `tests/*.sh` shell tests (no portable shell-coverage tool that fits the existing zero-dep setup; `kcov` is Linux-only, `bashcov` adds Ruby).
- Mutation testing (`mutmut`, `cosmic-ray`) — separate proposal if wanted.
- Property-based testing (`hypothesis`) — separate proposal if wanted.
- Replacing Codex / Claude Code review wiring with BDD step definitions — keep the existing `test_codex_review_dispatch.py` mock posture; BDD reuses the same fixtures.
- Codecov / Coveralls upload integration in slice B v1 — local `coverage report --fail-under=80` is the gate; remote upload deferred to a follow-on if wanted.

---

## Proposed Solution

### Slice A — Wire `test_install_sh.sh` into `make test`

`Makefile` `test:` target gets one additional line invoking the shell test, ordered after `test_release_workflow.sh` so the slowest tests run last. Wall-clock impact ~5 s (HTTP server bring-up + 10 cases). No changes to `test_install_sh.sh` itself; if port 18742 collides on a contributor's machine, follow up by switching to OS-allocated port 0.

### Slice B — Coverage with subprocess tracking

Three small artifacts plus a Make target:

- **`.coveragerc`** — `parallel = True`, `source = scripts,dev`, `sigterm = True`. Parallel mode is required because each subprocess writes its own data file; `sigterm = True` flushes coverage on graceful shutdown (matters for `cmd_review` which installs SIGTERM handlers for provider process-group cleanup).
- **`tests/sitecustomize_shim.py`** — three lines: `import coverage; coverage.process_startup()`. Auto-loaded by every Python child when `PYTHONPATH` includes its parent dir.
- **`tests/conftest.py`** — extends or creates the existing conftest to set `os.environ["COVERAGE_PROCESS_START"] = ".coveragerc"` and prepend `tests/` to `PYTHONPATH` for child processes. Avoids the "write to venv site-packages" hack the one-shot baseline run used.
- **`make coverage` target** — `coverage erase && pytest -q && coverage combine && coverage report --include='scripts/*,dev/*' --fail-under=80`. The 80% floor leaves headroom under today's 83% baseline.
- **Optional `.github/workflows/test.yml`** — `pull_request` + `push` (main) triggers, matrix `os: [ubuntu-latest, macos-latest]`. Runs `make setup && make test && make coverage`. Today CI is tag-only; this slot fills the gap.

### Slice C — `pytest-bdd` scenario layer

- **`tests/features/`** — five `.feature` files in Gherkin:
  - `dispatch_single.feature` — `/trinity glm "task"` → background agent + session entry persisted in `.claude/trinity.json`.
  - `review_preset_fanout.feature` — `/trinity review` expansion + the four-case A/B/C/D boundary from PR #42 as a Scenario Outline (no config / optional broken / optional working / required broken).
  - `plan_mode_autodecompose.feature` — `/trinity plan "high-level description"` → diagram → `[Execute] / [Modify] / [Cancel]`.
  - `heartbeat_and_timeout.feature` — proactive update + warn / max threshold transitions per `defaults.timeout`.
  - `install_atomic_rollback.feature` — `/trinity install <provider>` rolls back agent file + config entry on smoke-test failure.
- **`tests/step_defs/conftest.py` + `tests/step_defs/common_steps.py`** — shared `Given a Trinity config at <path>` / `When I run trinity <args>` / `Then the session file contains <key>` step implementations. Reuse `tmp_path`, `monkeypatch`, and the existing JSON fixture helpers from `test_session.py` and `test_codex_review_dispatch.py`.
- **`tests/test_bdd_scenarios.py`** — a thin pytest collector module (one per feature file or one shared) that calls `from pytest_bdd import scenarios; scenarios("features/")` to bind the `.feature` files to pytest. Without this collector, pytest discovers zero scenarios even if the `.feature` files exist — pytest-bdd does not auto-collect raw feature files.
- **`make test` integration** — once the collector module(s) are in place, `pytest tests/` discovers them like any other test module, and pytest-bdd's `scenarios(...)` call walks the feature dir at collection time. No separate runner.

---

## Test / BDD / Coverage Expectations

- Slice A: existing `make test` wall-clock baseline (~30 s) extends to ~35 s. The new step must produce 10 PASS markers from `test_install_sh.sh`. No new assertions in this slice.
- Slice B: `make coverage` must exit 0 with `coverage report` showing TOTAL ≥ 80%. Per-file coverage must match the baseline ±2% (codex.py 82%, session.py 81%, install.py 75%, config.py 88%, discover.py 88%, pr-update.sh external call covered by `make test`). New `.coveragerc`, conftest, and shim must not change pass/fail counts.
- Slice C: 5 new BDD scenarios, all green. Total `make test` cases grows to 141 + 5 + (subscenario rows from outlines) ≈ 150. No regressions in existing pytest cases.

---

## Acceptance

- TRN-2022-CHG / TRN-2023-CHG / TRN-2024-CHG drafted, plan-reviewed (slice-level review delegated to PR loop per operator default in TRN-2021-PLN), implemented, and merged in three separate PRs.
- `make test` on `main` after slice A merge runs `tests/test_install_sh.sh`.
- `make coverage` on `main` after slice B merge reports ≥80% line coverage on `scripts/` + `dev/`.
- `make test` on `main` after slice C merge runs 5+ new BDD scenarios with all green.
- TRN-2021-PLN closed out with merge SHAs, deviations, and any deferred items (e.g. CI workflow if deferred).
- GitHub issue #41 closed with links to all three PRs and to TRN-2020 / TRN-2021.

---

## Validation Commands

Per slice, before opening the PR:

```bash
make verify-built
make test
make lint
af validate --root .
```

Slice B additionally:

```bash
make coverage   # must exit 0; reports ≥80% TOTAL
```

Slice C additionally:

```bash
.venv/bin/pytest tests/test_bdd_scenarios.py -v   # collector module binds 5+ scenarios green
.venv/bin/pytest --collect-only tests/test_bdd_scenarios.py   # confirm non-zero scenarios actually bind
```

---

## Out of Scope / Deferred

- Shell-test coverage measurement (no portable tool fits the zero-dep setup).
- Mutation testing.
- Property-based testing.
- Codecov / Coveralls remote upload (local gate is sufficient v1).
- Refactoring tests away from `subprocess.run` (incompatible with the v2.0.0 regression evidence preserved by the subprocess pattern).
- Migration of existing unit tests to BDD form (only net-new BDD scenarios in v1; unit tests keep their shape).

---

## Authority Chain

- GitHub issue #41 — original tracker, populated with the three plans on 2026-05-07.
- This PRP (TRN-2020) — promotes #41 to a project PRP for `af`-tracked governance.
- TRN-2021-PLN — the COR-1614 multi-phase execution contract, subordinate to this PRP.
- TRN-2022-CHG / TRN-2023-CHG / TRN-2024-CHG — per-slice contracts, subordinate to TRN-2021.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft promoting issue #41 content into a TRN PRP | Claude Opus 4.7 |
| 2026-05-07 | Trinity panel review (glm PASS / deepseek PASS / gemini timeout). Slice A scope expanded with TRN-1800 baseline correction (F2+F3). Status: Draft → Approved. | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 4 P2 from Codex bot: pytest-bdd does NOT auto-collect `.feature` files; raw feature files require a Python collector module calling `scenarios("features/")` or `@scenario(...)` to bind to pytest. PRP slice C scope corrected: collector module added as an explicit deliverable. | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 5 P2 from Codex bot: §Validation Commands slice C entry pointed at `pytest tests/features/ -v`, which (per round 4's own fix) collects zero scenarios because the collector module lives at `tests/test_bdd_scenarios.py`, not under `features/`. Validation command corrected to target the collector module + added `--collect-only` evidence step. | Claude Opus 4.7 |
| 2026-05-07 | All three slices merged. Status: Approved → Implemented. Merge SHAs: slice A `5b0a666` (PR #44), slice B `cfe6e08` (PR #45), slice C `1e28392` (PR #46). Acceptance criteria all met. Deferred follow-ons: `plan_mode_autodecompose.feature` (skill-only), heartbeat threshold transitions, codecov upload, mutation testing, property-based testing, Windows runner, `TRN-2025-CHG-Switch-Install-Sh-Test-To-File-Url` (panel-recommended file:// rewrite, scoped via prior decision matrix). | Claude Opus 4.7 |

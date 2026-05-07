# CHG-2024: Add Pytest-BDD Scenario Layer

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Reviewed by:** Trinity panel review on 2026-05-07 (`.trinity/reviews/20260507-195543-rules/`): glm PASS, deepseek FAIL with 2 BLOCKING + 1 HIGH + 3 lower findings, gemini timeout. All blocking + high findings adopted (single-file consolidation per B1+B2+M4; full Scenario Outline steps per H3); status moved Proposed → Approved.
**Date:** 2026-05-07
**Requested by:** Frank (via GitHub issue #41 plan C + TRN-2020-PRP slice C)
**Implementer:** Claude Opus 4.7
**Priority:** Low
**Change Type:** Normal
**Related:** TRN-2020 (parent PRP), TRN-2021 (execution contract), TRN-2022 (slice A), TRN-2023 (slice B), COR-1614, COR-1616, COR-1500

---

## What

Slice C of the TRN-2020 / TRN-2021 multi-phase test-improvement contract. Adds a pytest-bdd scenario layer with five user-facing flows captured as Gherkin features, plus a collector module that binds them to pytest at collection time (per the round-4 fix on PR #44 — pytest-bdd does not auto-collect raw `.feature` files).

---

## Why

Trinity's user-facing flows (`/trinity` slash commands, `trinity review` CLI) have grown beyond the unit-test mental model. Every CHG that touches dispatch, presets, sessions, or install behavior triggers the same reviewer question — "what does this do for the user" — and the answer today requires stitching `SKILL.md` prose with mocked unit tests. Gherkin scenarios capture the user-narrative directly, in a single place, and pytest-bdd binds them to executable assertions so they don't drift.

Five seed scenarios cover the highest-leverage flows: session CRUD, review preset fan-out (the four-case A/B/C/D boundary that PR #42 just exercised), provider discovery, session heartbeat, and install atomic rollback.

---

## Impact and Risk

**Impact:**
- Adds one test-infra dependency (`pytest-bdd`) to `make setup`.
- Adds 7 new files: 5 `.feature` files under `tests/features/`, 1 collector + step-def module `tests/test_bdd_scenarios.py`, 1 `tests/features/__init__.py` placeholder. (Single-file approach — see §Deviation.)
- `make test` total grows from 141 pytest cases to ~150 (5 base scenarios, with at least one Scenario Outline expanding to 3 rows → ~9–10 collected items).
- Wall-clock impact on `make test`: ~1–2 s for the new scenarios.
- Coverage impact: scenarios drive real CLI invocations of `scripts/session.py`, `scripts/install.py`, `scripts/discover.py`, and `scripts/codex.py:resolve_preset_providers`. The BDD assertions largely overlap existing unit-test code paths, so the marginal coverage gain is expected to be small (0–1 pt on each module rather than 1–3 pt). The value is narrative documentation, not coverage uplift.

**Risk:** Low.

- pytest-bdd version drift: the library has a 7.x → 8.x stability split. Pin to ≥7.0 conservative range; let `make setup` install the latest 7.x.
- Step-def explosion: BDD step defs can become a parallel mini-DSL that contributors must learn. Mitigated by: keeping the 5 seed scenarios, sharing fixtures (`tmp_path` + JSON-shape helpers) with existing pytest tests, and documenting the convention in the CHG.
- Skill-only flows: two of the originally-named PRP scenarios (`plan_mode_autodecompose`, parts of `heartbeat_and_timeout`) are Claude Code skill behavior with no Python surface to test. Slice C delivers 5 fully-testable scenarios; the skill-only flows are deferred to a follow-on once the skill itself becomes testable.

---

## Deviation from Parent PRP

### File-structure deviation: single-file approach

The parent PRP (TRN-2020-PRP §Slice C) listed `tests/step_defs/conftest.py` + `tests/step_defs/common_steps.py` as separate-directory step-def modules. This slice **drops the `tests/step_defs/` directory entirely** and consolidates the scenarios collector + all step definitions into a single file `tests/test_bdd_scenarios.py`.

Reason: pytest-bdd does not auto-discover step-def modules from a parallel directory. The step-def file must be either imported by the collector or registered via `pytest_plugins` before collection begins. Putting both in one file eliminates the registration question by construction, halves the file count for the slice, and keeps the BDD test surface immediately discoverable for new contributors (one file to read instead of three).

Trade-off: a single 200–300 line file is less modular than parallel-directory step defs. Acceptable at this scale (5 scenarios, 1 collector). If the BDD layer grows past ~500 lines or 15 scenarios, splitting back into `tests/step_defs/` with explicit `pytest_plugins = ["tests.step_defs.common_steps"]` registration is the natural follow-on.

### Scenario substitutions

The parent PRP named these five scenarios:

1. `dispatch_single.feature` — `/trinity glm "task"` → session entry
2. `review_preset_fanout.feature` — `/trinity review` A/B/C/D
3. `plan_mode_autodecompose.feature` — `/trinity plan "..."` → diagram
4. `heartbeat_and_timeout.feature` — proactive update + thresholds
5. `install_atomic_rollback.feature` — `/trinity install` rollback

Of those, `plan_mode_autodecompose` has **no Python surface** to test — the auto-decomposition logic lives in the Claude Code skill (`SKILL.md`), not in `scripts/`. Driving it from BDD would require either mocking the skill (defeating the point) or a documentation-only scenario with no real assertion.

This slice replaces that scenario with `provider_discovery.feature` (drives `scripts/discover.py list` against various config/agent-file states — a real testable surface that mirrors what `/trinity status` reports to the user). The deviation preserves the PRP's intent ("five user-facing flows captured as Gherkin") while honoring the BDD principle that every step should map to executable code.

`heartbeat_and_timeout` is implemented as `session_heartbeat.feature`; the timeout-threshold portion is skill-level and deferred (the heartbeat *parsing* of an output file is testable via `session.py heartbeat`, the threshold *transitions* are not).

`plan_mode_autodecompose.feature` is filed as **deferred follow-on** to be implemented when:
- A skill-level BDD harness exists (could be a future PRP), OR
- The auto-decompose logic moves into `scripts/` as a callable function (current SKILL.md design has it inside Claude Code's reasoning, not callable)

---

## Implementation Plan

Eight file changes (mostly new), one commit:

1. **`Makefile`** — extend `setup:` to install `pytest-bdd>=7,<8` alongside `pytest pytest-cov coverage[toml] ruff`. (Already applied in the working tree as part of pre-review scaffolding.)

2. **`tests/test_bdd_scenarios.py`** (new) — single-file BDD module containing both step definitions (using `@given`/`@when`/`@then` decorators) and the `scenarios(...)` collector call that binds every `.feature` in `tests/features/`. Reuses `tmp_path`, `monkeypatch`, and JSON fixture helpers borrowed from `test_session.py`. Per the file-structure deviation above, this replaces `tests/step_defs/conftest.py` + `tests/step_defs/common_steps.py` from the parent PRP.

3. **`tests/features/__init__.py`** (new) — empty placeholder so the directory is a Python package. (Already applied in the working tree.)

4. **`tests/features/session_lifecycle.feature`** (new — replaces `dispatch_single.feature`) — session.py CRUD flow:
   ```gherkin
   Scenario: Writing a session entry persists provider key, session id, and task summary
   Scenario: Clearing a session entry removes it but preserves siblings
   ```

5. **`tests/features/review_preset_fanout.feature`** (new) — three of the four cases from PR #42 expressed as a Scenario Outline (cases A/B/C — varying optional provider state); case D (broken required provider) split into a separate Scenario because its shape differs:
   ```gherkin
   Scenario Outline: Optional provider preflight boundary
     Given required provider "glm" with CLI "/bin/sh"
     And the preset "p" has optional provider "codex" with CLI "<optional_cli>"
     When I resolve preset "p" against the config
     And I run preflight on the resolved fan-out
     Then the fan-out is "<expected_fanout>"
     And preflight overall ok is "<preflight_ok>"

     Examples:
       | optional_cli | expected_fanout | preflight_ok |
       | (no config)  | glm             | true         |
       | /no/such/bin | glm,codex       | false        |
       | /bin/sh      | glm,codex       | true         |

   Scenario: Required provider with broken CLI fails preflight
     Given required provider "glm" with CLI "/no/such/bin"
     And the preset "p" has no optional providers
     When I resolve preset "p" against the config
     And I run preflight on the resolved fan-out
     Then preflight overall ok is "false"
   ```

6. **`tests/features/provider_discovery.feature`** (new — replaces `plan_mode_autodecompose.feature` per the deviation above):
   ```gherkin
   Scenario: A provider with both config entry and agent file shows as usable
   Scenario: A provider with config but no agent file shows as unregistered (missing agent file)
   Scenario: A provider with agent file but no config shows as unregistered (missing config)
   ```

7. **`tests/features/session_heartbeat.feature`** (new — narrowed from `heartbeat_and_timeout.feature`):
   ```gherkin
   Scenario: Heartbeat against an empty output file reports starting state
   Scenario: Heartbeat against an output file with assistant lines reports the last tool use
   ```

8. **`tests/features/install_atomic_rollback.feature`** (new):
   ```gherkin
   Scenario: install.py register followed by unregister removes the provider config entry
   Scenario: install.py unregister on a provider that doesn't exist is a no-op
   ```

Plus `rules/TRN-0000-REF-Document-Index.md` regenerated by `af index` post-implementation (not counted in the eight above — it's tooling output).

---

## Test / BDD / Coverage Expectations

- `pytest --collect-only tests/test_bdd_scenarios.py` shows non-zero collected items (≥ 9 — five base scenarios with at least one outline expanding to 4 rows means total scenario count ≥ 9).
- `make test` total grows from 141 pytest cases to ≥ 150 with the new scenarios green.
- Coverage of `scripts/session.py`, `scripts/install.py`, `scripts/discover.py`, and `scripts/codex.py:resolve_preset_providers` rises by 1–3 pt on the most-covered (since BDD scenarios drive real CLI invocations).
- TOTAL coverage stays ≥ 80% (currently 83%; safe headroom).

---

## Acceptance

- `make test` on `main` post-merge runs the new BDD scenarios alongside the existing 141 pytest cases.
- `pytest --collect-only tests/test_bdd_scenarios.py` shows ≥ 9 collected items.
- All five `.feature` files have at least one `@scenario`-bound test case.
- `make coverage` continues to report ≥ 80% TOTAL.
- New CI workflow (slice B) keeps both Linux + macOS legs green on this PR.
- `af validate --root .` reports 0 issues.

---

## Validation Commands

The canonical entry point is `make test` (which runs `pytest tests/ -v`); the BDD-specific commands below are evidence steps to confirm the collector binds non-zero scenarios, not separate gates.

```bash
make verify-built          # passes
make test                  # 141 + 113 + 105 + 10 + 2 + ≥9 BDD scenarios PASS
make coverage              # TOTAL ≥ 80% (no significant change expected vs slice B)
make lint                  # ruff clean
af validate --root .       # 0 issues

# BDD evidence (run as part of pre-commit verification, not as separate gates):
.venv/bin/pytest --collect-only tests/test_bdd_scenarios.py
# expected: ≥ 9 items collected (5 base scenarios + outline rows)
```

Executed locally on `codex/trn-2024-bdd`:

```
$ .venv/bin/pytest --collect-only tests/test_bdd_scenarios.py
13 tests collected in 0.01s

$ make test
... existing 141 + 113 + 105 + 10 + 2 PASS, plus 13 new BDD scenarios PASS ...

$ make coverage
TOTAL  1521  262  83%
(scripts/discover.py rose 88% → 89% as the BDD scenarios drive previously
 untested code paths in the discover.list CLI handler)

$ make lint
All checks passed!  21 files already formatted

$ af validate --root .
105 documents checked, 0 issues found.
```

Scenario count breakdown:
- session_lifecycle: 2 scenarios
- review_preset_fanout: 1 outline expanded to 3 rows + 1 standalone = 4 scenarios
- provider_discovery: 3 scenarios
- session_heartbeat: 2 scenarios
- install_atomic_rollback: 2 scenarios
- TOTAL: 13 collected pytest items.

---

## Out of Scope

- `plan_mode_autodecompose.feature` — deferred until skill-level BDD harness or auto-decompose moves to `scripts/`.
- Timeout-threshold transitions in `heartbeat_and_timeout` — skill-level proactive triggering, not testable from pytest.
- Migrating existing unit tests to BDD form. The unit tests stay; BDD adds a parallel narrative layer.
- Expanding mock posture in `test_codex_review_dispatch.py`. BDD reuses existing fixtures, no new mock infrastructure.
- pytest-bdd 8.x adoption (their step-def API changed; pin to 7.x for now).
- BDD scenarios that drive `/trinity` Claude Code slash commands directly (no harness for that today).

---

## Authority

This CHG is subordinate to TRN-2021-PLN §4 (slice C definition). Operator defaults from TRN-2021-PLN §2 apply: branch `codex/trn-2024-bdd`, identity `ryosaeba1985`, plan-review per slice skipped, code-review per slice skipped (Codex bot is the gate).

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft of slice C delivery contract; documented PRP deviation (`plan_mode_autodecompose` deferred, `provider_discovery` substituted) | Claude Opus 4.7 |
| 2026-05-07 | Trinity panel plan-review (glm PASS, deepseek FAIL with 2 BLOCKING + 1 HIGH + 3 lower findings, gemini timeout). Adopted: B1+B2+M4 by single-file consolidation (drop `tests/step_defs/`, put scenarios + step defs in `tests/test_bdd_scenarios.py`), H3 by writing full Given/When/Then for the Scenario Outline + separate Scenario for case D, L5 by preferring `make test` over direct pytest invocations, glm coverage advisory by tempering the +1–3pt estimate to +0–1pt. Status: Proposed → Approved. Pre-review scaffolding (Makefile pytest-bdd dep, empty features/__init__.py) acknowledged as proposal-time validation aid, not premature implementation. | Claude Opus 4.7 |
| 2026-05-07 | PR #46 round 1 macOS CI failure — `test_review_sigint_writes_incomplete_json_and_cleans_up` (pre-existing, last touched in TRN-2019/a2a0f10) flaked on macOS-latest under `make coverage`. Root cause: slice B's coverage shim activates coverage in every Python child via sitecustomize, adding startup+exit overhead to the glm/deepseek synthetic provider scripts; on slower macOS runners this shifts the timing relationship enough that glm's exit hadn't propagated to codex.py's running-providers tracker when the test sent SIGINT. Latent race exposed by slice B's CI workflow now running the test cross-platform. Minimal fix: 0.5s settle delay between `wait_until_exists(glm_done)` and `proc.send_signal(SIGINT)`. Documented inline. Verified locally with `coverage run -m pytest`. Slight scope expansion of slice C; alternative (file as TRN-2025 follow-on) rejected because slice C's CI workflow is what surfaces the flake — fixing it here closes the loop. | Claude Opus 4.7 |
| 2026-05-07 | PR #46 round 2 P1 from Codex bot — `.github/workflows/release.yml` Test step installed only `pytest ruff` directly (separate from `make setup`), so slice C's top-level `from pytest_bdd import scenarios` in `tests/test_bdd_scenarios.py` would have failed the next release with `ModuleNotFoundError: pytest_bdd`. Slice B's `coverage[toml]` was silently absent too (sitecustomize would noisily fail to import coverage). Structural fix: replace the manual `pip install pytest ruff` block with `make setup`, making `make setup` the single source of truth for dev deps. Closes the cross-workflow drift class entirely; the comment in release.yml flags the lesson for future contributors. | Claude Opus 4.7 |
| 2026-05-08 | Status reconciled to Completed; merged in PR #46 at `dde49b7` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

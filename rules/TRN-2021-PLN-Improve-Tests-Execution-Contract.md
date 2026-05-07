# PLN-2021: Improve Tests — Execution Contract

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-07
**Last reviewed:** 2026-05-07
**Status:** Active
**Reviewed by:** Trinity panel review on 2026-05-07 (`.trinity/reviews/20260507-180721-rules/`): glm PASS, deepseek PASS, gemini timeout (no opinion). 2-of-3 PASS verdict; advisory findings F4, F5 (and slice-A scope expansion for F2/F3) adopted before activation.
**Related:** TRN-2020 (parent PRP), TRN-2022, TRN-2023, TRN-2024, COR-1614, COR-1616, COR-1612, COR-1615

---

## What Is It?

The COR-1614 multi-phase execution contract authorizing continuous delivery of three test-improvement slices (A: install-sh wiring, B: coverage tooling, C: pytest-bdd layer) under one approved plan. Subordinate to TRN-2020-PRP. Each slice ships as its own COR-1616 run with its own CHG and PR.

The contract makes the operator defaults explicit so the executor does not re-ask settled questions between slices, while still respecting hard stop conditions.

---

## Why

Three slices delivered serially without a contract risk drifting from the agreed scope, mixing review processes, or leaking ad-hoc decisions into PR text. With the contract, reviewers have a stable artifact to check whether each slice stayed inside the approved plan, and the executor has an unambiguous list of things it may do without re-asking and things that require an immediate stop-and-confirm.

---

## 1. Authority Documents

- **TRN-2020-PRP-Improve-Tests** (parent PRP) — defines the three slices, scope, and acceptance.
- **GitHub issue #41** — original tracker; the PRP body is the consolidated plan from #41.
- **`make test`, `make lint`, `af validate --root .`** — non-negotiable validation gates inherited from project routing (TRN-1000) and TRN-1001/TRN-1002.
- **`CLAUDE.md` user identity rule** — `gh` writes must publish as `ryosaeba1985`.

This contract cannot override any of the above. If a slice would require modifying the PRP scope, the executor stops and re-asks.

---

## 2. Operator Defaults and Permissions

The executor may take these actions without re-asking while this contract is active:

- **Branch naming**: `codex/trn-2022-wire-install-sh`, `codex/trn-2023-coverage`, `codex/trn-2024-bdd`.
- **GitHub identity**: `ryosaeba1985` for all `gh`-mediated writes (PR open, comments, replies). Push target: `fork` remote (`git@github.com:ryosaeba1985/trinity.git`). PR base: `frankyxhl/trinity:main`.
- **Plan-review per slice**: skipped — the parent PRP plan-review (which gates this contract) covers strategy. Per-slice plan-review is delegated to the PR review loop. (Operator decision: 2026-05-07.)
- **Code-review preset per slice**: not run locally — same delegation. The Codex GitHub App bot review on each PR is the gate.
- **PR review-loop**: COR-1612 §6 self-poll, cap-10, 3–5 min between polls. Same shape as PR #42.
- **After each merge**: `git checkout main && git pull origin main`, delete merged branch locally + on `fork`, run COR-1614 §10 re-check that the next slice still matches this contract.
- **CHG drafting**: each slice's CHG is drafted before the PR is opened, with the same shape as TRN-2011 / TRN-2014 / TRN-2017.
- **Validation evidence capture**: paste the executed `make test`, `make lint`, `af validate` output snippets into the CHG before opening the PR.
- **Privacy hygiene**: no absolute paths, no `~/.secrets/*` content, no shell history, no transcript snippets in PR/CHG bodies.

---

## 3. Non-Negotiable Behavior

The executor must NOT, under any circumstances within this contract:

- Force-push to any branch other than its own fork branch under `codex/trn-2022-*`, `codex/trn-2023-*`, `codex/trn-2024-*`.
- Push tags. (Path A release workflow, not this contract, owns tag creation.)
- Modify `VERSION`, `scripts/__init__.py:__version__`, `SKILL.md:REQUIRED_VERSION`, or `plugins/trinity/.codex-plugin/plugin.json:version` — those belong to the release loop, not this test-improvement loop.
- Modify any file under `rules/` ending in `-PRP-*.md` other than the four it owns (TRN-2020 parent, TRN-2022/2023/2024 children). No edits to other contributors' PRPs.
- Modify `COR-*.md`, `CLD-*.md`, or any document outside `rules/TRN-*.md` and the in-scope source/test files for each slice.
- Skip `make verify-built` if `providers/_base/` partials change. Generated `providers/*.md` must always match.
- Bundle two slices into one PR. Each slice ships independently.
- Add new dependencies beyond `pytest-cov`, `coverage[toml]`, `pytest-bdd` to `make setup`.
- Refactor tests to import-then-call instead of `subprocess.run`. The subprocess pattern preserves v2.0.0 incident-class regression evidence; only the coverage shim changes that posture, not the tests themselves.
- Treat the Codex bot's "queued" or "in-progress" reaction as approval. Per COR-1615, only a clean review counts.

---

## 4. Execution Slices

### Slice A — TRN-2022-CHG-Wire-Install-Sh-Test-Into-Make-Test

- **Scope**: (1) append `bash tests/test_install_sh.sh` to the `test:` target in `Makefile`, after `test_release_workflow.sh`; (2) update `TRN-1800-REF-Evolution-Philosophy.md` §Behavior Baseline to reflect current truth — pytest `63+ cases` is now `141+ cases`, and the `test_install_sh.sh` mention becomes accurate once slice A merges (panel review F2 + F3, deepseek 2026-05-07).
- **Out of scope**: any change to `test_install_sh.sh` itself; port reassignment; CI workflow changes; rewriting other parts of TRN-1800.
- **Tests**: existing `tests/test_install_sh.sh` runs as part of `make test` and produces 10 PASS markers.
- **Validation**: `make verify-built && make test && make lint && af validate --root .`.
- **Exit condition**: PR merged; `make test` on `main` post-merge invokes `test_install_sh.sh` and TRN-1800:22 baseline matches the actual gate set.

### Slice B — TRN-2023-CHG-Add-Coverage-Tooling

- **Scope**: extend `make setup` with `pytest-cov` + `coverage[toml]`; add `.coveragerc`, `tests/sitecustomize_shim.py`, and `tests/conftest.py` extension; add `make coverage` target with `--fail-under=80`. Optional: `.github/workflows/test.yml` for PR-triggered CI.
- **Out of scope**: codecov / coveralls remote upload; mutation testing; property-based testing; refactoring tests away from `subprocess.run`.
- **Tests**: `make coverage` exits 0 with TOTAL ≥ 80% and per-module numbers matching the baseline ±2%.
- **Validation**: `make verify-built && make test && make lint && af validate --root .` plus `make coverage`.
- **Exit condition**: PR merged; `make coverage` runs on `main` and reports ≥ 80%. CI workflow either merged in this slice or explicitly deferred to a follow-on slice if reviewers push back.

### Slice C — TRN-2024-CHG-Add-Pytest-BDD-Scenario-Layer

- **Scope**: extend `make setup` with `pytest-bdd`; create `tests/features/` with five `.feature` files; create `tests/step_defs/` with shared step implementations; create at least one collector test module (e.g. `tests/test_bdd_scenarios.py` with `from pytest_bdd import scenarios; scenarios("features/")`) so pytest binds the `.feature` files at collection time — pytest-bdd does not auto-collect raw `.feature` files. Integrate with existing `pytest tests/` invocation.
- **Out of scope**: migrating existing unit tests to BDD; expanding mock posture in `test_codex_review_dispatch.py`; adding additional scenarios beyond the five seed flows.
- **Tests**: `pytest tests/ -v -k bdd` (or equivalent) runs 5+ scenarios, all green; `make test` total grows to ≈ 150 cases with no regressions in existing pytest cases. Verification step before commit must include `pytest --collect-only tests/` to confirm the BDD collector binds non-zero scenarios.
- **Validation**: `make verify-built && make test && make lint && af validate --root .`; pre-commit also `pytest --collect-only tests/` showing each `.feature` scenario as a collected item under the BDD collector module.
- **Exit condition**: PR merged; `make test` on `main` runs the new BDD scenarios alongside the existing 141 pytest cases, with `pytest --collect-only` evidence proving the scenarios actually bind to the test runner.

---

## 5. Validation Matrix

| Gate | Slice A | Slice B | Slice C |
|------|---------|---------|---------|
| `make verify-built` | ✓ | ✓ | ✓ |
| `make test` (existing 141 + 220 shell) | ✓ | ✓ | ✓ |
| `make lint` (ruff check + format) | ✓ | ✓ | ✓ |
| `af validate --root .` (0 issues) | ✓ | ✓ | ✓ |
| `make coverage` ≥ 80% | n/a | ✓ (slice deliverable) | ✓ (must not regress) |
| `pytest tests/features/ -v` ≥ 5 scenarios green | n/a | n/a | ✓ (slice deliverable) |
| `tests/test_install_sh.sh` invoked by `make test` | ✓ (slice deliverable) | ✓ (must not regress) | ✓ (must not regress) |

**Deferred**: codecov upload, mutation testing, property-based testing, shell-test coverage. Each becomes its own follow-on slice or PRP if wanted.

---

## 6. External Review Policy

- **Local plan-review (COR-1602)**: only the parent PRP+PLN package goes through Trinity multi-model panel review with the `review` preset (`glm` + `gemini` + `deepseek`, optional `codex` + `claude-code`). Per-slice CHG plan-review is skipped per operator default.
- **Local code-review per slice**: skipped per operator default. Codex GitHub App bot review on each PR is the gate.
- **PR review bot loop (COR-1615 + COR-1612)**: every PR enters the §6 self-poll loop with cap-10. The same loop ran successfully on PR #42 (4 rounds: P1, P2, idle, P3, then "Breezy!" all-clear).
- **Review caps**:
  - PR review loop hits cap-10 → stop and report (per COR-1612 §6 stopping condition #4).
  - Reviewer pushback that conflicts with operator defaults → stop and re-ask.
  - Trinity panel review on PRP+PLN returns blocker findings → fix in TRN-2020/2021, re-review, do not start slice A until blockers clear.

---

## 7. Branch, PR, and Merge Policy

- **Branch source**: `main` at the start of each slice. No slice may branch from another slice's branch — they are independent.
- **Branch naming**: `codex/trn-2022-wire-install-sh`, `codex/trn-2023-coverage`, `codex/trn-2024-bdd`.
- **Draft state**: PRs open as `ready for review`, not draft (matches PR #42 convention).
- **Commit scope**: one commit per slice for the implementation; additional commits per round only if PR review surfaces fixes (matches the `4da1729` / `376914a` / `23ddf21` pattern from PR #42).
- **Merge method**: maintainer's choice (squash / merge commit / rebase) — the PR opener does not specify.
- **Pull-and-continue**: after each merge, `git checkout main && git pull origin main`, then `git branch -d codex/trn-2022-...` and `git push fork --delete codex/trn-2022-...`. Verify `git status` clean before opening the next slice.
- **Rollback**: revert the merge commit on `main` if a regression surfaces post-merge. The CHG and PRP stay; status moves to `Reverted` with the reason.

---

## 8. Runtime-Data and Privacy Rules

- No `~/.secrets/*` content in any committed file or PR/CHG body.
- No transcripts, terminal scrollback, or chat history in committed files or PR text.
- No absolute paths under `/Users/`, `/home/`, or `/private/var/...` in any committed file. Use `~/`, `$HOME`, or relative paths.
- No private hostnames or internal IPs.
- No GitHub tokens, API keys, or environment-derived secrets in PR text.
- The `tmp/` directory remains untracked (it is the user's scratch space); no slice in this contract commits content from `tmp/` or modifies `.gitignore` to track it.

---

## 9. Stop Conditions

The executor stops and reports instead of continuing when:

1. A slice would violate any item in §3 (Non-Negotiable Behavior).
2. Trinity panel review on the PRP+PLN returns at least one ≥ 9.0 blocker finding (per COR-1602 strict-mode threshold).
3. A PR review loop hits the COR-1612 §6 cap-10 fail-safe.
4. A required validation gate (`make test`, `make lint`, `af validate`, `make coverage`) fails for reasons that cannot be isolated within the slice's scope.
5. A slice's PR receives a CHANGES_REQUESTED review from `frankyxhl` (the maintainer) or any human reviewer with conflicting direction.
6. Continuing would require any destructive git operation outside the executor's own fork branches.
7. The next slice is materially larger or riskier than the parent PRP described — pause and re-write the CHG before proceeding.
8. Slice C reviewers argue BDD adds insufficient value to justify a new dependency — pause and re-discuss with the operator. Possible exit: drop slice C, close TRN-2024-CHG as `Rejected by review`, mark slice C as deferred in the closeout (§10).
9. Slice B reviewers reject the optional `.github/workflows/test.yml` proposal — defer to a follow-on slice; do not block slice B v1 on the optional CI piece.
10. Any operator instruction during execution that materially changes the contract — pause, update the contract, re-confirm with the operator before continuing.

---

## 10. Retention and Closeout

- This PLN's `## Change History` records every contract amendment. Initial draft and any re-scoping after Trinity panel review both belong here.
- Each slice's CHG records its own merge SHA, deviation list (if any), and post-merge regression evidence.
- The parent PRP (TRN-2020) updates its `Status:` field from `Draft` → `Approved` after Trinity panel review passes, and from `Approved` → `Done` after all three slices merge.
- This PLN updates its `Status:` field similarly: `Draft` → `Active` once review passes, `Active` → `Closed` after the closeout.
- GitHub issue #41 closes with links to PR-A, PR-B, PR-C, TRN-2020, and TRN-2021.
- Deferred items (e.g. codecov upload, mutation testing, additional BDD scenarios beyond the five seeds) are listed in the closeout with proposed follow-on PRPs/CHGs.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft of the COR-1614 execution contract subordinate to TRN-2020-PRP | Claude Opus 4.7 |
| 2026-05-07 | Trinity panel plan-review (glm PASS / deepseek PASS / gemini timeout). Adopted advisory F4 (generic "the executor" instead of named model), F5 (drop specific tmp/ filename). Folded F2 + F3 into slice A scope (TRN-1800:22 baseline correction). F1 (af-index title formatting) skipped — tool behavior. F6 (collapsed change history) skipped — `af index` autogenerates. F7 (forward refs) skipped — correct PRP pattern. glm "220 shell" finding rebutted — count is correct (113+105+2+10≈230). Status: Draft → Active. | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 4 P2 from Codex bot: §4 slice C scope corrected. pytest-bdd does NOT auto-collect `.feature` files — a Python collector module (`tests/test_bdd_scenarios.py` with `scenarios("features/")` or per-scenario `@scenario` decorators) is required for pytest to bind features. Validation also expanded to require `pytest --collect-only` evidence that scenarios actually bind. | Claude Opus 4.7 |

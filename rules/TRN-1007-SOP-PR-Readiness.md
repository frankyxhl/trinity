# SOP-1007: PR Readiness Gate — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Active

---

## What Is It?

A checklist the author runs **before opening a PR**. Closes a documented gap from PR #61 (TRN-2026 coverage shim) and PR #64 (TRN-3020 provider registry): both passed Trinity panel and bot review and merged cleanly, but `CHANGELOG.md` was not updated and PR #64 didn't refresh `README.md` for the new install-time registry probe.

Companion to:
- **COR-1612** — PR review-comment loop (post-open bot finding handling)
- **COR-1614** — multi-phase execution contract (full lifecycle)
- **COR-1616** — contract-first delivery (CHG → plan-review → implement → code-review → PR → bot loop)
- **TRN-1001** (Test), **TRN-1002** (Lint), **TRN-1003** (Version Bump), **TRN-1004** (Release)

This SOP doesn't replace any of the above — it adds the "before-open" checkpoint they all assume the author has already run.

---

## Why

Trinity ships moderate-frequency CHGs. Each one passes 4-provider panel review and a Codex-bot review on PR open. None of those gates check whether `README.md` mentions the new behavior or whether `CHANGELOG.md` has an unreleased-section entry. Two recent merges drifted documentation in exactly that way. A short pre-open verification scan prevents the drift; without it, future contributors (or future-you) read stale docs and don't know about merged behavior.

---

## When to Use

- **Before opening any PR** with substantive changes (code / config / install flow / SOP)
- **Referenced from each new CHG's "Acceptance Criteria"** by default; plan-review can verify the CHG covers the relevant items

## When NOT to Use

- Trivial typo fixes / single-character edits — use ad-hoc judgment
- Bot-generated PRs (release tagger, dependabot)
- Hotfix PRs where time-to-merge dominates (note skips in the PR body, follow up after)

---

## Prerequisites

- Branch is on the local clone, ready to push
- `.venv` exists (`make setup` if not)
- `gh auth status` resolves to the right identity

---

## Steps

Walk through these at "ready to open PR" time. For each item below: ✅ done, ❌ skipped with rationale, or ➖ not applicable.

1. **Docs sync** — see §1 below
2. **Tests + verification** — see §2
3. **Drift coverage** — see §3
4. **Methodology** — see §4
5. **Manual smoke** — see §5
6. **Identity** — see §6
7. **Branch hygiene** — see §7

PASS: every applicable item is ✅; skipped items have a one-line rationale; the rationale appears in the PR body or the CHG's Acceptance Criteria table.

---

## Gate Checklist Detail

### §1. Docs sync

- **`README.md`** — updated if user-visible install / config / command behavior changed
  - Examples warranting a README touch: new subcommand, changed install flow, new env-var, new flag, removed feature, changed default behavior
  - Skip rationale if N/A: "internal refactor only" / "test-only change"
- **`CHANGELOG.md`** — has an entry under `## [Unreleased]` naming the user-facing change
  - Match existing entry shape (see CHANGELOG.md `## [3.2.0]` for the canonical format with `### Added` / `### Changed` / `### Fixed` groupings)
  - **Substantive `rules/*` changes** (new SOP, CHG/REF that introduces material content, amended workflow) **MUST have a CHANGELOG entry** — they shape how Trinity is operated and contributed to. The path-filter in `.github/workflows/test.yml` skips CI for `rules/**` and `*.md`, so there is no later gate.
  - Skip rationale if N/A: "trivial docs edit (typo / formatting / one-line clarification)" / "test-only change" / "internal-only constant rename with no user-facing behavior change"
- **`SKILL.md` / `providers/*.md` / `providers/*.delta.md`** — updated if provider behavior or CLI registration changed. **Complementary** to TRN-3020 §A3.f / §A3.g drift tests: those tests verify CLI-string consistency byte-for-byte; this SOP item catches semantic prose drift (e.g., a paragraph describing the OLD behavior the test can't see).

### §2. Tests + verification

- **`make test`** — passes locally
- **`make lint`** — passes locally for the files YOU touched (pre-existing lint issues elsewhere are out of scope per recent CHGs)
- **`make coverage`** — TOTAL ≥ 80%, no per-module regression vs main
- **`af validate --root .`** — 0 issues
- **`make verify-built`** — passes (if touching `providers/_base/*` or generators)

### §3. Drift coverage

- **Registry drift tests pass** if touching `providers/registry.json`, `.agents/trinity.codex.json`, or any provider `cli` string: `pytest tests/test_provider_registry.py` (this is a fast-path pre-check; `make test` in §2 is the authoritative gate)
- **Test fixtures realigned** if changing provider CLIs:
  - `tests/test_codex_adapter.py` glm fixture matches registry
  - `tests/test_install_sh.sh` and `tests/test_build_providers.sh` literal CLI strings match registry

### §4. Methodology (PR #60 / #61 / #64-derived 6-step rule)

For new code surfaces, verify each step in the CHG body OR a PR-body checklist. Each item is "verified" when the named artifact below exists / passes:

1. **Trace caller flows** of any function the diff consumes data from
   - *Verify*: name at least one concrete caller function and the data it passes; cite file:line.
2. **Read writer schemas** of any data the diff parses
   - *Verify*: cite the writer's file:line and the field shape (or stdlib doc if external); show a test asserting the contract.
3. **Compare to sibling registration sites** for any new subcommand / feature / config key
   - *Verify*: list the sibling sites and confirm they're either updated or explicitly out-of-scope (e.g., reserved-words sets, config validators, help text registries).
4. **When fixing value-handling in helper X**, grep for the same hard-code/pattern in sibling helpers consuming the same data source
   - *Verify*: paste the `grep` command run; cite each hit either fixed or noted N/A.
5. **Comments asserting invariants** are paired with tests
   - *Verify*: each invariant docstring cites its corresponding test by name.
6. **Backwards-compat against older-tag matrix** verified — especially install / runtime spawn flows (PR #64 R1 lesson: piping `main`'s `install.sh` with `TRINITY_VERSION=<older-tag>` must still produce a clean failure or workaround)
   - *Verify*: state which version-pin / older-tag scenarios were checked and the expected behavior in each.

### §5. Manual smoke

- **Install / UI / runtime-spawn changes documented in the PR body** — include the actual command run and expected output, not just "verified locally"
- **Reproducer for any user-facing behavior change** — small command snippet showing pre/post
- **SKILL.md regression prompts** — run `samples/regression-prompts.md` manually when the PR touches SKILL.md dispatch syntax, parse order, reserved words, preset definitions, heartbeat shape, or error handling — or the other dispatcher surfaces the prompt set names: `providers/_base/` (provider discovery / agent resolution) and `scripts/session.py` / `scripts/session_path.py` (session keys, output capture, heartbeat mechanics). Pass each prompt's pass criteria before opening the PR.

### §6. Identity (per CLD `CLAUDE.md` global rule)

- **`gh auth status`** shows `ryosaeba1985` for any GitHub-visible writes (PR open, issue create, PR comment, label apply, review comment, draft/ready transition)

### §7. Branch hygiene

- Branch is **rebased on `origin/main`** (no merge conflicts; force-push with `--force-with-lease` is acceptable post-rebase)
- Branch name follows **`codex/<acid-shortname>`** pattern (e.g., `codex/trn-3023-env-sanitization`)
- Force-push only for rebase / squash; never to overwrite peer review history

---

## How CHGs Should Reference This SOP

Each new CHG's "Acceptance Criteria" table should include line items mapping to this SOP. Suggested mapping (skip rows that don't apply, with rationale):

| CHG AC item | TRN-1007 § |
|----|----|
| `make test`, `make lint`, `make coverage` ≥ 80%, `af validate` all pass | §2 |
| `README.md` updated to mention new behavior | §1 |
| `CHANGELOG.md` `[Unreleased]` entry added | §1 |
| Drift tests pass | §3 |
| 6-step methodology verified | §4 |
| Manual smoke documented in PR body | §5 |

If a CHG explicitly waives an item, document the rationale in one line (e.g., "test-only change; N/A for §1 README").

---

## Examples

### Good PR body excerpt (per this SOP)

```markdown
## Acceptance (TRN-1007)

- [x] §1 README: added "Provider Health" section documenting `trinity status --latest`
- [x] §1 CHANGELOG: `## [Unreleased]` gained "Added: trinity status command (TRN-2028)"
- [x] §2 make test (215 passed), make lint (clean), make coverage 83%, af validate (110/0)
- [x] §3 N/A — no provider CLI changes
- [x] §4 6-step rule: caller flows traced through cmd_review→cmd_status; ...
- [x] §5 Manual smoke: `trinity status --latest` output captured at <link>
- [x] §6 gh auth status → ryosaeba1985
- [x] §7 rebased on origin/main (commit f343104)
```

### Skip with rationale

```markdown
- [➖] §1 README: N/A — internal helper refactor, no user-facing behavior change
- [➖] §1 CHANGELOG: N/A — typo fixes in three SOP docs, no material change to gate behavior
```

---

## Companion follow-ups (separate issues, not this SOP)

- **Retroactive CHANGELOG backfill** for PR #61 (TRN-2026 coverage shim) and PR #64 (TRN-3020 provider registry) — file as a separate small PR
- **`.github/PULL_REQUEST_TEMPLATE.md`** that points to this SOP — file as a separate issue if useful

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per issue #65; closes the documentation-drift gap PR #61 + PR #64 surfaced | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel review (3 of 4 — codex review hung after ~30 min, skipped per operator decision; same precedent as gemini-skipped on TRN-3020): glm 9.25 PASS, deepseek 9.2 PASS, gemini 9.5 PASS (mean 9.32). Adopted convergent advisories: (1) drop "30-second checklist" claim — replaced with "short pre-open verification scan" per all 3 reviewers; (2) add per-item "how to verify" hints under §4 6-step rule per deepseek A2; (3) document §1 provider-doc check as complementary (semantic) not redundant to TRN-3020 §A3.f/g drift tests (CLI-string) per glm A3; (4) clarify §3 fast-path framing per deepseek; (5) verified COR-1612/1614/1616 cross-refs exist via `af read` (PKG-layer SOPs in fx-alfred). Deferred: TRN-3029-REF extraction of 6-step rule (per glm A2 + deepseek: appropriate at 10+ citations or subsection growth, not yet); retroactive CHANGELOG backfill for PR #61/#64/#66 (separate small PR per "Companion follow-ups"). | Claude Opus 4.7 |
| 2026-05-08 | PR #67 round 1 from Codex GitHub App bot — caught a **self-contradicting waiver** in the §1 CHANGELOG skip rationale. The original text "Skip rationale if N/A: 'rules/* docs only'" was too broad: substantive `rules/*` changes (new SOPs, material CHG/REF additions) shape how Trinity is operated and absolutely DO warrant CHANGELOG entries. Worse, `.github/workflows/test.yml`'s `paths-ignore` skips CI for `rules/**` and `*.md`, so there's no later gate. This very PR dogfooded a CHANGELOG entry for the SOP — but the SOP's waiver text would have permitted skipping it. **Fix**: narrow §1 CHANGELOG waiver to "trivial docs edit (typo / formatting / one-line clarification)" / "test-only change" / "internal-only constant rename with no user-facing behavior change". Substantive `rules/*` changes now MUST have a CHANGELOG entry. Same fix applied to the "Skip with rationale" example block. The 3-of-4 panel didn't catch this because all 3 reviewers focused on whether the SOP was internally coherent and well-scoped; the bot caught the self-contradicting case where the SOP's own change would have been allowed to skip the very gate it was being added to enforce. **Methodology gap logged**: future SOP/CHG dogfood pass should explicitly check whether the new SOP, applied to itself, would have caught its own omissions. | Claude Opus 4.7 |

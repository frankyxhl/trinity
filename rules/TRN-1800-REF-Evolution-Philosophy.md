# REF-1800: Evolution Philosophy

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-04-26
**Last reviewed:** 2026-04-26
**Status:** Active
**Inherits from:** COR-1800 (full-replace per table; unspecified tables inherit COR defaults)

---

## What Is It?

PRJ-layer override of COR-1800 for the `trinity` repo. Trinity is a Python skill package with concrete shipping behaviour: `pytest` tests, `make verify-built` build determinism, `make lint`, `install.sh` / `make install` produce a working trinity on a fresh user's machine. Default COR weights are reasonable but miss the load-bearing properties specific to trinity — cross-platform parity (macOS vs Linux), generated-vs-source provider files (TRN-2004), provider parity between `Makefile` and `install.sh`, and the share-readiness invariant (no `.zshrc` dependency, TRN-2009). This REF redefines weights, signal sources, and behaviour baseline accordingly.

---

## Behavior Baseline

`Fitness = same behavior / (LoC + doc words)` requires a "behavior" definition. For trinity:

- **Behavior** = the union of:
  1. `make test` is green (pytest 63+ cases, shell `tests/test_install_sh.sh` 10+ cases, `tests/test_release_workflow.sh` 53+ cases, `tests/test_build_providers.sh`)
  2. `make verify-built` is green (committed `providers/<name>.md` matches what `make build` would generate from `_base/*.md` + `<name>.delta.md`)
  3. `make lint` is green (ruff check + format)
  4. `install.sh` against a tmp `HOME` produces all 5 registered providers in `~/.claude/trinity.json` with absolute-path `cli` for the Anthropic-compat wrappers, and bin scripts present + executable
  5. Cross-platform CI (Linux runner via GitHub Actions release.yml) passes — local macOS pass alone is insufficient
  6. A representative dispatch sample produces a non-error response (e.g., `~/.claude/skills/trinity/bin/<provider> --version` returns claude's version string with the correct env injected)
- **Same behavior** = on a fixed regression set, the new code passes every gate above AND the dispatch sample produces an output a human reviewer rates ≥ the prior version.
- The dispatch sample lives in `samples/regression-dispatch.md` (created lazily — first evolve cycle that needs it creates it). When a sample case cannot be re-run (network-dependent provider call, transient quota issue), the baseline falls back to *PR diff + human review of the changed surface only* — no synthetic claim of equivalence.

---

## Override: Code Evolution Weights

Replaces COR-1800 default code weights in full. Sums to 100%.

| Dimension | Weight | Measures |
|-----------|--------|----------|
| Test coverage of changed surface | 30% | Every changed/added behaviour is asserted by a pytest case OR a shell-test case OR `make verify-built`. Bare config / docs changes are evaluated under the doc table instead. |
| Cross-platform parity | 20% | macOS-only test pass is INSUFFICIENT. Shell scripts assume neither BSD nor GNU exclusively (TRN-2008/9 lesson: `stat -f` vs `stat -c`; same trap class for `sed -i ''` vs `sed -i`, `readlink -f`, `date -d`, etc.). Bumps for this dimension: did the change introduce platform-conditional logic? Was the Linux path actually exercised by CI before merge? |
| Compression ratio | 20% | (chars deleted + chars merged) / (chars added). Net-negative or neutral preferred; net-positive must be justified by necessity (e.g., new tests, new SOP). |
| Scope restraint | 15% | Change touches one surface (one bin script / one provider .delta.md / one Makefile target / one SOP / one section of README). The `providers/_base/*` partial → 5-provider cascade counts as ONE surface (symmetric multi-file refactor). No cascade across surfaces in a single candidate. |
| Necessity | 15% | Concrete evidence: failing pytest, failing CI run, real install failure on a fresh user's machine, vendor doc change (e.g., new model ID). NOT "feels improvable." |

---

## Override: Document Evolution Weights

Replaces COR-1800 default doc weights in full. Sums to 100%.

| Dimension | Weight | Measures |
|-----------|--------|----------|
| Necessity | 25% | Evidence from session logs, repeated user corrections, validate failures, contributor confusion, `[Unreleased]` rot, or a misleading section that produced a bug (TRN-2008 lesson: README "Or install manually" missing bin script steps). |
| Generated-vs-source correctness | 25% | Edits to `providers/<name>.md` are rejected — must edit `<name>.delta.md` and run `make build` (TRN-2004). SOPs name the right surface. CHANGELOG `[Unreleased]` references real artefacts. |
| Atomicity | 15% | One SOP / one CLAUDE.md section / one README section = one thing. Multi-section rewrites split into N candidates. |
| Compression ratio | 15% | Same formula as code; documentation that grows must justify against deletions elsewhere. |
| Consistency | 10% | No conflict with COR PKG docs, other TRN docs, README, CHANGELOG, `Makefile`, `install.sh`. Pinned versions / model IDs match what's actually shipped. |
| Actionability | 10% | Includes shell commands, exact file paths, line numbers — not vague "be careful" guidance. |

---

## Override: Signal Sources

Replaces COR-1800 default signal table in full.

| Signal | Where to look | Cadence |
|--------|---------------|---------|
| Build drift | `make verify-built` | Per evolve cycle (mandatory) |
| Provider parity | `diff <(grep -A2 "register " Makefile) <(grep -A2 "register " install.sh)` — both must register the same 5 providers with the same `--cli` values | Per evolve cycle |
| Cross-platform shell traps | `grep -rnE "stat -[fc]\|sed -i ''\|readlink -f\|date -d " providers/bin/ scripts/ install.sh Makefile` — every hit is a candidate for the "did we test the other platform?" review | Per evolve cycle |
| Model-ID drift | `grep -E "ANTHROPIC_MODEL\|--model" providers/bin/* providers/*.delta.md install.sh Makefile` — compare against TRN-1006 example log and current vendor docs | Per evolve cycle |
| `install.sh` share-readiness | Run `install.sh` (or local `make install`) against `HOME=$(mktemp -d)`, then assert `~/.claude/trinity.json` has all 5 providers and bin scripts are executable | Per evolve cycle |
| CHANGELOG `[Unreleased]` lag | `git log $(git describe --tags --abbrev=0)..HEAD --oneline` — every behaviour-changing commit since last tag should map to a `[Unreleased]` entry | Continuous |
| SOP↔code drift | TRN-100x SOPs cite specific commands (`make test`, `make lint`, `make release-prep`); when those targets change, the SOP needs the same edit | Per evolve cycle |
| Test cross-coverage gaps | New code paths added without matching pytest case, especially platform-specific branches (`if [ "$(uname)" = "Darwin" ]`, BSD/GNU stat fallbacks, etc.) | Per change |
| `af validate` output | Structural issues in `rules/` PRJ docs (missing `Last updated` / `Last reviewed`, etc.). v2.0.0-era TRN-2004/5/6 still have this issue — flagged but un-fixed | Per evolve cycle |
| `[Unreleased]` rot | If `[Unreleased]` has entries older than 2 weeks AND no behaviour-changing commits since, signal for release-or-prune | Continuous |
| Repeated user corrections | Same user correction across recent sessions | Continuous (when noticed) |

---

## Inherited from COR-1800 (not overridden)

- Evolution cycle: Signal Collection → Candidate Generation → Evaluation → Implementation → Review → PR
- Thresholds: candidate discard < 7.0; review pass ≥ 9.0
- Guard rails: evolve process must not modify TRN-1800, TRN-1801, or COR-1800 itself; weight/threshold changes go through PRP/CHG, not the evolve loop
- Override contract semantics: full-replace per table

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-04-26 | Initial PRJ override of COR-1800 for the `trinity` repo. Mirrors the CLD-1800 shape used by `~/.claude/`; weights and signals customised for trinity's Python+shell+CI surface (cross-platform parity, generated-vs-source build, provider parity, share-readiness). | Claude Opus 4.7 |

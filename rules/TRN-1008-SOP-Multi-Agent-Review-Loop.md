# SOP-1008: Multi-Agent Review Loop

**Applies to:** Trinity project (`frankyxhl/trinity`) — drafted for trinity scope; intended for promotion to PKG/COR-1200 once stable
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Active
**Related:** TRN-1007 (PR readiness gate), TRN-1800 (evolution philosophy / weights), CLD-1802 (atomicity surface definition), COR-1612 / COR-1614 / COR-1616 (PR-loop SOPs the panel inherits from)

---

## What Is It?

The end-to-end loop a Claude orchestrator runs to ship a PR through a 4-provider review panel: pick the next issue, plan, dispatch a worker, panel-review the plan, implement, panel-review the code, iterate on bot/CI findings, hand off to the user for merge, then auto-pick the next issue. It captures three independent levers (auto-pick, dispatch heuristic, panel-review gate) plus the surrounding loop hygiene (branch base, identity, bot triage) in one place.

This SOP exists because the loop was being re-derived ad-hoc each session. Without it, three failure modes recur:

1. **Stale-branch base** — branching off a local `main` that lags `origin/main`, producing phantom-reference bugs (PR #68 lesson).
2. **Wrong dispatch lane** — orchestrator hand-edits 200-line refactors that should go to a worker, or dispatches a 2-line typo fix that round-trips through `droid exec` for no reason.
3. **Wrong gate semantics** — accepting a 3-of-4 PASS panel as "good enough" instead of holding the all-individual-≥9.0 line, then later discovering the dissenter caught a real bug.

---

## Why

Multi-agent review (panel of 4 providers per major change) catches classes of bugs single-reviewer flows miss — convergence across heterogeneous models is high-signal. But running it cleanly takes discipline: parallel dispatch, correct weights, honest gate enforcement. The loop also has a worker layer (orchestrator delegates implementation to a coding worker via `droid exec`) and an auto-pick layer (orchestrator picks the next issue without user input). Each is a non-trivial decision; documented together they form a coherent operating model.

This SOP is also the foundation for cross-project reuse — when promoted to COR-1200, it becomes the default orchestration shape for any repo with a multi-provider review setup.

---

## When to Use

- Substantive PRs that touch behaviour, schemas, or public surfaces.
- Any PR where a single-reviewer judgment call could be wrong (architecture, contract changes, security-adjacent code).
- Cross-cutting refactors (multi-file rename, API rename, lifting an abstraction).
- New CHGs / SOPs / PRPs.
- The first PR of a session (also re-pins branch base + identity even if you skip the panel).

## When NOT to Use

- One-line bug fixes with an obvious cause (typo, missing import, wrong constant). Direct edit, single-reviewer or self-review, ship.
- Pure documentation changes that don't touch CHGs / SOPs (README polish, CHANGELOG re-flow). Self-review is fine.
- Generated-file regeneration (`make build`, `af index`). The generator is the reviewer.
- Reverts of an already-reviewed change (the original PR carried the panel; a clean revert inherits the gate).

---

## Steps

The loop has 10 phases:

```
1. Auto-pick      ← user's auto-pick policy
2. Branch hygiene ← pin origin/main, identity gate
3. Plan           ← draft CHG / spec
4. Plan-review    ← 4-provider panel, all-individual ≥9.0
5. Dispatch       ← worker heuristic (orchestrator vs trinity-glm)
6. Verify worker  ← read symbols, tests, lint, af-validate
7. PR open        ← push to fork, gh pr create
8. Iterate        ← CI poll, bot poll, code-review panel
9. Triage         ← real bug → fix; advisory → batch into R3+
10. Handoff       ← "mergeable" = orchestrator done; user merges
```

### 1. Auto-pick

When the user grants the auto-pick mandate ("once current PR is mergeable, pick next issue without asking"):

- Sort candidates by **smallest-clearest-scope first**: deferred TRN-* tech-debt < single-file CHGs < feature CHGs depending on just-shipped work < broad audits / large designs.
- Open GitHub issues take priority over internal tech-debt only when the issue has clear scope.
- Skip issues that depend on an unmerged PR; revisit when the dependency lands.
- Decline issues whose scope is unbounded ("audit X codebase") unless the user explicitly asks.

### 2. Branch hygiene (PR #68 lesson)

Before every R1 dispatch:

```bash
git fetch origin main
git status -uno              # confirm clean
git log origin/main --oneline -3   # verify expected merge state
git checkout main && git pull origin main && git checkout -b codex/<slug>
```

The `git fetch origin main` is non-negotiable. Branching off a local `main` that lags upstream produces phantom-reference bugs (where a panel reviewer references a file that's been moved/deleted on origin/main but still exists on the stale local).

Identity gate before any GitHub-visible write:

```bash
gh auth status               # must show: ryosaeba1985 active
```

If the wrong account is active, abort. Public artifacts authored by the wrong identity are a CLAUDE.md-level violation and require immediate close-and-replace.

### 3. Plan (draft CHG / spec)

For substantive changes, write the CHG before code:

- Title: `TRN-<NNNN>-CHG-<Kebab-Title>.md` in `rules/`.
- Required sections: What / Why / Surfaces table / Acceptance Criteria (A1, A2, …) / Out of Scope / Change History.
- Mark Status `Proposed` initially; flip to `Approved` only after panel passes.
- Do NOT skip the CHG for non-trivial work. The plan-review panel scores the CHG; without it, plan-review is impossible.

For tiny scope (≤30 LoC, single file, no contract change), the CHG step can be inlined into the PR description per the issue's own scope hint. When in doubt, write the CHG.

### 4. Plan-review (4-provider panel)

Dispatch all 4 in parallel via the `Agent` tool:

- **gemini** (subagent_type `trinity-gemini`)
- **codex** (subagent_type `trinity-codex`)
- **glm** (subagent_type `trinity-glm`)
- **deepseek** (subagent_type `trinity-deepseek`)

Each prompt must include:
- The CHG path
- The TRN-1800 weights table verbatim (Test 30 / Cross-platform 20 / Compression 20 / Scope 15 / Necessity 15)
- The structured-output schema (per TRN-3022)
- The PASS gate restated: `weighted_score ≥ 9.0 AND blocking == []`

**Gate**: all-individual ≥ 9.0 AND every reviewer's `blocking` empty. Mean is informational; one PASS @ 9.0 with three at 9.5 is mean 9.375 but the 9.0 reviewer's findings still get triaged. A 3-of-4 PASS with one FIX is NOT a pass — fix the dissenter's blockers, re-dispatch.

Common R1 universal blockers (catalogue from past PRs):
- Returncode precedence undefined (TRN-3022)
- I/O contract widening (TRN-3022)
- Static-template constraints incompatible with runtime gating (TRN-3022)
- Stale-base reference / phantom file (TRN-3021)

Iterate on R2/R3+ until gate met. CHG `Status: Approved` lands only after gate.

### 5. Dispatch — orchestrator vs worker

**Heuristic (after PR #68 convergence):**

| Change shape | Lane |
|--------------|------|
| ≤ 2-line surgical fix in one function | Orchestrator-direct |
| Single file, no signature change, no new helper | Orchestrator-direct |
| Signature change crossing call sites | Worker (`trinity-glm` via `droid exec`) |
| New helpers / new files / multi-file refactor | Worker |
| Test additions ≥ 5 cases | Worker |
| Generated-file regeneration | Orchestrator-direct (run `make build`) |
| Substantial doc edits affecting structure | Worker if multi-section; orchestrator if single section |

The orchestrator is faster for surgical fixes and avoids round-trip overhead. The worker scales for substantial changes and isolates the orchestrator's context from large diffs.

**Worker dispatch contract:**
- Pass the CHG path; do not inline the spec into the prompt.
- Specify the implementation order from the CHG.
- List the exact verification commands (pytest, ruff, make verify-built, af validate).
- Constrain: do NOT push or commit. Orchestrator owns git ops.
- Ask for a structured report: files modified, helpers added, signature changes, test count, verification outputs, ambiguities resolved.

### 6. Verify worker

Trust but verify. Worker output is a claim, not proof:

```bash
grep -n "<each-helper-name>" scripts/<file>.py    # symbols exist
.venv/bin/pytest tests/ -q | tail -5              # all green
.venv/bin/ruff check <changed-paths>
.venv/bin/ruff format --check <changed-paths>
make verify-built 2>&1 | tail -2                  # if providers/ changed
af validate --root /Users/frank/Projects/trinity | tail -2
```

If any check fails, fix locally before push (or re-dispatch worker for substantial gaps). Spot-check 1-2 key invariants from the CHG by reading code (e.g. regex flags, constants, error-handler exception lists).

### 7. PR open

```bash
git add <specific-paths>                 # never -A (sweeps untracked tmp/, drafts)
git commit -m "$(cat <<'EOF' ... EOF)"   # HEREDOC for formatting
git push fork <branch-name>              # fork remote, not origin
gh pr create --repo frankyxhl/trinity --base main --head ryosaeba1985:<branch> ...
```

PR body includes: Summary / Why / Surfaces / Test plan / Files / `Closes #<issue>`. Plan-review gate scores belong in the body when applicable.

### 8. Iterate (CI + bot + code-review panel)

After R1 push:
- Wait for CI green on both runners (Linux + macOS).
- Wait for codex bot review (`chatgpt-codex-connector[bot]`). Bot reacts 👍 on the PR (no findings) or posts inline comments.
- Dispatch the 4-provider code-review panel (same shape as plan-review, but reviewing the diff, not the CHG).

Use `ScheduleWakeup` to poll without burning context. Default cadence: 270s (stays in 5-min cache window). Don't poll faster than every 60s.

### 9. Triage

Bot/panel findings classification:

| Severity | Action |
|----------|--------|
| Blocking (FIX in any reviewer) | Fix in next R (R2, R3, …); panel didn't pass |
| P2 from bot | Real bug → fix in next R; spec/UX nit → batch with other advisories |
| Convergent advisory (≥2 reviewers) | Fix in next R |
| Single-reviewer advisory | Batch into a tail R; defer if marginal |
| "Future refactor" / out-of-scope | Note in PR body, ship; file follow-up if needed |

After each R fix push, the same loop runs (CI, bot, optionally re-dispatch panel). Re-dispatch the panel only when blockers were addressed; for advisory-only iterations, the prior gate score still holds.

### 10. Handoff

When PR is mergeable (CI green, bot 👍, panel gate met, no open blockers):

- The orchestrator's job is done.
- Frank merges manually as repo owner. `ryosaeba1985` cannot merge under branch protection.
- Do NOT spam `gh pr merge --auto` retries; the GraphQL endpoint will reject.
- Move to phase 1 (auto-pick next issue).

---

## Worker Dispatch Heuristic (detail)

The 2-line threshold matters because every `droid exec` round-trip costs ~30-90s of latency plus the worker's own context window. For a typo fix that's a 95% loss; for a 200-line refactor that's a 95% gain (orchestrator context stays clean for the panel-review prompts).

Edge cases:

- **Symbol rename across N files**: worker, even if each per-file change is small.
- **Coordinated edit to one section + one test**: orchestrator (still single conceptual change).
- **5+ small fixes from a bot batch**: orchestrator, sequentially. Don't dispatch a worker for a list of grep-and-replaces.
- **Investigation that may or may not require code**: orchestrator first; promote to worker only if the diagnosis grows.

---

## Panel-Review Gate (detail)

**Why TRN-1800, not CLD-1800** (PR #69 lesson):

- CLD-1800 is the `.claude` repo's evolution philosophy (config-pruning surface). Compression weight is calibrated for net-negative LoC.
- TRN-1800 is the trinity repo's philosophy. Compression weight explicitly accepts net-positive when "justified by new tests, new SOP".
- Always verify the prompt names the project's own weights table. A misweighted panel will FIX a feature-add for the wrong reason.

**Why all-individual, not mean ≥9.0**:

- Means hide dissent. PR #60's lesson: a 3-of-4 PASS with mean 9.0 shipped a real bug the dissenting reviewer flagged.
- The all-individual gate forces every dissent to be addressed (or explicitly justified as out-of-scope).
- A reviewer scoring 8.95 isn't a "near-pass" — it's a fail the orchestrator iterates on.

**Convergence signal**: when ≥2 reviewers flag the same finding, treat it as proven (fix). Single-reviewer findings get triaged but may be deferred. Track the convergence count in the synthesis Summary block (TRN-3028).

---

## Auto-Pick Policy (detail)

The user grants auto-pick by saying something like "once mergeable, pick the next issue without asking". Until that grant, every issue pick goes through the user.

When granted, scope-rank the queue:

1. **Deferred internal tech-debt** (e.g. TRN-3025/3026/3027/3030) — usually doc-only or single-file, well-scoped from prior PR review.
2. **Issues unblocked by the just-shipped PR** — natural continuity.
3. **Single-file CHGs in the open issue list** — TRN-2027-shaped work.
4. **Multi-surface CHGs with clear scope** — TRN-3022-shaped work.
5. **Broad audits / large designs** — defer; ask before starting.

Never pick something whose scope you can't state in one sentence.

---

## Guard Rails

- **Never panel-review without TRN-1800 weights** in the prompt. CLD-1800 is for the `.claude` repo only.
- **Never accept 3-of-4 PASS as gate-met**. The dissenter's blockers must be addressed.
- **Never push to `origin/main`**. Push to `fork` (the `ryosaeba1985` remote).
- **Never bypass the identity gate**. `gh auth status` shows `ryosaeba1985` before any GitHub-visible write.
- **Never trust worker reports without spot-checking**. The worker says "done"; you verify "done".
- **Never sleep > 270s when cache is warm and you're polling**. The 5-min prompt-cache TTL is a real cost.
- **Never amend a published commit**. Add a new commit. The CHG history table tracks iterations.
- **Never skip the CHG for substantive changes**. Plan-review can't run without something to review.

---

## Examples

This session — 2026-05-08:

| PR | Issue | Lane | Plan-review | Code-review | Iterations | Outcome |
|----|-------|------|-------------|-------------|------------|---------|
| #69 | #39 (TRN-3022) | Worker | 4-round (mean 9.255) | 4-round (mean 9.45) | R1-R10 | Merged after 10 R-iterations; 4 bot findings + 5 panel advisories addressed |
| #70 | #57 (TRN-2027) | Orchestrator-direct | Skipped (issue scope: 5 lines) | Skipped (single test fixture) | R1 only | Merged immediately; bot 👍 |
| #71 | #55 (TRN-3028) | Worker | Inline-CHG (small) | 4-round (mean 9.31) | R1-R3 | Merged after R3; all-PASS on R1 panel |
| #72 | TRN-3027 (deferred) | Orchestrator-direct | Inline-CHG (doc-only) | Bot only | R1-R2 | Bot caught real Section A inconsistency in R1 |

Common pattern: panel-review ROI scales with surface size. PR #70 shipped clean without panel because the issue itself scoped it as 5 lines. PR #69 ran 10 R-iterations because the schema was new and got 6 architectural blockers in R1.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft (TRN-1008): captures multi-agent review loop developed across PR #66 → #72; intended for promotion to COR-1200 once stable | Claude Opus 4.7 |

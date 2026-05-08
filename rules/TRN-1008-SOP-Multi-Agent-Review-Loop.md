# SOP-1008: Multi-Agent Review Loop

**Applies to:** Trinity project (`frankyxhl/trinity`) — drafted for trinity scope; intended for promotion to PKG/COR-1200 once stable
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Active
**Related:** TRN-1007 (PR readiness gate), TRN-1800 (evolution philosophy / weights), CLD-1802 (atomicity surface definition; PKG-layer doc — see `~/.claude/rules/CLD-1802-*.md`), **COR-1602** (Multi Model Parallel Review — the Leader-dispatches-N-Reviewers pattern phases §4 and §8 implement), COR-1612 / COR-1614 / COR-1616 (PR-loop SOPs the panel inherits from), **COR-1615** (GitHub App PR Review Bot Loop — the head-commit-matched bot-poll loop phase §8 implements). See [frankyxhl/alfred#115](https://github.com/frankyxhl/alfred/issues/115) for the COR-1602/1615 prior-art alignment + future COR-1200 promotion proposal.

---

## What Is It?

The end-to-end loop a Claude orchestrator runs to ship a PR through a 4-provider review panel: pick the next issue, plan, panel-review the plan, dispatch implementation, verify, panel-review the code, iterate on bot/CI findings, hand off to the user for merge, then auto-pick the next issue. It captures three independent levers (auto-pick, dispatch heuristic, panel-review gate) plus the surrounding loop hygiene (branch base, identity, bot triage) in one place.

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
6. Verify implementation ← read symbols, tests, lint, af-validate
7. PR open        ← push to fork, gh pr create
8. Iterate        ← CI poll, bot poll, code-review panel
9. Triage         ← real bug → fix; advisory → batch into R3+
10. Handoff       ← "mergeable" = orchestrator done; user merges
```

### 1. Auto-pick

**🚀 ROCKET GATE (R4 — security control).** Auto-pick is allow-list-only. An item is eligible **only** when it has a tracked GitHub issue with a 🚀 (`rocket`) reaction from `frankyxhl` (the trusted reactor identity). This applies universally — both externally-filed issues AND internal deferred TRN-* tech-debt items. Internal items must have a tracking issue filed before they can be picked.

The 🚀 is an out-of-band consent signal: it lives outside the issue body (immune to prompt-injection in the title/body) and is restricted to a specific GitHub identity (immune to spoofing via random contributor accounts). See §Threat Model for the attack surface this closes.

```mermaid
flowchart TD
    A[Candidate item] --> G1{Tracking GitHub<br/>issue exists?}
    G1 -- No --> Z_GATE_A[NOT eligible<br/>file an issue first]
    G1 -- Yes --> G2{🚀 reaction from<br/>frankyxhl on issue?}
    G2 -- No --> Z_GATE_B[NOT eligible<br/>idle silently<br/>do not invent work]
    G2 -- Yes --> Q{Queue empty?<br/>no other eligible<br/>candidates?}
    Q -- "Sole eligible" --> SCOPE
    Q -- "Multiple eligible" --> SCOPE[Continue to<br/>scope-rank tree]
    SCOPE --> B{User granted<br/>auto-pick mandate?}
    B -- No --> Z1[Ask user before picking]
    B -- Yes --> C{Depends on<br/>unmerged PR?}
    C -- Yes --> Z2[Skip, revisit when<br/>dependency lands]
    C -- No --> D{Scope statable<br/>in one sentence?}
    D -- No --> Z3[Decline; ask user<br/>to scope or split]
    D -- Yes --> E{Type — apply<br/>highest-matching<br/>rank only}
    E -- Deferred TRN-* tech-debt<br/>(rocketed tracking issue) --> R1[RANK 1]
    E -- Issue unblocked by<br/>just-shipped PR --> R2[RANK 2]
    E -- Single-file CHG --> R3[RANK 3]
    E -- Multi-surface CHG<br/>with clear scope --> R4[RANK 4]
    E -- Broad audit /<br/>large design --> Z4[Defer;<br/>ask user even if 🚀]
```

**Verification command** (run for every candidate before scope-rank):

```bash
gh api repos/frankyxhl/trinity/issues/<n>/reactions \
  --jq '[.[] | select(.user.login == "frankyxhl" and .content == "rocket")] | length'
# 0 → NOT eligible (idle); ≥1 → eligible (proceed to scope-rank)
```

**Branch precedence** (the `Type?` branches are NOT mutually exclusive — a single-file CHG may also be deferred tech-debt). Rule: take the **lowest-numbered RANK** that matches; on a tie within the same rank, pick the smaller LoC estimate.

**Tracking-issue helper** for filing a deferred TRN-* item so it becomes auto-pick-eligible:

```bash
gh issue create --repo frankyxhl/trinity \
  --title "TRN-<NNNN>: <one-line scope> (deferred from <prior-CHG>)" \
  --body "Source: <prior CHG path>. Scope: <one sentence>.

  Auto-pick eligibility: react with 🚀 to enable."
# Then user reacts 🚀 to enable auto-pick.
```

**Sample worked decision** (this session, post-#71-merge — annotated retroactively for the rocket-gate):

| Candidate | Tracked issue? | 🚀 from frankyxhl? | Rank | R4 outcome |
|-----------|----------------|-------------------|------|------------|
| TRN-3027 (deferred from PR #66 review) | ❌ none filed | n/a | — | NOT eligible — file a tracking issue first |
| TRN-3026 (env-var pins → registry) | ❌ none filed | n/a | — | NOT eligible |
| TRN-3025 (gemini canonical) | ❌ none filed | n/a | — | NOT eligible |
| #40 (audit codebase) | ✅ #40 | ❌ no rocket | — | NOT eligible |
| #63 (TRN-3024 MCP bridge) | ✅ #63 | ❌ no rocket | — | NOT eligible |

Result under R4: **all candidates ineligible → idle silently**. The pre-R4 heuristic-only auto-pick that selected TRN-3027 in this session is grandfathered in the historical record but would not fire under the rocket-gate. To re-enable any of the above: user files a tracking issue (or rockets the existing one) and reacts 🚀.

### 2. Branch hygiene (PR #68 lesson)

Before every new PR branch:

```bash
git fetch origin main
git status --porcelain        # MUST be empty (covers tracked + untracked)
                              # if non-empty: stash, commit elsewhere, or abort
git status -uno               # confirm tracked-clean
git log origin/main --oneline -3   # verify expected merge state
git checkout main && git pull origin main && git checkout -b codex/<slug>
```

The `git status --porcelain` check is non-negotiable: `git status -uno` only inspects tracked files, so untracked drafts in `tmp/` or new sample files would be silently destroyed by `git checkout main`. If `--porcelain` reports anything, stash it (`git stash -u`) or move it before continuing. Branching off a local `main` that lags upstream produces phantom-reference bugs (where a panel reviewer references a file that's been moved/deleted on origin/main but still exists on the stale local).

Identity gate before any GitHub-visible write:

```bash
gh auth status               # must show: ryosaeba1985 active
```

If the wrong account is active, abort. Public artifacts authored by the wrong identity are a CLAUDE.md-level violation and require immediate close-and-replace.

### 3. Plan (draft CHG / spec)

```mermaid
flowchart TD
    A[Issue / tech-debt picked] --> X{Generated-file<br/>regen only?<br/>e.g. make build, af index}
    X -- Yes --> Z1[Skip CHG —<br/>generator is the spec.<br/>Regen, commit, ship.]
    X -- No --> B{LoC estimate?}
    B -- ">30 LoC OR<br/>multi-file" --> C[Write full CHG in rules/]
    B -- "≤30 LoC AND<br/>single file" --> D{Contract change?<br/>signature, schema, IO}
    D -- Yes --> C
    D -- No --> E{Issue Scope-hints<br/>section says<br/>no CHG?}
    E -- Yes --> F[Inline CHG in PR body]
    E -- No --> C
    F --> P{Inline-CHG<br/>≥30 LoC OR<br/>contract change?}
    P -- Yes --> H
    P -- No --> K
    C --> G[Status: Proposed]
    G --> H[Run plan-review panel<br/>see phase 4]
    H --> I{Gate met?}
    I -- No --> J[Iterate R2/R3+]
    J --> H
    I -- Yes --> K[Status: Approved]
```

**"Scope hints"** refers to the optional `## Scope hints` section of the GitHub issue template (see `.github/ISSUE_TEMPLATE/*.yml`). When the filer has explicitly written e.g. "no CHG needed; one-line fix", treat that as authorisation for an inline-CHG-in-PR-body shortcut. Absent that section, default to writing a full CHG.

**CHG skeleton:** see `rules/samples/sample-chg-skeleton.md` for the copy-paste template (with `##`-headed sections — that file is in `samples/` because it isn't subject to SOP-validator structural rules). Sections summarised below for orchestrator quick-reference (a real CHG uses `##` headings — see e.g. `rules/TRN-3022-CHG-*.md` for a worked instance):

- **Frontmatter**: `Applies to`, `Last updated`, `Last reviewed`, `Status: Proposed`, `Date`, `Requested by`, `Priority`, `Change Type`, `Targets`, `Closes #<issue>`, `Builds on <prior TRN>`.
- **What** — one paragraph: what changes.
- **Why** — one paragraph: why this matters; cite session evidence / failed CI / PR-review finding.
- **Out of Scope** — bullets; defer items to follow-up CHGs by name.
- **Surfaces** — table: # | Surface | Change. One row per file or symmetric class (per CLD-1802).
- **Acceptance Criteria** — bullets `A1: ...`, `A2: ...`. Each must be observable and testable.
- **Implementation Order** — numbered steps; final step is verify + CHANGELOG + commit.
- **Change History** — table: Date | Change | By.

**Heuristic:** when in doubt, write the CHG. Five minutes drafting is cheaper than a panel reviewing the wrong thing.

### 4. Plan-review (4-provider panel)

Dispatch all 4 in parallel via the `Agent` tool. **Parallelism is required** — running serially burns 5x the wall-clock and fragments the cache window.

```mermaid
flowchart LR
    A[CHG drafted<br/>Status: Proposed] --> B[Dispatch 4 in parallel]
    B --> G1[gemini]
    B --> G2[codex]
    B --> G3[glm]
    B --> G4[deepseek]
    G1 --> V1{Verdict OK?<br/>timeout / malformed JSON /<br/>missing score?}
    G2 --> V1
    G3 --> V1
    G4 --> V1
    V1 -- Malformed --> R1[Retry provider once]
    R1 --> V1
    V1 -- "Still bad" --> Drop[Mark provider unavailable<br/>see Failure Modes]
    V1 -- OK --> J[Collect verdicts]
    Drop --> J
    J --> N1{≥3 viable<br/>verdicts?}
    N1 -- No --> Abort[Abort panel<br/>notify user]
    N1 -- Yes --> K{All viable individual<br/>≥ 9.0 AND<br/>all blocking == []?}
    K -- Yes --> ADV{Advisories<br/>present?}
    ADV -- Yes --> L2[Status: Approved<br/>fix convergent advisories<br/>before phase 8]
    ADV -- No --> L[Status: Approved<br/>→ phase 5]
    K -- No --> M[Triage findings<br/>see phase 9]
    M --> NX[Apply fixes to CHG]
    NX --> A
```

**Sample plan-review prompt:** see `rules/samples/sample-plan-review-prompt.md` for the full copy-paste template. The template is parameterised over both **code-weights** (TRN-1800 §Override Code Weights — for code/test changes) and **doc-weights** (TRN-1800 §Override Document Weights — for doc-only CHGs); pick the right table per CHG type before dispatching. Doc-only CHGs (e.g. TRN-3027, TRN-1008 itself) get scored wrong if the prompt names the code table.

**Weights tables** (per TRN-1800 — both reproduced here for orchestrator quick-reference; the prompt template lists both verbatim):

*Code / test changes:*

| Dimension | Weight |
|-----------|--------|
| Test coverage of changed surface | 30% |
| Cross-platform parity | 20% |
| Compression ratio | 20% (net-positive justified by new tests/SOP) |
| Scope restraint | 15% |
| Necessity | 15% |

*Doc-only CHGs:*

| Dimension | Weight |
|-----------|--------|
| Necessity | 25% |
| Generated-vs-source | 25% |
| Atomicity | 15% |
| Compression ratio | 15% |
| Consistency | 10% |
| Actionability | 10% |

USE TRN-1800, NOT CLD-1800 (the `.claude` repo philosophy doesn't apply here).

**Common R1 universal blockers** (catalogue):
- Returncode precedence undefined (TRN-3022)
- I/O contract widening, e.g. write_synthesis return type (TRN-3022)
- Static-template constraints incompatible with runtime gating (TRN-3022)
- Stale-base reference / phantom file (TRN-3021 — fixed by phase-2 branch hygiene)
- Panel reviewing CLD-1800 weights instead of TRN-1800 (PR #69 R3 lesson)

**Gate enforcement**: the gate is `decision == PASS AND weighted_score >= 9.0 AND blocking == []` for *every* reviewer. Mean is informational only.

A structured verdict with `decision: PASS` but `weighted_score < 9.0` is malformed (the schema rule says PASS requires `score >= 9.0` AND `blocking == []`). Treat such verdicts as inconsistent and FIX-coerce them per TRN-3022's `effective_decision` logic — i.e. demote to FIX and require the reviewer to either raise the score or list blockers.

| Panel result | Action |
|--------------|--------|
| 4 PASS, every score ≥ 9.0, all blocking empty | Status: Approved → phase 5 |
| 3 PASS + 1 FIX | NOT passed — fix dissenter's blockers, re-dispatch |
| 4 PASS but one reviewer at 8.95 | NOT passed — 8.95 < 9.0 fails the gate; demote to FIX and iterate |
| Reviewer emits PASS with score < 9.0 | Malformed verdict; coerce to FIX (TRN-3022 effective_decision), iterate |
| 4 PASS, all blocking empty, advisories present | Passed — fix convergent advisories before code-review (phase 8) |

### 5. Dispatch — orchestrator vs worker

```mermaid
flowchart TD
    A[Implementation task] --> B{Generated file<br/>regen only?}
    B -- Yes --> O1[ORCHESTRATOR<br/>run make build]
    B -- No --> MIX{Mixed<br/>code+doc?}
    MIX -- "Yes — code surface dominates" --> C
    MIX -- "Yes — doc surface dominates" --> H
    MIX -- No --> H0{Multi-FILE<br/>multi-section<br/>doc edit?}
    H0 -- Yes --> W4[WORKER]
    H0 -- No --> H{Single doc file,<br/>≥3 sections changed?}
    H -- Yes --> W4
    H -- No --> C{≤ 2 lines in<br/>one function?}
    C -- Yes --> O2[ORCHESTRATOR<br/>direct edit]
    C -- No --> D{Signature change<br/>crossing call sites?}
    D -- Yes --> W1[WORKER<br/>trinity-glm via droid exec]
    D -- No --> E{New helpers /<br/>new files /<br/>multi-file refactor?}
    E -- Yes --> W2[WORKER]
    E -- No --> F{Test additions<br/>≥ 5 cases?}
    F -- Yes --> W3[WORKER]
    F -- No --> G{Single file<br/>AND no contract change?}
    G -- Yes --> O3[ORCHESTRATOR]
    G -- No --> O4[ORCHESTRATOR]
```

**Why the threshold matters**: every `droid exec` round-trip costs ~30-90s + the worker's own context window. For a typo fix that's a 95% loss; for a 200-line refactor that's a 95% gain (orchestrator context stays clean for plan-review prompts).

**Edge cases not in the tree:**

- **Symbol rename across N files** → worker (even if each per-file change is small).
- **Coordinated edit to one section + one test** → orchestrator (still single conceptual change).
- **5+ small fixes from a bot batch** → orchestrator, sequentially. Don't dispatch a worker for a list of grep-and-replaces.
- **Investigation that may or may not require code** → orchestrator first; promote to worker only if the diagnosis grows.

**Sample worker dispatch prompt:** see `rules/samples/sample-worker-dispatch-prompt.md` for the copy-paste template. Worker dispatch contract (do not omit): pass the CHG path (do not inline the spec); specify implementation order; list exact verification commands; constrain "do NOT push or commit"; ask for structured report.

### 6. Verify implementation

Trust but verify. Whether the diff came from a worker or from the orchestrator's own direct edits, the same checks apply — every claim ("tests green", "lint clean") is a claim, not proof until you re-run it locally:

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

```mermaid
flowchart TD
    A[R<n> pushed] --> B[Use ScheduleWakeup tool<br/>delay=270s]
    B --> C{CI status?}
    C -- "Green<br/>both runners" --> E{Bot reviewed<br/>this commit?}
    C -- "Pending /<br/>queued" --> F0[Wait another 270s]
    F0 --> C
    C -- "Cancelled" --> F1[Re-trigger workflow<br/>then wait 270s]
    F1 --> C
    C -- "Timeout" --> T{3rd timeout<br/>this PR?}
    T -- No --> F2[Log CI flake<br/>re-trigger + wait]
    F2 --> C
    T -- "Yes — 3 strikes" --> Tabort[Abort iterate loop<br/>surface to user]
    C -- "Failed" --> D[Read failing log<br/>fix → push R<n+1>]
    D --> A
    E -- No --> F[Wait another 270s]
    F --> E
    E -- Yes --> G{Bot 👍<br/>no NEW findings<br/>since last poll?}
    G -- No --> H[Triage bot finding<br/>see phase 9<br/>note: bot may post<br/>new findings on later<br/>commits — re-poll each R]
    H --> A
    G -- Yes --> I{Code-review<br/>panel run yet<br/>on this head?}
    I -- No --> J[Dispatch panel<br/>parallel]
    J --> K{All viable ≥ 9.0<br/>blocking == []?<br/>see Failure Modes<br/>for partial-panel rules}
    K -- No --> L[Triage panel findings<br/>see phase 9]
    L --> A
    K -- Yes --> M[Mergeable<br/>→ phase 10]
    I -- Yes --> M
```

**Polling cadence rules** (from the `ScheduleWakeup` tool's documentation — `ScheduleWakeup` is a tool name, not a concept):
- Default: 270s (stays inside 5-min cache window).
- Never < 60s (rate limits, no signal benefit).
- Never == 300s (cache-miss penalty without amortization).
- For long jobs (CI slow, panel slow): 1200-1800s.

### 9. Triage

```mermaid
flowchart TD
    A[Finding from bot or panel] --> P{Phase that<br/>produced this?}
    P -- "plan-review" --> PR1{Architectural /<br/>contract / scope<br/>blocker?}
    PR1 -- Yes --> PR2[Fix CHG document<br/>re-dispatch plan panel]
    PR1 -- No --> PR3[Treat as advisory<br/>continue tree below]
    P -- "code-review or bot" --> B
    PR3 --> B
    B{Severity?}
    B -- "P0 / security /<br/>data loss" --> X0[Fix immediately<br/>may bypass batching<br/>can ship hotfix R]
    B -- "Blocking<br/>FIX in any reviewer" --> X1[Fix in next R<br/>panel did NOT pass]
    B -- "P2 / P3 from bot" --> C{Real bug?<br/>repros / wrong output / contract violation}
    B -- "Hallucinated finding<br/>file:line not in diff" --> XH[Reject with note<br/>do NOT count toward<br/>convergence]
    C -- Yes --> X2[Fix in next R]
    C -- No --> D[Spec/UX nit]
    D --> E{Convergent<br/>≥2 reviewers<br/>flag same thing?}
    B -- Advisory --> E
    E -- Yes --> X3[Fix in next R<br/>convergence = proven]
    E -- No --> F{Stated as<br/>future-refactor /<br/>out-of-scope?}
    F -- Yes --> X4[Note in PR body<br/>ship; file follow-up<br/>if worth it]
    F -- No --> X5[Batch into tail R<br/>or defer if marginal]
```

**Severity vocabulary** (orient the tree):

| Severity | Examples | Action |
|----------|----------|--------|
| P0 | Security hole, data loss, credential leak, rm -rf risk | Fix immediately; may bypass batching; hotfix R if PR already merged |
| P1 | Correctness regression, contract widening, broken test | Fix in next R |
| P2 | UX nit, missing error message, poor log line | Batch into tail R |
| P3 | Cosmetic, naming preference, doc polish | Optional / defer |

**Worked example** (PR #69 R3 → R4 triage):

| Finding | Reviewer(s) | Severity | Decision |
|---------|-------------|----------|----------|
| `results.index(result)` fragile | codex + glm + deepseek | Convergent advisory | Fix R4 |
| Surface 3 doc gap (3 of 6 providers miss section) | codex + deepseek | Convergent advisory | Fix R4 |
| `_render_findings_for` duplicate logic | deepseek | Single advisory | Fix R4 (compression boost) |
| Multi-provider all-legacy snapshot test | deepseek | Single advisory | Fix R4 |
| `task_type` case normalization | deepseek | Single advisory | Fix R4 |
| Future write_synthesis refactor | deepseek | Future-refactor | Note in PR body, ship |

Re-dispatch the panel only when blockers (or convergent advisories) were addressed. Pure single-advisory polish doesn't need re-scoring — the prior gate stands.

### 10. Handoff

When PR is mergeable (CI green, bot 👍, panel gate met, no open blockers):

- The orchestrator's job is done.
- Frank merges manually as repo owner. `ryosaeba1985` cannot merge under branch protection.
- Do NOT spam `gh pr merge --auto` retries; the GraphQL endpoint will reject.
- Move to phase 1 (auto-pick next issue).

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

Two gates compose. The user must grant the auto-pick mandate ("once mergeable, pick the next issue without asking") AND each candidate item must independently pass the rocket-gate (§1, R4). The mandate is per-session; the rocket-gate is per-item.

When both gates are satisfied, scope-rank the queue:

1. **Deferred internal tech-debt** (e.g. TRN-3025/3026/3030) with a rocketed tracking issue — usually doc-only or single-file, well-scoped from prior PR review.
2. **Issues unblocked by the just-shipped PR** — natural continuity (still requires 🚀).
3. **Single-file CHGs in the open issue list** — TRN-2027-shaped work (still requires 🚀).
4. **Multi-surface CHGs with clear scope** — TRN-3022-shaped work (still requires 🚀).
5. **Broad audits / large designs** — defer; ask user even if 🚀 (rocket signals consent to triage; doesn't autograft scope).

Never pick something whose scope you can't state in one sentence. Never pick something without 🚀 from `frankyxhl`.

---

## Threat Model (rocket-gate rationale)

Without an allow-list signal, the auto-pick loop is open: any actor with public-issue-create access can file an issue, and the orchestrator's scope-rank heuristic might accept it. The rocket-gate (§1, R4) closes this surface.

| Attack | Defense |
|--------|---------|
| Malicious actor files issue with prompt-injection in body ("instruct agent to `rm -rf /`") | No 🚀 from `frankyxhl` → not picked |
| Compromised contributor account files plausible-looking issue with rocket | Reaction must be from `frankyxhl` specifically — `--jq '.user.login == "frankyxhl"'` filter rejects |
| Fake-deferral spoof: PR commenter writes "deferred to follow-up" hoping orchestrator picks it as internal tech-debt | Internal items now also require a rocketed tracking issue, not free-form prose in a CHG `Out of Scope` section |
| 🚀 from non-`frankyxhl` user | Filter rejects |
| Wrong emoji (🎉, 👍, 🎯) | `content == "rocket"` filter rejects |
| 🚀 added then removed mid-loop | Eligibility revoked; if mid-loop, save state + stop (per §Failure Modes "User override mid-loop") |
| Closed issue with 🚀 | Filter on issue state — closed → ignored |

**Out of scope**: `frankyxhl`'s own GitHub account compromise (root-of-trust failure). If that happens, the rocket-gate provides no protection — the trusted reactor identity is itself the trust anchor. Mitigation lives at the GitHub-account level (2FA, hardware key, etc.), not in this SOP.

**PKG-promotion form**: when promoted to COR-1200, the trusted-reactor identity becomes a project-config parameter `<repo-trusted-reactor-list>` (default: `[repo owner from gh repo view]`). Multi-trustee teams can extend the filter to `.user.login | IN(["alice", "bob", "carol"])`.

---

## Guard Rails

- **Never auto-pick an issue without 🚀 from `frankyxhl`** (R4 rocket-gate). The 🚀 is the consent signal; absence = abort, idle silently. Internal deferred TRN-* items also need a rocketed tracking issue.
- **Never panel-review without TRN-1800 weights** in the prompt. CLD-1800 is for the `.claude` repo only.
- **Never accept 3-of-4 PASS as gate-met**. The dissenter's blockers must be addressed.
- **Never push to `origin/main`**. Push to `fork` (the `ryosaeba1985` remote).
- **Never bypass the identity gate**. `gh auth status` shows `ryosaeba1985` before any GitHub-visible write.
- **Never trust worker reports without spot-checking**. The worker says "done"; you verify "done".
- **Never sleep > 270s when cache is warm and you're polling**. The 5-min prompt-cache TTL is a real cost.
- **Never amend a published commit**. Add a new commit. The CHG history table tracks iterations.
- **Never invent work when no candidate is rocket-eligible.** Idle silently; wait for the user to file or rocket an issue.
- **Never skip the CHG for substantive changes**. Plan-review can't run without something to review.

---

## Examples

This session — 2026-05-08 (auto-picks marked **(pre-rocket-gate)** are grandfathered from before R4; under the post-R4 rule they would have required a 🚀 from `frankyxhl`):

| PR | Issue | Lane | Plan-review | Code-review | Iterations | Outcome |
|----|-------|------|-------------|-------------|------------|---------|
| #69 | #39 (TRN-3022) | Worker | 4-round (mean 9.255) | 4-round (mean 9.45) | R1-R10 | Merged after 10 R-iterations; 4 bot findings + 5 panel advisories addressed |
| #70 | #57 (TRN-2027) **(pre-rocket-gate auto-pick)** | Orchestrator-direct | Skipped (issue scope: 5 lines) | Skipped (single test fixture) | R1 only | Merged immediately; bot 👍 |
| #71 | #55 (TRN-3028) | Worker | Inline-CHG (small) | 4-round (mean 9.31) | R1-R3 | Merged after R3; all-PASS on R1 panel |
| #72 | TRN-3027 (deferred) **(pre-rocket-gate auto-pick — under R4 would need a tracking issue + 🚀)** | Orchestrator-direct | Inline-CHG (doc-only) | Bot only | R1-R2 | Bot caught real Section A inconsistency in R1 |
| #73 | TRN-1008 (this SOP) **(direct user request — gate-bypass authorised inline)** | Mixed | Comprehensibility-review (3-of-4) | Self-application via panel after R4 | R1-R4 | This SOP's own creation |

Common pattern: panel-review ROI scales with surface size. PR #70 shipped clean without panel because the issue itself scoped it as 5 lines. PR #69 ran 10 R-iterations because the schema was new and got 6 architectural blockers in R1. **Under R4, none of #69/#70/#71/#72 would have been auto-pickable without a 🚀**; #73 was a direct user-instruction (an explicit user message is itself the consent signal; the rocket-gate applies to autonomous picks, not user-directed ones).

---

## Failure Modes

The happy-path loop assumes 4 healthy providers, a responsive bot, and a stable CI. Each of these can fail. The orchestrator must handle every mode below explicitly — silent fall-through is how panels ship the wrong thing.

### Reviewer timeout / API error / invalid JSON

A provider call that times out, returns a non-2xx, or emits malformed JSON (no fenced block, missing keys, invalid types) does NOT count as a verdict. Protocol:

1. Retry the failed provider once with the same prompt.
2. If it still fails: mark the provider unavailable for this round and proceed with the remaining N-1 reviewers, **but only if** N-1 ≥ 3 AND the failed provider was not the dissenter on the previous round.
3. Otherwise: abort the panel, surface the API outage to the user, and pause the loop.
4. Always document the missing reviewer in the panel tally (e.g. "deepseek: API outage 2026-05-08; 3-of-3 PASS over the remaining viable providers"). The PR body should record it too.

### CHG abandonment after R3 reveals wrong approach

When 3+ rounds of review converge on "this approach is structurally wrong, not just buggy" (e.g. multiple reviewers flag the same architectural blocker in R3 that they raised in R1, with the same severity), do NOT loop indefinitely. Exit criterion:

1. Orchestrator drafts a `## Lessons Learned` section in the CHG, summarising what went wrong and why the approach is unrecoverable.
2. Set `Status: Abandoned` in the frontmatter.
3. File a follow-up issue (or new CHG) sketching the alternative approach.
4. Close the PR with a comment pointing at the follow-up. The abandoned CHG stays in `rules/` as a historical record — it is itself the artifact.

### User override mid-loop

The auto-pick mandate is checked at phase 1, but the user can revoke or redirect at any point. User messages mid-loop take priority over the current loop. Protocol:

1. Save loop state: current phase number, R-number, panel verdicts collected so far, pending fixes, the active CHG path.
2. Acknowledge the user message and answer / act on it.
3. When the user signals "resume" (or implicitly resumes by silence after the side-task completes), restart from the saved phase + R-number — do NOT replay earlier phases.

### Provider unavailability

The panel must have ≥3 viable providers to enforce the gate meaningfully. Protocol:

- 4 viable: standard all-individual ≥ 9.0 gate over all 4.
- 3 viable: all-individual ≥ 9.0 over the 3 is the gate. Document the missing fourth in the PR body.
- < 3 viable: abort the panel and notify the user. Do NOT proceed with 2-of-2 or 1-of-1 — the convergence signal collapses below 3 reviewers.

### Post-handoff user rejection

If Frank rejects a panel-passed PR (either pre-merge "don't merge this" or post-merge "revert this"), the loop resumes at phase 9 (triage) with the rejection note treated as a new finding. Additional protocol:

- If the rejection cites scope or architectural issues the panel did not flag, also append a one-line entry to `samples/panel-blind-spots.md` (create the file if missing) describing what the panel missed. These entries feed future plan-review prompt updates so reviewers learn to look for the missed dimension.
- A revert is itself a PR that inherits the original gate (per `## When NOT to Use`); the rejection does not require a re-panel of the revert itself.

### CI timeout vs CI failure

The iterate tree must distinguish four CI outcomes — conflating them produces false-positive "fix the code" cycles when the real issue is infrastructure:

| CI status | Action |
|-----------|--------|
| Pending / queued | Wait another 270s; loop on status check |
| Cancelled (e.g. manual cancel, branch update) | Re-trigger the workflow; wait |
| Timeout (job killed at runtime limit) | Log + re-trigger ONCE per occurrence; if 3 timeouts hit on the same PR, abort the iterate loop and surface "consistent CI timeouts — likely test or infra regression" to the user |
| Failed (assertion / exit code) | Read the failing log; fix in code; push R<n+1> |

The 3-strikes rule prevents an infrastructure flake from masquerading as a code bug indefinitely.

### Follow-up bot comments after initial 👍

GitHub review bots can post additional findings on later commits even after they 👍'd an earlier commit. The iterate tree must re-poll the bot's reactions on **each** new R-push, not assume the prior 👍 carries forward. Specifically: at phase 8, when polling `gh pr view --json reviews,comments`, treat any bot comment whose `submitted_at` is after the current HEAD's push timestamp as a NEW finding to triage — even if the same bot 👍'd the previous head.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft (TRN-1008): captures multi-agent review loop developed across PR #66 → #73; intended for promotion to COR-1200 once stable | Claude Opus 4.7 |
| 2026-05-08 | R3: applied 3-of-4 comprehensibility-review findings (gemini + codex + glm-reviewer); deepseek deferred due to API outage. PKG-promotion parameterisation deferred to a follow-up CHG. | Claude Opus 4.7 |
| 2026-05-08 | R4: rocket-gate security control. Auto-pick now requires a tracking GitHub issue with a 🚀 reaction from `frankyxhl` (universal — applies to internal deferred TRN-* items as well as externally-filed issues). When no candidate is rocket-eligible, idle silently. New §"Threat Model" section catalogues attack surface closed. Direct user request; gate-bypass authorised inline. Per the SOP's own self-application, the R4 diff should run through the panel before merge. | Claude Opus 4.7 |

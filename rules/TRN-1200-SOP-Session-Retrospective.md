# SOP-1200: Session Retrospective — Trinity

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-06-14
**Last reviewed:** 2026-06-14
**Status:** Active
**Last executed:** —
**Depends on:** COR-1200 (generic Session Retrospective — cycle, af-log reconstruction recipe, scoring rubric)
**Related:** TRN-1008 (Multi-Agent Review Loop), TRN-1009 (Issue Filing), TRN-1007 (PR Readiness), TRN-1801 (Evolve Trinity), TRN-1800 (Evolution Philosophy)

---

## What Is It?

Trinity's instantiation of COR-1200. It inherits COR-1200's retrospective cycle, activity-log reconstruction recipe, and scoring rubric without restating them, and binds two trinity-specific things on top:

1. **Where** a trinity retrospective is recorded (area + the memory-vs-doc routing).
2. **What** to scan that COR-1200's generic prompts don't name — the multi-agent loop (TRN-1008) and the Assembly + codex review pipeline that does most of trinity's work.

This document is the single source of truth for *how trinity reflects*; COR-1200 remains the source of truth for the *generic mechanics*.

---

## Why

Trinity's day-to-day work runs through a pipeline COR-1200 was not written for: issues dispatched to `iterwheel-assembly`, PRs reviewed adversarially by codex, merged owner-side by `@frankyxhl`. The recurring lessons live in that pipeline (Assembly's capability limits, codex finding patterns, permission boundaries, the replacement-PR workaround) — not in the generic "did I repeat a command" prompts. Without a trinity overlay, those lessons stay in chat scrollback and get re-learned every session. This SOP names the trinity signal sources and routes each finding to its durable home.

---

## When to Use

- Before ending a session that merged ≥1 PR, dispatched ≥1 Assembly run, or ran a TRN-1008 loop.
- After a milestone (a batch of issues shipped, a dependency sweep, a release).
- When context is about to be compacted.

## When NOT to Use

- Read-only exploration or a Q&A-only session with no mutations.
- A trivially short session with nothing to reflect on.
- Inherits COR-1200 §When NOT to Use otherwise.

---

## Steps

This SOP's procedure is COR-1200's cycle plus a trinity overlay. Run the three steps in order.

### Step 1 — Run COR-1200's cycle unchanged

Execute COR-1200's steps as written; this SOP does not restate them. Specifically inherited:

- **COR-1200 Step 0** — close all open `D` discussion items (COR-1201).
- **COR-1200 Step 1** — reconstruct "Actions Taken" from `./rules/logs/<UTC>.jsonl` (the `af` activity log), falling back to chat history when the log is empty.
- **COR-1200 Steps 2–4** — repeated-pattern → automation candidate; undocumented process → new-SOP candidate; SOP gap → SOP update.
- **COR-1200 §Scoring** — the 0–10 rubric (Frequency 35 / Actionability 30 / Impact 20 / Detection gap 15) and its action thresholds decide whether a finding becomes a tracked issue, a memory entry, or is discarded. Use it unmodified.

### Step 2 — Scan the trinity-specific signal sources (§B)

After COR-1200's generic prompts, run the trinity signal scan in §B below. These cover the multi-agent loop and the Assembly + codex pipeline that COR-1200's generic prompts do not name.

### Step 3 — Route each finding to its durable home (§A + §C)

Score each finding per COR-1200 §Scoring, then send it to the destination in §A that matches its shape, applying the §C routing rule. Drop anything below the discard threshold.

---

## §A. Where the retrospective lands

Two destinations, not one — route each finding deliberately:

| Finding shape | Destination | How |
|---------------|-------------|-----|
| A reusable behavioural lesson (a correction, a confirmed approach, a permission/tool boundary) | **Auto-memory** | Write a `feedback_*` / `reference_*` file under the session memory dir and add the one-line `MEMORY.md` pointer. This is the primary home for pipeline lessons; see the existing `reference_assembly_slash_command`, `reference_merge_permission_owner_only` entries. |
| A process gap in an existing trinity SOP | **TRN doc update** | Amend the target TRN SOP + add a Change History row (COR-1200 step 4). |
| A genuinely new, repeatable trinity process | **New TRN SOP** + GitHub issue | File per TRN-1009, draft the SOP per TRN-1801. |
| A session summary worth preserving verbatim | **Retro REF doc** | `af create ref --prefix TRN --area 12 --title "Session Retrospective <UTC>-DN"` (area 12 = Check phase, matching COR-1200 step 5). Optional — only when the session is large enough to warrant a standing record. |

Memory is the default and lowest-friction home; reserve a retro REF doc for milestone sessions.

## §B. Trinity-specific signal sources to scan

In addition to COR-1200's generic prompts, ask these each retrospective:

| Signal | Prompt | Where lessons usually go |
|--------|--------|--------------------------|
| **Assembly dispatch** | Did an `/assembly` run fail (SQLite lock from parallel dispatch, 900s OMP timeout on a large refactor, `workflows`-permission push rejection, TestPilot skipping `make lint`)? Did I dispatch within the N≤2 concurrent-PR cap? | `reference_assembly_slash_command` |
| **codex review** | Were findings real (this session: 14/14 valid, 0 noise)? Did I fix → reply → **resolve thread only after both exist** (never batch-resolve untriaged)? Did codex run the test to reproduce? | `reference_codex_bot_pass_signal`; thread-resolve discipline in `reference_merge_permission_owner_only` |
| **PR lifecycle** | Did an Assembly branch need a replacement PR because `ryosaeba1985` can't push to it? Did CI fail on something a worktree pre-check would have caught (lint, stale version-pin tests)? | `reference_merge_permission_owner_only`, `feedback_always_pr_no_direct_push` |
| **Permission boundary** | Did `ryosaeba1985` hit an owner-only wall (merge, issue-close, `update-branch`, `@dependabot` command)? Record the exact refusal so it's not re-attempted. | `reference_merge_permission_owner_only` |
| **Test/CI fragility** | Did a test break on a correct change because it froze a value Dependabot manages (the action-pin `# vN` lesson)? Generalise the assertion. | TRN doc / issue |
| **MEMORY pressure** | Is `memory/MEMORY.md` near its truncation limit? Any stale or duplicate entries to prune? | Prune in place |

## §C. Routing rule

For each finding: score per **COR-1200 §Scoring**, then send it to the §A destination matching its shape. A finding that scores below the COR-1200 discard threshold is dropped — do not record noise. Prefer a memory entry over a new SOP unless the finding is a genuinely repeatable multi-step process (atomicity per TRN-1800).

---

## Guard Rails

- Never duplicate COR-1200 content here; cite it. If COR-1200's generic mechanics need changing, that is a COR-layer change, not a trinity edit.
- Never record a lesson the repo already encodes (CI config, a merged PR, git history). Record what was *non-obvious* about it.
- This SOP must not be edited by the TRN-1801 evolve loop; changes go through normal PR review.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-06-14 | Initial version — trinity instantiation of COR-1200; adds §A destination routing, §B trinity signal sources (Assembly / codex / PR-lifecycle / permission / CI-fragility / memory), §C scoring-to-destination rule | Claude Code |

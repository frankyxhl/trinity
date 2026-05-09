# SOP-1000: Workflow Routing PRJ — Trinity

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-10
**Last reviewed:** 2026-05-10
**Status:** Active

---

## What Is It?

Project-level routing SOP for Trinity. Supplements the PKG (COR-1103) and USR (ALF-2207) routing layers. Defines how to route tasks specific to Trinity: testing, linting, releasing, versioning, skill installation, model-ID management, evolve cycles, PR readiness, multi-agent review, and issue filing.

---

## Why

Trinity has concrete operational tasks (test, lint, release, version bump) that need consistent, repeatable workflows. Without a PRJ routing document, `af guide` has no project context and contributors must infer the correct steps ad hoc.

---

## When to Use

- At the start of any Trinity development session
- When deciding which SOP to follow for a given task (see Decision Tree below)

## When NOT to Use

- For tasks already covered by COR (general lifecycle: PRP, CHG, ADR)
- For tasks unrelated to Trinity development

---

## Project Context

- **Language:** Python 3.6+
- **Test runner:** pytest (via `.venv` — `uv venv` + `uv pip install pytest`)
- **Package structure:** `scripts/` → `~/.claude/skills/trinity/scripts/`, `providers/` → `~/.claude/agents/`, `SKILL.md` → `~/.claude/skills/trinity/`
- **Version source of truth:** `VERSION` file at repo root (single line, semver e.g. `1.0.0`)
- **Release mechanism:** git tag + GitHub Release
- **VCS:** git, hosted at `github.com/frankyxhl/trinity`

---

## Project Decision Tree

```
Start: what kind of task is this?

1. Running / writing tests?
   └── TRN-1001 (Test SOP) — pytest tests/ -v

2. Linting / formatting code?
   └── TRN-1002 (Lint SOP) — ruff check + ruff format

3. Bumping version?
   └── TRN-1003 (Version Bump SOP) — update CHANGELOG + make bump (unstaged)

4. Cutting a release?
   └── TRN-1004 (Release SOP) — make release-prep (local) + push tag (CI publishes via TRN-2006)

5. Installing Trinity locally?
   └── TRN-1005 (Install SOP) — copy SKILL.md + scripts/ + providers/ to ~/.claude/

6. Pinning / updating a provider model ID? (e.g. deepseek-v4-pro → deepseek-v4-pro[1m])
   └── TRN-1006 (Provider Model IDs SOP) — bracket-suffix convention,
       where each provider's model ID lives, update steps + shell-quoting guard rails

7. Auditing the repo / running an evolve cycle / pre-release tightening?
   └── TRN-1801 (Evolve Trinity SOP) — 6-step Signal → Candidate → Eval → Impl → Review → PR
       → Uses TRN-1800 weights and signal sources (PRJ override of COR-1800)
       → Trigger: "run evolve", "audit trinity", before any minor/major release,
                  or > 2 months since last evolve cycle

8. Opening a PR / pre-PR readiness check?
   └── TRN-1007 (PR Readiness SOP) — branch hygiene, tests/lint green, CHANGELOG updated, PR body checklist

9. Running a full PR cycle / auto-pick / orchestrating an issue?
   └── TRN-1008 (Multi-Agent Review Loop) — end-to-end loop:
       auto-pick → branch → plan → panel-review → dispatch → verify → PR → iterate → handoff

10. Filing a new issue / bug report / feature request?
    └── TRN-1009 (Issue Filing SOP) — ISSUE_TEMPLATE field-label alignment, repro steps, acceptance criteria

11. New feature / design work?
    └── COR-1102 (PRP) → COR-1602 strict review → COR-1101 (CHG)

12. Bug / incident?
    └── INC → COR-1101 (CHG)

13. Code change (any)?
    └── COR-1500 (TDD) overlay always applies
```

---

## Coverage audit

Run periodically (and as part of TRN-1801 evolve signal collection) to confirm every TRN SOP file on disk has a corresponding routing entry in the Decision Tree above:

```bash
# Both sides canonicalized to TRN-NNNN tokens. LHS is filename-based (only actual
# SOP files: 4-digit ACID + literal -SOP-), excluding TRN-1000 itself (the routing
# doc has no self-routing entry by design). RHS is Decision-Tree-scoped (range
# stops BEFORE the Coverage audit section so the audit's own prose / snippet
# filename can't false-positive). `comm -23` reports tokens present in LHS but
# missing from RHS — i.e., SOP files on disk with no routing entry.
comm -23 \
  <(ls rules/TRN-[0-9][0-9][0-9][0-9]-SOP-*.md \
     | grep -v 'TRN-1000-SOP-Workflow-Routing' \
     | grep -oE 'TRN-[0-9]+' | sort -u) \
  <(sed -n '/^## Project Decision Tree/,/^## Coverage audit/p' \
       rules/TRN-1000-SOP-Workflow-Routing-PRJ.md \
     | grep -oE 'TRN-[0-9]+' | sort -u)
```

**Expected output**: empty. Non-empty output = a TRN SOP file exists on disk without a corresponding Decision Tree routing entry. That is a drift defect; add the routing entry in the same PR that adds the SOP.

---

## Project Golden Rules

```
VERSION file is the single source of truth — update it first, scripts follow
Never release without tests passing (TRN-1001 must be green)
Never release without lint passing (TRN-1002 must be clean)
Release = tag + GitHub Release notes + CHANGELOG entry
Makefile targets map 1:1 to SOPs: make test → TRN-1001, make lint → TRN-1002, etc.
```

---

## Steps

This is a routing SOP — no procedural steps. See the Project Decision Tree above to find the applicable SOP, then follow it.

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Frank + Claude Code |
| 2026-04-26 | Decision tree path 4: release flow now `release-prep` + CI (TRN-2006) | Claude Opus 4.7 |
| 2026-04-26 | Decision tree: add path 6 (TRN-1006 model-ID pinning) and path 7 (TRN-1801 evolve cycle); shift feature/incident/TDD paths to 8/9/10 | Claude Opus 4.7 |
| 2026-05-10 | Decision tree: add paths 8 (TRN-1007 PR readiness), 9 (TRN-1008 multi-agent review loop), 10 (TRN-1009 issue filing); shift feature/incident/TDD paths to 11/12/13; add Coverage audit section with drift-detection snippet | Claude Opus 4.7 |

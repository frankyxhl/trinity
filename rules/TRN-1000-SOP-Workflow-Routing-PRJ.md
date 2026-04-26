# SOP-1000: Workflow Routing PRJ — Trinity

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-03-21
**Last reviewed:** 2026-03-21
**Status:** Active

---

## What Is It?

Project-level routing SOP for Trinity. Supplements the PKG (COR-1103) and USR (ALF-2207) routing layers. Defines how to route tasks specific to Trinity: testing, linting, releasing, versioning, and skill installation.

---

## Why

Trinity has concrete operational tasks (test, lint, release, version bump) that need consistent, repeatable workflows. Without a PRJ routing document, `af guide` has no project context and contributors must infer the correct steps ad hoc.

---

## When to Use

- At the start of any Trinity development session
- When running tests, linting, releasing, or bumping version
- When deciding which SOP to follow for a given task

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
   └── TRN-1001 (Test SOP) — pytest trinity/tests/ -v

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

8. New feature / design work?
   └── COR-1102 (PRP) → COR-1602 strict review → COR-1101 (CHG)

9. Bug / incident?
   └── INC → COR-1101 (CHG)

10. Code change (any)?
    └── COR-1500 (TDD) overlay always applies
```

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

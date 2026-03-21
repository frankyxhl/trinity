# CHG-2001: Release Infrastructure

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Last updated:** 2026-03-21
**Last reviewed:** 2026-03-21
**Status:** In Progress
**Date:** 2026-03-21
**Requested by:** Frank
**Priority:** Medium
**Change Type:** Normal
**Related:** CSA-2307 (PRP, Approved), CSA-2306 (Scripts CHG, Completed)

---

## What

Implement release infrastructure per CSA-2307 (Approved).

1. `VERSION` — semver single source of truth (repo root, initial: `1.0.0`)
2. `CHANGELOG.md` — Keep a Changelog format, initial v1.0.0 entry
3. `Makefile` — 6 targets: setup, test, lint, install, bump, release
4. `scripts/__init__.py` — add `__version__ = "1.0.0"` constant
5. `scripts/session.py`, `config.py`, `discover.py`, `install.py` — add `__version__` import via `importlib.util` fallback
6. `SKILL.md` — `REQUIRED_VERSION` managed by `make bump`; fix reinstall guidance
7. `rules/TRN-1001` through `TRN-1005` — 5 operational SOP files
8. `rules/TRN-0000` — add TRN-1001 through TRN-1005 to document index
9. `rules/TRN-1000` — update decision tree descriptions for TRN-1003/TRN-1004
10. `.gitignore` — exclude `__pycache__/`, `*.pyc`, `.venv/`

---

## Why

CSA-2307 PRP approved (Codex 9.5/PASS, Gemini 10.0/PASS). No version tracking, no release process, no Makefile, no CHANGELOG, no operational SOPs.

---

## Impact Analysis

- **Systems affected:** `trinity/` repo only
- **Downtime required:** No
- **Rollback plan:** All files revertible via git

---

## Implementation Plan

Per COR-1500 (TDD): tests first where applicable, then implementation.

1. Add `.gitignore`
2. Create `VERSION` file
3. Create `CHANGELOG.md`
4. Create `Makefile`
5. Update `scripts/__init__.py` — add `__version__` constant
6. Update `scripts/session.py`, `config.py`, `discover.py`, `install.py` — add `importlib.util` import
7. Update `SKILL.md` — fix `REQUIRED_VERSION` sed pattern + reinstall guidance
8. Create `rules/TRN-1001` through `rules/TRN-1005`
9. Update `rules/TRN-0000` and `rules/TRN-1000`
10. Run `pytest tests/ -v` — all green
11. Code review (Codex + Gemini, COR-1602)
12. `git push`

---

## Approval

- [x] Pre-approved via CSA-2307 PRP (Codex 9.5/PASS, Gemini 10.0/PASS, 2026-03-21)

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-03-21 | CHG created, PRP approved | Ready for implementation |

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |

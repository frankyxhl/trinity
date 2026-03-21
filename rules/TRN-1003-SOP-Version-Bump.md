# SOP-1003: Version Bump — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Human preparation step before `make release`. Updates CHANGELOG and bumps version in all files.

---

## Steps

0. **Prerequisite:** Ensure all non-release files are clean (no unstaged modifications). Commit or stash any unrelated work first.
1. Decide new version (semver: MAJOR for breaking, MINOR for new feature, PATCH for fix)
2. Update `CHANGELOG.md`: rename `[Unreleased]` to `[x.y.z] - YYYY-MM-DD`, add new empty `[Unreleased]` section above it
3. Run `make bump VERSION=x.y.z` — updates `VERSION`, `scripts/__init__.py`, and `SKILL.md`
4. Do not commit — `make release` stages and commits all 4 files together
5. Worktree will be dirty (CHANGELOG.md + VERSION + __init__.py + SKILL.md modified, all unstaged) — expected

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |

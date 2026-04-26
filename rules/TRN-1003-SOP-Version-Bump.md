# SOP-1003: Version Bump — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-04-26
**Last reviewed:** 2026-04-26
**Status:** Active

---

## What Is It?

Human preparation step before `make release-prep` (TRN-1004). Updates CHANGELOG and bumps version in all files.

---

## Steps

0. **Prerequisite:** All feature code and tests MUST be committed first. Run `git status` — only release files (CHANGELOG, VERSION, __init__.py, SKILL.md) should change after this point. If there are unstaged `.py` or test files, commit them before proceeding.
1. Decide new version (semver: MAJOR for breaking, MINOR for new feature, PATCH for fix)
2. Update `CHANGELOG.md`: rename `[Unreleased]` to `[x.y.z] - YYYY-MM-DD`, add new empty `[Unreleased]` section above it
3. Run `make bump VERSION=x.y.z` — updates `VERSION`, `scripts/__init__.py`, and `SKILL.md`. Also runs `make build` (TRN-2004) to regenerate `providers/*.md` from `*.delta.md` + `_base/` partials. If providers/ has uncommitted regenerated content, commit it before continuing — the release commit only stages release-metadata files.
4. Do not commit the metadata files — `make release-prep` (TRN-1004) stages and commits all 4 files together as `Release vX.Y.Z` and creates the local tag
5. Worktree will be dirty (CHANGELOG.md + VERSION + __init__.py + SKILL.md modified, all unstaged) — expected. Proceed to TRN-1004.

**Portable in-place rewrite:** `make bump` uses `perl -i -pe` (cross-platform: macOS BSD + Linux GNU) to rewrite `__version__` in `scripts/__init__.py` and `REQUIRED_VERSION` in `SKILL.md`. The prior BSD-only `sed -i ''` form would fail on Linux because GNU sed treats `''` as the input file path. Regression test: `tests/test_make_bump.sh` (T1 = portable rewrite semantics; T2 = static guard against re-introducing the BSD-only form). Wired into `make test`.

The release workflow (TRN-2006) still does not call `make bump` — release-time version edits are made before pushing the tag, not from inside CI — but the portability fix removes a contributor-side trap on Linux dev machines.

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |
| 2026-04-03 | Strengthen Step 0: explicit commit-first requirement | Claude Code |
| 2026-04-25 | Note `make build` runs as part of `make bump` (TRN-2004) | Claude Opus 4.7 |
| 2026-04-26 | TRN-1801 evolve cycle 1: replace stale `sed -i ''` note with `perl -i -pe` (matches C1 Makefile fix) + reference `tests/test_make_bump.sh`. Add `Last reviewed`. | Claude Opus 4.7 |
| 2026-04-26 | Step 4: `make release` → `make release-prep` (TRN-2006); add BSD-sed warning | Claude Opus 4.7 |

# SOP-1004: Release — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Cut a GitHub release: test → lint → commit → tag → push → gh release.

---

## Prerequisites

- All feature code and tests committed (`git status` shows only release files dirty)
- TRN-1003 completed (CHANGELOG updated, `make bump` run, 4 files unstaged)
- `providers/*.md` is up-to-date with `*.delta.md` + `_base/` partials (TRN-2004) — `make verify-built` exits 0
- `gh auth status` shows authenticated

## Steps

1. Complete TRN-1003 first
2. Verify `gh auth status` shows authenticated
3. Run `make release` — automatically runs verify-built (TRN-2004) + test (TRN-1001) + lint (TRN-1002); abort on any failure. Asserts `providers/` has no uncommitted changes before staging release files.
4. Verify GitHub Release page at `github.com/frankyxhl/trinity/releases/tag/vx.y.z`

## Recovery

- Branch push fails: `git reset HEAD` to unstage, fix push issue, then `make release`
- Tag push fails: `git push origin vx.y.z`
- gh release fails: `gh release create vx.y.z --title vx.y.z --notes "..."`

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |
| 2026-04-03 | Add explicit prerequisite: commit code before release | Claude Code |
| 2026-04-25 | Add `make verify-built` prerequisite + step (TRN-2004) | Claude Opus 4.7 |

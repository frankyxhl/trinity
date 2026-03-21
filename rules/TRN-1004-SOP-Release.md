# SOP-1004: Release — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Cut a GitHub release: test → lint → commit → tag → push → gh release.

---

## Prerequisites

- TRN-1003 completed (CHANGELOG updated, `make bump` run, 4 files unstaged)
- `gh auth status` shows authenticated

## Steps

1. Complete TRN-1003 first
2. Verify `gh auth status` shows authenticated
3. Run `make release` — automatically runs test (TRN-1001) + lint (TRN-1002); abort on any failure
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

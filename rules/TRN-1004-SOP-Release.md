# SOP-1004: Release — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-04-26
**Status:** Active

---

## What Is It?

Cut a GitHub release. Local steps prepare the release commit + tag; CI publishes the GitHub Release on tag push. Per TRN-2006, `make release` was replaced by `make release-prep` (local-only) plus `.github/workflows/release.yml` (CI publishing).

---

## Prerequisites

- All feature code and tests committed (`git status` shows only release-metadata files dirty)
- TRN-1003 completed (CHANGELOG updated, `make bump VERSION=x.y.z` run, 4 files unstaged)
- `providers/*.md` is up-to-date with `*.delta.md` + `_base/` partials (TRN-2004) — `make verify-built` exits 0
- Branch is on `main` (or about to merge to `main` via PR — see Step 1)
- One-time setup: tag-protection rules in repo settings restrict `v[0-9]+.[0-9]+.[0-9]+` to maintainers (see TRN-2006 §D8)

---

## Steps

1. **Land the release-metadata commit on `main`** (one of two paths):
   - **Direct push (maintainer with push access):** run `make release-prep` from `main`, then `git push origin main vX.Y.Z`
   - **PR-from-fork (contributor):** open a "Release vX.Y.Z" PR; on merge, locally `git fetch && git checkout main && git pull`, then `git tag vX.Y.Z <merge-commit-sha>` and `git push origin vX.Y.Z` (someone with push access does this)
2. **`make release-prep`** runs:
   - `make verify-built` (TRN-2004) + `make test` (TRN-1001) + `make lint` (TRN-1002)
   - Asserts `providers/` clean
   - Stages 4 metadata files + commits `Release vX.Y.Z` + creates local tag `vX.Y.Z`
   - **Does NOT push, does NOT call `gh release create`** — that's CI's job
3. **Push branch + tag**: `git push origin <branch> vX.Y.Z` (single command pushes both refs)
4. **Watch CI**: `github.com/frankyxhl/trinity/actions` — the `Release` workflow validates tag↔VERSION + tag-on-main + verify-built/test/lint, extracts CHANGELOG section, and runs `gh release create`. Typical runtime ~3 min.
5. **Verify**: `github.com/frankyxhl/trinity/releases/tag/vX.Y.Z` exists with extracted notes

## Recovery

| Failure | Recovery |
|---------|----------|
| `make release-prep` fails (test/lint/verify-built) | Fix root cause, `git reset HEAD~1` if commit was made, retry |
| Branch push fails (auth) | Fix SSH/HTTPS auth, then `git push origin <branch> vX.Y.Z` |
| Tag push succeeds but CI never triggers | Check tag matches `v[0-9]+.[0-9]+.[0-9]+` exactly (no `-rc1`, no `v1.2`) — workflow only triggers on strict semver |
| CI fails before publish (validation, test, lint) | Fix on `main` via new PR; bump patch version; new release-prep + tag |
| CI fails AT publish (`gh release create` 5xx) | Use **workflow_dispatch**: Actions tab → `Release` → "Run workflow" → enter `tag_name=vX.Y.Z`. Same pre-flight runs; safe to retry. |
| Tag already exists in remote, want to re-publish | NEVER force-overwrite a tag. If release was never created: use workflow_dispatch. If you must re-tag from a different commit: `git push --delete origin vX.Y.Z` first (destructive, breaks anyone who fetched the old tag) |

---

## Notes

- `make release` no longer exists. If muscle memory makes you type it: `make` will print "No rule to make target 'release'" — that's the intended footgun-prevention.
- `workflow_dispatch` is the documented retry path; never delete + re-push a tag to "rerun" CI.
- The publish job's `GITHUB_TOKEN` has only `contents: write` (least privilege). No PAT needed.

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |
| 2026-04-03 | Add explicit prerequisite: commit code before release | Claude Code |
| 2026-04-25 | Add `make verify-built` prerequisite + step (TRN-2004) | Claude Opus 4.7 |
| 2026-04-26 | Full rewrite: `make release` → `make release-prep` + CI publish (TRN-2006) | Claude Opus 4.7 |

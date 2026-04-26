# SOP-1004: Release — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-04-26
**Status:** Active

---

## What Is It?

Cut a GitHub release. The release pipeline lives entirely in `.github/workflows/release.yml` (TRN-2006). Per TRN-2007 there are now three entry points: a **one-click** UI button (recommended), tag push, and `workflow_dispatch` retry.

---

## Prerequisites

- All feature code and tests committed (`git status` clean)
- TRN-1003 completed on `main`: `CHANGELOG.md` has a non-empty `## [X.Y.Z]` section, `VERSION` / `scripts/__init__.py` / `SKILL.md` reflect `X.Y.Z`. (Easiest path: a "Release vX.Y.Z" PR with these 4 files, merged to main.)
- `providers/*.md` is up-to-date with `*.delta.md` + `_base/` partials (TRN-2004) — `make verify-built` exits 0
- One-time setup: tag-protection ruleset in repo settings (see TRN-2007 §D11). Pattern `v[0-9]*.[0-9]*.[0-9]*` (fnmatch — GitHub Rulesets do NOT support regex `+`). Bypass list MUST include **Repository admin** with `Always` mode for Path B (maintainer CLI tag push). **Path A constraint on personal repos**: GitHub Actions integration cannot be added to ruleset bypass on personal repos — Path A requires either a `RELEASE_TAG_PAT` repo secret (PAT-based push, see TRN-2007 §D11) or removing the ruleset. Path C (retry existing tag, no push) is unaffected.

---

## Path A — One-click (recommended)

Use this when the Release PR is merged to main and you want to publish.

1. Open https://github.com/frankyxhl/trinity/actions/workflows/release.yml
2. Click **"Run workflow"** in the top-right
3. **Branch: `main`** (default). **Leave the `tag_name` field empty.**
4. Click **"Run workflow"**

CI then: validates tag/VERSION agreement → runs verify-built/test/lint → extracts the CHANGELOG section → creates and pushes the tag → publishes the GitHub Release. ~3 min total.

5. Verify: https://github.com/frankyxhl/trinity/releases/tag/vX.Y.Z

## Path B — Tag push (CLI for power users)

Equivalent to Path A but driven from the terminal. Useful if you're already in a shell or need to script.

1. From `main` after the Release PR has merged:
   ```bash
   git fetch origin
   git checkout main && git pull --ff-only
   git tag vX.Y.Z origin/main
   git push origin vX.Y.Z
   ```
2. Watch the same workflow at the same URL. Same ~3 min runtime, same result.

## Path C — Retry an existing tag (operator failure recovery)

Use this only when the workflow ran for a tag but failed before/at publish (e.g., `gh release create` 5xx) and the GitHub Release does NOT yet exist.

1. https://github.com/frankyxhl/trinity/actions/workflows/release.yml → **Run workflow**
2. Set `tag_name` to the existing tag (e.g., `v1.7.0`). Branch dropdown is irrelevant in this path.
3. Click Run.

Same pre-flight runs. Workflow fails cleanly with "Release vX.Y.Z already exists" if the release was already published — safe to invoke without checking.

## Local helper: `make release-prep`

`make release-prep` is provided for maintainers who prefer to bundle bump-commit-tag locally before pushing. It runs verify-built/test/lint, commits `Release vX.Y.Z`, and creates a local tag. **It does NOT push and does NOT publish** — you still go through one of the paths above to actually release. Optional convenience target; not required.

## Recovery

| Failure | Recovery |
|---------|----------|
| One-click fails: "Tag X already exists" | Bump VERSION (TRN-1003) on `main` via another PR, then click Run again. The tag-already-exists error means the version on main was already released. |
| One-click fails before publish (test/lint/build) | Fix root cause on `main` via PR; if CHANGELOG/VERSION need to change, do a new bump PR. Re-trigger Path A. |
| One-click fails AT publish (`gh release create` 5xx) | Tag is already on remote. Use **Path C** (retry with explicit `tag_name`). |
| Tag push triggered nothing | Tag must match `v[0-9]+.[0-9]+.[0-9]+` exactly (no `-rc1`, no `v1.2`). |
| Tag already exists in remote and you must re-tag from a different commit | Destructive. `git push --delete origin vX.Y.Z` first (breaks anyone who fetched the old tag), then push fresh. Avoid if any release notes referenced the old tag. |

---

## Notes

- `make release` no longer exists (TRN-2006). Calling it prints `make: *** No rule to make target 'release'` — intended footgun-prevention.
- All paths converge at the same publish step. The pre-flight checks (semver regex, tag↔VERSION, tag-on-main, CHANGELOG section non-empty) run identically regardless of entry point.
- Workflow uses the auto-issued `GITHUB_TOKEN` only — no PAT, no OIDC, no secrets. Tag pushes still go through repository tag-protection rulesets.

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |
| 2026-04-03 | Add explicit prerequisite: commit code before release | Claude Code |
| 2026-04-25 | Add `make verify-built` prerequisite + step (TRN-2004) | Claude Opus 4.7 |
| 2026-04-26 | Full rewrite: `make release` → `make release-prep` + CI publish (TRN-2006) | Claude Opus 4.7 |
| 2026-04-26 | Add Path A (one-click), restructure into A/B/C paths (TRN-2007) | Claude Opus 4.7 |

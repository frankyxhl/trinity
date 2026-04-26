# CHG-2006: Release-on-tag GitHub Action

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-04-26
**Status:** In Progress
**Requested by:** Frank
**Priority:** Medium
**Change Type:** Standard
**Implementer:** Claude Opus 4.7
**Related:** Issue #2 (frankyxhl/trinity#2)

---

## What

Replace the local `make release` "push + tag + create release" workflow with a GitHub Actions workflow that fires on tag push (and `workflow_dispatch` for manual retry) and publishes the GitHub Release automatically. The local Makefile target `release` is removed and replaced with `release-prep` which only does the bump-commit-tag-locally part.

| File | Action |
|------|--------|
| `.github/workflows/release.yml` | New — semver tag trigger + workflow_dispatch fallback, runs verify/test/lint, extracts CHANGELOG section, calls `gh release create` |
| `tests/test_release_workflow.sh` | New — YAML structural assertions + CHANGELOG extraction fixtures + semver regex cases |
| `tests/fixtures/changelogs/` | New — 4 fixture CHANGELOG files for the awk extractor (full / last / missing / header-only) |
| `Makefile` | Replace `release` target with `release-prep`; `setup` target uses uv→pip fallback |
| `rules/TRN-1003-SOP-Version-Bump.md` | Step 4 rewritten — `make release-prep` now stages/commits/tags |
| `rules/TRN-1004-SOP-Release.md` | Full rewrite — new flow PR-merge → release-prep → tag push → CI auto-publishes |
| `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` | Decision tree path 4 wording updated |
| `rules/TRN-0000-REF-Document-Index.md` | Add TRN-2006 |
| `CHANGELOG.md` | `[Unreleased]` entry |

---

## Why

`make release` bundled `git push` + `git tag` + `gh release create` into one local command requiring direct push access to `frankyxhl/trinity`. PR-from-fork contributors cannot complete a release. Surfaced concretely while landing PR #1 (TRN-2005, Release v1.6.0): the PR was openable via fork, but tag + GitHub Release still required a manual local step from the maintainer.

Issue #2 (https://github.com/frankyxhl/trinity/issues/2) captures the proposal. Per multi-model review (Codex gpt-5.5 + Gemini 3.1 Pro, both FAIL on initial draft, blockers folded into this CHG), routing was downgraded from `path 6 (PRP→review→CHG)` to `path 7 (incident-style direct CHG)` because the issue body + this design section already provide a complete proposal.

---

## Design Decisions

### D1 — Trigger surface

```yaml
on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'    # strict semver glob (rejects v1.2.3.4, v1.2, v1.2.3-rc1)
  workflow_dispatch:
    inputs:
      tag_name:
        description: 'Existing tag to (re)publish, e.g. v1.7.0'
        required: true
```

`workflow_dispatch` is the documented retry path when the auto-trigger fails (network blip, runner failure, partial publish). Same pre-flight runs; `gh release create` returns "already exists" → workflow fails cleanly without mutating state. **No tag delete/repush dance required.** (Decision per user, 2026-04-26.)

### D2 — Setup strategy: uv → pip fallback

Both `Makefile` and CI workflow use the same logic:

```bash
if command -v uv >/dev/null 2>&1; then
  uv venv && uv pip install pytest ruff
else
  python3 -m venv .venv && .venv/bin/pip install pytest ruff
fi
```

Local devs (and macOS) keep using uv (faster). CI installs uv via `astral-sh/setup-uv@v5` for parity. If `setup-uv` is ever unavailable, the fallback keeps things working.

### D3 — `make release` → `make release-prep`

`make release` is **deleted**, not deprecated. New `release-prep` target does only:

1. Run `make verify-built` + `make test` + `make lint`
2. Assert `providers/` clean and `VERSION` matches new bump
3. `git add VERSION scripts/__init__.py CHANGELOG.md SKILL.md` + `git commit -m "Release vX.Y.Z"` + `git tag vX.Y.Z`

It does **NOT** push, does **NOT** call `gh release create`. The caller pushes the branch + tag (`git push origin <branch> vX.Y.Z`); CI takes it from there.

Reasoning: keeping `release` as a deprecated alias would leave a footgun. Multiple maintainers might revert to muscle memory and skip CI.

### D4 — Token & permissions (least privilege)

```yaml
permissions:
  contents: read     # default for all jobs

jobs:
  release:
    permissions:
      contents: write  # only the publishing job can mutate release/tag refs
```

Uses the workflow's auto-issued `GITHUB_TOKEN`. No PAT, no secret, no OIDC. Third-party actions (`softprops/action-gh-release` etc.) are NOT used — direct `gh release create` only — to keep supply chain trivially auditable.

### D5 — Tag↔VERSION verification (CI side, defense in depth)

Even though the trigger glob already enforces semver, CI re-validates because `workflow_dispatch.inputs.tag_name` accepts arbitrary input:

```bash
TAG="${{ github.event.inputs.tag_name || github.ref_name }}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Bad tag: $TAG"; exit 1; }
VERSION_FILE=$(tr -d '[:space:]' < VERSION)            # strip newline + whitespace
[ "${TAG#v}" = "$VERSION_FILE" ] || {
  echo "Tag $TAG ≠ VERSION $VERSION_FILE"; exit 1; }
```

Tag must also resolve to a commit on `main` (not a stray branch):

```bash
git rev-parse "$TAG" >/dev/null
git merge-base --is-ancestor "$TAG" origin/main || {
  echo "Tag $TAG not on main"; exit 1; }
```

### D6 — CHANGELOG extraction (fail on empty)

```bash
NOTES=$(awk -v v="$VERSION_FILE" '
  $0 ~ "^## \\["v"\\]" {found=1; next}
  found && /^## \[/ {exit}
  found {print}
' CHANGELOG.md)
[ -n "$(echo "$NOTES" | tr -d '[:space:]')" ] || {
  echo "CHANGELOG section [$VERSION_FILE] missing or empty"; exit 1; }
```

Fixture-tested: full version, last version, missing version, header-only-no-body. All four cases live in `tests/fixtures/changelogs/`.

### D7 — Idempotency / failure modes

- **Re-trigger same tag (push or workflow_dispatch)**: pre-flight passes, `gh release create` fails with "already exists", workflow fails. State unchanged. Operator inspects existing release manually.
- **Pre-flight fails**: workflow fails before `gh release create`. Tag remains, no release created. Operator may delete tag (`git push --delete origin vX.Y.Z`) and re-tag from a fixed commit, OR fix the underlying issue (e.g., missing CHANGELOG section) on `main` and use `workflow_dispatch` to re-run.
- **`gh release create` fails after pre-flight passes**: rare (GitHub API issue). Workflow logs the error; operator runs `gh release create vX.Y.Z --notes-file -` manually with the extracted notes (notes are written to a job artifact for retrieval).

### D8 — Protected tags (out of workflow, in operations)

The workflow does not enforce who can push tags — that's a **GitHub Repository Rulesets** concern. Required setup (one-time, manual):

```bash
# Repo Settings → Rules → Rulesets → New ruleset
# Target: Tags matching v[0-9]+.[0-9]+.[0-9]+
# Bypass: maintainers only
# Restrict creations + restrict updates + restrict deletions
```

Without this, anyone with write access can publish a release by pushing a tag. CHG documents it; first-release runbook checks it.

### D9 — Makefile `bump` BSD-sed footgun

Current `Makefile:63-64`:
```makefile
@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' scripts/__init__.py
@sed -i '' 's/REQUIRED_VERSION=".*"/REQUIRED_VERSION="$(VERSION)"/' SKILL.md
```

`sed -i ''` is BSD syntax; fails on Linux GNU sed. `make bump` is a **local-only** operation — CI must NEVER call it. Workflow explicitly avoids it. CHG flags this; future portability fix is out of scope (separate ticket if desired).

---

## Impact Analysis

- **Systems affected:** Trinity release pipeline. No code/runtime changes to providers or skill itself.
- **Behavior change:** Maintainers no longer run `make release`. New flow: `make release-prep` locally → `git push origin main vX.Y.Z` → wait for CI → verify Release page.
- **Downtime:** None. Existing releases (1.0.0–1.6.0) untouched.
- **Rollback:** Re-add `release` target to Makefile + revert SOPs (3 files). `.github/workflows/release.yml` deletion stops auto-publish. Plan: keep PR #1 (this PR) revertable as a single git revert.

---

## Implementation Plan

Per COR-1500 (TDD): tests first where applicable.

1. Write `tests/fixtures/changelogs/` (4 cases) + `tests/test_release_workflow.sh`
2. Write `.github/workflows/release.yml`
3. Modify `Makefile`: remove `release`, add `release-prep`, change `setup` to uv→pip fallback
4. Verify `make test` (now includes new shell test) passes
5. Update SOPs: TRN-1003 step 4, TRN-1004 (full rewrite), TRN-1000 path 4 wording, TRN-0000 index
6. Update `CHANGELOG.md` `[Unreleased]`
7. Commit + push branch to fork + open PR
8. After merge: separate "Release v1.7.0" PR (bump only) → tag push → first end-to-end CI validation

---

## Approval

- [x] Reviewed by Codex (gpt-5.5, EFFORT=high) — initial FAIL on 4 blockers, all folded into this design
- [x] Reviewed by Gemini (3.1 Pro, EFFORT=high) — initial FAIL on 3 blockers, all folded into this design
- [x] User approved decisions D1–D4 (2026-04-26)

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-04-26 | CHG written, multi-model review consensus folded in | Ready for implementation |

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-04-26 | Initial version | Claude Opus 4.7 |

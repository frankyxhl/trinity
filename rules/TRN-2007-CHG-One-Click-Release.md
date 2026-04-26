# CHG-2007: One-click release via workflow_dispatch

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-04-26
**Status:** In Progress
**Requested by:** Frank
**Priority:** Low
**Change Type:** Standard
**Implementer:** Claude Opus 4.7
**Related:** TRN-2006 (Release-on-tag GitHub Action)

---

## What

Make `tag_name` input on `.github/workflows/release.yml`'s `workflow_dispatch` trigger optional. When omitted, the workflow derives the tag from `VERSION` on the dispatched ref, creates + pushes the tag, then publishes — turning the existing release pipeline into a "one-click" path. Existing tag-push and retry-with-tag-name flows are unchanged.

| File | Action |
|------|--------|
| `.github/workflows/release.yml` | `tag_name` `required: false` + new `Verify dispatched from main` guard step + new `Create + push tag` step (one-click path only) + extended `Resolve and validate tag` step to derive from VERSION |
| `tests/test_release_workflow.sh` | New T10 section covering one-click path: optional input, main-only guard, create-tag step, version-derivation logic |
| `rules/TRN-1004-SOP-Release.md` | One-click added as the primary path; tag-push and retry remain as alternative entry points |
| `rules/TRN-0000-REF-Document-Index.md` | Add TRN-2007 |
| `CHANGELOG.md` | `[Unreleased]` entry |

---

## Why

Per TRN-2006 the publish step is automated, but **tag creation is still manual** (`git tag vX.Y.Z origin/main && git push origin vX.Y.Z`). Two friction points:

1. **PR-from-fork contributors** can land code via PR but cannot complete a release — they need a maintainer to push the tag from a machine with SSH push access.
2. Even maintainers have to context-switch to a terminal after merging the Release PR.

A "click Run workflow in Actions UI" path solves both. No CLI required. No SSH key required. Branch protection + tag protection still apply (tag push still goes through the `GITHUB_TOKEN` write permission, gated by repo rulesets).

---

## Design Decisions

### D1 — Input semantics

`workflow_dispatch.inputs.tag_name` becomes optional. Behavior table:

| Trigger | `tag_name` | Behavior |
|---------|-----------|----------|
| `push: tags: 'v[0-9]+.[0-9]+.[0-9]+'` | n/a | Existing: validate + publish |
| `workflow_dispatch` | empty | **NEW**: derive `vX.Y.Z` from `VERSION` on dispatched ref → tag must NOT exist on remote → create + push tag → publish |
| `workflow_dispatch` | `v1.7.0` | Existing retry path: re-attempt publish for already-existing tag |

### D2 — Main-only guard for one-click

`workflow_dispatch` allows triggering from any branch (default-branch dropdown in the UI). To prevent accidentally cutting a release from a feature branch:

```yaml
- name: Verify dispatched from main (one-click path only)
  if: github.event_name == 'workflow_dispatch' && github.event.inputs.tag_name == ''
  run: |
    if [ "${{ github.ref }}" != "refs/heads/main" ]; then
      echo "::error::One-click release must be triggered from main, got ${{ github.ref }}"
      exit 1
    fi
```

The retry path (with explicit `tag_name`) is NOT main-gated — that path explicitly addresses an existing tag, so the dispatched branch is irrelevant.

### D3 — Tag-already-exists check happens early

In one-click path, if the tag derived from VERSION already exists on remote, fail in the resolve step (before running tests/lint) with a clear message:

> Tag $TAG already exists on remote. Did you forget to bump VERSION? Use the retry path (provide tag_name input) to re-publish an existing tag.

This catches the common mistake of clicking Run without bumping VERSION first, without burning ~3 min of CI time.

### D4 — Skip "Verify tag is on main" in one-click path

That step uses `git rev-parse "$TAG"` to confirm the tag exists. In one-click path the tag doesn't exist yet (we'll create it later in the workflow). Since the main-only guard already enforces we're on main, the tag we're about to create is trivially on main — skip the redundant check.

### D5 — Tag creation timing: after all checks pass

The `Create + push tag` step runs **after** verify-built/test/lint/extract-notes succeeded, **before** publish. This way:
- A failing test/lint never produces a stray tag
- A failing CHANGELOG extraction never produces a stray tag
- Publish failure leaves the tag on remote (operator can retry via the retry path — same as TRN-2006 today)

### D6 — Race protection at tag push time

Re-check `git ls-remote --tags origin "refs/tags/$TAG"` immediately before `git tag + git push`. If another workflow run pushed the same tag during our test window, fail cleanly rather than overwriting (`git push origin <tag>` would fail anyway without `--force`, but explicit check gives a clearer error).

### D7 — `make release-prep` unchanged

Local `make release-prep` continues to create a local tag. That tag is now optional (one-click doesn't need it pushed) — but harmless. People who prefer the CLI flow can keep using `git push origin <branch> vX.Y.Z`. Both paths converge at the same publish step.

### D8 — Token & permissions (revised 2026-04-26 after multi-model review)

Multi-model review (Codex + Gemini, both FAIL on initial draft) flagged that the original single-job design exposed `contents: write` to every step including third-party actions like `astral-sh/setup-uv`. Restructured into 2 jobs (D9). Tag pushes via `GITHUB_TOKEN` are subject to the tag-protection ruleset (D11); the workflow's identity must be on the bypass list for one-click to succeed.

### D9 — 2-job split for least-privilege (added per Codex blocker)

Restructured into:

- **`verify` job** — `permissions: contents: read`. Runs checkout, semver/VERSION validation, `make verify-built`/`test`/`lint`, CHANGELOG extraction, artifact upload. Third-party actions (`astral-sh/setup-uv@v6`) cannot push tags or mutate releases because the job's `GITHUB_TOKEN` is read-only.
- **`publish` job** — `permissions: contents: write`. `needs: verify`. Only first-party `actions/checkout@v6` + `actions/download-artifact@v5`. Steps: optional checkout (one-click only), download release-notes artifact, `git tag + push` (one-click only), `gh release create`.

Job outputs (`tag`, `version`, `one_click`) flow from verify to publish via `needs.verify.outputs.*`. Release notes flow via uploaded artifact.

### D10 — `concurrency:` key (added per Gemini blocker)

```yaml
concurrency:
  group: release
  cancel-in-progress: false
```

At most one Release workflow runs at a time. Two simultaneous one-click dispatches for the same tag would otherwise burn ~3 min CI before colliding at `git push`. `cancel-in-progress: false` because we never want to interrupt an in-flight publish.

### D11 — Tag-protection ruleset bypass requirement (clarified per both reviewers)

The original TRN-2006 §D8 said "configure tag protection" without specifying bypass mechanics. Both reviewers caught that without explicit bypass for the workflow's identity, the one-click path's `git push origin "$TAG"` would 403.

**Required configuration** (one-time, per repo):

1. Settings → Rules → Rulesets → New tag ruleset
2. **Target tags pattern**: `v[0-9]*.[0-9]*.[0-9]*`
   - ⚠️ GitHub Rulesets use **fnmatch (glob) syntax**, NOT regex. The `+` quantifier from regex is unsupported here. `[0-9]*` in fnmatch means "one digit followed by any chars" — slightly more permissive than the workflow trigger filter (which uses GitHub workflow-filter syntax that DOES support `+`), but the divergence is safe: tags like `v1.2.3` are covered by both, oddly-named tags like `v1abc.2.3` would be protected (no harm) but wouldn't trigger publish.
3. Rules: Restrict creations + Restrict updates + Restrict deletions
4. Bypass list MUST include BOTH:
   - **Repository admin** role with `Always` mode — covers maintainers running Path B (CLI tag push)
   - **GitHub Actions** integration with `Always` mode — covers Path A workflow tag push (`github-actions[bot]` identity)

**Important**: The "GitHub Actions" bypass cannot be added via the Rulesets POST API directly — `gh api -X POST .../rulesets` with `actor_type: "Integration", actor_id: 15368` returns:

> Actor GitHub Actions integration must be part of the ruleset source or owner organization

It MUST be added through the UI: Settings → Rules → Rulesets → `<your ruleset>` → "Add bypass" → search `GitHub Actions` → mode `Always` → Save.

Without the GitHub Actions bypass, Path A (`workflow_dispatch` empty `tag_name`) fails at the `Create + push tag` step with HTTP 403. Path B (CLI tag push by maintainer with admin bypass) and Path C (retry existing tag, no push) are unaffected.

**Reference configuration** (frankyxhl/trinity, 2026-04-26): ruleset id 15562010, target `refs/tags/v[0-9]*.[0-9]*.[0-9]*`, bypass `RepositoryRole id 5 (admin) Always` + `GitHub Actions integration Always` (added via UI).

### D12 — Context-injection hardening (per Gemini)

All `${{ github.* }}` and `${{ github.event.* }}` references inside `run:` blocks are passed via `env:` mapping rather than inlined into shell strings. While these are GitHub-controlled metadata (not user input), this matches GitHub's documented best practice and reduces audit-flag noise. Affected steps: `Verify dispatched from main` (GITHUB_REF), `Resolve and validate tag` (INPUT_TAG / EVENT_NAME / REF_NAME), `Verify tag is on main` / `Create + push tag` / `Publish GitHub Release` (TAG).

`gh release create` also gets explicit `--repo "$GITHUB_REPOSITORY"` to avoid implicit-context surprises.

---

## Impact Analysis

- **Systems affected:** Trinity release pipeline only.
- **Behavior change:** New entry point. Existing tag-push and retry paths unchanged.
- **Downtime:** None.
- **Rollback:** Revert this PR's commit. Existing tag-push flow continues to work uninterrupted.
- **Compatibility:** The workflow file is on `main`, used by maintainers only. No external consumer behavior changes.

---

## Implementation Plan

1. Modify `.github/workflows/release.yml` per D1–D12 (initial draft D1–D8; D9–D12 added after multi-model review)
2. Add T10 + T11 test sections to `tests/test_release_workflow.sh`
3. `make verify-built` + `make test` + `make lint` all green
4. Rewrite TRN-1004 SOP to lead with one-click, retain tag-push and retry as alternatives
5. Update TRN-0000 + CHANGELOG
6. Open PR — first end-to-end validation comes when you (post-merge) configure the bypass ruleset (D11) and click Run workflow on a future Release PR

---

## Approval

- [x] Skip PRP per user — issue body + design section sufficient (consistent with TRN-2005 / TRN-2006 routing)
- [x] User approved design (2026-04-26): main-only guard, skip-PRP, direct CHG
- [x] Multi-model review post-implementation (Codex + Gemini, both FAIL on initial draft) — blockers folded into D9–D12 + 17 new T11 assertions; user approved follow-up fixes 2026-04-26

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-04-26 | CHG written, initial implementation (D1–D8) | Ready for review |
| 2026-04-26 | Multi-model review (Codex + Gemini) | FAIL — 4 blockers folded into D9–D12 |
| 2026-04-26 | Restructured into 2-job verify/publish split, added concurrency, env-mapping, ruleset bypass docs | Ready for merge once tag ruleset configured per D11 |

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-04-26 | Initial version (D1–D8) | Claude Opus 4.7 |
| 2026-04-26 | Add D9 (2-job split) + D10 (concurrency) + D11 (ruleset bypass) + D12 (env-mapping) per multi-model review | Claude Opus 4.7 |

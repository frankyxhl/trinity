# CHG-3043: Archive Completed PRPs

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-18
**Last reviewed:** 2026-05-18
**Status:** Proposed
**Date:** 2026-05-18
**Requested by:** @frankyxhl via issue #75
**Priority:** Low
**Change Type:** Documentation cleanup
**Targets:** `main`
**Closes:** #75

---

## What

Move completed PRP records out of the active `rules/` list into
`rules/archive/`:

- `TRN-2002-PRP-Remote-Install-Script.md`
- `TRN-2008-PRP-Remove-Zsh-Dependency.md`
- `TRN-2010-PRP-Codex-Review-Adapter.md`

Regenerate `TRN-0000` so the active document index no longer lists archived
PRPs, and add a changelog entry. As a prerequisite cleanup, reconcile stale CHG
headers for TRN-2003 and TRN-2009 from `In Progress` to `Completed`; their
implemented artifacts are already present in the repository.

## Why

The active `rules/` directory currently mixes live planning documents with PRPs
whose matching CHGs have already shipped. Keeping superseded PRPs in the active
index makes `af list` noisier and invites readers to treat old proposal text as
current work. Archiving preserves the historical record while reducing active
navigation clutter.

## Out of Scope

- Merging PRP text into matching CHGs.
- Archiving active PRPs or CHGs.
- Changing Alfred archive semantics beyond using `rules/archive/` as a normal
  repository folder.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| S1 | `rules/archive/` | New directory containing the three completed PRPs moved with `git mv`. |
| S2 | `rules/TRN-2003-CHG-Remote-Install-Script.md` | Status reconciled to `Completed`; change-history note added. |
| S3 | `rules/TRN-2009-CHG-Remove-Zsh-Dependency.md` | Status reconciled to `Completed`; change-history note added. |
| S4 | `rules/TRN-0000-REF-Document-Index.md` | Regenerated after archive move and new CHG. |
| S5 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry for the archive cleanup. |

## Acceptance Criteria

- [ ] `rules/archive/` exists.
- [ ] The three PRP files are moved via `git mv` and no longer live in the
  active `rules/` root.
- [ ] TRN-2003 and TRN-2009 status headers say `Completed`.
- [ ] `af list --root .` no longer shows TRN-2002, TRN-2008, or TRN-2010 in the
  active PRJ list.
- [ ] `af validate --root .` passes.
- [ ] CHANGELOG `[Unreleased] ### Changed` entry added.

## Implementation Order

1. Create `rules/archive/` and `git mv` the three PRPs.
2. Reconcile stale CHG status headers for TRN-2003 and TRN-2009.
3. Regenerate `TRN-0000` with `af index --root .`.
4. Add CHANGELOG entry.
5. Validate `af list`, `af validate`, and `git diff --check`.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-18 | Initial draft. Direct continuation from TRN-1008 queue pick; #75 selected after #82/#81 were triaged as no-op/wontfix. | Codex |

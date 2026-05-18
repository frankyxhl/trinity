# CHG-3043: Deduplicate Codex Skill Copies

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-18
**Last reviewed:** 2026-05-18
**Status:** Approved
**Date:** 2026-05-18
**Requested by:** @frankyxhl via issue #76
**Priority:** Medium
**Change Type:** Build / packaging refactor
**Targets:** `main`
**Closes:** #76

---

## What

Make `.agents/skills/trinity/SKILL.md` the source of truth for the Codex skill text and generate `plugins/trinity/skills/trinity/SKILL.md` from it during the build.

Add a drift check so the committed plugin copy must stay byte-identical to the source file. The existing `make build`, `make verify-built`, `make test`, release workflow, and pre-commit hook become the enforcement path.

The existing `tests/test_codex_compat.py` byte-identity assertion remains as defense in depth; this CHG adds the build-time generator and a negative drift gate so equality is enforced before commit/release, not only during pytest.

## Why

The repo currently carries two byte-identical Codex skill files for two distribution paths:

- repo-local skill loading: `.agents/skills/trinity/SKILL.md`
- plugin marketplace packaging: `plugins/trinity/skills/trinity/SKILL.md`

Both physical files must remain because the two consumers read them from different on-disk package roots. Keeping both as hand-edited sources creates a silent drift hazard: an edit to one path can leave the other stale, and the current provider-generation drift gate does not cover this pair.

Issue #76 reports exactly this audit finding: the two Codex skill files are byte-for-byte identical today, must both remain physically present, and are not covered by TRN-1801's current parity-diff cycle.

## Alternatives Considered

- **Keep both files hand-maintained** — rejected. This preserves the current silent drift surface and relies on reviewer memory plus pytest catching equality late.
- **Symlink the plugin copy to the repo-local skill** — rejected. It removes source duplication but is fragile across tar archives, plugin packaging, Windows checkouts, and marketplace distribution.
- **Generate both files from a third template** — rejected. It adds a third file and a new abstraction when one existing file is already the canonical Codex skill surface.
- **Add only a pytest equality assertion** — rejected as insufficient. The repo already has byte-identity coverage; this CHG moves enforcement into `make build`, `make verify-built`, release-prep, and pre-commit.

## Out of Scope

- No change to the Codex skill content.
- No symlink-based packaging; both files remain regular files for archive and cross-platform portability.
- No change to Claude Code's root `SKILL.md` install path.
- No change to plugin manifest metadata.
- No version-pin change for the Codex skill file; it has no version frontmatter today. `make bump` already runs `make build`, so the generated plugin copy follows the source file if a future version field is added.
- No change to `make install-codex`; it already installs from `.agents/skills/trinity/SKILL.md`, which this CHG designates as the source of truth.
- No generated-file warning header is added to the plugin skill copy; the copy remains byte-identical to the source file by design, and provenance is enforced through build/check tooling rather than content divergence.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| S1 | `scripts/build_codex_skill.sh` | New build/check script that copies `.agents/skills/trinity/SKILL.md` to `plugins/trinity/skills/trinity/SKILL.md`, or checks byte identity in `--check` mode. The script checks source existence before mode branching, creates the target directory before copying, replaces a symlinked target path with a regular file during build, rejects a symlinked target in check mode, compares staged index blobs when either skill file is staged, rejects unknown arguments, and exits clearly: 0 OK, 1 drift, 2 script/input error. |
| S2 | `Makefile` | Wire the script into `build` and `verify-built`; update target descriptions to cover generated artifacts beyond providers; update `install-hooks` text/comment to reference the expanded generated-artifact drift gate, not TRN-2004 only; add `release-prep` worktree and staged-index dirty guards for the Codex skill source/copy pair before `git reset HEAD`. |
| S3 | `scripts/pre-commit-hook.sh` | Run the expanded drift gate and update messaging from provider-only to generated-artifact drift. The hook aborts on any non-zero build-check result, preserves the underlying script output so drift (exit 1) and script/input errors (exit 2) remain distinguishable, and gives remediation text for both generated artifact families. |
| S4 | `tests/test_codex_compat.py` | Add tests that the build/check script exists, passes on the committed tree, rejects intentional working-tree drift, rejects symlinked targets in check mode, replaces symlinked targets in build mode, rejects missing source / unknown args with exit 2, rejects staged-index drift after a partial `git add`, and that `make build`/`make verify-built`/`release-prep` wiring is present. Keep the existing plugin/source byte-identity assertion as defense in depth. |
| S5 | `CHANGELOG.md` | Add an Unreleased changed entry referencing #76. |
| S6 | `rules/TRN-0000-REF-Document-Index.md` | Regenerate via `af index --root .` and commit the resulting index diff so TRN-3043 appears in the active document index. This is not a dry-run validation step. |

## Acceptance Criteria

- [ ] `.agents/skills/trinity/SKILL.md` is documented by code/tests as the source of truth for the Codex skill text.
- [ ] `make build` regenerates `plugins/trinity/skills/trinity/SKILL.md` from the source file and is idempotent.
- [ ] `make verify-built` fails if the two Codex skill files drift.
- [ ] `scripts/build_codex_skill.sh --check` rejects an intentionally modified plugin copy in a test and returns a non-zero drift signal.
- [ ] `scripts/build_codex_skill.sh --check` rejects staged-index drift when a developer stages only one Codex skill copy after regeneration.
- [ ] `make build` replaces a symlinked plugin skill path with a regular file, and `--check` rejects symlinked plugin skill paths.
- [ ] `scripts/build_codex_skill.sh` returns exit 2 for missing source and unknown arguments.
- [ ] `release-prep` fails when the Codex skill source/copy pair has uncommitted worktree or staged-index changes.
- [ ] The pre-commit hook runs the expanded generated-artifact drift gate.
- [ ] Both Codex skill files still exist as regular files after `make build`.
- [ ] `make verify-built` passes.
- [ ] `af validate --root .` passes.
- [ ] CHANGELOG `[Unreleased] ### Changed` includes #76.
- [ ] TRN-0000 index includes TRN-3043 after `af index --root .`.

## Implementation Order

1. Add `scripts/build_codex_skill.sh` with normal and `--check` modes.
2. Wire `build` and `verify-built` in `Makefile`.
3. Update `scripts/pre-commit-hook.sh` to run the expanded drift check.
4. Add focused tests in `tests/test_codex_compat.py`, including a temporary-copy drift test that mutates only the plugin copy and verifies the check path fails.
5. Run `make build`, `make verify-built`, targeted tests, `af index --root .`, and `af validate --root .`; commit the `TRN-0000` index update produced by `af index`.
6. Add CHANGELOG entry.
7. Open PR with `Closes #76`.

## Risks / Rollback

Risk is limited to build, test, release-prep, and pre-commit enforcement. The runtime skill text is unchanged, both physical package files remain present, and `make install-codex` already reads the chosen source file.

Pre-commit enforcement requires `make install-hooks`, and `git commit --no-verify` can bypass local hooks. The durable gates are `make verify-built`, `make test`, and release-prep, which all run the same build-check path. In the hook, provider drift and Codex-skill drift each run as separate checks; the script's own stderr distinguishes drift (`exit 1`) from script/input errors (`exit 2`), and either aborts the commit.

Rollback is a clean `git revert` of the PR. That restores the plugin copy to hand-maintained status and removes the Makefile/pre-commit drift check without migrating data or touching external state.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-18 | Initial draft for issue #76. | Codex |
| 2026-05-18 | R2: tighten advisory gaps from plan review — defense-in-depth note, explicit drift-negative test, source-existence guard, `install-codex`/`make bump` scope notes, expanded pre-commit wording, risks/rollback. | Codex |
| 2026-05-18 | R3: close MiniMax plan-review advisories — distinguish hook error/drift output, make TRN-0000 regeneration committed/non-dry-run, add explicit index AC, and document why generated-copy headers are out of scope. | Codex |
| 2026-05-18 | R4: add alternatives analysis and explicit pre-commit bypass/error-handling note per MiniMax R3. | Codex |
| 2026-05-18 | R5: implementation polish — target directory creation documented for the build script. | Codex |
| 2026-05-18 | R6: codex-bot P2 fix — `--check` compares staged index blobs when either skill file is staged, closing the partial-`git add` drift hole. | Codex |
| 2026-05-18 | R7: codex-bot P2 fix — build mode removes symlinked target paths before copy, and check mode rejects symlinked plugin copies to preserve the regular-file packaging invariant. | Codex |
| 2026-05-18 | R8: code-review advisory fixes — reject unknown args with exit 2, add exit-2 tests, and add `release-prep` dirty-tree guard for the Codex skill source/copy pair. | Codex |
| 2026-05-18 | R9: codex-bot P2 fix — `release-prep` now checks both worktree and staged-index changes for the Codex skill source/copy pair before `git reset HEAD`. | Codex |

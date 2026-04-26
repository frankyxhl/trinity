# CHG-2004: Provider Files Refactor (Build-Time Composition)

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-04-25
**Last updated:** 2026-04-25
**Last reviewed:** 2026-04-26
**Requested by:** Frank
**Status:** Approved
**Priority:** Medium
**Change Type:** Normal
**Scheduled:** TBD (target: trinity 1.5.0)
**Related:** TRN-2001 (Release Infrastructure), TRN-1005 (Install SOP), TRN-1004 (Release SOP)

---

## What

Eliminate ~400 lines of duplication across the 5 provider agent templates (`providers/codex.md`, `gemini.md`, `glm.md`, `openrouter.md`, `deepseek.md`) by introducing **build-time composition** in the source repo, while keeping the installed agent files (`~/.claude/agents/trinity-<name>.md`) self-contained and unchanged from the user's perspective.

### Source-tree restructure

```
providers/
  _base/
    common-session.md   ← Session Management H2 + Reading/Writing H3s. NO frontmatter.
    common-tail.md      ← Timeout, Iteration, Response Format, common Rules
                          (post-session shared content). NO frontmatter.
    family-wrapper.md   ← anthropic-wrapper shared logic (openrouter/deepseek):
                          TRINITY_TRACE marker selector + JSONL extraction.
                          NO frontmatter.
                          (NOTE: family-native.md was planned but dropped during
                           implementation — codex/gemini/glm CLIs share no
                           meaningful shell beyond what common-* already covers.)
  codex.delta.md        ← FULL provider file with frontmatter at top, CLI-specific
                          bash blocks, and `@include _base/common.md` / `@include
                          _base/family-native.md` directives placed where shared
                          content should be inlined. The delta IS the structural
                          template; partials are body fragments inlined by the
                          build script.
  gemini.delta.md
  glm.delta.md
  openrouter.delta.md
  deepseek.delta.md

scripts/build_providers.sh
  For each delta:
    1. Read delta.md
    2. Replace each `@include <path>` line with the contents of <path>
       (simple line-based substitution; partial path resolved relative to
        providers/)
    3. Assert: output starts with `---\n` (frontmatter on first byte)
    4. Assert: output ends with exactly one `\n`
    5. Write to providers/<name>.md (committed to repo)

providers/codex.md ... providers/deepseek.md
  ← Generated, byte-stable, committed. install.sh continues to download these
    5 files unchanged.
```

**Why `@include` instead of plain `cat`:** frontmatter must be at the file's first byte for Claude Code's agent loader to recognize it. Naive `cat _base/common.md _base/family-X.md delta.md` would either bury the frontmatter or force every partial to start with `---\n`. The `@include` directive lets each delta keep frontmatter at the top, place shared content wherever it makes structural sense, and avoid section-collision when authors decide to override one section per provider.

**Partial conventions (enforced by build + test):**
- Partials in `_base/` MUST NOT contain frontmatter (`---`)
- Every partial MUST end with exactly one `\n` (no trailing whitespace, no double-LF)
- `@include` directives MUST be on a line by themselves; surrounding blank lines are preserved verbatim from the delta
- Partial paths in `@include` MUST resolve relative to `providers/`

### Bundled bug fixes (this CHG only)

1. **Codex reasoning effort flag** — source uses `-c reasoning.effort=high`; codex-cli 0.124.0 silently ignores it. Replace with `-c model_reasoning_effort=$EFFORT` and per-prompt override parsing (default `xhigh`). Fix lives in `codex.delta.md`. Already validated on user Frank's local install (`~/.claude/agents/trinity-codex.md` was hand-patched ~weeks ago and proven). **Caveat:** users who hand-patched their own local `trinity-codex.md` will have those edits overwritten on reinstall. This is expected and desired behavior — the upstream fix subsumes the local one. Document in CHANGELOG release notes.
2. **`ls -t | head -1` race** — `openrouter.md` and `deepseek.md` both flag this as unsafe under concurrent same-project dispatches. Fix once in `_base/family-wrapper.md`. Replacement strategy: capture the parent shell's `$$` PID before the CLI call, scan SESSION_DIR for files modified after the call started AND containing the prompt's unique marker (or use the CLI's own session-id output if available).
3. **"Verify output looks reasonable" rule drift** — `codex.md` L104 says "If Codex produces code, verify it looks reasonable before returning"; `glm.md` L102 says "If GLM-5 produces code, ...". The two are NOT byte-identical — they hard-code provider names. Lift into `_base/common.md` with generic phrasing: "If the provider produces code, verify it looks reasonable before returning." This is an intentional behavior change (now applies to all 5), not a regression to mask in tests.

---

## Why

Drift has already produced three distinct bugs in 4 months (see bundled fixes 1–3). At 5 providers, ~400 lines of duplicated markdown across `session.py` calls, Response Format, Timeout, Iteration, and Rules sections cannot be edited atomically. Build-time composition gives a single source of truth at the repo level while preserving the flat, zero-runtime-dependency markdown that the orchestrator (`SKILL.md`) and Claude Code sub-agent loader already handle reliably.

Three alternatives were evaluated via parallel dispatch to GLM, Codex, and Gemini (2026-04-25):

- **Option A — SKILL.md absorbs shared logic, sub-agent reads two files at runtime.** Rejected. Codex and Gemini correctly identify that runtime composition is prompt discipline, not a mechanical guarantee — replacing one soft-rule problem with another.
- **Option B — Shared `worker_lib.sh` library sourced by each provider.** Deferred. Adds a runtime dependency for marginal benefit at 5 providers; revisit at 10+ or when shell logic outgrows markdown.
- **Option C — Two family base templates, providers extend.** Strong runner-up (Codex's pick). Less aggressive than D but still leaves duplication between the two family templates and across each family's providers.
- **Option D (this CHG) — Build-time concat in source repo.** Gemini's recommendation. Repo-side single source of truth; install-side state unchanged.

Option D wins on three dimensions:

- **Drift prevention**: a single edit in `_base/common.md` propagates to all 5 generated files mechanically (via `scripts/build_providers.sh`).
- **Backward compatibility**: `install.sh` downloads the same 5 self-contained `providers/*.md` files; users see no change in install footprint or runtime behavior.
- **Sub-agent loading model**: no change to how the orchestrator spawns workers or how workers load their instructions.

---

## Impact Analysis

- **Systems affected:** `trinity/` source repo. Installed agent files keep the same paths and remain self-contained markdown; only their textual content changes (the 3 bundled bug fixes).
- **User-facing changes at runtime:** None. SKILL.md's spawn contract (line 136: `Read your instructions from ~/.claude/agents/trinity-{base}.md first`) is path-only and references no internal section structure of provider files. Verified by grep over SKILL.md — no references to "verify code", "Response Format", "Timeout", "Iteration", or any section heading inside provider files. No SKILL.md doc update is required.
- **install.sh impact:** None. `install.sh` uses **explicit `_download` calls** for exactly 5 provider files (`providers/glm.md`, `codex.md`, `gemini.md`, `openrouter.md`, `deepseek.md`) — not a glob. Newly introduced `providers/_base/*.md` and `providers/*.delta.md` exist only in the source tree and are never downloaded by the installer. Verified by reading `install.sh` line by line.
- **Local hand-patches will be overwritten on reinstall:** Frank's local `~/.claude/agents/trinity-codex.md` was hand-patched with the `model_reasoning_effort=$EFFORT` fix; `M agents/trinity-codex.md` and `M agents/trinity-deepseek.md` show in the user's `~/.claude/` git working tree. Reinstalling 1.5.0 will overwrite both with the upstream-fixed versions. This is the intended outcome — the upstream fix subsumes the local one. Release notes must call this out so any user with similar local patches confirms before reinstalling.
- **Users on 1.4.0 who don't reinstall:** Continue to work. They retain the three known bugs.
- **Reinstall recommendation:** Users should reinstall to pick up the bundled bug fixes (especially #1 — silent Codex reasoning-effort degradation).
- **Build dependencies added:** `python3` (already required by trinity scripts) for `scripts/build_providers.sh` — using Python rather than pure bash for robust line-based `@include` substitution. No new toolchain.
- **Downtime required:** No.
- **Rollback plan:** All changes revertible via git. The pre-built `providers/*.md` files are committed, so rollback is `git revert` on the merge commit; no install-side action required.

---

## Implementation Plan

Per COR-1500 (TDD overlay) where applicable; mostly mechanical refactor with shell test coverage.

1. **Author `_base/` partials** — extract sections that appear with byte-identical content across all 5 provider files (or all 3 native, or all 2 wrapper). For sections that differ in trivial ways (e.g., provider-name string), normalize the wording and document the change as intentional. Each partial:
   - MUST NOT contain frontmatter
   - MUST end with exactly one `\n`
   - MUST NOT contain `@include` directives (no nested includes in v1)
2. **Author `*.delta.md` files** — full provider files with frontmatter at top, CLI-specific bash, and `@include _base/<partial>` directives where shared content should be inlined.
3. **Write `scripts/build_providers.sh`** (Python under bash wrapper) implementing:
   - `@include <path>` directive substitution (line-based; only when `@include` is the sole non-whitespace content on the line)
   - Pre-build invariant checks on partials (no frontmatter, exactly one trailing LF, no `@include`)
   - Post-build invariant checks on output (starts with `---\n`, ends with exactly one `\n`, contains no remaining `@include`)
   - Idempotent: running twice with no source changes produces identical output
4. **Write `tests/test_build_providers.sh`:**
   - **T1 — Determinism**: run build twice; outputs must be identical
   - **T2 — Frontmatter**: every generated file's first 3 bytes are `---`
   - **T3 — Trailing LF**: every generated file ends with exactly one `\n`
   - **T4 — Partial invariants**: every `_base/*.md` passes the "no frontmatter, single LF" rule
   - **T5 — No stale `@include`**: no generated file contains `@include`
   - **T6 — Behavior preservation (semantic, not byte-exact)**: for each generated provider, assert the file contains: the correct frontmatter `name`, the provider-specific CLI command from the delta, the session.py read/write boilerplate (matched by stable substring), the Response Format header, the Iteration cap rule. Phrased as "section presence" assertions, not whole-file diff against 1.4.0 (since the 3 bug fixes intentionally change content).
   - **T7 — Drift sentinel**: assert `_base/common.md` contains the generic "verify output looks reasonable" rule (so it lands in all 5 generated files); assert `_base/family-wrapper.md` does NOT contain `ls -t | head -1` (drift fix #2 stays fixed); assert `codex.delta.md` contains `model_reasoning_effort=` (drift fix #1 stays fixed).
5. **Apply the three bug fixes** in the partials:
   - `_base/common.md`: add generic "If the provider produces code, verify it looks reasonable before returning."
   - `_base/family-wrapper.md`: replace `ls -t | head -1` with race-safe selector (capture pre-call file list; pick the file that appeared after; or use CLI's own session-id output where available)
   - `codex.delta.md`: switch to `model_reasoning_effort=$EFFORT` with default `xhigh` and prompt-line override parsing (port from `~/.claude/agents/trinity-codex.md`)
6. **Regenerate `providers/*.md`** via `scripts/build_providers.sh` and commit the generated output.
7. **Update `Makefile`** — add three targets:
   - `build`: runs `scripts/build_providers.sh`
   - `verify-built`: regenerates to a temp dir, diffs against committed `providers/*.md`, fails non-zero if drift detected
   - `make build` becomes a prerequisite of `test` and `release`
   - `make verify-built` runs in `test`, ensuring committed output matches partials
8. **Add pre-commit hook** (`.git/hooks/pre-commit` template + `make install-hooks` target) that runs `make verify-built`. Prevents the "someone hand-edits providers/codex.md and forgets the delta" failure mode flagged by Frank's review (Q4).
9. **Update `install.sh`** — no change required (verified above). Verify via existing `tests/test_install_sh.sh` still green.
10. **Update SOPs:**
   - `TRN-1003` (Version Bump): note `make build` must run before bumping
   - `TRN-1004` (Release): add `make verify-built` to the release checklist (CI/local both)
   - `TRN-0000` (Index): add `TRN-2004` (already done)
11. **Update CHANGELOG.md** — 1.5.0 entry covering: 3 bundled bug fixes, source-tree restructure (developer-facing only), reinstall recommendation, hand-patch overwrite warning.
12. **Code review** — Codex + Gemini per COR-1602 strict.
13. **Bump VERSION** to `1.5.0`, tag, push, release.

---

## Approval

- [x] Reviewed by: Claude Opus 4.7 (initial draft + 7-concern revision)
- [x] Approved by Frank (project lead) — 2026-04-25 (verbal authorization to proceed end-to-end)

---

## Open Questions / Resolved Concerns

Frank reviewed the initial draft and raised 7 concerns. Each is addressed below; see the section called out in parentheses for the in-document resolution.

1. **Cat boundary / trailing LF** (resolved in §What → "Partial conventions"): partials must end with exactly one `\n`; enforced by build-time precheck and tests T3/T4.
2. **Frontmatter ordering** (resolved in §What → "Why `@include` instead of plain `cat`"): plain `cat common + family + delta` is rejected. Build script uses `@include` directive replacement so the delta keeps frontmatter at byte 0. T2 asserts.
3. **"Verify ... reasonable" not byte-identical between codex.md and glm.md** (resolved in §Bundled bug fixes #3): confirmed by grep — codex says "Codex", glm says "GLM-5". Lifting requires a generic rephrase ("the provider"); this is an intentional behavior change, not a regression to hide. Test T6 is reframed as semantic ("section presence") not byte-exact diff against 1.4.0.
4. **Drift gate / generated vs partials** (resolved in §Implementation Plan steps 7–8): added `make verify-built` target and pre-commit hook to catch hand-edits of generated files.
5. **install.sh impact** (resolved in §Impact Analysis): verified by reading install.sh — explicit `_download` per file, not glob. New `_base/` and `*.delta.md` paths are not in the download list and won't be pulled.
6. **Local hand-patch overwrite on reinstall** (resolved in §Impact Analysis + §Bundled bug fixes #1): documented as expected behavior. Release notes must call out that reinstalling 1.5.0 overwrites local edits to `~/.claude/agents/trinity-codex.md` (and `trinity-deepseek.md` for any wrapper-related local changes), and that the upstream fixes subsume the patches.
7. **SKILL.md references to provider structure** (resolved in §Impact Analysis): grep over SKILL.md shows the only reference is path-based (`~/.claude/agents/trinity-{base}.md` at line 136). No section names, headings, or rule contents from provider files are referenced. No SKILL.md update required.

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-04-25 | CHG drafted from three-model feasibility study (GLM/Codex/Gemini) | Pending approval |
| 2026-04-25 | Resolved 7 review concerns from Frank; tightened partial conventions, replaced cat with `@include`, added `make verify-built` + pre-commit hook | Updated |
| 2026-04-25 | Approved by Frank; status → Approved; implementation begins | Approved |
| 2026-04-25 | Implementation iteration 1 complete: partials authored, build script written, providers regenerated, T1–T7 green | In review |
| 2026-04-25 | COR-1602 review iteration 1 (Codex + Gemini, parallel). Convergent BLOCKERS: (a) `### Writing sessions` orphaned under `## Instance Key` — markdown hierarchy regression; (b) race-safe selector still races within sub-second on 1s mtime resolution. Codex-only BLOCKER: (c) `declare -A` is bash 4+ — broken on macOS default `/bin/bash` 3.2. Plus MAJOR M1 (`minimal` is not a valid effort value), M3 (no `@include` path sandbox), M6 (release may stage stale providers/). | REQUEST_CHANGES |
| 2026-04-25 | Iteration 2 fixes: (a) merged common-head + Writing-sessions into single `_base/common-session.md` so both H3s sit under their parent `## Session Management`; (b) replaced mtime-array selector with prompt-marker grep (`TRINITY_TRACE`), bash-3.2-compatible and sub-second-safe; (c) dropped `minimal` from EFFORT regex; (d) added realpath sandbox to `@include` (must resolve under `providers/_base/` and end in `.md`); (e) `make release` now runs `verify-built` and asserts `providers/` is clean. New tests: H3-under-H2 walker, no-`declare -A` sentinel, `TRINITY_TRACE` presence in wrappers, `minimal`-rejected sentinel. | Resolved |

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-04-25 | Initial draft | Claude Opus 4.7 |
| 2026-04-25 | Address Frank's 7 review concerns (Q1 trailing LF, Q2 frontmatter ordering via `@include`, Q3 normalize "verify reasonable", Q4 drift gate, Q5 install.sh verified, Q6 hand-patch overwrite, Q7 SKILL.md unaffected) | Claude Opus 4.7 |

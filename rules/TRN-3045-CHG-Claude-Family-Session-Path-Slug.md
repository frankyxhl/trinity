# CHG-3045: Keep Leading Dash in Claude-Family Session-Path Slug

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-06-27
**Last reviewed:** 2026-06-27
**Status:** Approved (§4 plan-review R3 PASS: glm 9.70 / deepseek 9.90 / minimax 9.65 — all ≥9.5, all blocking empty)
**Date:** 2026-06-27
**Requested by:** Frank Xu (issue #262)
**Priority:** High
**Change Type:** Bugfix
**Closes:** #262
**References:** TRN-2004 (provider files refactor); TRN-2009 (remove zsh dep — family-wrapper); TRN-1007 (PR readiness gate); TRN-1008 §3/§4 (CHG drafting + plan-review); TRN-1800 (CODE weights); CLD-1802 (atomicity surface / symmetric class)

---

## What

Stop stripping the leading dash from the project slug in the claude-family session-path resolver and provider templates, so it matches the claude CLI's actual on-disk layout (`-Users-frank-…`, dash kept). This is a **minimal, deletion-only bugfix**: `_encode_project_slug` in `scripts/session_path.py` drops `.lstrip("-")`; the three claude-family provider **sources** (`providers/{claude-code,deepseek,openrouter}.delta.md`) drop `s|^-||` from `PROJECT_SLUG` (`make build` regenerates `*.md`); the test helper `_claude_slug` drops `lstrip("-")`; all strip-claiming docstrings are corrected; and a literal-anchor test pins the real claude-CLI slug (macOS + Linux) independent of the helper. No refactor, no helper collapse, no tangential alignment (see Out of Scope).

## Why

The `session-path` resolver returns exit 3 ("transcript file not found") for **every** claude-family provider because it computes a no-dash slug (`Users-frank-Projects-trinity`) while the claude CLI writes transcripts under the dashed slug (`-Users-frank-Projects-trinity`). Surfaced by the 2026-06-27 trinity-glm/minimax/deepseek smoke test and independently re-confirmed by all three §4 plan-reviewers (the deepseek reviewer's own session JSONL landed in the dashed dir during review — live reproduction):

- Real transcript: `~/.claude-deepseek/projects/-Users-frank-Projects-trinity/7b7ae10f-….jsonl` (dashed, 11868 bytes). The no-dash sibling dir trinity computes is empty.
- `python3 scripts/session_path.py /Users/frank/Projects/trinity deepseek:smoke` → exit 3, path `…/projects/Users-frank-Projects-trinity/…` (no dash).
- Native `~/.claude/`, `~/.claude-trinity-claude-code/`, `~/.claude-openrouter/` projects all use the dashed form — the strip assumption is wrong for the whole family.

It only keeps working in practice because the deepseek worker agent improvises a fallback to the dashed directory (LLM-supplied, not a stable code path). Worse, `tests/test_session_path.py`'s own `_claude_slug` helper replicates the same `lstrip("-")`, so the suite passes while asserting the wrong path — test and implementation share the bug, giving false confidence.

**Cross-platform note:** the on-disk evidence is macOS, but the claude CLI is node-based with identical slug logic on Linux, and `sed 's|/|-|g` is POSIX-portable (no GNU/BSD split). The literal-anchor test (Surface 3c) pins BOTH the macOS and Linux expected forms so the CI matrix (`ubuntu-latest` + `macos-latest`) enforces parity rather than asserting it by inference.

## Scope Justification

Three surfaces in one CHG. These are indivisible for this bugfix: all three encode the SAME incorrect "strip leading dash" assumption — (1) the Python resolver `_encode_project_slug`, (2) the agent-template `PROJECT_SLUG` sed in the 3 `.delta.md` (one symmetric class per CLD-1802), (3) the test helper that mirrors the bug. Fixing any subset leaves the others contradicting it: a half-fix ships a resolver that disagrees with its own agent template and its own tests. One root cause → one coordinated CHG. Splitting per-surface is worse: a resolver-only PR leaves `make test` red (the `_claude_slug` helper still strips → parametrized claude-family cases fail); a template-only PR leaves the resolver computing the wrong path. The coordinated change is the minimal unit that keeps the suite green end-to-end.

## Out of Scope

- Droid-based provider session extraction (`glm` / `minimax`) — tracked in #263 (unrelated root cause: `droid search` content lookup).
- Codex transcript resolver (`_resolve_codex` — different layout, unaffected).
- The trace-marker race-safe selection mechanism itself (`_base/family-wrapper.md`) — only the `PROJECT_SLUG` line changes.
- **Thin-alias collapse of `_encode_project_slug` onto `_encode_project_path`** — deferred to a follow-up CHG. Post-fix both bodies are identical (`abspath.replace("/", "-")`), but collapsing is an independent refactor, not part of the strip bug (§4 R2 minimax finding). Both functions are left in place with corrected docstrings noting the post-fix equivalence.
- **`_claude_slug` `Path.resolve()` → `os.path.abspath()` alignment** — deferred to a follow-up CHG. It is a pre-existing symlink discrepancy unrelated to the strip bug (§4 R2 minimax finding). This CHG only removes the `lstrip("-")`.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `scripts/session_path.py` | (a) `_encode_project_slug` (~L95-108): drop `.lstrip("-")` only — body becomes `abspath.replace("/", "-")`, identical to `_encode_project_path`; leave both functions in place (collapse deferred). (b) Correct EVERY docstring that claims a strip — module-level docstring L27-33 ("STRIP leading dash" + the embedded `s|/|-|g; s|^-||` sed snippet), `_resolve_claude_family` docstring L128-134, and `_encode_project_slug`'s own docstring L95-105 (note post-fix equivalence with `_encode_project_path`). |
| 2 | `providers/claude-code.delta.md:56`, `providers/deepseek.delta.md:40`, `providers/openrouter.delta.md:40` (`PROJECT_SLUG` source — symmetric class) | Drop `s|^-||` from the sed expression. `make build` regenerates the committed `*.md`; the 3 `.delta.md` AND regenerated `*.md` are committed in the SAME commit; `make verify-built` must stay clean. |
| 3 | `tests/test_session_path.py` | (a) `_claude_slug` helper L79-83: drop `lstrip("-")` ONLY (do NOT touch `Path.resolve()` — deferred). (b) Parametrized-case docstring L196-201 ("leading-dash-stripped" → "leading-dash-kept"). (c) NEW literal-anchor test `test_claude_slug_matches_real_claude_cli_layout()` asserting hardcoded expected values NOT routed through `_claude_slug` — `_encode_project_slug("/Users/frank/Projects/trinity") == "-Users-frank-Projects-trinity"` (macOS) AND `"/home/runner/work/trinity/trinity"` → `"-home-runner-work-trinity-trinity"` (Linux CI). Breaks the `f(resolver)==f(helper)` tautology (glm R1 blocker). |

## Acceptance Criteria

- **A1**: `python3 scripts/session_path.py <project> deepseek:<inst>` resolves to the real transcript path (exit 0) for an existing session; same for `openrouter` / `claude-code`.
- **A2**: `_encode_project_slug` retains the leading dash (no `lstrip`) and its docstring no longer claims a strip.
- **A3**: The three `.delta.md` `PROJECT_SLUG` expressions no longer strip the leading dash; `make build && make verify-built` exits 0 (no drift); delta + regenerated md in one commit.
- **A4**: `tests/test_session_path.py` claude-family cases expect the dashed slug; `make test` green, `make lint` clean.
- **A5**: `CHANGELOG.md` records the fix under the unreleased section.
- **A6**: No residual strip prose — `grep -rniE "strip|s\|\^-" scripts/session_path.py tests/test_session_path.py` returns no claim that claude-family strips the leading dash.
- **A7**: New literal-anchor test asserts hardcoded macOS + Linux expected slugs (not via `_claude_slug`) and passes on the CI matrix.
- **A8**: `providers/*.delta.md` edits and regenerated `providers/*.md` are committed in the SAME commit.

## Implementation Order

1. `scripts/session_path.py`: drop `.lstrip("-")` in `_encode_project_slug` (leave function in place); correct ALL strip-claiming docstrings (module L27-33, `_resolve_claude_family` L128-134, `_encode_project_slug` L95-105).
2. `providers/{claude-code,deepseek,openrouter}.delta.md`: drop `s|^-||` from `PROJECT_SLUG`.
3. `make build`; commit the 3 `.delta.md` AND regenerated `*.md` in the SAME commit; confirm `make verify-built` clean.
4. `tests/test_session_path.py`: drop `lstrip("-")` in `_claude_slug` (do NOT touch `Path.resolve()`); update L196-201 docstring; ADD literal-anchor test (hardcoded macOS + Linux expected).
5. `grep` verify no residual strip prose (A6).
6. `make test && make lint && make coverage` (focused `pytest tests/test_session_path.py -v` first).
7. `CHANGELOG.md` entry.
8. Commit (identity per §2 / CLAUDE.md).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-06-27 | Initial Proposed CHG per issue #262 (surfaced by glm/minimax/deepseek smoke test) | Claude Code (ryosaeba1985) |
| 2026-06-27 | R2: address §4 R1 findings (glm 8.40 / deepseek 8.2 / minimax 9.05, all FIX) — enumerate all strip-claiming docstrings (minimax); add literal-anchor test (glm); add Cross-platform note + Linux literal form (deepseek); add Scope Justification (deepseek); new AC A6-A8. Result: glm PASS 9.80, deepseek PASS 9.65, minimax FIX 9.475 (no blocker). | Claude Code (ryosaeba1985) |
| 2026-06-27 | R3: narrow scope per §4 R2 minimax finding (9.475, compression docked for scope creep) — DEFER thin-alias collapse and `_claude_slug` abspath alignment to follow-up CHG (both are refactor/pre-existing, not the strip bug); fix is now deletion-only. Simplify A6 grep regex (drop redundant `\|lstrip`); tighten Scope Justification wording (per-surface split breaks `make test`, not `make verify-built`). literal-anchor test retained (glm blocker resolution). | Claude Code (ryosaeba1985) |
| 2026-06-27 | §4 plan-review R3 PASS — glm 9.70 / deepseek 9.90 / minimax 9.65, all blocking empty. Status → Approved. Convergent advisories to address before §8 code-review: confirm no non-claude consumer of `_encode_project_slug` (glm); add provenance comment to literal-anchor hardcoded slugs (glm); verify `make build` regen has no unrelated whitespace diff (glm). | Claude Code (ryosaeba1985) |

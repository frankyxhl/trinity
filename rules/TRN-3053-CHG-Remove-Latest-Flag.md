# CHG-3053: Remove Speculative `trinity status --latest` Flag

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #245 (ponytail audit 2026-06-23); batch mandate from @frankyxhl (2026-07-04)
**Priority:** Low
**Change Type:** Chore (dead-flag removal)
**Targets:** `main`
**Closes:** #245

---

## What

Delete the `--latest` flag from the `status` subparser
(`scripts/codex.py:591-598`). Its `store_true` value is read nowhere
(`git grep "args.latest"` → zero hits); its own help text admits it is
"reserved for forward-compatibility". YAGNI, straight from the audit.

## Issue premises verified vs rejected

- ✅ Verified: `args.latest` has zero readers; the flag is pure dead surface
  since TRN-2028 introduced it.
- ⚠️ Corrected — "status command behaves identically" is wrong for one
  input: `trinity status --latest` currently succeeds as a no-op; after
  removal it exits 2 with argparse "unrecognized arguments". User-visible
  CLI removal → declared Changed row + `### Removed` CHANGELOG section.
- ⚠️ Surfaces the issue missed: `docs/codex-compatibility.md:112-113`
  documents the flag (two lines); `scripts/_review.py:1007` comment
  mentions `trinity status --latest` (comment sync, same TRN-3051-style
  discipline); `tests/test_status_latest.py` has a `latest: bool = False`
  helper param whose `if latest:` branch is DEAD CODE — all 26 call sites
  use the default, ZERO pass `latest=True` (three-reviewer convergent R1
  fact-correction of this doc's earlier "exactly one call site" claim; the
  dead flag's test helper was itself dead — double YAGNI).

## Behavioral Contract

**Preserved:** bare `trinity status` output byte-identical (the flag never
altered behavior); all other status paths.

**Changed (declared + pinned):**

| Invocation | Before | After |
|---|---|---|
| `trinity status --latest` | accepted, identical to bare `status`, exit 0 | argparse "unrecognized arguments: --latest", stderr, exit 2 |

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/codex.py` | Delete the `status.add_argument("--latest", ...)` block (~591-598). | trinity-glm |
| 2 | `scripts/_review.py` | Comment-only (~1007): `trinity status --latest` → `trinity status`. | trinity-glm |
| 3 | `docs/codex-compatibility.md` | Delete/reword lines 112-113 (drop the `--latest` row; keep the bare-status line). | trinity-glm |
| 4 | `tests/test_status_latest.py` | Remove the dead `latest: bool = False` param + `if latest:` branch from `_run_status` (no call sites to touch — zero pass True) and the docstring's `[--latest]`; ADD one pin for the Changed row (`status --latest` → exit 2, stderr mentions the EXACT `--latest` token — abbreviations like `--lat` are subsumed by the same delta per R1 glm, pin the full token only). File name stays (it tests "latest review" semantics, not the flag). | trinity-deepseek |
| 5 | `CHANGELOG.md` | `### Removed` entry referencing #245 with the exit-0→2 delta. | trinity-glm |
| 6 | `rules/TRN-0000-REF-Document-Index.md` | `af index` regen. | orchestrator |

Write sets disjoint (glm: scripts/ + docs/ + CHANGELOG; deepseek: tests/).

## Acceptance Criteria

- [ ] `git grep -- --latest scripts/ docs/` → zero hits;
  `git grep "args.latest"` → zero hits anywhere.
- [ ] Bare `trinity status` output unchanged (existing suite passes with
  only the Surface 4 edits).
- [ ] New pin: `status --latest` → exit 2.
- [ ] Full `pytest -q`; ruff on changed files; `af validate`; PR body
  `Closes #245` + the no-op→error delta stated.

## Implementation Order

1. trinity-deepseek: Surface 4 (the exit-2 pin is RED against current code;
   the helper cleanup is mechanical).
2. trinity-glm: Surfaces 1-3 + 5.
3. Orchestrator: verify, index, PR.

## Migration / Backward-compat

Scripted callers passing `--latest` (none in-repo; the flag was
documentation-only advertised in docs/codex-compatibility.md) break loudly
with exit 2. The flag never did anything — removal cannot change any
observed output for callers not passing it.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 9.57 PASS | 9.78 PASS | 9.65 PASS | ✅ (first-round) |

R1 folds (all advisory-grade): three-reviewer convergent fact-correction —
"one latest=True call site" → ZERO (helper branch is dead code);
abbreviation subsumption note (`--lat` accepted today via allow_abbrev
default, same delta class, exact-token pin only); loud-breakage stance
ratified by minimax (deprecation shim would preserve the dead code the
audit deletes; TRN-2028 framed the flag as placeholder from birth).
Proportionality: full CHG earned by the 3 issue-error corrections; minimax
calibration — TRN-3053 sets the FLOOR for the future CHG-stub tier, not a
member of it.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #245. Corrects the issue's "behaves identically" claim (one declared no-op→exit-2 delta) and adds the docs/comment/test surfaces it missed. | Claude Code (orchestrator) |

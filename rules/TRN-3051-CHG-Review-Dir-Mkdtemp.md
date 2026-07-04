# CHG-3051: make_review_dir via tempfile.mkdtemp

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #241 (ponytail audit 2026-06-23); batch mandate from @frankyxhl (2026-07-04)
**Priority:** Low
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #241

---

## What

Replace `make_review_dir`'s 100-iteration `FileExistsError` retry loop
(`scripts/_review.py:565-579`) with one atomic
`tempfile.mkdtemp(prefix=f"{stamp}-{slug}-", dir=base)`. `raw/` and `logs/`
subdir creation unchanged. `base.mkdir(parents=True, exist_ok=True)` runs
first (mkdtemp requires `dir=` to exist; the old `mkdir(parents=True)`
created it implicitly).

## Issue premises verified vs rejected

- ✅ Verified: the retry loop is pure collision-avoidance that stdlib does
  atomically; `raw`/`logs` creation is orthogonal.
- ✅ Verified (beyond the issue): the `_status.py` latest-review ordering is
  SAFE under mkdtemp — its sort key is `(d.name[:15], mtime)` and the
  `%Y%m%d-%H%M%S` stamp is exactly 15 chars, so the random suffix never
  enters the key; same-second ties were already mtime-broken (PR #60 R7,
  pinned by `test_t15_same_second_reviews_use_mtime_tiebreak`).
- ⚠️ Corrected: "same behavior" needs four declared deltas (below); the
  issue's Task Plan missed them.

## Behavioral Contract

**Preserved:** dir lives under `out_dir`; name starts with the 15-char
second-granular stamp + `-<slug>-`; `raw/` + `logs/` created inside;
returns the `Path`; `_status.py` ordering + `metadata.json` placement
unaffected.

**Changed (declared + pinned):**

| Aspect | Before | After |
|---|---|---|
| Dir name tail | `<stamp>-<slug>` bare on first create; `-<index>` only on same-second collision | always `<stamp>-<slug>-<8 random chars>` (mkdtemp suffix) |
| Dir permissions | umask-derived (typically 0755) | 0700 (mkdtemp contract; R1 minimax endorsement: old behavior was incidental, new is documented and safer). Single-user local artifact. Declared, not worked around — an explicit `chmod` would re-add the code the issue deletes. **Asymmetry note (R1 glm/deepseek):** subdirs `raw/`/`logs/` keep umask defaults via plain `mkdir()` — functionally moot since the 0700 parent gates traversal; the test suite pins BOTH the 0700 parent AND the non-0700 subdirs (preventing a future copy-paste of the chmod pattern into the subdir calls). |
| Exhaustion path | `SystemExit` after 100 collisions | deleted — mkdtemp cannot collide; OS errors surface as `OSError` (consistent with every other filesystem failure in the module) |
| `_status.py:287` comment | describes `<slug>[-<index>]` suffix scheme | reworded for the mkdtemp suffix (comment-only; the mtime-tiebreak CODE is untouched and remains necessary) |

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/_review.py` | `import tempfile`; `make_review_dir` body: base-mkdir, `mkdtemp`, wrap in `Path`, create subdirs, return. Retry loop + `SystemExit` deleted. Est. −13/+7. | trinity-glm |
| 2 | `scripts/_status.py` | Comment-only: update the `_sort_key` rationale block (~287) to describe the mkdtemp suffix instead of `[-<index>]`, AND fix the pre-existing stale line-reference `scripts/codex.py:914` → `scripts/_review.py` (R1 glm/minimax convergent — the comment is being rewritten anyway; TRN-3021 module-split drift). | trinity-glm |
| 3 | `tests/test_review_dir.py` (new) or nearest existing suite | Pins: name matches `^<stamp regex>-<slug>-[a-z0-9_]{8}$` shape (8-char suffix is CPython `_RandomNameSequence` behavior, verified on macOS; Linux CI run confirms before merge per R1 deepseek); `raw`/`logs` exist AND are NOT 0700 (umask defaults — pins the asymmetry); two same-second calls yield distinct dirs; parent dir mode 0700 with `@pytest.mark.skipif(sys.platform == "win32", ...)` forward-guard (R1 glm); `result.parent == Path(out_dir).expanduser()` (preserved-contract pin, R1 glm). ~5 assertions across ≤3 test bodies, parametrize where natural. | trinity-deepseek |
| 4 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry referencing #241 incl. the 0700 + always-suffix deltas. | trinity-glm |
| 5 | `rules/TRN-0000-REF-Document-Index.md` | `af index` regen. | orchestrator |
| 6 | `skills/trinity-zc/SKILL.md` | Doc-sync (R1 glm blocker): line ~337's review-dir layout `<YYYYMMDD-HHMMSS-slug>/...` → `<YYYYMMDD-HHMMSS-slug>-<rand8>/...` with a one-line mkdtemp credit. | trinity-glm |


## Acceptance Criteria

- [ ] No retry loop / `range(100)` / `SystemExit` in `make_review_dir`;
  single `mkdtemp` call.
- [ ] `raw/` + `logs/` still created; return type `Path`.
- [ ] New tests pin the Changed-table rows (name shape, uniqueness,
  subdirs, 0700).
- [ ] `_status.py` comment updated (incl. stale codex.py:914 ref fixed);
  `_sort_key` code byte-identical.
- [ ] `skills/trinity-zc/SKILL.md` layout line reflects the `-<rand8>` tail.
- [ ] Existing suites pass unmodified (incl. `test_status_latest.py` t15).
- [ ] Full `pytest -q`; ruff both files; `af validate`; PR body `Closes #241`.

## Implementation Order

1. trinity-deepseek: contract tests (RED where behavior changes: name-shape
   + 0700 rows fail against current code; uniqueness/subdirs pass). Note:
   the subdir-NOT-0700 assertion is umask-022-dependent (R2 glm — under
   umask 077 it would false-fail; trinity CI uses 022; leave a one-line
   comment on the assertion).
2. trinity-glm: Surfaces 1-2 + 4 + 6.
3. Orchestrator: verify, index, PR.

Write sets disjoint (glm: scripts/ + CHANGELOG + skills/; deepseek: tests/).

## Migration / Backward-compat

Review dirs are local artifacts consumed by `trinity status` (ordering
safe, see above) and humans. Existing dirs keep old names — mixed naming in
`reviews/` is cosmetic. 0700 affects only hypothetical other-user readers;
none exist in-repo.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 9.18 FAIL | 9.53 PASS | 9.65 PASS | ❌ |

R1 fold: Surface 6 added for the missed `skills/trinity-zc/SKILL.md:337`
layout doc (glm blocker); Surface 2 now explicitly folds the stale
`codex.py:914` line-ref fix (glm + minimax convergent); Surface 3 gains the
expanduser preserved-contract pin, the subdir-NOT-0700 assertion, and the
win32 skipif guard; perms-asymmetry note added to the Changed table.
minimax endorsed the 0700 declared-not-chmod'd stance and the
premises-verified-vs-rejected template section.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #241. Adds the four behavior deltas the issue's "same behavior" claim missed; verifies _status.py ordering safety with evidence. | Claude Code (orchestrator) |
| 2026-07-04 | R1 fold: +Surface 6 (SKILL.md:337 layout doc, glm blocker); Surface 2 folds stale codex.py:914 ref (glm+minimax); Surface 3 +expanduser pin, +subdir-NOT-0700 assert, +win32 skipif; perms-asymmetry note. R2 fold: Implementation Order + write-set enumeration synced to Surface 6; umask-022 dependency noted on the subdir assertion. Gate met R2: glm 9.55 / deepseek 9.53 / minimax 9.65. | Claude Code (orchestrator) |

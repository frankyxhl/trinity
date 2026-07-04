# CHG-3050: Remove Dead auth= Param in _doctor.py; Keep base_env= Justified

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #244 (ponytail audit 2026-06-23); batch mandate from @frankyxhl (2026-07-04)
**Priority:** Low
**Change Type:** Refactor (behavior-preserving)
**Targets:** `main`
**Closes:** #244

---

## What

Remove the never-used `auth=None` parameter from
`_make_health_result` (`scripts/_doctor.py:60`); the result dict keeps its
`"auth"` key hardcoded to `None` (consumers read `h["auth"]`, and
`cmd_doctor` overwrites it for wrapper providers — that flow is untouched).
The one call site passing an explicit `auth=None` (line ~277) drops the
kwarg.

**`base_env=` on `detect_env_pollution` is KEPT** — resolving the issue's
embedded either/or per its own AC clause ("justified + kept if a test
genuinely needs it").

## Why the issue's second half is rejected

Issue #244 claims `base_env=` "exists only as a test-injection seam;
production always uses `os.environ`" and asks to remove it + "update the 2
test file(s) that inject base_env". Verified 2026-07-04:

- `tests/test_doctor_preflight.py` calls `detect_env_pollution({...})` with
  literal dicts in 6+ tests (A2/A3/A16/A17, redaction, essentials). The
  seam is load-bearing, not vestigial.
- The alternative (monkeypatching the whole `os.environ` per test) trades a
  pure-function signature for global-state mutation — strictly worse.
- The "2 test file(s)" count was wrong anyway: `test_provider_env.py`'s
  `base_env` references belong to `build_provider_env` (codex.py), a
  different function out of scope.

## Behavioral Contract

Behavior-preserving; pinned by existing tests (no new pins):

| Pin | Where |
|---|---|
| `_make_health_result("glm", ok=True)` result shape incl. `"auth"` key | test_doctor_preflight.py:44 + 10 more call sites |
| `cmd_doctor` wrapper-auth overwrite path (success) | test_codex_adapter.py ~line 1630 (attribution corrected per R1 deepseek); missing-auth failure path has NO end-to-end pin — pre-existing gap recorded for future work, untouched here |
| `detect_env_pollution` dict-injection behavior | A2/A3/A16/A17 tests, unmodified |

No test passes `auth=` to `_make_health_result` (verified by grep — the
`"auth missing"` strings in tests are issue-list contents, not kwargs).

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/_doctor.py` | Remove `auth=None` param (line 60); replace the `"auth": auth,` literal at line 80 with `"auth": None,` (**key retained, value hardcoded** — consumers at line ~336 and the `cmd_doctor` overwrite at ~607 depend on the key); drop the `auth=None` kwarg at the one explicit call site (~line 277). Add one comment on `base_env=` noting it is a deliberate test seam, citing the load-bearing call sites at test_doctor_preflight.py:66/72/78/91/97/106 (issue #244 disposition). Est. −3/+2 lines. | trinity-glm |
| 2 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry referencing #244, noting the base_env keep-decision. | trinity-glm |
| 3 | `rules/TRN-0000-REF-Document-Index.md` | `af index` regen. | orchestrator |

No test surface: zero test files change (corrected from the issue's stale
task plan). No RED step — pure deletion under existing coverage.

## Acceptance Criteria

- [ ] `_make_health_result` has no `auth` parameter; result dict still
  carries `"auth": None`; `git grep "auth=" scripts/_doctor.py` returns
  **zero hits** (the line-607 overwrite is `h["auth"] = auth`, which does
  not match).
- [ ] `detect_env_pollution(base_env=None)` unchanged, + seam comment.
- [ ] Full `pytest -q` passes with tests **unmodified**.
- [ ] `ruff check` / `format --check` on `scripts/_doctor.py` pass.
- [ ] `af validate --root .` passes; PR body includes `Closes #244` and the
  base_env keep-rationale (the issue AC's checkbox for `base_env` is
  satisfied via the "justified + kept" branch).

## Implementation Order

1. trinity-glm: Surface 1-2.
2. Orchestrator: verification + index regen.

## Migration / Backward-compat

None. `_make_health_result` is module-private; no out-of-repo callers.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 9.70 PASS | 9.53 PASS | 9.70 PASS | ✅ (first-round) |

R1 advisories folded: Surface 1 key-retention wording tightened + seam
comment line-anchored (glm); AC grep claim corrected to zero-hits (glm);
pin-table overwrite attribution corrected to test_codex_adapter.py + the
missing-auth failure-path coverage gap recorded (deepseek). Process
advisory (minimax): "CHG stub" lightweight tier for ≤5-LoC audit items —
carried to §11 retrospective nomination.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #244 with the base_env either/or resolved to KEEP (load-bearing test seam; issue's removal premise refuted by test evidence). | Claude Code (orchestrator) |

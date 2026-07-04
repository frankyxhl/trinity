# CHG-3052: Inline the Single-Entry STRICT_REVIEW_TEMPLATES Registry

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #242 (ponytail audit 2026-06-23); batch mandate from @frankyxhl (2026-07-04)
**Priority:** Low
**Change Type:** Refactor (behavior-preserving)
**Targets:** `main`
**Closes:** #242

---

## What

Inline the sole `STRICT_REVIEW_TEMPLATES` entry (the `("COR-1602",
"COR-1609")` template, `scripts/_review.py:42-67`) into
`resolve_strict_review` (line ~457); delete the module-level dict and the
tuple-key `.get()`. The supported-combo check becomes an explicit
comparison; the template dict-literal is returned as before.

## Issue premises verified vs rejected

- ✅ Verified: exactly one entry, keyed by one tuple; `resolve_strict_review`
  is the only reader inside `_review.py`; `resolve_strict_review` has no
  direct test today (the issue's characterization-test AC stands).
- ⚠️ Beyond the issue (contract points the body missed):
  1. **`scripts/codex.py:148` re-exports `STRICT_REVIEW_TEMPLATES`** (issue
     #206 module-split convention). Repo-wide grep: that re-export line is
     the ONLY consumer outside `_review.py` — no test, script, or doc
     imports it. The re-export line is deleted with the dict; declared in
     §Migration.
  2. **TRN-3034 consistency**: TRN-3034 rejected its Option B partly
     because the registry "is the natural single source of truth for
     per-template metadata" (co-locating `decision_rule` with
     `pass_threshold` prevents drift). The inline PRESERVES that rationale:
     the template stays one cohesive dict-literal — both fields remain
     co-located — only the one-entry registry indirection and tuple-key
     lookup die. Callers still receive the same template object; no
     per-call threshold plumbing is introduced (the exact thing TRN-3034
     rejected).

## Behavioral Contract

Behavior-preserving; pinned by NEW characterization tests (none exist today
— issue AC):

| Invocation | Behavior (unchanged) |
|---|---|
| neither `--sop` nor `--rubric` (incl. empty strings — `bool("")` falsy) | returns `None` |
| only one of the pair | `SystemExit("trinity: --sop and --rubric must be used together")` |
| malformed id (e.g. `cor1602`, bare `1602`) | `SystemExit` from `normalize_review_doc_id` ("must look like COR-1602") — fires BEFORE the combo check (5th branch, R1 deepseek/glm convergent) |
| `--sop COR-1602 --rubric COR-1609` (incl. lowercase/padded variants normalize accepts) | **top-level ENVELOPE** `{enabled: True, sop, rubric (normalized), pass_threshold: 9.0, calibration, decision_rule, output_schema (== STRICT_REVIEW_OUTPUT_SCHEMA), template}` — `write_synthesis` consumes the TOP-LEVEL `pass_threshold` per TRN-3034's threshold-flow fix, so the envelope (not just the nested template) is the load-bearing contract (R1 glm blocker). The nested `template` carries `pass_threshold` 9.0, `decision_rule`, `calibration` COR-1611, `rubric_title`, 5 `criteria` rows, `non_code_note` — content byte-equal to today's entry |
| any other (sop, rubric) combo | `SystemExit("trinity: unsupported strict review template: SOP <sop> with rubric <rubric>")` — same message shape |

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/_review.py` | Delete the module-level dict (lines 42-67); in `resolve_strict_review`, replace the `.get()` with `if (sop, rubric) != ("COR-1602", "COR-1609"): raise SystemExit(<same message>)` followed by the inlined `template = {...}` literal (content byte-identical to the current entry). Est. net ~−4 lines (indirection removed; literal moves). | trinity-glm |
| 2 | `scripts/codex.py` | Delete line 148 (`STRICT_REVIEW_TEMPLATES = _review_mod.STRICT_REVIEW_TEMPLATES`) — re-export of a deleted name; zero external consumers (grep evidence in §Issue premises). | trinity-glm |
| 3 | new `tests/test_strict_review.py` | Characterization tests (issue AC): all FIVE contract rows — None path (incl. one empty-string parametrize row), pair-mismatch SystemExit, malformed-id SystemExit, unsupported-combo SystemExit message, and the happy path asserting the FULL ENVELOPE: `enabled is True`, top-level `pass_threshold == 9.0` AND `== template["pass_threshold"]`, `calibration == "COR-1611"`, `output_schema == STRICT_REVIEW_OUTPUT_SCHEMA` (import both names), normalized `sop`/`rubric` at top level, nested template's 5 criteria + decision_rule prose. Parametrize the happy path over at least one lowercase variant (proves normalize precedes lookup). Error rows in ONE parametrized body; ~40 LoC. These PASS against current code (characterization — no RED phase; the refactor must keep them green). | trinity-deepseek |
| 4 | `CHANGELOG.md` | `[Unreleased]`: `### Changed` entry for the inline referencing #242; the re-export deletion filed under `### Removed` (Keep-a-Changelog convention for public-name removals, R1 glm advisory). | trinity-glm |
| 5 | `rules/TRN-0000-REF-Document-Index.md` | `af index` regen. | orchestrator |

Write sets disjoint (glm: scripts/ + CHANGELOG; deepseek: tests/).

## Acceptance Criteria

- [ ] `git grep STRICT_REVIEW_TEMPLATES -- scripts/ tests/` returns zero
  hits (rules/ history docs and the CHANGELOG removal prose legitimately
  retain mentions; wording per code-review R1 glm advisory).
- [ ] `resolve_strict_review` behavior byte-equal per the contract table;
  characterization tests green BEFORE and AFTER the inline (write-first,
  verify against current code, then refactor).
- [ ] Full `pytest -q` passes; ruff on changed files; `af validate`.
- [ ] PR body includes `Closes #242` + the TRN-3034-consistency note.

## Implementation Order

1. trinity-deepseek: characterization tests — MUST pass against CURRENT
   code (this is characterize-then-refactor, not RED/GREEN: the tests pin
   today's behavior so the refactor can't drift).
2. trinity-glm: Surfaces 1-2 + 4; characterization suite must stay green.
3. Orchestrator: verify, index, PR.

## Migration / Backward-compat

`STRICT_REVIEW_TEMPLATES` disappears as an importable name from both
`_review.py` and the `codex.py` re-export surface. Grep evidence: no
consumer exists outside the deleted re-export line itself. The #206
module-split promise ("existing importers unaffected") is not violated —
there are no importers; the promise protected call sites that existed at
split time, and this name's only split-time consumer was the re-export.
`resolve_strict_review` (the actually-used API) is unchanged.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 9.30 FAIL | 9.58 PASS | 9.50 PASS | ❌ |
| R2 (2026-07-04) | 9.51 PASS | — (R1 carry) | — (R1 carry) | ✅ |

R2 advisories (folded into Surface 3 as implementation notes): one-line
comment on the output_schema equality assertion's list-copy assumption;
empty-string row noted as bool()-semantics pin.

**Code-review tier (PR #287, head c0c1fb8):** deepseek 9.78 PASS (incl.
empirical pre-refactor green proof via git-archive run at the test commit);
glm **9.47 FAIL with EMPTY blocking list** — structural compression/
necessity floor, zero correctness findings, byte-identity + both-commit
green independently verified. glm's wrapper caught and reversed a
threshold-seeking re-score (9.47→9.49→"9.50"), recommitting the honest
9.47. **Delegate adjudication: PASS** — per the operator-ratified PR #276
precedent (empty-blocking structural dissent) and the operator's 2026-07-04
batch delegation ("作为我的代表来决定能不能合"); dissent recorded here and
in the PR verdict. Codex bot: clean @ c0c1fb8, zero findings.

R1 fold: happy-path contract row rewritten around the TOP-LEVEL ENVELOPE
(glm blocker — `write_synthesis` reads the envelope's `pass_threshold`, the
TRN-3034 threshold-flow key; pinning only the nested template would leave
that regression path unguarded); +malformed-id 5th branch row and
empty-string parametrize (deepseek/glm convergent); happy-path lowercase
parametrize; CHANGELOG re-export under `### Removed`. minimax ratified the
clean deletion over a shim (empty-dict stub = footgun) and calibrated the
necessity honestly (win smaller than the audit's framing; test-gap-fill on
a previously-untested API is the real lift).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #242. Adds the codex.py re-export surface + TRN-3034 consistency analysis the issue missed; characterize-then-refactor test order. | Claude Code (orchestrator) |

# CHG-3042: Plan Review MiniMax And Worker Role Split

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-18
**Last reviewed:** 2026-05-18
**Status:** Proposed
**Date:** 2026-05-18
**Requested by:** @frankyxhl chat directive 2026-05-18; tracked as issue #125
**Priority:** Medium
**Change Type:** SOP / routing policy
**Targets:** `main`
**Closes:** #125

---

## What

Update TRN-1008 so plan-review uses three required reviewers: GLM, DeepSeek, and MiniMax. Keep code-review separate: GLM + DeepSeek remain the required code-review panel unless the user explicitly requests MiniMax on a specific PR.

Update worker routing so implementation and test-code work are no longer sent to the same default worker:

- Implementation worker: `trinity-glm via droid exec`
- Test-code worker: `trinity-deepseek`
- Mixed implementation + test tasks dispatch both workers with disjoint write sets.

TRN-1209 is updated as the binding source of truth for the new plan-review tier, code-review tier, and worker role split.

## Why

MiniMax is already available as a Trinity provider (TRN-3035). Adding it to plan-review restores a third independent planning voice without increasing the latency of every code-review iteration. Separating implementation and test-code workers reduces single-model ownership of both behavior and the tests that prove it: GLM writes implementation; DeepSeek writes test code.

## Out of Scope

- No runtime provider registry change. MiniMax provider wiring already exists from TRN-3035.
- No `.agents/trinity.codex.json` preset change in this CHG; this is the TRN-1008 SOP and TRN-1209 binding policy.
- No change to the §8 code-review tier unless the user requests MiniMax for a specific PR.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| S1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` | §4 plan-review tier becomes GLM + DeepSeek + MiniMax; §5 worker routing splits implementation/test-code; §8 code-review tier stays GLM + DeepSeek; failure modes and guard rails updated. |
| S2 | `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md` | Binding rows split plan-review providers, code-review providers, implementation worker, and test-code worker. |
| S3 | `CHANGELOG.md` | Add Unreleased change note. |
| S4 | `rules/TRN-0000-REF-Document-Index.md` | Regenerate via `af index --root .`. |

## Acceptance Criteria

- [ ] TRN-1008 §4 names `trinity-minimax` as a required plan-reviewer alongside `trinity-glm` and `trinity-deepseek`.
- [ ] TRN-1008 §8 clearly keeps code-review on `trinity-glm` + `trinity-deepseek` unless explicitly overridden by the user.
- [ ] TRN-1008 §5 routes implementation work to GLM and test-code work to DeepSeek, with mixed tasks using disjoint write sets.
- [ ] TRN-1209 bindings match the SOP wording.
- [ ] `af index --root .` and `af validate --root .` pass.

## Implementation Order

1. Update TRN-1008 normative text and diagrams.
2. Update TRN-1209 bindings.
3. Add CHANGELOG entry.
4. Regenerate document index.
5. Validate with `af validate --root .`.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-18 | Initial draft and implementation. Direct user directive; docs-only routing change. | Codex |

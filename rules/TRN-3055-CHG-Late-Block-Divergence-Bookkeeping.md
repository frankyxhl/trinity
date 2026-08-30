# CHG-3055: Late-Block Divergence Bookkeeping

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-08-30
**Last reviewed:** 2026-08-30
**Status:** Proposed
**Date:** 2026-08-30
**Requested by:** Owner ruling PFC-2502/D25 via graph-engineering.bob (2026-08-30): split out of TRN-3054 so the PRP states intent only
**Priority:** Medium
**Change Type:** Process + tooling (doc amendments, new script, new tests)
**Targets:** `main`
**Related:** TRN-3054 (the compression carve-out PRP), TRN-1800 (weights), TRN-1008 (§4/§8/§9), issue #321 (deterministic score mapping — separate)

---

## What Is It?

The exact bookkeeping for the declared-vs-actual divergence check at every §8 re-score, moved verbatim out of TRN-3054 per the D25 ruling (a PRP states intent; the implementing CHG specifies and tests the algorithm). Scope: ALL cited blocks at every re-score — the first post-implementation one included — where a plan-time block's baseline is its pre-implementation declared budget and a late block's (demanded after the first §8 re-score) baseline is its fold-time record. Attribution across blocks is non-overlapping (Machinery item 6): a later fold overlapping an earlier block's span re-baselines the earlier block's measurement endpoint, so the extension counts once, for the late block. TRN-3054 keeps only the intent: acceptance folds record a baseline; oversized late tests trip the divergence check.

## Machinery (moved verbatim from TRN-3054 rounds 20–29; Citex-reviewed)

1. **Fold records.** Every acceptance fold that demands a test block records: the block's declared estimates (added/deleted/merged characters; merged defaults to 0 unless a consolidation is declared), its **fold-time baseline commit** (the head SHA at fold time), and a **stable locator** — file path plus the line range of the demanded block as it exists at that commit, captured from the fold's own diff.
2. **Actuals.** A late block's actuals — added, deleted, and merged separately — are derived by diffing **exactly the locator's span** between the baseline commit and the re-score head. Only changes since the fold count; replacing a 20-character assertion with a different one correctly yields 20 added + 20 deleted, not a zero delta.
3. **Merged intent (unchanged).** `chars merged` counts content eliminated by consolidation; pure relocations (verbatim moves, near or far, including whole-file moves) never count toward merged — their text counts once, in `chars deleted`. The exact counting algorithm (line/hunk/diff-tool semantics, anchors, canonical command) is defined and pinned by this CHG's implementation and its tests.
4. **Thresholds.** Checked PER BLOCK first — any single cited block whose aggregate delta exceeds 10% of that block's own combined (declared + actual) volume flags a Scope-restraint finding — plus the CHG-level aggregate (sum over all cited blocks vs 10% of combined volume) as a secondary catch. Per-block checking prevents older accurate blocks from diluting a late oversized one (a block declared 10, shipped 500, trips at 490/510 = 96% regardless of neighbors).
5. **Cadence.** Every §8 re-score — first post-implementation and all subsequent — runs the check over ALL cited blocks, newly folded ones included.
6. **Attribution (non-overlapping, by time window).** Every character change inside a cited block's span is attributed to exactly ONE block. Each block's actuals window runs from its own measurement baseline to the re-score head — a plan-time block's measurement baseline is the CHG's pre-implementation commit (its declared budget stays the plan estimate); a late block's is its fold-time baseline commit (item 2). When a later acceptance fold's locator overlaps an earlier cited block's span (e.g. a later finding extends the same test function), the earlier block's measurement endpoint is CLAMPED to the earliest overlapping fold's baseline commit: changes up to that commit count for the earlier block; changes after it within the overlapped span count for the late block alone. A legitimate extension that ships at its fold-time estimate therefore neither inflates the earlier block's actuals (no false Scope-restraint finding) nor counts twice in the CHG aggregate.

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` | Fold sites (§4 triage, §9 triage, §8 iterate-cycle folds, passing-round advisory-acceptance folds): fold rows gain item 1's record fields — declared per-component estimates, fold-time baseline commit, stable locator — and the §8 re-score step references this CHG for the all-block divergence check and the item-6 attribution clamp. | trinity-glm |
| 2 | `rules/TRN-3022-CHG-Normalize-Review-Result-Schema.md` | Schema note: fold records carry an optional `blocks` array (block/finding id + declared estimates + baseline commit + locator), populated at fold time by the orchestrator, never required from the model. | trinity-glm |
| 3 | `scripts/block_divergence.py` (new) | The canonical counting implementation this CHG pins: two-endpoint locator-span diff (`git diff --unified=0` between a block's measurement baseline and the re-score head, honoring the item-6 clamp), separate added/deleted/merged actuals, relocation exclusion, per-block and CHG-aggregate 10% verdicts; deterministic output for the grep audit. | trinity-glm |
| 4 | `tests/test_block_divergence.py` (new) | Pins Machinery items 2–6 on a fixture repo: component actuals incl. the replace-20-chars case (20 added + 20 deleted, not a zero delta); pure relocation never counts toward merged; per-block dilution case (declared 10 / shipped 500 trips at 96%) plus the aggregate catch; the item-6 clamp (late extension of a plan-time block at its declared estimate → counts once, no per-block finding, no aggregate inflation). | trinity-deepseek |
| 5 | `rules/TRN-0000-REF-Document-Index.md` + `CHANGELOG.md` | `af index` regen; `[Unreleased] ### Added` row referencing this CHG. | orchestrator |

## Acceptance Criteria

- [ ] The implementing change wires fold records (estimates + baseline commit + locator) into the TRN-1008 fold sites
- [ ] Actuals derive from the two-endpoint locator-span diff; the three components are computed separately
- [ ] No pure relocation ever counts toward merged; relocations count once via chars deleted (tested)
- [ ] Per-block and CHG-level thresholds both implemented and tested, including the dilution case
- [ ] Non-overlapping attribution (item 6) implemented and tested: a late fold overlapping an earlier cited block's span clamps the earlier block's measurement endpoint to that fold's baseline commit; the extension counts exactly once — no false per-block Scope-restraint finding, no double count in the CHG aggregate
- [ ] `af validate` clean

## Implementation Order

1. trinity-deepseek: contract tests (surface 4) RED first — they encode Machinery items 2–6, including the attribution clamp.
2. trinity-glm: implement `scripts/block_divergence.py` (surface 3) to green; ruff clean.
3. trinity-glm: TRN-1008 fold-site record fields + §8 re-score reference (surface 1); TRN-3022 optional `blocks` note (surface 2).
4. trinity-minimax: worked example — synthetic plan-time block + late extension shipped at its fold-time estimate, showing the clamp yields no divergence finding; recorded in this CHG.
5. Verify + ship: full `pytest -q`, ruff the new files, `af validate`, `af index`, CHANGELOG row, commit.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-08-30 | Initial draft (Status: Proposed): machinery moved verbatim from TRN-3054 per D25 ruling; rounds 20–29 of the #319 Codex review are the provenance. | pi (ryosaeba1985) |
| 2026-08-30 | Round 32: added non-overlapping attribution (Machinery item 6 — a late fold overlapping an earlier block clamps its measurement endpoint) and completed the TRN-1008 CHG skeleton (frontmatter fields, Surfaces, Implementation Order). | pi (ryosaeba1985) |

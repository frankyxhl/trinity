# CHG-3055: Late-Block Divergence Bookkeeping

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-08-30
**Last reviewed:** 2026-08-30
**Status:** Proposed
**Requested by:** Owner ruling PFC-2502/D25 via graph-engineering.bob (2026-08-30): split out of TRN-3054 so the PRP states intent only
**Related:** TRN-3054 (the compression carve-out PRP), TRN-1800 (weights), TRN-1008 (§4/§8/§9), issue #321 (deterministic score mapping — separate)

---

## What Is It?

The exact bookkeeping for the declared-vs-actual divergence check on test blocks demanded AFTER the first §8 re-score, moved verbatim out of TRN-3054 per the D25 ruling (a PRP states intent; the implementing CHG specifies and tests the algorithm). TRN-3054 keeps only: late acceptance folds record a baseline; oversized late tests trip the divergence check.

## Machinery (moved verbatim from TRN-3054 rounds 20–29; Citex-reviewed)

1. **Fold records.** Every acceptance fold that demands a test block records: the block's declared estimates (added/deleted/merged characters; merged defaults to 0 unless a consolidation is declared), its **fold-time baseline commit** (the head SHA at fold time), and a **stable locator** — file path plus the line range of the demanded block as it exists at that commit, captured from the fold's own diff.
2. **Actuals.** A late block's actuals — added, deleted, and merged separately — are derived by diffing **exactly the locator's span** between the baseline commit and the re-score head. Only changes since the fold count; replacing a 20-character assertion with a different one correctly yields 20 added + 20 deleted, not a zero delta.
3. **Merged intent (unchanged).** `chars merged` counts content eliminated by consolidation; pure relocations (verbatim moves, near or far, including whole-file moves) never count toward merged — their text counts once, in `chars deleted`. The exact counting algorithm (line/hunk/diff-tool semantics, anchors, canonical command) is defined and pinned by this CHG's implementation and its tests.
4. **Thresholds.** Checked PER BLOCK first — any single cited block whose aggregate delta exceeds 10% of that block's own combined (declared + actual) volume flags a Scope-restraint finding — plus the CHG-level aggregate (sum over all cited blocks vs 10% of combined volume) as a secondary catch. Per-block checking prevents older accurate blocks from diluting a late oversized one (a block declared 10, shipped 500, trips at 490/510 = 96% regardless of neighbors).
5. **Cadence.** Every §8 re-score — first post-implementation and all subsequent — runs the check over ALL cited blocks, newly folded ones included.

## Acceptance Criteria

- [ ] The implementing change wires fold records (estimates + baseline commit + locator) into the TRN-1008 fold sites
- [ ] Actuals derive from the two-endpoint locator-span diff; the three components are computed separately
- [ ] No pure relocation ever counts toward merged; relocations count once via chars deleted (tested)
- [ ] Per-block and CHG-level thresholds both implemented and tested, including the dilution case
- [ ] `af validate` clean

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-08-30 | Initial draft (Status: Proposed): machinery moved verbatim from TRN-3054 per D25 ruling; rounds 20–29 of the #319 Codex review are the provenance. | pi (ryosaeba1985) |

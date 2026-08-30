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

The exact bookkeeping for the declared-vs-actual divergence check at every §8 re-score, moved verbatim out of TRN-3054 per the D25 ruling (a PRP states intent; the implementing CHG specifies and tests the algorithm). Scope: ALL cited blocks at every re-score — the first post-implementation one included — where a plan-time block's baseline is its pre-implementation declared budget and a late block's (demanded after the first §8 re-score) baseline is its fold-time record. Attribution across blocks is non-overlapping (Machinery item 6): a later fold overlapping an earlier block's span re-baselines the earlier block's measurement endpoint within the overlap, so the extension counts once, for the late block. TRN-3054 keeps only the intent: acceptance folds record a baseline; oversized late tests trip the divergence check.

## Machinery (moved verbatim from TRN-3054 rounds 20–29; Citex-reviewed)

1. **Fold records.** Every acceptance fold that demands a test block records: the block's declared estimates (added/deleted/merged characters; merged defaults to 0 unless a consolidation is declared), its **fold-time baseline commit** (the head SHA at fold time), and a **stable locator** — file path plus the line range of the demanded block as it exists at that commit, captured from the fold's own diff. A demanded block that does not exist at the fold commit (a wholly new test) records an **insertion anchor** instead: file path plus the nearest stable existing anchor the finding itself names (the containing function/class it extends, or the adjacent line/hunk it cites), as that anchor exists at the fold commit. At the first re-score whose head contains the block, the anchor is **promoted** to the realized span — captured from the implementing diff — and the promotion is recorded in the fold record; from then on the span is the locator. A locator is therefore well-defined at every point between fold and re-score. If the finding names no anchor of its own, the orchestrator records a deterministic fallback: the file the finding's evidence cites — or, for a cross-cutting finding with empty evidence, the intended target file the orchestrator designates at acceptance per the implementing CHG's test-layout convention — anchored at that file's fold-commit end-of-file line. Promotion at first sight is citation-driven and file-independent: the added block carrying an inline `# pins <finding-id>` marker, or the exact additions a Change-History row maps that finding ID to, searched across the implementing push's whole diff (finding IDs are globally unique, so the designated file is a planning hint, never a blocker). A fold-time locator always exists — named anchor, cited file, or neither.
2. **Actuals.** A late block's actuals — added, deleted, and merged separately — are derived by diffing **exactly the locator's span** between the baseline commit and the re-score head. Only changes since the fold count; replacing a 20-character assertion with a different one correctly yields 20 added + 20 deleted, not a zero delta.
3. **Merged intent (unchanged).** `chars merged` counts content eliminated by consolidation; pure relocations (verbatim moves, near or far, including whole-file moves) never count toward merged — their text counts once, in `chars deleted`. The exact counting algorithm (line/hunk/diff-tool semantics, anchors, canonical command) is defined and pinned by this CHG's implementation and its tests.
4. **Thresholds.** Three tiers, smallest first: (a) PER COMPONENT within a block — |actual − declared| for added, deleted, and merged each vs 10% of that component's own combined (declared + actual) volume; (b) PER BLOCK — the block's aggregate delta vs 10% of its combined volume; (c) the CHG-level aggregate (sum over all cited blocks) as a secondary catch. Component-first prevents an accurate large component from hiding an oversized small one in the same block — declared/actual deletion of 10,000 plus declared addition 10 / actual addition 500 trips at the component tier (490/510 = 96%) even though the block aggregate is only 2.4%; block-tier prevents older accurate blocks from diluting a late oversized one (declared 10, shipped 500 → 96% regardless of neighbors). Any tier breach flags a Scope-restraint finding in that §8 re-score verdict — blocking-class: the verdict cannot declare CLEAN with one open until the block is trimmed or an honest re-estimate is accepted in a new fold. A re-estimate fold updates ONLY the block's declared estimates; the measurement baseline, locator, and actuals-to-date are retained, so the next re-score compares full actuals-to-date against the new declaration — an honest re-estimate of shipped reality yields a near-zero delta, while padding the estimate to hide growth re-breaches when that growth ships.
5. **Cadence.** Every §8 re-score — first post-implementation and all subsequent — runs the check over ALL cited blocks, newly folded ones included.
6. **Attribution (non-overlapping, by span×time).** Every character change is attributed to exactly ONE cited block: the block whose span contains the change and whose measurement window covers the commit that introduced it. Each block's window runs from its own measurement baseline to the re-score head — a plan-time block's measurement baseline is the CHG's pre-implementation commit (its declared budget stays the plan estimate); a late block's is its fold-time baseline commit (item 2). When a later fold's locator overlaps only PART of an earlier block's span, the earlier block's window is cut back to that fold's baseline commit ONLY WITHIN the spatial intersection; outside the intersection it still runs to the re-score head. A late assertion covering lines 10–12 of a 20-line cited function takes over exactly lines 10–12 after the fold — a post-fold correction on lines 2–3 still counts for the earlier block — while a legitimate extension shipped at its fold-time estimate neither inflates the earlier block's actuals (no false Scope-restraint finding) nor counts twice in the CHG aggregate.

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` | Fold sites (§4 triage, §9 triage, §8 iterate-cycle folds, passing-round advisory-acceptance folds): fold rows gain item 1's record fields — declared per-component estimates, fold-time baseline commit, stable locator — and the §8 re-score step references this CHG for the all-block divergence check and the item-6 attribution clamp. | trinity-glm |
| 2 | `rules/TRN-3022-CHG-Normalize-Review-Result-Schema.md` | Schema note: fold records carry an optional `blocks` array (block/finding id + declared estimates + baseline commit + locator), populated at fold time by the orchestrator, never required from the model. | trinity-glm |
| 3 | `scripts/block_divergence.py` (new) | The canonical counting implementation this CHG pins: two-endpoint locator-span diff (`git diff --unified=0` between a block's measurement baseline and the re-score head, honoring the item-6 clamp), separate added/deleted/merged actuals, relocation exclusion, component/block/CHG-aggregate 10% verdicts with blocking Scope-restraint findings on any breach; deterministic output for the grep audit. | trinity-glm |
| 4 | `tests/test_block_divergence.py` (new) | Pins Machinery items 1–6 on a fixture repo: component actuals incl. the replace-20-chars case (20 added + 20 deleted, not a zero delta); the item-1 insertion anchor promoted to a span at the first re-score that sees the block, incl. the no-named-anchor fallback (file-level anchor — cited file or designated target file for file-less findings — promoted span resolved by either citation form across the implementing diff); pure relocation never counts toward merged; per-component dilution (deletion 10,000 accurate + addition 10→500 trips at 96% despite a 2.4% block aggregate) plus the block-tier dilution case (declared 10 / shipped 500 trips at 96%) and the aggregate catch; the re-estimate recovery path (declaration-only update, baseline retained); the item-6 SPATIAL clamp (late extension at its declared estimate → counts once, no false finding; a post-fold edit outside the overlap still counts for the earlier block). | trinity-deepseek |
| 5 | `rules/TRN-0000-REF-Document-Index.md` + `CHANGELOG.md` | `af index` regen; `[Unreleased] ### Added` row referencing this CHG. | orchestrator |

## Acceptance Criteria

- [ ] The implementing change wires fold records (estimates + baseline commit + locator, with insertion anchors promoted to realized spans at first sight — deterministic file-level fallback when the finding names no anchor or file: designated target file at acceptance, promotion citation-driven — inline `# pins` marker or Change-History row) into the TRN-1008 fold sites
- [ ] Actuals derive from the two-endpoint locator-span diff; the three components are computed separately
- [ ] No pure relocation ever counts toward merged; relocations count once via chars deleted (tested)
- [ ] Component-tier, per-block, and CHG-level thresholds all implemented and tested, including both dilution cases: accurate blocks hiding an oversized one (block tier), and an accurate large component hiding an oversized small one in the same block (component tier)
- [ ] A threshold breach at any tier emits a blocking Scope-restraint finding in the §8 verdict — the re-score cannot declare CLEAN with one open
- [ ] The re-estimate recovery path is tested: a re-estimate fold updates only the declared estimates — measurement baseline, locator, and actuals-to-date are retained
- [ ] Non-overlapping attribution (item 6) implemented and tested: a late fold overlapping part of an earlier cited block's span cuts the earlier block's window back to that fold's baseline commit WITHIN the spatial intersection only — the extension counts exactly once (no false per-block Scope-restraint finding, no double count in the CHG aggregate), and a post-fold edit outside the overlap still counts for the earlier block
- [ ] `af validate` clean

## Implementation Order

1. trinity-deepseek: contract tests (surface 4) RED first — they encode Machinery items 1–6, including anchor promotion and the spatial attribution clamp.
2. trinity-glm: implement `scripts/block_divergence.py` (surface 3) to green; ruff clean.
3. trinity-glm: TRN-1008 fold-site record fields + §8 re-score reference (surface 1); TRN-3022 optional `blocks` note (surface 2).
4. trinity-minimax: worked example — synthetic plan-time block + late extension shipped at its fold-time estimate, showing the clamp yields no divergence finding; recorded in this CHG.
5. Verify + ship: full `pytest -q`, ruff the new files, `af validate`, `af index`, CHANGELOG row, commit.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-08-30 | Initial draft (Status: Proposed): machinery moved verbatim from TRN-3054 per D25 ruling; rounds 20–29 of the #319 Codex review are the provenance. | pi (ryosaeba1985) |
| 2026-08-30 | Round 32: added non-overlapping attribution (Machinery item 6 — a late fold overlapping an earlier block clamps its measurement endpoint) and completed the TRN-1008 CHG skeleton (frontmatter fields, Surfaces, Implementation Order). | pi (ryosaeba1985) |
| 2026-08-30 | Round 33: item-6 clamp made spatial (intersection-only, so post-fold edits outside an overlap are never dropped); item 1 gains the insertion anchor for blocks absent at fold time, promoted to a realized span at first sight. | pi (ryosaeba1985) |
| 2026-08-30 | Round 34: item 4 thresholds now three-tier (component → block → CHG aggregate) so an accurate large component cannot hide an oversized small one; item 1 gains the deterministic no-named-anchor fallback (file-level anchor; `# pins` marker disambiguates promotion). | pi (ryosaeba1985) |
| 2026-08-30 | Round 35: restored the breach outcome — any tier breach emits a blocking Scope-restraint finding that holds the §8 verdict out of CLEAN; anchor promotion now resolves both permitted citation forms (inline marker or Change-History row). | pi (ryosaeba1985) |
| 2026-08-30 | Round 36: re-estimate recovery defined — a re-estimate fold updates only the declared estimates; measurement baseline, locator, and actuals-to-date are retained (tested). | pi (ryosaeba1985) |
| 2026-08-30 | Round 37: file-less cross-cutting findings get a designated target file at acceptance, and anchor promotion is citation-driven and file-independent (whole-diff marker search). | pi (ryosaeba1985) |

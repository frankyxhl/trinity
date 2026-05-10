# CHG-3039: Align TRN-1008 with Promoted PKG Multi-Agent Loop Family

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-10
**Last reviewed:** 2026-05-10
**Status:** Proposed
**Date:** 2026-05-10
**Requested by:** @frankyxhl (chat directive: "we have a promoted SOP. can you study and revise TRN-1008?")
**Priority:** Medium
**Change Type:** Refactor (documentation alignment)
**Targets:** `main`
**Builds on:** COR-1801 (Pattern Promotion meta-SOP) — COR-1617 cluster was promoted from TRN-1008 lineage per its §Lineage note.

---

## What

The PKG layer now ships the **Multi-Agent Loop family** — COR-1615 (GitHub App PR Review Bot Loop), COR-1617 (umbrella), COR-1618 (consent gate), COR-1619 (worker dispatch), COR-1620 (loop primitives), COR-1621 (triage), COR-1622 (parameter schema). Per COR-1617's §Lineage paragraph, this cluster was promoted directly from TRN-1008's R1–R26 evolution + follow-up CHGs (TRN-3029 / TRN-3030 / TRN-3031), with explicit attribution.

This CHG aligns TRN-1008 with the promoted PKG family without losing the trinity-specific overlays that PKG does not cover.

Concretely:

1. **NEW `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md`** — pure parameter binding per COR-1622 schema. Resolves every config-placeholder TRN-1008 / COR-1617 cluster docs cite (`<repo>`, `<consent-signal>`, `<panel-providers>`, `<wakeup-tool>`, etc.) to a concrete trinity value, plus seven trinity-only extension bindings (`$AGENT_GH_LOGIN`, `$TRUSTED_REACTOR`, `$REPO`, concurrent-PR cap N, agent-branch prefix regex, CLARIFY round-counter cap, fast-review-tier providers — seven rows in TRN-1209 §Trinity-only extensions). Single source of truth for config-bindings — runtime placeholders (`<seconds>`, `<N>`, `<BRANCH_NAME>`, etc.) follow COR-1622 §Placeholder Convention's runtime-namespace and are NOT in TRN-1209. Orchestrators read this REF once per session.

2. **TRN-1008 §0 prologue** — new top-of-doc section: "Relationship to PKG cluster". Maps each existing TRN-1008 section to its owning COR doc (e.g. §1 base auto-pick → COR-1618; §2 → COR-1505; §4 → COR-1602 + COR-1617 §4; §5 → COR-1619; §8 → COR-1615 + COR-1620; §9 → COR-1621; §Threat Model → COR-1618 §Threat Model; §Failure Modes → COR-1620 §Stop conditions). Preserves existing TRN-1008 prose (the *why-this-shape* archaeology that survives in the CHG/R-iteration history) but makes the PKG dependency explicit. Per the user's choice, **annotated existing** shape (vs thin overlay) — every existing TRN-1008 section is retained; PKG xrefs are added in-line.

3. **TRN-1008 per-section PKG xrefs** — adds a one-line "Shared with COR-XXXX" annotation directly under each section header that overlaps PKG. Eleven sections receive an annotation: §1, §2, §3, §4, §5, §6, §7, §8, §9, §10, §11. The trinity-only sections (§1.5 Comprehension check) carry no PKG xref — they remain trinity overlays. Cross-cutting sections (§Threat Model, §Panel-Review Gate detail, §Failure Modes (a)–(f)) carry their PKG mappings inside the §0 prologue table rather than as per-header annotations, since their content spans multiple PKG docs (COR-1618 + COR-1620 + COR-1621).

4. **TRN-1008 §Related list** — adds COR-1617, COR-1618, COR-1619, COR-1620, COR-1621, COR-1622 + reference to TRN-1209.

5. **TRN-1008 §Change History row** — records the alignment.

6. **TRN-0000 index regen** via `af index --root .` to pick up TRN-1209 + TRN-3039.

7. **CHANGELOG `[Unreleased] ### Changed`** — entry summarizing the alignment.

## Why

**Promotion creates an SSOT split.** Before COR-1617 cluster, TRN-1008 was the only authoritative source for the multi-agent-loop pattern. Now the *generalized* shape lives in PKG and the *trinity-specific overlays* live here. Without explicit xrefs and a parameter binding doc, the two layers drift independently and orchestrators reading TRN-1008 cannot tell which prose is shared (PKG-canonical) from which is trinity-only.

**The four design decisions captured here:**

1. **Annotated existing, not thin overlay** — preserves R1–R26 archaeology (lineage note in COR-1617 §Lineage cites trinity PRs #66 → #73 explicitly; the prose those PRs shaped lives in TRN-1008 today and disappears under a thin-overlay rewrite). Aligns with the project's evolution philosophy (CLD-1800) which values archaeology over compression for governance docs.

2. **Sibling parameter REF** instead of inlined values — every TRN-1008 mention of `frankyxhl` / `ryosaeba1985` / `trinity-glm` / `TRN-1800` / `2FA` becomes a single citation chain (TRN-1008 → TRN-1209 → COR-1622 schema). One value change touches one row of one REF; no SOP edits propagate.

3. **Trinity overlays kept verbatim** — §1.5 Comprehension check, CHG-3036 dual-state mergeable-gate, CHG-3037 wake-prompt-refs, CHG-3038 round-counter / CLARIFY-via-comment, fast-review tier ≥9.5, agent-branch prefix regex (`^(codex|claude)/`), concurrent-PR cap N≤2 — these are NOT in PKG. The CHG documents the boundary.

4. **No panel-review** for this CHG — alignment-after-promotion is documentation routing, not behaviour change. Per COR-1104, this falls below the substantive-CHG threshold; recorded for traceability only.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md` (NEW) | Pure parameter binding per COR-1622 schema; resolves all placeholders + 6 trinity-only extension bindings. |
| 2 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §0 prologue (NEW, after the **Related** line) | New "Relationship to PKG cluster" section: maps every overlapping TRN-1008 section to its owning COR doc; explicitly lists trinity-only overlays not in PKG. |
| 3 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` per-section xrefs | One-line "Shared with COR-XXXX (see there for the canonical pattern)" added under each section header that overlaps PKG. Trinity-only sections unchanged. |
| 4 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §Related line (~L7) | Append `COR-1617, COR-1618, COR-1619, COR-1620, COR-1621, COR-1622` + reference to TRN-1209. |
| 5 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §Change History | New row: `2026-05-10 | CHG-3039: align with promoted PKG (COR-1617 cluster); §0 prologue + per-section xrefs + TRN-1209 sibling.` |
| 6 | `rules/TRN-3039-CHG-Align-With-Promoted-PKG.md` (this file, NEW) | Records the rationale + surfaces. |
| 7 | `rules/TRN-0000-REF-Document-Index.md` | Regenerated by `af index --root .`. |
| 8 | `CHANGELOG.md` `[Unreleased] ### Changed` | Entry: "TRN-1008 aligned with promoted PKG multi-agent loop family (COR-1615/1617/1618/1619/1620/1621/1622); new TRN-1209 parameter binding doc; trinity-specific overlays preserved. CHG-3039." |

**Atomicity note**: per CLD-1802 surface taxonomy, this CHG is a cross-class set (single-purpose REF/CHG file additions + multi-section TRN-1008 edits). Bundled because partial application creates a worse intermediate state than either endpoint (e.g. xrefs without TRN-1209 leaves placeholders unresolved; TRN-1209 without xrefs leaves the dependency invisible). Surfaces 1-2-3-5 form the coherent alignment unit; 6-7-8 are the standard CHG/index/changelog tail.

**Compression note**: net-positive growth (~+200 lines on TRN-1209 + ~50 lines on TRN-1008 §0 + ~10 lines of xrefs). Justified per TRN-1800 doc weights: necessity (high — promotion is the trigger; without alignment, the SSOT split silently drifts), atomicity (each surface = one decision), consistency (this CHG IS the consistency restoration). Compression dimension is unfavourable but the alternative (no-op until natural drift makes alignment harder) is worse.

## Acceptance Criteria

- [ ] Surface 1: TRN-1209 created; every COR-1622 required key has a value (no `unset`); trinity-only extension bindings table present.
- [ ] Surface 2: TRN-1008 §0 prologue lists every overlapping section with its owning COR doc; lists every trinity-only overlay separately.
- [ ] Surface 3: every TRN-1008 §1 / §2 / §3 / §4 / §5 / §6 / §7 / §8 / §9 / §10 / §11 section has a "Shared with COR-XXXX" annotation directly under its header where applicable; §1.5 has no annotation (trinity-only).
- [ ] Surface 4: §Related line cites COR-1617/1618/1619/1620/1621/1622 + TRN-1209.
- [ ] Surface 5: TRN-1008 §Change History row added (UTC 2026-05-10).
- [ ] Surface 7: `af index --root .` regenerated; TRN-1209 and TRN-3039 appear.
- [ ] Surface 8: CHANGELOG entry added.
- [ ] `af validate --root .` clean.
- [ ] No removal of existing TRN-1008 prose (this CHG is additive — annotation only).
- [ ] PR body: `Closes` no issue (this CHG was directly requested in chat, no tracking issue); cross-link COR-1617 §Lineage as the upstream trigger.

## Migration / Backward-compat

**Zero behaviour change.** Orchestrators executing TRN-1008 see identical procedure; the new prologue + xrefs are reading aids, not directives. Existing in-flight PRs are unaffected. Future PRs can cite COR-1617 cluster docs by ACID; old PRs that cite TRN-1008 by section number remain valid.

**Operator-facing**: TRN-1209 is a new mandatory read for any operator setting up a fresh trinity clone — substituting for the previously-implicit "look up the inline values in TRN-1008". This is a documentation improvement, not a workflow change.

## Threat Model assessment

**No new attack surface.** The CHG is documentation alignment; no consent paths, no review gates, no git operations are altered.

**Accepted residual**: TRN-1008 is now ~907 lines of prose plus xrefs against a 6-doc PKG cluster — total reading load increased. Mitigation: TRN-1209 collapses every value lookup to one table; §0 prologue lets readers route directly to PKG for shared sections without re-reading trinity-specific overlay prose. Net reading load is up-front (one-time) rather than per-task (each session).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-10 | Initial draft (Status: Proposed). User-directed alignment after PKG cluster promotion. | Claude Opus 4.7 |

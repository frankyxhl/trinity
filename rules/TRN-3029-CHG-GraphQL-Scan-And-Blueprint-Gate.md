# CHG-3029: GraphQL Scan + Blueprint-Ready Label Gate

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** @frankyxhl
**Priority:** Medium
**Change Type:** Feature
**Targets:** `main`
**Closes:** #85
**Builds on:** TRN-1008 (R20-R26 hardened the per-issue gate; R17 collapsed bypass-clause duplications; this CHG honors both invariants)
**Supersedes:** #84 (closed; bundled here per @frankyxhl direction)

---

## What

Two coordinated changes:

1. **Scan efficiency** — new `scripts/scan_rocket_issues.sh` does pure label-narrowing via single-call GraphQL (`issues(states: OPEN, labels: ["blueprint-ready"])`). Returns candidate issue numbers. Drops O(N) per-issue REST loop; reduces to one GraphQL call + per-candidate REST verify.

2. **Two-layer gate** — `verify_rocket_eligibility` in TRN-1008 §1 grows from 4 checks to 5. Check 5 = blueprint-ready label currently present AND most-recent `LABELED` event for that label has `actor.login` ∈ trusted set (`iterwheel-blueprint[bot]`, `$TRUSTED_REACTOR`). REST per-issue, paginated, fail-closed.

**Architecture decision (R3 pivot):** the script does NARROW (server-side label filter only); the per-issue gate does TRUTH (full 5 checks via REST with proper pagination). Bug class avoided: any nested-connection truncation in GraphQL (reactions, timeline, labels) would only false-negative the scanner's narrowing — and the gate is authoritative. R2 conflated the two responsibilities (GraphQL doing rocket + applier filters as well), introducing 4 truncation/lifecycle bugs codex caught. R3 separates them.

## Why

- **Scan efficiency**: per-issue REST is O(N) — 6s/tick for 13 issues, ~500s for 1000. Label-only GraphQL scan + per-candidate REST is O(1 + K) where K = blueprint-ready issue count. Faster AND simpler.
- **Intake-quality gate**: 🚀 alone passes today's gate even when the issue has no structured intake. `iterwheel-blueprint[bot]` already enforces intake via `/blueprint`; this CHG surfaces that signal into the rocket-gate.

## R-history (panel-driven)

- R1 (mean 6.275, all FIX): test coverage gap, bash 3.2 compat, SSOT, exec-bit, labels(first:20) overclaim, "no extra API call" inconsistency, label attack-surface, bypass-clause ambiguity.
- R2 (mean 8.55, gemini PASS @ 9.9 / glm 8.6 / deepseek 8.5 / codex 7.2): R1 blockers resolved BUT R2 introduced 4 new codex blockers — applier-identity lifecycle bug (trusted-add → untrusted-readd accepted), reactions(first:20) reintroduces reaction-spam DoS, timelineItems(first:50) truncation + missing UNLABELED_EVENT, A20 test gaps. Plus glm flagged compression (~10 redundant lines) and deepseek flagged A23 phantom-reference (count-free language needed).
- **R3 (this revision)**: architecture pivot per codex's lifecycle finding — script becomes label-narrower only; gate owns lifecycle. Drops nested-connection bugs entirely. Compression + A23 fixed.

## Out of Scope

- Migration of #74-#83 — happens organically via `/blueprint`. Rocket-gate idle until each issue has both signals.
- Bot-down fallback — `$TRUSTED_REACTOR` can manually apply `blueprint-ready`; gate accepts via applier-identity rule.
- Changes to TRN-1008 phases other than §1 / §Threat Model / §Examples / §Change History.
- Install-manifest SSOT (#79). Until that ships, install.sh + Makefile + tests/test_install_sh.sh updated in parallel.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `scripts/scan_rocket_issues.sh` (NEW) | Label-narrower GraphQL scan. ~25 lines bash. Bash 3.2 compat. jq dep check. |
| 2 | `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1 | Spec table 4→5 rows; row 5 = applier-identity-aware label check. Mermaid + fail-closed prose use generic "all checks" wording (R17 SSOT). One-line note pointing at the script. |
| 3 | TRN-1008 §1 normative bypass clause | One sentence: live-chat picks bypass ALL checks, count-free phrasing. |
| 4 | TRN-1008 §Threat Model | One new attack/defense pair (rocketed-without-blueprint-ready OR untrusted-applier). Bot-timing-race note. |
| 5 | TRN-1008 §Examples + §Change History | Row + history entry. |
| 6 | `install.sh` + `Makefile install` + `tests/test_install_sh.sh` T1 | Install + assert-executable. (Single-source install-manifest deferred per #79.) |
| 7 | `CHANGELOG.md` | `[Unreleased] ### Added` (script + test) + `### Changed` (gate semantics). |
| 8 | `tests/test_scan_rocket_issues.sh` (NEW) | 8 mocked-`gh` cases (T1a-T1h) covering script behavior + edge cases. |

## Acceptance Criteria

**Script (scripts/scan_rocket_issues.sh):**
- **A1**: exists, mode 0755, takes `$REPO` (defaulted via `gh repo view --json nameWithOwner -q .nameWithOwner`). Script does NOT consume `$TRUSTED_REACTOR` — that env var is consumed by `verify_rocket_eligibility` (the per-candidate gate), not the label-narrower. (Per glm R3 advisory: avoid required-but-unused env vars.)
- **A2**: GraphQL query is **pure label-narrower**: `issues(states: OPEN, labels: ["blueprint-ready"])`. NO reaction filter. NO timeline/applier filter. Pagination via `pageInfo.hasNextPage` + `endCursor`. Output = one issue number per line for every issue with the label currently present (rocket + applier-identity verified per-candidate by `verify_rocket_eligibility`, NOT by the script).
- **A3**: Exits 0 on success regardless of result count; non-zero on `gh` failure, auth error, or missing `jq`.
- **A4**: Output format suitable for `xargs` / `while read` consumption.
- **A5**: Smoke-test on `frankyxhl/trinity`: returns set of issue numbers that have blueprint-ready label currently present (regardless of rocket — verify_rocket_eligibility authoritative for full eligibility).

**TRN-1008 SOP amendments:**
- **A6**: §1 spec table has 5 rows. Row 5 = "blueprint-ready label currently present AND most-recent LABELED event for that label has `actor.login` ∈ {`iterwheel-blueprint[bot]`, `$TRUSTED_REACTOR`}". Source: `gh api repos/$REPO/issues/$N` (existing check-1 REST call returns `.labels[]` for label-presence) + `gh api repos/$REPO/issues/$N/timeline --paginate` for applier-identity (shared with check 3 which already paginates timeline).
- **A7**: §1 mermaid `V` node uses generic "Pass: ALL checks | Fail: any check fails — fail-closed" wording. NO per-check restate.
- **A8**: §1 fail-closed prose uses generic "any check failure → not eligible; checks documented in spec table above". NO per-check restate.
- **A9**: §1 has a short usage-shape note showing the Phase 1 flow: `scripts/scan_rocket_issues.sh | while read N; do verify_rocket_eligibility "$N" || continue; … done` — script narrows; gate is authoritative for the 5 checks. (Per codex R3 advisory A3.)
- **A10**: §1 normative bypass clause adds ONE sentence (count-free): "User-directed picks bypass ALL `verify_rocket_eligibility` checks. Live chat input subsumes both consent and intake-quality signals."
- **A11**: §Threat Model adds ONE new attack/defense pair: "rocketed without blueprint-ready, OR with label applied by non-trusted user → 5th check fails closed". Brief bot-timing-race note: "rocketed-but-unlabeled issue silently skipped per cron tick until bot labels it; expected; operator runs `/blueprint` to trigger."
- **A12**: §Examples row showing eligible state.
- **A13**: §Change History row referencing this CHG.

**Implementation of check 5 in `verify_rocket_eligibility` (REST):**
- **A14**: Check 5 fetches `gh api repos/$REPO/issues/$N/timeline --paginate`, filters events where `event ∈ {"labeled", "unlabeled"}` AND `label.name == "blueprint-ready"`, sorts by `created_at` ascending, walks forward to determine current-state-and-actor, and asserts: (a) current state is "labeled" (consistent with check-1's `.labels[]` containing the label), (b) most recent `event == "labeled"` for blueprint-ready has `actor.login` ∈ trusted set. Fail-closed on any error. **Same-second tie-break (per codex R3 advisory A1):** GitHub timestamps are second-granular; if two events for `blueprint-ready` share an identical `created_at`, fail closed (do not infer order). Parallel to TRN-1008 R26 history note on rocket-vs-event tie-breaks.

**Install + tests:**
- **A15**: `install.sh` adds `_download` line for the script + explicit `chmod +x` (since `_download` doesn't preserve mode).
- **A16**: `Makefile install` adds copy line (`cp -r` preserves +x).
- **A17**: `tests/test_install_sh.sh` T1 asserts `[ -x ~/.claude/skills/trinity/scripts/scan_rocket_issues.sh ]`.
- **A18**: NEW `tests/test_scan_rocket_issues.sh` exists, mode 0755, runs in `make test`. Mocks `gh` via shim. **8 cases**:
  - **T1a**: blueprint-ready label present → output contains issue number (exit 0).
  - **T1b**: blueprint-ready absent → empty output (exit 0).
  - **T1c**: pagination across 2 pages with eligible issue on page 2 → output contains that number.
  - **T1d**: `$REPO` not set AND `gh repo view` fails (no current-repo context) → exit non-zero with clear stderr.
  - **T1e**: `gh api` failure mid-pagination → exit non-zero.
  - **T1f**: empty repo (no issues) → empty output (exit 0).
  - **T1g**: missing `jq` → exit non-zero (per A3 entry-check).
  - **T1h**: 100+ blueprint-ready issues forcing pagination → all returned.

  *(T1g coverage of the trusted-reactor-as-applier and rocket-pagination edge cases moves from script-tests to gate-tests since the script is no longer responsible for those checks. Gate tests are TRN-1008's existing surface; outside this CHG.)*

**Build hygiene:**
- **A19**: `af validate --root .` clean. `make test` clean.
- **A20**: Reference implementation (below) accurately reflects what will land.

## Implementation Order

1. Branch off `origin/main` (per TRN-1008 §2).
2. Create `scripts/scan_rocket_issues.sh` per reference impl. `chmod +x`.
3. Create `tests/test_scan_rocket_issues.sh` per A18. `chmod +x`.
4. Smoke-test: `bash tests/test_scan_rocket_issues.sh` → all 8 pass; `TRUSTED_REACTOR=frankyxhl ./scripts/scan_rocket_issues.sh` returns issues with blueprint-ready label.
5. Update TRN-1008 SOP per Surfaces #2-#5. SSOT enforced: 5 checks listed ONCE in spec table.
6. Update `verify_rocket_eligibility` semantics in TRN-1008 §1 spec table row 5 (A14 algorithm spec).
7. Wire install: `install.sh` (`_download` + `chmod +x`), `Makefile install` (`cp` line).
8. Update `tests/test_install_sh.sh` T1 (`[ -x ]`).
9. CHANGELOG entries.
10. `af validate` + `make test` clean.
11. Commit; PR with `Closes #85`. Plan-review R3 dispatch.

## Reference Implementation

````bash
#!/usr/bin/env bash
# scripts/scan_rocket_issues.sh
# GraphQL label-narrower for the TRN-1008 §1 rocket-gate Phase 1 scan.
# Returns OPEN issues with blueprint-ready label currently present.
# NOT authoritative — verify_rocket_eligibility (REST per-issue) is the
# truth. This script just narrows the candidate set cheaply.
#
# Min bash: 3.2 (macOS default). POSIX-only constructs.
# Required tools: gh (GitHub CLI), jq.
#
# Usage:
#   ./scripts/scan_rocket_issues.sh
#   REPO=owner/repo ./scripts/scan_rocket_issues.sh
#
# Output: one issue number per line, or empty.
# Exit: 0 on success; non-zero on missing jq / gh api failure / auth error.
#
# Architecture: script returns SUPERSET of eligible issues (label-only
# filter). Per-candidate verify_rocket_eligibility (REST, paginated)
# does the full 5-check gate including reactor identity + applier
# identity + timeline events. Splitting these responsibilities avoids
# nested-connection truncation bugs (reactions, timeline, labels) that
# any GraphQL-only scanner would hit.
set -e

command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq is required. Install via brew/apt." >&2
  exit 2
}

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
OWNER="${REPO%/*}"
NAME="${REPO#*/}"

cursor=""
while :; do
  if [ -z "$cursor" ]; then
    after=""
  else
    after=", after: \"$cursor\""
  fi

  resp=$(gh api graphql -f query="
    {
      repository(owner: \"$OWNER\", name: \"$NAME\") {
        issues(states: OPEN, labels: [\"blueprint-ready\"], first: 100$after) {
          pageInfo { hasNextPage endCursor }
          nodes { number }
        }
      }
    }
  ") || exit 1

  echo "$resp" | jq -r '.data.repository.issues.nodes[].number'

  has_next=$(echo "$resp" | jq -r '.data.repository.issues.pageInfo.hasNextPage')
  [ "$has_next" != "true" ] && break
  cursor=$(echo "$resp" | jq -r '.data.repository.issues.pageInfo.endCursor')
done
````

That's the entire script. The lifecycle / applier-identity / reaction-pagination concerns now live in `verify_rocket_eligibility` (REST per-issue, TRN-1008 §1 spec table — already paginated for check 3's timeline-events guard, so check 5 is a free addition). The script does not consume `$TRUSTED_REACTOR` — that env var is the gate's, not the narrower's.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft (Status: Proposed) | Claude Opus 4.7 |
| 2026-05-08 | R2 panel: gemini 4.8 / codex 8.1 / glm 5.5 / deepseek 6.7 (mean 6.275, all FIX). Applied 4-of-4 + critical 1-of-4 findings. Switched to applier-identity verification via timelineItems LabeledEvents. Added 6 mocked test cases. SSOT enforced. | Claude Opus 4.7 |
| 2026-05-08 | R3 panel: gemini 9.9 / codex 7.2 / glm 8.6 / deepseek 8.5 (mean 8.55; gemini PASS, others FIX). Codex caught 4 NEW blockers in R2's GraphQL filtering: (1) applier-identity lifecycle bug — trusted-add → untrusted-readd accepted because R2 only checked "any historical trusted LabeledEvent"; (2) `reactions(first: 20)` reintroduces reaction-spam DoS; (3) `timelineItems(first: 50)` truncation + missing UNLABELED_EVENT; (4) A20 test gaps. **R3 architecture pivot**: instead of paginating every nested connection in GraphQL (complex, error-prone), the script becomes a pure label-narrower (`issues(labels: ["blueprint-ready"])` only). Per-candidate `verify_rocket_eligibility` (REST, paginated, already runs for check 3 timeline-events) gains the applier-identity logic for check 5. Drops all nested-connection bugs entirely. Script shrunk ~50→25 lines. Plus glm B1 (compression) addressed via tighter prose. Plus deepseek advisory 1 (A10/A23 phantom-reference) addressed via count-free phrasing throughout. | Claude Opus 4.7 |
| 2026-05-09 | R3 panel CLOSED at gemini 9.9 / codex 9.2 / glm 9.0 / deepseek 9.0 (mean 9.275, all-individual ≥9.0 + blocking empty → plan-review gate MET). All 4 R2 codex blockers (B1 lifecycle, B2 reactions truncation, B3 timeline truncation, B4 test gaps) marked CLOSED. Status flipped Proposed → Approved. R4 polish applied for 4 trivial advisories: (a) glm — dropped required-but-unused `$TRUSTED_REACTOR` from script (A1, A3, A18-T1d, reference impl, footer prose); (b) gemini+codex+deepseek convergent — fixed A18-T1g phantom xref `A21` → `A3`; (c) codex A1 — added same-second tie-break fail-closed clause to A14 timeline walk (parallel to TRN-1008 R26 history note); (d) codex A3 — A9 now specifies a concrete Phase 1 usage shape (`scan | while read N; do verify_rocket_eligibility "$N" \|\| continue; done`) for TRN-1008 §1. | Claude Opus 4.7 |

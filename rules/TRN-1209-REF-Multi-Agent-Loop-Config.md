# REF-1209: Multi-Agent Loop Project Configuration

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-10
**Last reviewed:** 2026-05-10
**Status:** Active
**Related:** TRN-1008 (Multi-Agent Review Loop — trinity overlay that consumes these bindings), COR-1622 (parameter schema authored from), COR-1617 (umbrella SOP), COR-1618 (consent gate), COR-1619 (worker dispatch), COR-1620 (loop primitives), COR-1621 (triage), COR-1615 (bot loop)

---

## What Is It?

Trinity's instantiation of the COR-1622 parameter schema. Every key the COR-1617 cluster references (`<repo>`, `<consent-signal>`, `<panel-providers>`, `<wakeup-tool>`, etc.) resolves to a concrete value here.

This document is the single source of truth for trinity's loop bindings. TRN-1008 and any future trinity SOP that adopts COR-1617 cites this REF rather than inlining values; the COR cluster reads its placeholders against this table.

---

## Why

COR-1622 §Why explains the separation of *shape* (PKG) from *values* (PRJ). Without a binding doc, every TRN-1008 section would either re-state `frankyxhl` / `ryosaeba1985` / four-provider names inline (drift risk) or leave the COR placeholders unbound at execution time (orchestrator hard-error per COR-1622 §Guard Rails).

---

## How to Use

- Orchestrators executing TRN-1008: read this REF first; substitute `<key>` references encountered in TRN-1008 or any cited COR-1617 cluster doc against the table below.
- Reviewers / contributors editing TRN-1008: never inline a value that has a binding here. Cite the key.
- Changing a value: update this REF + record the rationale in §Change History; downstream SOPs need not be edited.

---

## Bindings

### Identity & repository

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<repo>` | `frankyxhl/trinity` | Owner-of-record. |
| `<repo-owner>` | `frankyxhl` | Owner segment of `<repo>`. |
| `<repo-trusted-reactor-list>` | `[frankyxhl]` | Single-trustee project; consent reactions from any other login do NOT pass COR-1618 check 2. |
| `<gh-write-identity>` | `ryosaeba1985` | Distinct from `<repo-owner>` — the agent's GitHub account that authors PRs / comments / replies. `<repo-trusted-reactor-list>` is the consent surface; `<gh-write-identity>` is the write surface. Must be confirmed via `gh auth status` per COR-1505 before every visible-write op. |
| `<pr-push-remote>` | `fork` | Trinity uses fork-PR topology. PR head branches push to the `fork` remote (owned by `<gh-write-identity>`); never to `origin/main`. |

### Consent gate (COR-1618)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<consent-signal>` | `rocket` | 🚀 reaction on the issue body (not on comments) per COR-1618 §3. |
| `<intake-quality-mode>` | `2FA` | Both consent reaction AND intake-quality label required. |
| `<intake-quality-label>` | `blueprint-ready` | Applied by the trinity intake bot after a structural pass on the issue template. |
| `<intake-quality-applier-set>` | `[iterwheel-blueprint[bot], frankyxhl]` | Bot is the normal applier; `frankyxhl` is the manual override path. |

### Review panel (COR-1602 binding)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<panel-providers>` | Fast-review tier: `[trinity-glm, trinity-deepseek]`. Full panel (when invoked): `[trinity-gemini, trinity-codex, trinity-glm, trinity-deepseek]` | Trinity routes through the **fast-review tier** by default per CHG-3032 — the higher per-reviewer threshold (9.5) compensates for lost convergence-redundancy of the prior 4-provider panel. Codex's signal arrives post-push via `chatgpt-codex-connector[bot]` (see `<bot-actors>`). |
| `<weights-doc>` | `TRN-1800` | Scalar form (single rubric across all artifact types in trinity). |
| `<spec-format>` | `CHG` | Trinity ships substantive changes as CHG documents. |
| `<panel-pass-threshold>` | `9.5` | Higher than COR-1622's default `9.0` to compensate for the smaller fast-review-tier panel size. CHG-3032 §Threshold rationale. |

### Worker dispatch (COR-1619)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<worker-agent>` | `trinity-glm via droid exec` | Default coding worker. Other trinity providers (codex, deepseek, gemini) MAY be selected per task. |
| `<worker-min-loc>` | `0` | **Trinity overrides the schema default of 30.** Trinity's TRN-1008 §5 dispatches to `<worker-agent>` as the DEFAULT with an explicit exceptions list (git ops, single-section docs, sequential bot grep-and-replace batch, investigations) governing the orchestrator-direct path. Setting `<worker-min-loc>` = `0` makes COR-1619's LoC-threshold branch always fall through to the structural-question branches (signature change / multi-file / test count), matching trinity's "worker by default" stance. The exceptions list itself is not LoC-bounded and is encoded directly in TRN-1008 §5 — that prose is the authoritative dispatch rule for trinity, not COR-1619's tree. Adopters that want the standard 30-LoC threshold continue to use the schema default. |

### Resilience (CLI retry / failure escalation; COR-1622 §Resilience, alfred v1.16.0)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<cli-retry-attempts>` | `1` | **Trinity overrides the schema default of 3.** Matches TRN-1008 §Failure Modes "Reviewer / provider unavailability" — the existing rule is "retry once with the same prompt; if it still fails, mark the provider unavailable for this round". Adopters that want the standard 3-retry policy continue to use the schema default. |
| `<cli-retry-backoff-seconds>` | `600` (schema default) | Wait between retry attempts. TRN-1008 does not specify a wait; schema default is acceptable. |
| `<cli-retry-on-failure>` | `mark-non-viable` | **Trinity overrides the schema default of `pause-and-ask`.** Matches TRN-1008 §Failure Modes — the existing rule is "mark the provider unavailable for this round; proceed with N-1 only if N-1 ≥ 3 AND the failed provider wasn't the prior round's dissenter; otherwise abort the panel and surface the outage". COR-1622 §Guard Rails enforces the same dissenter + 3-viable check on `mark-non-viable` and auto-escalates to the operator when those conditions fail; for trinity's 2-provider fast-review tier, the auto-escalation path is reached on every provider failure — semantically equivalent to `pause-and-ask` in trinity's panel topology, but stated as `mark-non-viable` to preserve TRN-1008's prose-level meaning ("mark unavailable + escalate-when-below-quorum"). |

### Bot polling (COR-1615 binding)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<bot-actors>` | `[chatgpt-codex-connector[bot]]` | Trinity's PR-review GitHub App. PASS signal: 👍 on PR body. Auxiliary clearance bot `iterwheel-clearance[bot]` is observable but not normative. |

### Loop primitives (COR-1620)

| Key | Trinity value | Notes |
|-----|---------------|-------|
| `<wakeup-tool>` | `ScheduleWakeup` | Claude Code default. |
| `<idle-cap>` | `12` | 6 h @ 1800 s cadence. |
| `<merge-watch-cap>` | `24` | 12 h @ 1800 s cadence. Higher than `<idle-cap>` because branch-protected merges typically take longer than no-work-pending waits. |

### Trinity-only extensions (NOT in COR-1622)

These bindings drive trinity-specific overlays in TRN-1008 that COR-1617 does not cover. Documented here for completeness so a single read of this REF resolves every placeholder in TRN-1008.

| Key | Trinity value | Where used |
|-----|---------------|-----------|
| `$AGENT_GH_LOGIN` | `ryosaeba1985` | Alias for `<gh-write-identity>`; appears in TRN-1008 §1 concurrent-PR-cap query and §1.5 CLARIFY anchor logic. |
| `$TRUSTED_REACTOR` | `frankyxhl` | The single member of `<repo-trusted-reactor-list>`; appears in TRN-1008 §1.5 CLARIFY anchor step (ii) and TRN-3038. |
| `$REPO` | `frankyxhl/trinity` | Shell-variable form of `<repo>` for `gh api repos/$REPO/...` calls. |
| Concurrent-PR cap `N` | `2` | CHG-3036 hard cap. Set as a §1 phase-1 guard, not a hardcoded constant — future evolve cycles may revisit via PRP/CHG. |
| Agent-branch prefix regex | `^(codex\|claude)/` [^pipe-esc] | TRN-1008 §11 State-B branch guard accepts both prefixes. `codex/` is legacy from when the orchestrator was Codex; `claude/` is current. |
| CLARIFY round-counter cap | `3` | TRN-1008 §1.5 per-issue counter; CHG-3038 §Why. |
| Fast-review-tier providers | `[trinity-glm, trinity-deepseek]` | Subset of `<panel-providers>` used by default in §4 / §8 panels. CHG-3032. |

[^pipe-esc]: The pipe is escaped (`\|`) per GFM table-cell syntax. The actual regex used by `git rev-parse --abbrev-ref HEAD` matching has no backslash; do not embed `\|` into the regex itself.

---

## Validation

Run before every orchestrator session:

```bash
af validate --root .                       # structural
gh auth status                             # confirms <gh-write-identity> active
git remote -v | grep -E "^fork\\b"         # confirms <pr-push-remote> exists
```

If `<intake-quality-mode>` ever changes (e.g. from `2FA` to `1FA`), every previously-rocket-eligible issue MUST be re-checked against the new mode per COR-1622 §Guard Rails — do NOT silently re-interpret the queue.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-10 | Initial version — instantiates COR-1622 parameter schema for trinity. Authored from existing TRN-1008 inline values; no behaviour change. CHG-3039. | Claude Opus 4.7 |
| 2026-05-10 | R1: escape pipe in agent-branch regex table cell (codex-bot finding on PR #118). | Claude Opus 4.7 |
| 2026-05-10 | R2: add §Resilience parameter group (`<cli-retry-attempts>`, `<cli-retry-backoff-seconds>`, `<cli-retry-on-failure>`) per alfred v1.16.0 / FXA-146 schema extension. Trinity inherits all three schema defaults; `mark-non-viable` ruled out because the fast-review tier's 2-provider panel cannot tolerate dropping below the 3-viable minimum. No behaviour change (matches current TRN-1008 §Failure Modes "retry once + surface" behaviour, modulo the count). | Claude Opus 4.7 |

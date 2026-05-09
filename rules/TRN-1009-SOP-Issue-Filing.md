# SOP-1009: Issue Filing — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-05-09
**Last reviewed:** 2026-05-09
**Status:** Active

---

## What Is It?

The canonical checklist for filing GitHub issues in `frankyxhl/trinity`. Sits before TRN-1007 (PR Readiness Gate) in the lifecycle: issue → CHG → implement → PR-ready → merge. Makes the `iterwheel-blueprint[bot]` intake structure the single source of truth for agent-filed issues intended for the TRN-1008 §1 rocket-gate.

## Why

Three independent validation surfaces exist (`.github/ISSUE_TEMPLATE/*.yml` forms, `iterwheel-blueprint[bot]`, `iterwheel-stack[bot]`) and they disagree on required fields and labels. Issues #55 and #88 were filed using `feature_request.yml` field labels that the Blueprint bot doesn't recognise; issue #84 was filed without the required `[Kind]:` prefix and required a rename round-trip. Each failure costs a revision round-trip. A single canonical structure eliminates the ambiguity.

## When to Use

- **File an issue first** when the work is CHG-worthy (touches behaviour, schemas, SOPs, or public surfaces) or estimated > 30 LoC. TRN-1008 §3 (Plan / draft CHG) expects a tracked issue to exist before branch creation.
- Any autonomous auto-pick via TRN-1008 §1 rocket-gate requires a tracked issue with `blueprint-ready` label — this SOP is how you create one that passes.

## When NOT to Use

- Trivial typo fixes or single-character edits — skip straight to PR per TRN-1007.
- Bot-generated PRs (release tagger, dependabot) — they have their own flow.
- Hotfix PRs where time-to-merge dominates — file a retroactive issue after merge if needed.

## Steps

### 1. Identity check

Before any `gh issue create`: `gh auth status` MUST show `ryosaeba1985` active. See user-level `~/.claude/CLAUDE.md` §"User-Level GitHub Identity Rule" — do not duplicate the rule here. Repo ownership is `frankyxhl`; agent-authored artifacts must be `ryosaeba1985`.

### 2. Title and body

#### Title Format

`[Kind]: <one-line summary>` — ≤ 70 characters rule of thumb.

Allowed kinds: `Task`, `Bug`, `Feature`, `Docs`, `Refactor`, `Chore`, `CI`, `Test`, `Spike`.

**Do not** use lowercase conventional-commit prefixes (`feat:`, `fix:`, `docs:`) — the Blueprint bot rejects them.

#### Body Structure (Blueprint intake — CANONICAL)

Use these 8 markdown headings **in this order**. This structure overrides `feature_request.yml` for any agent-filed issue intended for the rocket-gate.

1. **`## Work Type`** — Kind + one-line scope (e.g., `Docs (new SOP)` or `Refactor (provider registry)`).
2. **`## Problem / Goal`** — What hurts today + what success looks like. One short paragraph.
3. **`## Context`** — Relevant prior art: TRN doc refs, related issues/PRs, session evidence.
4. **`## Expected Outcome`** — Concrete artifacts: file paths, sections, behaviours. Bullet list.
5. **`## Acceptance Criteria`** — Checkbox list (`- [ ] item`). **At least one checkbox is required** — see §Acceptance Criteria gotcha below.
6. **`## Reproduction Steps / Task Plan`** — Bug → numbered repro steps; Task/Docs/Feature → numbered task plan.
7. **`## Priority`** — `Low` / `Medium` / `High` + one-line justification.
8. **`## Requester / Owner`** — `Requester: @handle`; `Owner: TBD` or `@handle`.

#### Acceptance Criteria gotcha

**At least one `- [ ]` checkbox is required**, or `iterwheel-blueprint[bot]` rejects with `blueprint-requests-revision` and the `blueprint-ready` label is never applied. Plain prose bullets (`- item`) do not satisfy the check. If no per-item AC makes sense, use a single `- [ ] All surfaces implemented and verified`.

### 3. Post-filing

File the issue with:

```bash
gh issue create --repo frankyxhl/trinity \
  --title "[Kind]: <one-line summary>" \
  --body-file /tmp/issue-body.md
# Verify gh auth status shows ryosaeba1985 first.
```

Then:

1. Run `/blueprint` by posting it as a regular issue comment (`gh issue comment <N> --repo frankyxhl/trinity --body "/blueprint"`). The bot is webhook-driven on comment events and evaluates the intake against the 8-field structure.
2. If `blueprint-requests-revision` is applied: read the bot's missing-fields list, edit the body, re-run `/blueprint` (revision round-trip). Repeat until `blueprint-ready` is applied.
3. Confirm `iterwheel-stack[bot]` classification labels (Type / Area / Size / Risk). If `stack-needs-review` is applied, set them manually in the GitHub UI.
4. Author (or any GitHub handle in `$TRUSTED_REACTOR` — see TRN-1008 §1 for the trusted-set definition) reacts 🚀 **on the issue body** (NOT on a comment) to enable autonomous auto-pick per TRN-1008 §1 rocket-gate (CHG-3029 5-check `verify_rocket_eligibility`).

## Anti-patterns

- **Using `feature_request.yml` field labels** (`One-paragraph summary`, `Concrete user scenario`, `Alternatives considered`, `Scope hints (optional)`, `Provider(s) most affected`) instead of the 8 Blueprint headings above — bot rejects with `blueprint-requests-revision` (issues #55 and #88 hit this).
- **Title not in `[Kind]:` format (missing prefix entirely, or using lowercase conventional-commit `feat:` / `fix:` instead)** — issue #84 was filed without the required `[Kind]:` prefix and required a rename round-trip.
- **Reacting 🚀 on a comment** rather than the issue body — `verify_rocket_eligibility` only counts body-level reactions; consent never registers (see TRN-1008 §1 for endpoint detail).
- **Filing under the wrong `gh` identity** — root-of-trust violation per user-level CLAUDE.md. Repo is `frankyxhl`; agent must be `ryosaeba1985`.
- **Omitting `- [ ]` checkboxes in Acceptance Criteria** — bot rejects with `blueprint-requests-revision`; the `blueprint-ready` label is never applied, blocking autonomous auto-pick.

## Examples

For a complete Blueprint-compliant filing, see **issue #100** — its body structure passed the bot's intake check on first submission, but the title required a `[Refactor]:` prefix fix in one revision round-trip (the exact anti-pattern §Anti-patterns item 2 warns against). Minimal skeleton:

```markdown
## Work Type
Docs (new SOP for issue filing)

## Problem / Goal
No canonical issue-filing checklist exists; three validation surfaces disagree on field labels.

## Context
Issues #55, #84, #88 each required revision round-trips due to mismatched field structure.

## Expected Outcome
- New file `rules/TRN-1009-SOP-Issue-Filing.md`
- Cross-refs to TRN-1007, TRN-1008 §1, TRN-3029

## Acceptance Criteria
- [ ] SOP covers 8-field Blueprint intake structure
- [ ] Post-filing checklist includes 🚀 placement rule
- [ ] `af validate --root .` clean

## Reproduction Steps / Task Plan
1. Draft per issue spec
2. Validate with `af validate`
3. Commit, push, open PR

## Priority
Medium — unblocks future agent-filed issues without revision round-trips.

## Requester / Owner
Requester: @frankyxhl; Owner: TBD
```

*(In the skeleton: `Requester:` is whoever asked for the work — typically `@frankyxhl`. The `gh` CLI identity that creates the issue is separately governed by the §Identity-Check rule — `ryosaeba1985`. Do not conflate.)*

## Cross-references

No content duplicated below — pointers only.

- **TRN-1007** — PR Readiness Gate (post-issue, pre-merge checklist)
- **TRN-1008 §1** — rocket-gate auto-pick (`verify_rocket_eligibility` 5-check; requires `blueprint-ready` label this SOP exists to earn)
- **TRN-1008 §3** — CHG drafting (when issue maps to a CHG-shape change)
- **User-level `~/.claude/CLAUDE.md`** — GitHub identity rule (`ryosaeba1985`)
- **TRN-3029-CHG** — origin of the `blueprint-ready` rocket-gate requirement

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-09 | Initial version per issue #89; standardizes Blueprint intake + identity gate + post-filing 🚀 placement | Claude Opus 4.7 |
| 2026-05-09 | Plan-review R1: nested Identity-Gate / Title / Body / AC / Post-filing under ## Steps to match TRN-1007's validator-friendly shape (instead of flat per spec). Content unchanged. | Claude (Opus 4.7) |
| 2026-05-09 | Plan-review R2: rephrased #100 example to honestly reflect its title-fix round-trip (the SOP's own anti-pattern, in production); broadened §Anti-patterns item 2 header to cover missing-prefix and wrong-case-prefix; clarified `Requester:` vs `gh` identity in skeleton; replaced `#89 spec` historical reference in skeleton template. | Claude (Opus 4.7) |

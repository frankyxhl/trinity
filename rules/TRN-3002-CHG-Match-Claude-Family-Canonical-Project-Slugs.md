# CHG-3002: Match Claude-Family Canonical Project Slugs

**Applies to:** TRN project
**Last updated:** 2026-08-02
**Last reviewed:** 2026-08-02
**Status:** Approved
**Related:** TRN-3001, TRN-3040, TRN-3045, TRN-1005, TRN-1007
**Date:** 2026-08-02
**Requested by:** Frank Xu
**Priority:** High
**Change Type:** Normal

---

## What

Replace Trinity's slash-only Claude-family project-slug encoding with the
canonical Claude Code 2.1.220 algorithm and make `claude-code`, `deepseek`, and
`openrouter` provider templates consume the same source helper. Preserve the
separate Droid/GLM encoder unchanged.


## Why

DeepSeek continuation currently exits 3 for a known valid session whenever the
project path contains an underscore: Trinity preserves `_`, while Claude stores
the transcript below a `-` at that position. The same shared defect affects
Claude Code and OpenRouter, and the current implementation also omits Claude's
long-path truncation/hash behavior. A literal `_` substitution would repair the
reported example but would leave dots, spaces, non-ASCII UTF-16 code units, and
long paths inconsistent with the runtime that writes the files.

Runtime provenance: the installed Claude Code 2.1.220 executable
(`sha256:8addc857f3fe64d5a0368af9ee50321b50afb4a6918ba3ef018ab84f5dbbe081`)
was inspected with bounded binary extraction around its project-key functions.
Its project-path flow uses functions equivalent to:

```text
sanitized = path.replace(/[^a-zA-Z0-9]/g, "-")
if sanitized.length <= 200: sanitized
else: sanitized.slice(0, 200) + "-" + abs(jsHash(path)).toString(36)

jsHash(path):
  hash = 0
  for each UTF-16 code unit u in the ORIGINAL unsanitized path:
    hash = toSignedInt32((hash << 5) - hash + u)
  return hash
```

The function feeds `<config-home>/projects/<sanitized>`. JavaScript length,
regex replacement, and hash iteration operate on UTF-16 code units; Trinity's
Python implementation must match that behavior, including astral characters.
`Math.abs` is applied after the final signed 32-bit coercion, and the magnitude
is rendered in lowercase base 36 without padding.


## Impact Analysis

- **Systems affected:** `scripts/session_path.py`, the generated provider agents
  for `claude-code` / `deepseek` / `openrouter`, focused tests, `SKILL.md`, and
  `CHANGELOG.md`.
- **Compatibility:** existing paths containing only ASCII alphanumerics and `/`
  remain identical when the sanitized slug is at most 200 UTF-16 code units.
  Paths containing other characters begin resolving to the directory Claude
  actually writes. Named instance lookup and `:default` normalization are
  preserved.
- **GLM/MiniMax:** `_encode_project_path` and Droid provider templates remain
  unchanged; focused tests pin this boundary.
- **Security/privacy:** helper remains path-only; no JSONL content is opened,
  parsed, or emitted. No API key or provider config is printed.
- **Downtime:** none.
- **Rollback plan:** revert the source/test/provider/doc diff, then run
  `make build && make verify-built`. A later global sync, if separately
  acknowledged, can be rolled back by reinstalling Trinity 3.3.0, the version
  preceding this unreleased change.


## Out of Scope

- Project-path identity normalization (literal path vs symlink/realpath). This
  CHG matches Claude's slug transform while preserving Trinity's intentional
  no-symlink-following contract in `scripts/codex.py`.
- Changes to the Droid encoder, GLM/MiniMax provider templates, provider model
  IDs, API endpoints, or authentication.
- Global installation and a live DeepSeek resume call until the separately
  explained bounded sync/resume plan is acknowledged.


## Implementation Plan

1. RED: add literal canonical fixtures independent from the implementation for
   underscore, dot, space, punctuation, BMP and astral Unicode, leading dash,
   exactly 200 and 201 UTF-16 code units, positive and negative signed hashes,
   and an astral-containing long path with hardcoded base-36 hash suffixes.
2. RED: add end-to-end Claude-family cases for all three providers, including a
   named DeepSeek instance and DeepSeek `:default` wrapper normalization; add
   GLM and MiniMax underscore-path cases that prove Droid slash-only behavior
   is unchanged.
3. GREEN: implement the canonical encoder in `scripts/session_path.py` using
   only the Python standard library, explicitly iterating UTF-16 code units and
   reproducing JavaScript signed 32-bit string hashing/base-36 output.
4. GREEN: add the provider-facing helper command
   `python3 <trinity-scripts>/session_path.py --encode-claude-project-slug <project-dir>`.
   On success it writes exactly one slug plus newline to stdout, writes nothing
   to stderr, and exits 0. Missing/extra arguments write the helper-specific
   usage to stderr, write nothing to stdout, and exit 1. The existing normal
   two-positional-argument transcript-path contract remains unchanged.
5. GREEN: update the three `.delta.md` provider sources to call the installed
   shared helper. Each command substitution has an explicit failure guard that
   emits a non-secret diagnostic and exits before transcript scanning. Run
   `make build` so generated `.md` files match. Add static generated-template
   assertions plus a fake-installed-layout execution test for the helper.
6. REFACTOR: update `SKILL.md` path-encoding prose and `CHANGELOG.md`; audit all
   Claude-family slug assumptions with `rg` and keep the diff minimal.
7. Verify focused tests, existing transcript resolution, `make verify-built`,
   `make test`, `make lint`, and `make coverage`. Run targeted
   `af validate --root . TRN-1201 TRN-3001 TRN-3002` and require zero issues.
   Also run full-root `af validate --root .`; require no issues beyond the
   captured pre-existing annotated-status defects in TRN-3045 and TRN-3046.
8. Obtain independent code review (score >=9.5/10 and no blockers) and
   independent fresh verification before commit/PR.
9. Run TRN-1007, confirm GitHub identity and branch hygiene, then commit, push,
   and open the authorized PR.
10. Stop before global installation. Present the exact TRN-1005 sync and bounded
    one-call DeepSeek resume plan for acknowledgement; the call must explicitly
    select `deepseek-v4-flash` and must not surface secrets or transcript text.


## Acceptance Criteria

- [x] `_encode_project_slug` matches hardcoded Claude 2.1.220 fixtures for all
  relevant character and long-path cases, including exact 200/201-unit
  boundaries, positive/negative hashes, and astral UTF-16 semantics.
- [x] Existing transcript `f988a621-5dba-436f-8a4e-12cb816f6cd1` resolves for
  `deepseek:hbp-smoke` in the read-only reproduction project with exit 0.
- [x] `claude-code`, `deepseek`, and `openrouter` use one shared source encoder;
  named instances and DeepSeek `:default` normalization are covered.
- [x] GLM/MiniMax slash-only path encoding remains byte-for-byte unchanged and
  is protected by underscore-path regression tests.
- [x] The helper CLI obeys its exact stdout/stderr/exit contract; generated
  templates for all three providers call the fake-installed shared helper and
  stop on helper failure before transcript scanning.
- [x] Provider `.delta.md` sources and generated `.md` artifacts agree;
  `make verify-built` passes.
- [x] `make test`, `make lint`, and `make coverage` pass; targeted Alfred
  validation is clean and full-root validation introduces no issue beyond the
  captured pre-existing TRN-3045/TRN-3046 status annotations.
- [x] `SKILL.md` and `CHANGELOG.md` describe canonical behavior; README is N/A
  because no install/config/command syntax changes.
- [x] Every required reviewer scores the plan and implementation >=9.5/10 with
  no blocking findings, and an independent verifier reproduces the required
  evidence.
- [x] No global-install mutation or live provider call occurs before the
  separate bounded sync/resume plan is explained and acknowledged.


## Approval

- [x] Reviewed under COR-1602 / COR-1613 by the frozen plan-review unit below
- [x] Approved on 2026-08-02

### Plan Review Unit

```yaml
review_id: TRN-3002-plan-r1
target: rules/TRN-3002-CHG-Match-Claude-Family-Canonical-Project-Slugs.md
mechanism: decision_matrix
rubric: COR-1609
threshold: every reviewer weighted average >= 9.5 and blocking findings empty
reviewers:
  - gpt-5.6-sol-plan-a
  - gpt-5.6-sol-plan-b
  - gpt-5.6-sol-plan-c
quorum: 3
abstention_rule: abstain_blocks
tie_break: reject
disagreement_threshold: any
blind: true
```

### Code Review Unit

```yaml
review_id: TRN-3002-code-r1
target: working-tree diff for TRN-3002 after GREEN/REFACTOR
mechanism: decision_matrix
rubric: COR-1610/COR-1611
threshold: every reviewer weighted average >= 9.5 and blocking findings empty
reviewers:
  - gpt-5.6-sol-code-a
  - gpt-5.6-sol-code-b
quorum: 2
abstention_rule: abstain_blocks
tie_break: reject
disagreement_threshold: any
blind: true
```

Code review R1 found one formatter blocker. The test owner applied only the
mechanical Ruff formatting, after which both frozen reviewers independently
re-ran the focused checks. R2 passed 9.9/9.9 with no blocking findings.

Independent verification passed after the three process-inspection tests that
the sandbox denied were re-run with the required permission. Final evidence:
`make test` 543 passed/2 deselected plus all shell suites; `make coverage` 89%
total and 90% for `scripts/session_path.py`; focused provider build tests
136/0; targeted Alfred validation 3 documents/0 issues; source DeepSeek and
GLM control resolution both exit 0. Full-root Alfred validation retains only
the captured pre-existing TRN-3045/TRN-3046 issues and tag warnings.

---

## Change History

| Date       | Change                                                                                                                                                                                                                       | By    |
|------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|
| 2026-08-02 | Drafted runtime-backed normal-change plan and acceptance gates                                                                                                                                                               | Codex |
| 2026-08-02 | Plan-review R1 revision: specify exact JS hash and helper CLI contracts, 200/201 and signed-hash fixtures, installed-template failure tests, GLM/MiniMax coverage, checksum provenance, and baseline-aware Alfred validation | Codex |
| 2026-08-02 | Council review TRN-3002-plan-r1 R2 (decision matrix; 3 reviewers; each >=9.5 and blocking empty) passed 9.9/9.9/9.9; status Approved                                                                                         | Codex |
| 2026-08-02 | Froze independent code-review unit TRN-3002-code-r1 (2 reviewers; COR-1610/COR-1611; each >=9.5 and blocking empty)                                                                                                      | Codex |
| 2026-08-02 | Code-review R1 formatter blocker remediated by the test owner; R2 passed 9.9/9.9 with no blocking findings                                                                                                                       | Codex |
| 2026-08-02 | Independent verification passed; full suite 543/0, coverage 89%, source DeepSeek and GLM controls exit 0                                                                                                                            | Codex |

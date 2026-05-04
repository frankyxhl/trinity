# CHG-2013: Trinity Review Presets

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-05
**Last reviewed:** 2026-05-05
**Status:** In Progress
**Date:** 2026-05-04
**Requested by:** Frank
**Implementer:** Codex
**Priority:** Medium
**Change Type:** Normal
**Related:** TRN-1000, TRN-1005, TRN-2011, TRN-2012

---

## What

Add named Trinity presets so users can invoke common multi-provider workflows
with one keyword instead of listing every provider each time.

Primary target syntax:

```text
/trinity review "Review current diff"
/trinity fast-review "Quick review this change"
/trinity deep-review "Release-blocker review for this PR"
```

Codex terminal equivalent:

```bash
trinity review --preset review --scope .
trinity review --preset deep-review --scope rules/TRN-2013-CHG-Trinity-Review-Presets.md
```

`trinity review --scope .` should continue to work and use the configured
default preset when available.

Current implementation scope as of 2026-05-05: Codex terminal review and doctor
support `--preset ...`, preset aliases, `review.default_preset`, optional
provider skip warnings, and legacy `review.default_providers` fallback. Claude
Code `/trinity <preset> "task"` is documented in the root skill instructions and
still depends on Claude Code following those instructions at runtime.

---

## Why

The current user flow requires repeated long prompts such as:

```text
please code review with trinity-gemini, trinity-codex, trinity-glm, trinity-claude-code
```

This is slow, typo-prone, and discourages routine multi-model review. Presets
make the common case short while keeping the provider expansion visible and
configurable.

---

## Preset Config

Add a top-level `presets` map to Trinity config. Like `providers`, global
entries are loaded first and project entries override by key. Preset values are
not deep-merged.

Example:

```json
{
  "presets": {
    "review": {
      "providers": ["gemini", "codex", "glm"],
      "optional_providers": ["claude-code"],
      "task_type": "review"
    },
    "fast-review": {
      "providers": ["glm", "deepseek"],
      "task_type": "review"
    },
    "deep-review": {
      "providers": ["gemini", "codex", "glm", "deepseek"],
      "optional_providers": ["claude-code"],
      "task_type": "review"
    }
  },
  "preset_aliases": {
    "r": "review",
    "fr": "fast-review",
    "dr": "deep-review"
  },
  "review": {
    "default_preset": "review"
  }
}
```

Rules:

- Preset objects are replaced shallowly by key. If project config defines
  `presets.review`, it replaces the entire global `presets.review` object;
  omitted fields from the global preset do not carry over. Presets are atomic
  workflows, not field collections.
- `providers` are required. Missing or unusable required providers fail before
  dispatch.
- `optional_providers` are included when usable and skipped with an explicit
  stderr warning when missing. This lets `claude-code` become active
  automatically after TRN-2012 is implemented without breaking current installs.
- "Usable" means:
  - Claude Code `/trinity`: provider has both a config entry and matching
    `trinity-<provider>.md` agent file, following current discovery semantics.
  - Codex `trinity review`: provider exists in Codex config and has a non-empty
    `cli` entry.
  - Anything else is missing/unusable for preset expansion.
- Optional-provider warnings should distinguish fix paths:
  - missing config/key: `trinity: optional provider '<name>' skipped: missing config`
  - missing agent file: `trinity: optional provider '<name>' skipped: missing agent`
  - missing/empty CLI: `trinity: optional provider '<name>' skipped: missing cli`
- `task_type` is metadata for timeout selection and launch summaries. It is not
  part of provider validation, and defaults to Trinity's existing task-type
  inference when omitted. Valid values are `tdd`, `review`, `prp`, and
  `general`; invalid values fail during preset resolution before dispatch.
  When valid, preset `task_type` takes precedence over keyword inference.
- `preset_aliases` are optional. Aliases must not collide with built-in
  subcommands, provider names, or preset names.
- Preset names must not collide with built-in subcommands. If a preset name
  collides with a provider name, dispatch must fail with an ambiguity error
  rather than guessing.
- Alias resolution is one level only. Alias targets must be preset names, not
  other aliases. Nested aliases and circular aliases are invalid configuration
  and must fail before dispatch.

Claude Code `/trinity` dispatch precedence:

1. Built-in subcommands first: `status`, `clear`, `plan`, `heartbeat`,
   `install`, and `help`.
2. If the first token is both a provider and a preset/alias, fail with an
   ambiguity error.
3. If the first token is a preset or alias, expand the preset and dispatch all
   resolved providers in parallel with the same task.
   `/trinity review "..."` specifically means "expand the `presets.review`
   preset"; it is not a built-in subcommand.
4. Otherwise, parse the first token as the existing provider syntax, including
   `provider:instance` and `provider*N`.
5. Unknown token keeps the existing unknown-provider error, augmented with
   available presets when any exist.

Task text remains required. Bare `/trinity review` without a quoted task fails
with Trinity's existing empty-task behavior.

Resolution priority:

1. Explicit provider list wins:
   `trinity review --providers glm,gemini --scope .`
   If `--providers` and `--preset` are both supplied, `--providers` wins and
   Codex writes a stderr warning:
   `trinity: --providers supplied; ignoring --preset '<name>'`.
2. Explicit preset is next:
   `trinity review --preset deep-review --scope .`
3. Configured `review.default_preset` is next.
4. Legacy `review.default_providers` remains the compatibility fallback.
5. If none resolve to at least one provider, fail before dispatch.

Failure modes must use concrete messages:

- Unknown preset: `trinity: unknown preset '<name>'`
- Missing default preset: `trinity: review.default_preset '<name>' not found`
- Empty task: `trinity: task cannot be empty`
- Empty preset: `trinity: preset '<name>' has no providers`
- All providers unusable: `trinity: preset '<name>' has no usable providers`
- Ambiguous provider/preset name: `trinity: '<name>' is both provider and preset`
- Alias collision: `trinity: preset alias '<alias>' collides with <kind>`
- Nested alias: `trinity: preset alias '<alias>' points to another alias`

The existing top-level `review` config namespace is intentionally preserved for
Codex review settings (`output_dir`, `prompt_template`, `default_providers`,
`default_preset`). The preset named `review` lives at `presets.review`; docs must
show the full paths to avoid ambiguity.

---

## Impact Analysis

- **Systems affected:** root `SKILL.md` command grammar, config merge behavior,
  provider discovery/validation instructions, `/trinity status` display,
  Codex adapter config and CLI, README docs, tests, and user-level
  `~/.claude/trinity.json` /
  `~/.codex/trinity.json` after install.
- **Systems intentionally preserved:** explicit provider dispatch
  (`/trinity glm "..."`), multi-provider manual dispatch, session storage,
  current Codex `trinity review --providers ...`, existing installed providers,
  and TRN-2012's future `claude-code` provider plan.
- **Downtime required:** No.
- **Main risks:** ambiguous preset/provider names, accidentally skipping required
  reviewers, hidden provider expansion, and default presets referencing providers
  that are not installed yet.
- **Rollback plan:** remove `presets`, `preset_aliases`, `review.default_preset`,
  `.agents/trinity.codex.json` preset entries, parser/config changes, docs, and
  tests. Existing provider dispatch should continue unchanged and
  `review.default_providers` should remain usable.
- **Migration note:** existing `review.default_providers` config remains valid.
  Users may optionally migrate to `review.default_preset: "review"` after
  confirming the preset's required providers are installed.
- **In-flight sessions:** presets only affect dispatch expansion. Existing
  `.claude/trinity.json` sessions remain keyed by provider/instance and do not
  require migration or rollback handling.

---

## Implementation Plan

1. RED: add config merge tests in `tests/test_config.py` for `presets`,
   `preset_aliases`, shallow project override semantics, one-level alias
   resolution constraints, and preservation of unrelated
   provider/default/session behavior.
2. RED: add Codex adapter tests in `tests/test_codex_adapter.py` for
   `--preset`, `review.default_preset`, required-provider failure,
   optional-provider warning/skip, unknown preset, invalid alias, and explicit
   `--providers` overriding preset selection when both `--providers` and
   `--preset` are supplied.
3. RED: add edge-case tests for missing `review.default_preset`, empty preset
   provider lists, preset lists where every provider is unusable,
   preset/provider name ambiguity, alias collisions, alias targets that point to
   another alias, circular aliases, invalid `task_type`, optional-provider
   warnings on stderr, combined `--providers` + `--preset` stderr warning, and
   legacy `review.default_providers` fallback.
4. RED: add root `SKILL.md`/README textual regression tests so Claude Code
   behavior documents `/trinity review`, `/trinity fast-review`, and
   `/trinity deep-review`. Use the existing `tests/test_codex_compat.py`
   pattern: read the files as text and assert command examples, dispatch
   precedence, Reserved Words/collision language, and status output guidance are
   documented.
5. RED: add rollback compatibility tests proving that after removing `presets`,
   `preset_aliases`, and `review.default_preset` from a config fixture, legacy
   `review.default_providers` still resolves and dispatches through mocked
   provider CLIs.
6. GREEN: update `scripts/config.py` to merge top-level `presets` and
   `preset_aliases`. Project config wins by key.
7. GREEN: update `.agents/trinity.codex.json` with default presets and
   `review.default_preset`.
8. GREEN: update `scripts/codex.py`:
   - add `trinity review --preset <name>`
   - resolve aliases before preset lookup
   - use `review.default_preset` when neither `--providers` nor `--preset` is
     supplied
   - keep `--providers` as the highest-priority explicit override
   - retain `review.default_providers` as compatibility fallback
   - include optional providers only when configured and known
   - write optional-provider warnings to stderr
   - write expanded provider list and skipped optional providers to metadata
9. GREEN: update root `SKILL.md` command grammar, parser instructions, and
   dispatch instructions for `<preset-name> "task"` expansion. The launch
   summary must show the expanded provider list and any skipped optional
   providers.
10. GREEN: update the `SKILL.md` Reserved Words section to keep built-in
   subcommands distinct from preset names, and document that preset/provider
   collisions are rejected rather than reserved silently.
11. GREEN: update `/trinity status` guidance to show configured presets and
   aliases after registered providers.
12. REFACTOR: extract preset and alias resolution into small helper functions in
   `scripts/codex.py` so validation, provider expansion, metadata writing, and
   stderr warnings are testable without duplicating parsing logic.
13. Docs: update README with the shorter commands, config examples, ambiguity
   rules, and a note that `claude-code` participates only after TRN-2012 is
   implemented and installed.
14. Verification: run focused tests, `make test`, `make lint`,
   `af validate --root .`, and `make install-codex` smoke.

---

## Testing / Verification

Expected evidence before marking complete:

- `.venv/bin/pytest tests/test_config.py -q`
- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- `.venv/bin/pytest tests/test_codex_compat.py -q`
- `make test`
- `make lint`
- `af validate --root .`
- `make install-codex`
- `trinity review --preset review --scope .` using mocked provider CLIs
- `trinity review --preset deep-review --scope .` using mocked provider CLIs
- Claude Code compatibility smoke: `/trinity status` still loads existing
  providers and explicit `/trinity glm "..."` remains valid

---

## Approval

- [x] Approved for implementation
- [x] Implemented
- [x] Verified locally
- [x] PR opened

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-04 | Created CHG draft for review presets | Proposed |
| 2026-05-04 | Reviewed with Trinity GLM, Gemini, and DeepSeek | GLM/Gemini passed with recommendations; DeepSeek Codex CLI path failed due local `deepseek-v4-pro[1m]` droid model mismatch |
| 2026-05-04 | Re-reviewed with installed DeepSeek wrapper | REQUEST_CHANGES: clarify dispatch ambiguity, merge semantics, combined `--providers`/`--preset` test, optional-provider usability, task_type validation, and alias chains |
| 2026-05-04 | Re-reviewed with GLM, Gemini, and DeepSeek wrapper config | GLM/DeepSeek requested explicit `--providers` + `--preset` warning, all-unusable error, `/trinity review` wording, Reserved Words update, and task_type precedence; Gemini hit quota |
| 2026-05-04 | COR-1602 strict review round on PR #20 | DeepSeek scored 9.3 PASS with metadata-order advisory; GLM saw no PR diff due committed-branch review wrapper limitation |
| 2026-05-04 | COR-1602 strict review round 2 with explicit PR diff | GLM scored 9.2 PASS; DeepSeek scored 8.5 FIX for under-specified textual tests, rollback verification, missing REFACTOR step, and bare `/trinity review` behavior |
| 2026-05-04 | Seeded preset config files | Added `review`, `fast-review`, `deep-review`, and `r`/`fr`/`dr` config seeds; preset resolution remained pending under this CHG |
| 2026-05-05 | Implemented Codex preset resolver | Added `trinity review --preset`, `trinity doctor --preset`, alias resolution, default-preset priority, optional-provider skip metadata, and legacy fallback |
| 2026-05-05 | Verified locally | `make test`, `make lint`, `af validate --root .`, `make install-codex`, `trinity doctor --preset fast-review`, and `trinity review --check-providers --preset fast-review` passed |
| 2026-05-05 | Reviewed with Trinity GLM and DeepSeek | Round 1 PASS from both; DeepSeek advisory on `doctor` preset support was implemented |
| 2026-05-05 | Re-reviewed with Trinity GLM and DeepSeek | Round 2 PASS from both; DeepSeek cleanup advisory to remove unused `split_providers()` was implemented |
| 2026-05-05 | Opened PR #25 | Ready for review |

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial CHG for Trinity review presets | Codex |
| 2026-05-04 | Revised after Trinity review recommendations | Codex |
| 2026-05-04 | Revised after DeepSeek wrapper review | Codex |
| 2026-05-04 | Revised after final GLM/DeepSeek review pass | Codex |
| 2026-05-04 | Reordered CHG metadata and added migration note after COR-1602 review | Codex |
| 2026-05-04 | Added rollback test, explicit textual test mechanism, REFACTOR step, and empty-task behavior after COR-1602 round 2 | Codex |
| 2026-05-04 | Recorded preset config seed as a partial setup step before resolver implementation | Codex |
| 2026-05-05 | Implemented Codex terminal preset resolver and updated Claude/Codex docs | Codex |
| 2026-05-05 | Added doctor preset support and removed dead resolver code after Trinity review | Codex |

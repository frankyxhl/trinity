# CHG-3020: Consolidate Provider Config Into a Single Source

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #37)
**Priority:** Medium
**Change Type:** Refactor + glm CLI realignment fix
**Closes:** #37
**References:** TRN-3000 (REF, OpenClaw CLI-backend lessons), CLD-1802 (cross-class atomicity)

---

## What

Add a **single canonical provider registry** (`providers/registry.json`) listing 5 of the 6 providers Trinity supports (glm, codex, openrouter, deepseek, claude-code — **gemini deliberately deferred**) with their CLI command and optional metadata. Make every other site that currently hard-codes the same data **derive from or be drift-tested against** this registry.

Concretely:

1. **`providers/registry.json` (NEW)** — single source of truth. JSON, hand-edited, version-controlled. **No external schema file** — validation lives in `install.py`'s `_validate_registry()` (~30 lines, no `jsonschema` dependency added to `make setup`).

2. **`scripts/install.py`** — add `register-from-registry <path-to-registry>` subcommand that:
   - Loads `registry.json`
   - Calls `_validate_registry()` (inline; raises `SystemExit` on schema mismatch)
   - Iterates entries and calls existing `cmd_register()` per provider, with `{HOME}` substituted at iteration time
   - Drops `supports_resume` / `resume_arg` / `timeout` / `optional` registry-only metadata fields when calling `cmd_register` — **these fields do NOT propagate to `~/.claude/trinity.json`** (codex-side metadata only; see "Field disposition" below)

3. **`Makefile install:` target** — replace 5 hard-coded `install.py register <provider> --cli "..."` blocks (glm, codex, openrouter, deepseek, claude-code) with one `register-from-registry` call. Keep gemini's hard-coded `register` block for now (deferred from registry per user direction).

4. **`install.sh`** — same replacement. Also `_download "providers/registry.json"` early in the sequence and validate JSON parseability immediately after (`python3 -c "import json,sys; json.load(open('${HOME}/.claude/skills/trinity/providers/registry.json'))"`) before invoking `register-from-registry`.

5. **`.agents/trinity.codex.json`** — realign `glm.cli` from `droid exec --model glm-5.1 --reasoning-effort high` to `droid exec --auto medium --model glm-5.1 --reasoning-effort high` (matches registry + claude-side install). Other entries unchanged.

6. **`tests/test_provider_registry.py` (NEW)** — drift detection (see "Drift coverage" below).

7. **`tests/test_codex_adapter.py` fixture realignment** — line 131-143 hard-codes `glm.cli` without `--auto medium`; update fixture to match the realigned registry value (otherwise the existing test asserts a stale value).

### Registry schema (single field, no template branching)

```json
{
  "version": 1,
  "providers": {
    "glm": {
      "cli": "droid exec --auto medium --model glm-5.1 --reasoning-effort high",
      "supports_resume": true,
      "resume_arg": "-s",
      "timeout": 360
    },
    "codex": {
      "cli": "codex exec --skip-git-repo-check -m gpt-5.5",
      "supports_resume": true,
      "resume_arg": "experimental resume",
      "timeout": 600
    },
    "openrouter": {
      "cli": "{HOME}/.claude/skills/trinity/bin/openrouter -p",
      "supports_resume": false,
      "timeout": 600
    },
    "deepseek": {
      "cli": "{HOME}/.claude/skills/trinity/bin/deepseek -p",
      "supports_resume": true,
      "resume_arg": "-r",
      "timeout": 600
    },
    "claude-code": {
      "cli": "{HOME}/.claude/skills/trinity/bin/claude-code -p",
      "supports_resume": true,
      "resume_arg": "--resume",
      "timeout": 600
    }
  }
}
```

**Schema decisions** (each driven by panel feedback):

- **Single `cli` field** with universal `{HOME}` substitution. No `cli_template` branching (panel: 2 of 4 wanted collapse, 1 ambiguous, 1 wanted distinction; collapse wins because parser-side branching has zero benefit).
- **No `install_paths` field**. The drift test discovers cross-references; the registry doesn't need to encode them. (Panel: 3 of 4 said drop it.)
- **No `cli_template` for codex-side `~/.codex/...` paths**. The registry encodes the **claude-side** install root because that's the dominant path. Codex-side `.agents/trinity.codex.json` keeps its existing `~/.codex/skills/...` paths untouched (per glm B2: a single `{HOME}` substitution can't bridge the two roots, and trying to encode both paths in one entry adds complexity for negligible gain). Drift test handles the asymmetry: it normalizes the install-root prefix before comparing CLI strings between registry and `.agents/trinity.codex.json`.
- **`version: 1`** top-level field for forward-compat (per gemini A3 — readers can refuse-to-parse on unknown major version rather than silently drop fields).
- **Inline validator, not JSON Schema**. `_validate_registry(data)` checks: `version == 1`, `providers` is dict, each provider has `cli: str`, optional `supports_resume: bool`, `resume_arg: str` (required iff `supports_resume`), `timeout: int`. ~30 lines, no new dep on `make setup`. (Panel: 3 of 4 want this; 1 wants JSON Schema. Inline wins because `make setup` line 8-10 doesn't currently install `jsonschema`.)

### Field disposition (`supports_resume`, `resume_arg`, `timeout`)

The registry has these fields; `~/.claude/trinity.json` (the writer schema of `cmd_register`) does not. Decision: **these fields are codex-side metadata only. They live in `.agents/trinity.codex.json` (which already has them) and in the registry. They do NOT propagate to `~/.claude/trinity.json` via `register-from-registry`.**

Rationale:
- `~/.claude/trinity.json` runtime consumers don't read these fields today; adding them would require a co-evolving change to `scripts/codex.py`'s claude-side dispatch path (out of scope here).
- Putting them in the registry makes them available to the **drift test** (which compares registry → `.agents/trinity.codex.json`) without coupling to `cmd_register`'s writer schema.

Documented explicitly so the panel doesn't catch this on round 2 (per panel B2-class finding from deepseek/codex/glm).

### Drift coverage (extends to docs and tests per user)

`tests/test_provider_registry.py` asserts:

- **A3.a Schema**: `_validate_registry(load(registry.json))` does not raise.
- **A3.b Codex JSON consistency** (with explicit normalizer): For each provider in `registry["providers"]` that also appears in `.agents/trinity.codex.json[providers]`, `cli` matches after applying a documented two-step normalizer:
  1. **Tilde-vs-token swap**: `~/` ↔ `{HOME}/` (the codex JSON uses `~/`; the registry uses `{HOME}/`).
  2. **Claude-vs-codex root swap**: `.claude/skills/trinity` ↔ `.codex/skills/trinity` (registry encodes claude-side root; codex-side install puts the bin scripts under the codex root).
  Currently overlap = `{glm, deepseek}`. The test loudly logs the overlap set so accidental drops surface in CI output.
- **A3.c (DROPPED — folded into A3.b)**: `codex.py init-config` is a byte-for-byte copy of `.agents/trinity.codex.json` per `write_default_config` (scripts/codex.py:125-144), so a separate init-config drift assertion is tautological with A3.b. If `write_default_config` ever grows transformations, a follow-up CHG can re-add this check.
- **A3.d Makefile coverage**: Parse `Makefile install:` body, assert it invokes `register-from-registry` exactly once with `providers/registry.json`. Assert it does NOT contain hard-coded `register glm/codex/openrouter/deepseek/claude-code --cli "..."` blocks (regex-grep). Gemini's hard-coded block is allowed.
- **A3.e install.sh coverage**: Same parse + assertion against `install.sh`'s register section.
- **A3.f Provider-doc drift** (split by invocation style):
  - **Direct-invocation providers** (`glm`, `codex`): full `cli` value must appear verbatim in `providers/<provider>.md` AND `providers/<provider>.delta.md` AND any `providers/_base/*.md` partial that composes them. (`grep -F` substring match.)
  - **Wrapper-style providers** (`openrouter`, `deepseek`, `claude-code`): the bin-path component (e.g., `{HOME}/.claude/skills/trinity/bin/openrouter` rendered as `$HOME/.claude/skills/trinity/bin/openrouter` in shell-script style) must appear in the same files. Wrapper docs use `run_<provider>() { "$HOME/.claude/skills/trinity/bin/<provider>" "$@"; }` rather than the full registry CLI string, so a verbatim full-CLI match would false-fail. The asymmetry is documented in the test docstring.
- **A3.g README + SKILL drift**: Same split as A3.f. For each provider in registry: full-CLI match (direct providers) or bin-path-only match (wrapper providers) in `README.md` and `SKILL.md` if the provider's name appears at all.
- **A3.h Test fixture realignment**: `tests/test_codex_adapter.py:131-143` provider fixture's `glm.cli` value must equal the registry's `glm.cli` (after the realignment). The fixture's `supports_resume`/`resume_arg`/`timeout` fields stay unchanged (they are not in scope for this fixture's drift assertion).
- **A3.i No-orphan check**: Every provider in `Makefile install:` and `install.sh` register section is either in `registry["providers"]` OR is the explicit gemini exception (whitelisted by name). Catches future "added a 6th hardcoded register block" mistakes.
- **A3.j Test-fixture drift** (per glm round-2 B1): `tests/test_install_sh.sh:283` and `tests/test_build_providers.sh:157` both hard-code `glm`'s `--auto medium ...` CLI as expected output. Both must equal `registry["providers"]["glm"]["cli"]` verbatim. Without this, a future glm CLI change leaves these shell tests silently stale.

### Confirmed drift this fixes

| Provider | Pre-CHG sites | Pre-CHG values | Post-CHG (single source) |
|----|----|----|----|
| **glm** | `.agents/trinity.codex.json:4` | `droid exec --model glm-5.1 --reasoning-effort high` (no `--auto medium`) | `droid exec --auto medium --model glm-5.1 --reasoning-effort high` (registry + realigned codex.json) |
|  | `Makefile:59`, `install.sh:62` | `droid exec --auto medium --model glm-5.1 --reasoning-effort high` | (same, now via registry) |

**Behavior change disclosure**: After this CHG merges, codex-side `trinity review` runs with glm now invoke `droid exec --auto medium ...` (gain `--auto medium` flag). Reproduces the claude-side behavior. Listed as **the** behavior change, not "no behavior change" (per panel B5).

### What's NOT in this CHG (deliberately out of scope, with follow-up issues queued)

- **Gemini in registry** — deferred. Canonical CLI value (`gemini -p` vs `gemini --model gemini-3.1-pro-preview -p` vs other) requires a runtime test against the gemini API; currently rate-limited. Follow-up: file as TRN-3025 once gemini quota resets and the canonical value is decided.
- **`providers/bin/deepseek` line 43 (`ANTHROPIC_MODEL="deepseek-v4-pro[1m]"`) and `providers/bin/openrouter` line 43 (`qwen/qwen3.6-plus:free`)** — model pins in shell-script env vars. Conceptually different from CLI pins; needs a separate registry shape (env-var coverage). Follow-up: file as TRN-3026.
- **`rules/TRN-1006-SOP-Provider-Model-IDs.md`** — currently lists pin locations + step-by-step pin-update procedure; will become partially obsolete once registry exists. Cannot amend in-CHG without scope creep. Follow-up: file as TRN-3027 (SOP amendment to reference registry as authoritative for the 5 providers covered).
- **`scripts/codex.py` runtime to read registry directly at startup** — large refactor; the registry is install-time only for now.
- **Generating `.agents/trinity.codex.json` from registry** — would eliminate the hand-maintenance + drift-test pattern but requires a generator + commit-time hook. Defer.
- **Adding env-allowlist / clearlist fields to registry** — that's TRN-3023 / issue #62.
- **Adding `output: jsonl|text` / `input: arg|stdin` / `system_prompt_mode` fields** — those are #38/#39 territory. Plugin-shape expansion lands once #37 foundation exists.

### CLD-1802 cross-class atomicity waiver

Per CLD-1802 §2 strict reading, this CHG touches multiple file-classes (1 JSON config, 1 Python script, 1 Makefile, 1 shell script, 1 codex JSON config, 2 test files) and per the strict atomicity rule should be N=7 sub-CHGs.

**Waiver**: kept as one CHG because the 7 edits are mechanically derived from one decision (registry as single source of truth) and splitting fragments the diff in a way that hurts review (each sub-CHG would be unreviewable in isolation — Makefile alone makes no sense without the registry it consumes). Per CLD-1802 §2 last sentence ("the *class* is the surface" for symmetric multi-file refactors), this fits the symmetric-class shape: each of the 7 edits is the same conceptual move applied to one file. Reviewers should evaluate atomicity at the per-file level inside this CHG.

## Why

Six providers × four sites (`.agents/trinity.codex.json`, `Makefile`, `install.sh`, `providers/_base/`) plus three more found by panel review (`providers/*.md`, `README.md`, `SKILL.md`, test fixtures) = up to **49 places** where the same model pin or `--cli` flag can drift. Two confirmed drifts in `main` today: glm `--auto medium` (originating bug) and gemini `gemini -p` vs model-pinned (deferred per user). Future drift is statistically inevitable.

Issue #37 documents this. TRN-3000 frames it as the keystone for the broader CLI-backend engineering-quality set (#37 → #38 → #39 → #55 → #62 → #63). Doing #37 first means later issues bolt onto a single config object rather than chasing 7+ parallel ones.

## Impact

### Surfaces touched

| # | Surface | Edit |
|---|----|----|
| 1 | `providers/registry.json` (NEW) | 5-provider registry with `version: 1`, `cli`, optional `supports_resume`/`resume_arg`/`timeout` |
| 2 | `scripts/install.py` | Add `register-from-registry <path>` subcommand + `_validate_registry()` (~50 lines net add) |
| 3 | `Makefile install:` target | Replace 5 hard-coded register blocks with 1 `register-from-registry` call. Net `-25, +2` lines. Gemini block stays. |
| 4 | `install.sh` | Same as Makefile change. Also add `_download "providers/registry.json"` + post-download JSON-parse validation. Net `-25, +5` lines. |
| 5 | `.agents/trinity.codex.json` | Realign `glm.cli` to gain `--auto medium`. 1-line edit. |
| 6 | `tests/test_provider_registry.py` (NEW) | 9 drift assertions (A3.a, A3.b, A3.d–A3.j; A3.c was dropped). ~150 lines. |
| 7 | `tests/test_codex_adapter.py:131-143` | Update fixture's `glm.cli` to match realigned value. 1-line edit. |
| 8 | `SKILL.md:83 + SKILL.md:284` | Sync codex CLI (currently missing `-m gpt-5.5`) to match registry. 2-line edit. (Per deepseek round-2 B1: SKILL.md is a third active drift in main.) |
| 9 | `install.sh` mkdir line (additional) | Add `mkdir -p ${HOME}/.claude/skills/trinity/providers/` before the `_download "providers/registry.json"` call so the destination directory exists. (Per deepseek round-2 A2.) |

Net change: 2 new files, 5 modified. Total ~+200 lines (mostly tests + registry data).

### CI impact

- `make test` will run the new `test_provider_registry.py` (auto-discovered by pytest).
- `make coverage` unaffected — same code surface with extra test coverage.
- `make verify-built` unaffected (registry doesn't touch the TRN-2004 partials build).
- `make install` follows the new `register-from-registry` path.

### Backwards compatibility

- `~/.claude/trinity.json` is **not** rewritten by this change. Users with existing installs keep their config; they see the `--auto medium` improvement on glm only after the next `make install` run.
- `.agents/trinity.codex.json` schema unchanged (still has `providers`/`review`/`presets`/`preset_aliases` blocks); only `glm.cli` realigns.
- No deprecations.

### Rollback

Revert this PR. The registry file disappears, the 5 hard-coded register blocks come back, drift returns. Clean rollback.

## Acceptance Criteria

| # | Check | How |
|---|-------|-----|
| A1 | `_validate_registry(json.load(open('providers/registry.json')))` does not raise | Unit test in `test_provider_registry.py` |
| A2 | `make install` invokes `register-from-registry providers/registry.json` exactly once and produces register calls for all 5 registry providers + the 1 gemini exception in `~/.claude/trinity.json` | Integration test (drift A3.d) + manual smoke (CHG body) |
| A3 | All 9 drift assertions (A3.a–A3.i above) pass | `pytest tests/test_provider_registry.py -v` |
| A4 | `make test`, `make lint`, `make coverage` ≥ 80%, `af validate --root .` all pass | Local + CI |
| A5 | `make verify-built` still passes (TRN-2004 partials build untouched) | Local + CI |
| A6 | Install smoke: from a clean shell, `make install` followed by `trinity doctor` reports all 6 providers OK on a machine with the CLIs installed | Manual on local; documented in PR body |

## Authority

Standalone single-slice CHG with explicit cross-class waiver (above). Same shape as TRN-2025 / TRN-2028 / TRN-2026.

Operator defaults: identity `ryosaeba1985` for GitHub-visible writes, branch `codex/trn-3020-provider-registry`, plan-review and code-review via Trinity panel with **all panel members PASS individually at ≥9.0** gate (PR #60 lesson: mean alone is insufficient).

**Round 2+ panel composition**: glm + deepseek + codex (3 providers; gemini deferred this cycle per user direction — token quota constraint, not technical disqualification). The 3-provider gate is acceptable for this CHG given gemini's panel finding from round 1 was largely overlapping with the others (gemini drift, hidden sibling sites, drop cli_template, drop JSON Schema), so no unique signal is lost.

### Code-review prompt addendum (5-step methodology rule, version 5)

From PR #60 + PR #61 lessons; embedded in plan-review and code-review dispatches:

1. **Trace caller flows** of any function the diff consumes data from
2. **Read writer schemas** of any data the diff parses
3. **Compare to sibling registration sites** for any new subcommand / feature / config key
4. **When fixing value-handling in helper X**, grep for the same hard-code/pattern in sibling helpers consuming the same data source
5. **Comments asserting invariants** must be verified against the writer/producer

Specifically for THIS CHG:

- (1) caller flow: `Makefile install:` → `install.py register-from-registry` → reads `registry.json` → `_validate_registry()` → loops → `cmd_register()` per provider → writes `~/.claude/trinity.json`. Any link broken = install broken.
- (2) writer schema: `cmd_register()` (install.py:115-125) writes `{cli, installed: True}`. Registry's `supports_resume`/`resume_arg`/`timeout` fields are dropped at iteration time — documented in §"Field disposition".
- (3) sibling sites: 7 places hold provider data today (registry, Makefile, install.sh, .agents/trinity.codex.json, providers/*.md, providers/*.delta.md, README.md, SKILL.md, test fixtures). Drift test A3.a–A3.i covers all of them.
- (4) sibling helpers: `cmd_register` is the existing writer; `register-from-registry` MUST call it, not duplicate. `cmd_unregister` not affected.
- (5) comment-stated invariants: any docstring claiming "this matches registry" needs a test asserting it. The registry/install.py docstrings will name the corresponding A3 assertion.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3, with PR #60+#61 5-step methodology rule embedded. References TRN-3000 REF for the broader CLI-backend consolidation context. | Claude Opus 4.7 |
| 2026-05-08 | PR #64 round 1 from Codex GitHub App bot — caught a **backwards-compatibility bug** the 3-provider panel missed: when a user pipes `main`'s `install.sh` with `TRINITY_VERSION` pinned to an older tag, `BASE_URL` points to that tag (which doesn't have `providers/registry.json` or `register-from-registry`). Result: install fails mid-stream with a confusing "failed downloading providers/registry.json" error. Fix: add an early `curl --head` probe at install.sh:28-44; if `providers/registry.json` is absent at the target version, emit a clear error directing the user to that tag's own self-contained `install.sh` and exit. Updated `tests/test_install_sh.sh` T6 fixture to include `providers/registry.json` so the probe doesn't short-circuit before the 404 scenario T6 actually tests. **The panel chain missed this because it reviewed the diff against the current main, not against the matrix of older tagged releases**. Logging as a methodology gap to apply to future install-flow CHGs: explicitly check backwards-compat against documented version-pin flows. | Claude Opus 4.7 |
| 2026-05-08 | Code-review round 1 (3-provider panel; gemini still deferred): codex **9.7 PASS** (no blocking, no advisory), glm **9.25 PASS** (2 advisories), deepseek **9.20 PASS** (3 advisories). Mean 9.38. **Both gates met** (plan-review 9.07, code-review 9.38). Adopted shared polish advisory: 4 additional `_validate_registry` rejection tests (non-bool supports_resume, non-positive timeout, empty providers, plus previously existing 3) — bringing validator branch coverage from ~30% to ~80%. Test count grows from 20 to 23. Other advisories (encoding nit, style nit, redundant anchor assertion) noted as forensic but not adopted — low-priority polish that doesn't justify another rev. | Claude Opus 4.7 |
| 2026-05-08 | **Status**: Proposed → Approved. Plan-review round 3 (2-provider re-dispatch — glm already PASSed in R2): codex **9.15 PASS** (was 7.45), deepseek **9.05 PASS** (was 7.9). Round-3 mean across all 3 active providers: 9.07 (glm 9.0 + codex 9.15 + deepseek 9.05). All round-2 blockers RESOLVED (codex B1 wrapper-style mechanic via A3.f/g split; codex B2 normalizer; deepseek B1 SKILL.md fix). 4 advisories (3 robustness nits, 1 README staleness note) — non-blocking, can address at code-review time. Ready to implement. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 2 (3-provider panel — gemini deferred per token quota): glm **9.0 PASS** (was 7.00), codex 7.45 FAIL (was 7.55), deepseek 7.9 FAIL (was 3.85). Mean 8.12. All round-1 blockers RESOLVED across all 3 providers; 4 new findings in round 2 — all targeted test-design issues, all adopted in round 3: (1) glm B1 — extend drift coverage to `tests/test_install_sh.sh:283` + `tests/test_build_providers.sh:157` (added as A3.j); (2) codex B1 / deepseek A1 — A3.f + A3.g must split direct-invocation (glm, codex: full CLI match) from wrapper-style (openrouter, deepseek, claude-code: bin-path-only match), since wrapper docs use `run_<provider>() { ... }` and never inline the full CLI; (3) codex B2 — A3.b normalizer must handle BOTH `~`↔`{HOME}` AND `.claude`↔`.codex` swaps explicitly; (4) deepseek B1 — `SKILL.md:83+284` codex CLI is missing `-m gpt-5.5` (third active drift in main); fix in this CHG via 2-line edit added to surfaces table. Also adopted: codex A1 — A3.c dropped (write_default_config is byte-for-byte; tautological with A3.b); deepseek A2 — install.sh `mkdir -p providers/` before download; glm A1 advisory on TRN-1006:88 staleness deferred to TRN-3027 follow-up. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 1 (4-provider panel, **all FAILed**): glm 7.00, gemini 5.5, deepseek 3.85, codex 7.55 (mean 5.98). Universal pushback. **Round 2 revisions**: (1) Drop gemini from registry per user direction (token quota; canonical-value decision deferred to TRN-3025); (2) Drop `cli_template` field — single `cli` with `{HOME}` substitution; (3) Drop `install_paths` field — drift test handles cross-references; (4) Drop JSON Schema, use inline `_validate_registry()` (~30 lines, no `jsonschema` dep); (5) Add `version: 1` top-level field for forward-compat; (6) Document `supports_resume`/`resume_arg`/`timeout` field disposition (codex-side metadata only, do NOT propagate to `~/.claude/trinity.json`); (7) Extend drift test to providers/*.md, providers/*.delta.md, README.md, SKILL.md, tests/test_codex_adapter.py fixture (per user "providers/*.md in scope" + panel B2 findings); (8) Add codex.py init-config drift assertion A3.c (per codex B3); (9) Add install.sh download integrity check; (10) Fix self-contradiction: Change Type now "Refactor + glm CLI realignment fix" — disclose the glm behavior change as THE change (per deepseek B5); (11) Add explicit CLD-1802 cross-class waiver paragraph; (12) Defer providers/bin/* env-var pins → TRN-3026; defer TRN-1006 SOP amendment → TRN-3027; (13) Round 2 panel = 3 providers (glm + deepseek + codex; gemini deferred per token quota). | Claude Opus 4.7 |

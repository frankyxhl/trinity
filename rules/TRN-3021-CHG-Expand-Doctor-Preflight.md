# CHG-3021: Expand Provider Doctor Preflight Checks

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #38)
**Priority:** Medium
**Change Type:** Feature (additive — extends existing `cmd_doctor` output)
**Closes:** #38
**References:** TRN-3000 (CLI-backend lessons); TRN-3020 (registry as single source); TRN-3023 (env sanitization at spawn); TRN-1007 (PR readiness gate)

---

## What

Expand `trinity doctor` to surface configuration and environment issues that currently only show up at review-execution time. Four targeted additions, each tied to a real failure mode users hit. Plus several **architectural fixes** the round-1 panel surfaced (warning schema separation, format parameterization for `cmd_review` co-consumer, env-var-precedence in auth check, metadata threading for REQUIRED/OPTIONAL split, output backwards-compat).

1. **Display the resolved CLI command** for each provider (today doctor shows only the resolved executable path; users with stale `~/.claude/trinity.json` see "OK" with the wrong CLI string).
2. **Env pollution warnings** — flag any host env vars matching `_DEFAULT_ENV_CLEAR_PATTERNS` from TRN-3023. The vars are stripped at spawn (so reviews are safe), but operators benefit from knowing what's leaking from their shell.
3. **Auth-file presence checks for wrapper providers** — `~/.secrets/deepseek_api_key`, `~/.secrets/openrouter_api_key` (files-only, no network calls — per #38 "out of scope: requiring network calls"). The wrapper bin scripts read these at exec time; missing files cause opaque "command not found"-adjacent failures during review.
4. **Timeout sanity warning** — flag providers configured with `timeout < 60` seconds. Most reviews exceed this and would fail with a timeout that's misconfigured-not-merely-tight.

### What's NOT in this CHG (deliberately deferred)

- **`--version` probe** for each provider's CLI — feasible for some (`droid --version`, `gemini --version`, `codex --version`) but introduces caching/timeout/failure-policy decisions. Deferred to TRN-3030 if real need.
- **Model-option validation** — would need provider-specific schema (which `--model` values each CLI accepts). Heavy. Defer.
- **Network probes** — explicitly out of scope per issue #38.
- **Failing on optional-provider issues** — explicitly out of scope per #38; optional-provider warnings stay non-fatal.
- **Configurable verbosity** — keep the existing one-shot output. Future CHG can add `--quiet` / `--verbose` if useful.
- **`trinity doctor --fix`** auto-repair — not in scope.

### How each addition surfaces

`cmd_doctor`'s output gains structured rows. Approximate format (adjust during code-review per panel feedback):

```
trinity doctor — 6 providers checked

REQUIRED:
  glm        ✅ ok    cli: droid exec --auto medium --model glm-5.1 --reasoning-effort high
                     resolved: /Users/frank/.toolbox/bin/droid
                     timeout: 360s

  codex      ✅ ok    cli: codex exec --skip-git-repo-check -m gpt-5.5
                     resolved: /Users/frank/.codex/bin/codex
                     timeout: 600s

  deepseek   ❌ fail  cli: ~/.claude/skills/trinity/bin/deepseek -p
                     resolved: /Users/frank/.claude/skills/trinity/bin/deepseek
                     timeout: 600s
                     issue:    auth file missing: $DEEPSEEK_API_KEY unset and ~/.secrets/deepseek_api_key absent

OPTIONAL:
  claude-code ⚠️  warn cli: ~/.claude/skills/trinity/bin/claude-code -p
                     resolved: /Users/frank/.claude/skills/trinity/bin/claude-code
                     timeout: 30s
                     warning:  timeout 30s is below 60s minimum recommended

ENV POLLUTION (alphabetical; would leak into provider spawn pre-TRN-3023; now stripped at spawn):
  ⚠️  OPENAI_BASE_URL set in shell (https://corp…) — stripped at spawn
  ⚠️  OTEL_EXPORTER_OTLP_ENDPOINT set in shell — stripped at spawn

trinity doctor: 1 fatal issue + 1 warning across 6 providers; 2 env-pollution warnings
exit 1 (REQUIRED provider 'deepseek' has auth-missing issue)
```

Exit code semantics (per Architectural fix E):
- REQUIRED-provider with `issues` non-empty → exit 1.
- OPTIONAL-provider with `issues` non-empty → demoted to warning, exit 0.
- Any provider with `warnings` only (no `issues`) → exit 0.
- Env pollution → warning only, never affects exit code.

### Detail per addition

**1. Resolved CLI command**: extend `provider_health` to populate `cli: str` from the parser, rendered via `shlex.join([resolved_executable, *command[1:]])` for safe quoting (per codex round-1 advisory).

**2. Env pollution detection**: new helper `detect_env_pollution(base_env=None)`. Reuses TRN-3023's `_DEFAULT_ENV_CLEAR_PATTERNS`, `_UNIVERSAL_ENV_KEEP_LITERAL`, `_UNIVERSAL_ENV_KEEP_GLOB`, AND `_is_essential` (single source of truth — not just patterns; `_is_essential` ordering matters per glm round-1 Step 4 note). Returns list of `(key, redacted_value)` tuples. Values truncated to first 12 chars + "…" by default to avoid leaking corp hostnames / token-adjacent strings (per glm round-1 A4); full values behind a future `--show-env-values` flag (deferred).

**3. Auth-file presence**: new helper `wrapper_auth_check(provider)` returns `{"source": "env"|"file"|"missing", "file": path|None, "mode_ok": bool|None, "env_var": name|None}`. Logic mirrors the wrapper's actual contract (verified at `providers/bin/deepseek:10-31` and `providers/bin/openrouter:10-31`):

   1. If `$DEEPSEEK_API_KEY` (resp. `$OPENROUTER_API_KEY`) is set in `os.environ` → `source: "env"`, no file check (preserves wrapper precedence). Doctor reports OK.
   2. Else if `~/.secrets/<provider>_api_key` exists with mode `600` or `400` → `source: "file"`, `mode_ok: True`. Doctor reports OK.
   3. Else if the file exists with wrong mode → `source: "file"`, `mode_ok: False`. The wrapper runtime-refuses with `exit 1` (verified `providers/bin/deepseek:22-29` and `providers/bin/openrouter:22-29`), so this is **fatal not warning** for REQUIRED providers. Goes into `issues` (REQUIRED) or `warnings` (OPTIONAL — same metadata-aware demotion path as for `missing`). Per codex round-4 #1: aligns severity with wrapper's actual exit-1 behavior.
   4. Else (no env, no file) → `source: "missing"`. Same severity rule as wrong-mode (case 3): REQUIRED → `issues` (fatal, exit 1 — review will fail anyway); OPTIONAL → `warnings` (demoted).

   Hardcoded list for v1: `{deepseek, openrouter}`. Other providers (`glm`, `codex`, `gemini`, `claude-code`) → N/A; `wrapper_auth_check` returns `None` (auth via vendor's own login flow). **Tagged tech-debt**: declarative `auth_env` + `auth_file` registry fields belong in TRN-3030 follow-up CHG (per glm B2 + gemini B3 + deepseek advisory). Hardcoded list is acceptable for v1 only because the registry covers exactly 2 wrapper providers and they're the only ones with this pattern (verified via `grep KEY_FILE providers/bin/*`).

**4. Timeout sanity**: extend `provider_health`. If `timeout < _MIN_TIMEOUT_WARNING_SECONDS` (named module constant, `= 60` per gemini A1 + deepseek), append a warning. Warning-only — fields go into a NEW separate `warnings: list[str]` field on the result dict, NOT into `issues` (per codex round-1 #3: `health_results_ok` at line 468-469 fails on any non-ok, so warnings in `issues` would change exit-code semantics). `health_results_ok` continues to check only `issues`.

### Architectural fixes (round-1 panel-driven)

**A. Warning schema separation** (codex round-1 #3): `provider_health` result dict gains TWO new fields:
- `warnings: list[str]` — informational, not exit-code-affecting
- (existing) `issues: list[str]` — fatal, exit 1 if any

Routing rules (per codex round-5 #1 — must match wrapper runtime severity):

- **`timeout-sanity`** (e.g., `timeout < 60s`): always `warnings` regardless of REQUIRED/OPTIONAL — never wrapper-fatal.
- **`env-pollution`**: always `warnings` (display-only; spawn already strips them per TRN-3023).
- **`wrapper-auth-MISSING`** (case 4 above): REQUIRED → `issues` (fatal, matches wrapper's `exit 1` at run time); OPTIONAL → `warnings` (demoted via metadata-aware `health_results_ok`).
- **`wrapper-auth-WRONG-MODE`** (case 3 above): REQUIRED → `issues` (fatal, matches `providers/bin/deepseek:22-29` `exit 1`); OPTIONAL → `warnings`.

This means the v3 line "Auth-file-mode-warning ... all go into warnings" is REVISED — only timeout-sanity + env-pollution go unconditionally into `warnings`. Auth severity is metadata-aware.

**B. format_health_results parameterization** (glm B1 + codex advisory + gemini Step 3): the formatter is currently shared between `cmd_doctor` and `cmd_review --check-providers` (lines 1397-1403). Signature becomes `format_health_results(results, *, env_pollution=None, preset_metadata=None, verbose=False)`:
- `cmd_doctor` calls with `verbose=True` + `env_pollution=detect_env_pollution()` + `preset_metadata=resolve_review_providers(...)[1]` → renders REQUIRED/OPTIONAL split + CLI strings + warnings + env section.
- `cmd_review --check-providers` calls with `verbose=False` (default) → renders the **existing first-line shape** `{provider}: OK - {executable} (timeout Ns)` per provider. **No format change for cmd_review.**

**C. Output backwards-compat** (gemini B4): even in `verbose=True` mode, the first line per provider stays grep-compatible `{provider}: OK - {path}` (or `{provider}: FAIL - <issue>`). Detail rows (CLI string, timeout, auth) appear as INDENTED lines below. Any external script using `trinity doctor | grep "^<provider>: OK"` continues to work. CHANGELOG entry will be filed under `### Changed` (not just `### Added`) to reflect the format extension.

**D. Synthetic-error branch coverage** (codex round-1 #4): `provider_health_results` builds result dicts directly at lines 425-432 and 440-446 (synthetic-error branches for malformed config / missing-provider). New helper `_make_health_result(provider, *, ok, issues=(), warnings=(), executable=None, timeout=None, cli=None, auth=None, timeout_warning=False)` factors out the dict construction. All three sites (canonical at line 413, synthetic at 425, synthetic at 440) call this helper. `format_health_results` defensively `.get()`s new keys with safe defaults so old result dicts (if any consumer constructs them) don't crash.

**E. Metadata threading for REQUIRED/OPTIONAL** (universal blocker — round-2 panel found schema mismatch):

`cmd_doctor` currently discards `resolve_review_providers`'s preset metadata at line 1487 (`_, _, resolver_warnings`). Round-1 plan said "thread the 2nd tuple element through" — but round 2 caught that the actual returned dict (verified at `scripts/codex.py:269-287`) has keys `{requested, resolved, source, task_type, skipped_optional_providers}` — neither `providers` nor `optional_providers`. So the formatter has nothing to render REQUIRED/OPTIONAL from.

**Round-2 fix**: extend `resolve_preset_providers` to additionally return `providers` (the preset's required providers) and `optional_providers` (the preset's optional providers, including those that were skipped due to missing config — `skipped_optional_providers` is the SKIPPED subset, not the full optional set).

Concrete signature change to `scripts/codex.py:resolve_preset_providers` (around line 277). **Preserve existing 5 keys' semantics verbatim** — `requested` keeps the caller's literal input (alias name etc.); `resolved` keeps the resolved preset name; `source` / `task_type` / `skipped_optional_providers` unchanged. ADD only:
```python
return {
    # Existing 5 keys — semantics UNCHANGED:
    "requested": requested,           # caller's input (preserved per existing test contract)
    "resolved": resolved_name,
    "source": source,
    "task_type": task_type,
    "skipped_optional_providers": skipped,
    # NEW (TRN-3021):
    "providers": list(preset_def.get("providers", [])),
    "optional_providers": list(preset_def.get("optional_providers", [])),
}
```
For `--providers` invocations (no preset path at line 300-309), keys remain absent → formatter renders a single PROVIDERS section as fallback.

`cmd_doctor` updated to thread `preset_metadata` into BOTH the formatter AND the exit-code decision (codex round-3 #1 — specification without invocation):
```python
providers, preset_metadata, resolver_warnings = resolve_review_providers(args, config)
...
print(format_health_results(
    health,
    env_pollution=detect_env_pollution(),
    preset_metadata=preset_metadata,
    verbose=True,
))
return 0 if health_results_ok(health, preset_metadata=preset_metadata) else 1
```
`health_results_ok`'s new `preset_metadata` parameter defaults to `None` (per glm round-3 advisory) so existing call sites in `cmd_review --check-providers` (lines 1400-1401) work unchanged — `None` treats all providers as REQUIRED, preserving today's exit-code semantics.

**REQUIRED/OPTIONAL exit semantics** (codex round-2 #1): clarified explicitly. `health_results_ok` becomes metadata-aware:
- A provider with non-empty `issues` and listed in `preset_metadata.providers` (REQUIRED) → fatal, exit 1.
- A provider with non-empty `issues` and listed in `preset_metadata.optional_providers` (OPTIONAL) → demoted to a warning (the `issues` are surfaced but don't fail exit code).
- When `preset_metadata` is None (--providers path), all selected providers are treated as REQUIRED for exit-code purposes.

This matches the per-issue-#38 "Out of scope: failing optional providers unless explicitly requested" guidance.

**F. Schema-name normalization** (codex round-2 advisory): the result-dict key for auth status is `auth` (not `auth` as I wrote in some rows). All references in §Surfaces / §Acceptance / §Algorithm use `auth` consistently.

**G. detect_env_pollution filter rule** (deepseek round-2 advisory #4): explicit one-line spec: "Flag a key iff `_matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS) AND NOT _is_essential(key)`. The order matters; `_is_essential` short-circuits to preserve PATH/HOME/etc. even if a future clearlist pattern would otherwise match them." Result list is sorted by key alphabetically (gemini round-2 A1) for deterministic display.

**H. Example output inconsistency fix** (deepseek round-2 advisory #3): the round-1 example showed `deepseek` under REQUIRED with auth-missing rendered as `⚠️  warn` and `exit 0`, contradicting Architectural fix A's rule that "Wrapper-auth-MISSING for a REQUIRED provider still goes into `issues`". Fixed: example now shows `❌ fail` for the REQUIRED-deepseek-missing-auth case with exit 1. To preserve the warn-only example, a separate row shows `claude-code` under OPTIONAL with a non-fatal warning.

## Why

Issue #38 documents three specific cases where review execution surfaces issues doctor today doesn't catch: missing login, unsupported model options, weak timeout configuration. Plus PR #66 (TRN-3023 env sanitization) introduced a new failure mode visibility gap — env pollution is now silently stripped at spawn, but operators may want to know it's there (e.g., to fix their `direnv` setup so they don't depend on accidental leakage). Doctor is the natural place to surface this.

The narrow framing (4 specific checks, no network calls, no auto-repair) keeps risk low while addressing the highest-frequency complaint.

## Impact

### Surfaces touched

| # | Surface | Edit |
|---|----|----|
| 1 | `scripts/codex.py:provider_health` | Add `cli` (rendered via `shlex.join`), `auth` (dict from `wrapper_auth_check`), `warnings: list[str]` (NEW separate field), `timeout_warning: bool` to result dict. Pure additive — existing keys (`provider`, `ok`, `executable`, `timeout`, `issues`) unchanged. |
| 2 | `scripts/codex.py` | New helpers: `_make_health_result(...)` (factor out result-dict construction; used by canonical at line 413 + synthetic-error branches at 425, 440), `detect_env_pollution(base_env=None)` (reuses TRN-3023's `_DEFAULT_ENV_CLEAR_PATTERNS` + `_UNIVERSAL_ENV_KEEP_*` + `_is_essential`), `wrapper_auth_check(provider)` (env-or-file with mode 600/400 contract), `_MIN_TIMEOUT_WARNING_SECONDS = 60` constant. |
| 3 | `scripts/codex.py:format_health_results` | **Parameterized**: `format_health_results(results, *, env_pollution=None, preset_metadata=None, verbose=False)`. Default (`verbose=False`) preserves existing single-line `{provider}: OK - {executable} (timeout Ns)` per provider — `cmd_review --check-providers` co-consumer (lines 1397-1403) is unaffected. Verbose mode adds REQUIRED/OPTIONAL split (from `preset_metadata`) + indented detail rows + ENV POLLUTION section. First line per provider stays grep-compatible (per gemini B4 backwards-compat). |
| 4 | `scripts/codex.py:cmd_doctor` | (a) Capture `preset_metadata` from `resolve_review_providers`'s 2nd tuple element (currently discarded as `_` at line 1487); (b) compute `env_pollution = detect_env_pollution()`; (c) pass both to `format_health_results(..., verbose=True)`; (d) thread `preset_metadata` into `health_results_ok(...)` for the exit-code decision. |
| 4b | `scripts/codex.py:resolve_preset_providers` | Extend metadata dict (around line 277) with 2 new keys: `providers` (list of REQUIRED) + `optional_providers` (list of OPTIONAL). Existing 5 keys unchanged. (Per round-2 universal blocker — 3 reviewers found my v2 schema-mismatch claim that these keys already existed.) |
| 4c | `scripts/codex.py:health_results_ok` | Extend to be metadata-aware: only fatal when a REQUIRED provider has `issues`. OPTIONAL-provider `issues` demoted to warnings (non-fatal). When `preset_metadata` is None, all providers treated as REQUIRED (--providers path). |
| 5 | `tests/test_doctor_preflight.py` (NEW) | ~18-20 unit tests covering each addition + edge cases (env-var precedence, mode 600/400 boundary, timeout==60 boundary, env value redaction, format backwards-compat for cmd_review path, REQUIRED/OPTIONAL fallback when no preset). |
| 6 | `README.md` | Update "Provider health" section to mention the new output (per TRN-1007 §1). |
| 7 | `CHANGELOG.md` | `[Unreleased]` entries: `### Added` (env pollution, auth-file checks, timeout sanity, REQUIRED/OPTIONAL split) + `### Changed` (format_health_results gains verbose mode in doctor; cmd_review preflight format unchanged). |

Total: 1 new file, 4-5 modified. Net delta ~+250 lines (slight uptick from R1 due to factored `_make_health_result` helper and parameterization).

### Behavior change

| Pre-CHG | Post-CHG |
|---------|----------|
| Doctor shows: resolved-executable + timeout + issues | + CLI string + auth-file status + env-pollution section + timeout sanity warnings |
| Wrong CLI string in `~/.claude/trinity.json` shows "OK" | Now visible; user can compare against expected |
| Missing wrapper auth file fails opaquely at review time | Now flagged at doctor time |
| `OPENAI_BASE_URL` in shell silently stripped at spawn (post-TRN-3023) | Doctor warns it's set |
| `timeout: 30` accepted silently | Doctor warns "below 60s minimum recommended" |

**Exit code semantics preserved**:
- 0 if all required providers OK (warnings allowed)
- 1 if any required provider has a fatal issue

### CI impact

- New `test_doctor_preflight.py` runs in `make test` (~15 tests, unit-level).
- No CI workflow changes.
- `make coverage` increases on `scripts/codex.py` (new helpers fully tested).

### Backwards compatibility

- The `provider_health` result dict gains keys; existing keys unchanged. Any consumer using `health[i]["ok"]` etc. continues to work.
- Output format adds rows; existing rows preserved. If any external script greps the output, the existing strings stay matchable.

### Rollback

Revert this PR. Doctor reverts to current behavior. Clean rollback.

## Acceptance Criteria (per TRN-1007)

| # | Check | How | TRN-1007 § |
|---|-------|-----|------------|
| A1 | `provider_health` result includes `cli`, `auth`, `timeout_warning` keys | Unit test asserting result shape | §2 |
| A2 | `detect_env_pollution()` returns `OPENAI_BASE_URL` when set in `base_env` | Unit test | §2 |
| A3 | `detect_env_pollution()` does NOT return `OPENAI_API_KEY` (auth not in clearlist) | Unit test | §2 |
| A4 | `wrapper_auth_check("deepseek")` returns `source: "missing"` when neither env var NOR file present | Unit test with patched os.environ + HOME | §2 |
| A4b | `wrapper_auth_check("deepseek")` returns `source: "env"` (and OK) when `$DEEPSEEK_API_KEY` set, regardless of file presence | Unit test (per panel universal blocker — wrapper precedence) | §2 |
| A4c | `wrapper_auth_check("deepseek")` returns `source: "file", mode_ok: True` for mode 600 / 400; `mode_ok: False` for 644 (matches wrapper refusal at `providers/bin/openrouter:28`). For REQUIRED-provider mode-644 → result has `issues` non-empty (FATAL, exit 1, matches wrapper's `exit 1` at `providers/bin/deepseek:22-29`); for OPTIONAL-provider mode-644 → demoted to `warnings` (per codex round-4 #1 fatality alignment). | Unit test | §2 |
| A5 | `wrapper_auth_check("glm")` returns `None` (N/A — vendor login flow) | Unit test | §2 |
| A6 | `provider_health` flags `timeout < _MIN_TIMEOUT_WARNING_SECONDS` (= 60) into the new `warnings` field | Unit test | §2 |
| A6b | `timeout == 60` is NOT flagged (boundary; per deepseek round-1 advisory) | Unit test | §2 |
| A7 | Required-provider with `issues` non-empty → exit 1; `warnings` non-empty alone → exit 0 (per codex round-1 #3 — warnings must NOT enter `issues`) | Unit test | §2 |
| A8 | `format_health_results(verbose=True)` output includes "ENV POLLUTION" section with redacted values (first 12 chars + …) | Snapshot-style unit test | §2 |
| A8b | `format_health_results(verbose=False)` (the cmd_review co-consumer path) renders the EXISTING `{provider}: OK - {executable} (timeout Ns)` first line — backwards-compat preserved (per gemini B4) | Snapshot-style unit test | §2 |
| A8c | `provider_health_results` synthetic-error branches at lines 425-432, 440-446 produce dicts with all new keys present (via `_make_health_result`) — formatter doesn't crash on either path (per codex round-1 #4) | Unit test | §2 |
| A13 | `resolve_preset_providers` returns metadata dict with both new keys `providers` AND `optional_providers` populated for the `review` preset (REQUIRED ⊆ {glm, gemini, deepseek}; OPTIONAL ⊆ {codex, claude-code}) | Unit test (per round-2 universal blocker) | §2 |
| A14 | `health_results_ok` returns True when ONLY OPTIONAL provider has `issues`; False when REQUIRED provider has `issues`; True when only `warnings` (any provider) | Unit test (per codex round-2 #1) | §2 |
| A15 | `format_health_results(verbose=True)` renders REQUIRED and OPTIONAL sections with the providers placed correctly per `preset_metadata`; falls back to single PROVIDERS section when `preset_metadata is None` | Snapshot-style unit test | §2 |
| A16 | ENV POLLUTION list is sorted alphabetically by key (per gemini round-2 A1) | Unit test | §2 |
| A17 | `detect_env_pollution` tests use a clean (empty) base_env, not host `os.environ` (per gemini round-2 A2) | Test fixture pattern | §2 |
| A9 | Manual smoke: `OPENAI_BASE_URL=https://example.invalid trinity doctor` shows the env pollution warning | Manual on local; documented in PR body | §5 |
| A10 | `make test`, `make lint`, `make coverage ≥ 80%`, `af validate --root .` all pass | Local + CI | §2 |
| A11 | `README.md` "Provider health" section updated | Manual review | §1 |
| A12 | `CHANGELOG.md` `[Unreleased]` entry added | Manual review | §1 |

### TRN-1007 dogfood (the SOP we just shipped, applied to this CHG)

- §1 README: ✅ A11
- §1 CHANGELOG: ✅ A12
- §1 SKILL/providers: ➖ N/A — no provider behavior change
- §2 verification: ✅ A1-A10
- §3 drift: ➖ N/A — no provider CLI changes; no fixture realignment
- §4 6-step methodology: applied during code-review (panel + bot)
- §5 manual smoke: ✅ A9
- §6 identity: gh auth status → ryosaeba1985 (verified at PR-open time)
- §7 branch hygiene: branch `codex/trn-3021-doctor-preflight`; rebased on origin/main pre-push

## Authority

Standalone single-slice CHG. Operator defaults: identity `ryosaeba1985`, branch `codex/trn-3021-doctor-preflight`, plan-review and code-review via Trinity panel with **all active providers PASS individually at ≥9.0** gate.

Panel composition: try 4 providers (gemini was active for TRN-3023 R1; codex was killed for TRN-1007 review but should be available now); if any reviewer hangs, kill via TaskStop and proceed with remaining 3+ per the TRN-3020 / TRN-1007 precedent.

### Code-review prompt addendum (6-step methodology rule + new self-application check)

From PR #60/#61/#64/#67. Latest addition (PR #67 R1 lesson):

7. **Self-application check** — when adding/changing a SOP or process doc, verify the new doc applied to itself would have caught its own omissions. (For TRN-3021 specifically: would the expanded doctor catch any preflight issue THIS PR is introducing? E.g., are the new helpers themselves at risk of polluting env / missing auth files?)

Specifically for THIS CHG:

1. Caller flow: `cmd_doctor` → `provider_health_results` → `provider_health(provider, provider_config, root)` → calls `executable_health` + new `wrapper_auth_check` + new timeout sanity. `cmd_doctor` separately calls `detect_env_pollution`. `format_health_results` renders all of it.
2. Writer schemas: `provider_health` result dict gains keys; existing keys unchanged. Test A1 asserts shape contract.
3. Sibling sites: `cmd_review --check-providers` (codex.py:1397-1403) IS a formatter + `health_results_ok` co-consumer — protected via `verbose=False` default and `preset_metadata=None` default which preserve existing single-line output and "all-required" exit semantics. `provider_command`, `parse_provider_command` consume provider_config for spawn (not health) and don't display.
4. Sibling helpers: `detect_env_pollution` should reuse TRN-3023's `_DEFAULT_ENV_CLEAR_PATTERNS` and `_UNIVERSAL_ENV_KEEP_*` constants — single source of truth.
5. Comment-stated invariants: every docstring claim has a corresponding test.
6. Backwards-compat: provider_health result dict additive; output format additive. No older-tag matrix concern.
7. Self-application: doctor's new env-pollution detector would catch its OWN env pollution if any leaked from the test fixture — verify A2 with `OPENAI_BASE_URL` set in patched env.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3, with PR #60/#61/#64/#67 7-step methodology rule embedded (PR #67 R1 added the "self-application check" step). Tight scope: 4 specific doctor additions (CLI display, env pollution, auth files, timeout sanity). Deferred: --version probe, model-option validation, --fix auto-repair. References TRN-1007 dogfood — this is the first CHG to use the new SOP's Acceptance Criteria mapping. | Claude Opus 4.7 |
| 2026-05-08 | Code-review round 1 (4-provider panel, all PASS individually): gemini **9.8 PASS**, deepseek 9.4 PASS, glm 9.4 PASS, codex 9.1 PASS (mean 9.43). Both gates met (plan-review 9.075, code-review 9.43). Adopted advisories: dead `optional=False` parameter on `_format_provider_block` removed (gemini A1); `test_a5_claude_code_returns_none` added (glm A1); `test_a4c_wrong_mode_routes_to_issues_for_required` end-to-end test added at provider_health layer (codex advisory). Test count: 32 → 34. Codex independently verified ALL 11 plan-review findings (R1 #1-4, R3 #1-3, R4 #1-2, R5, R5 advisory) RESOLVED with line citations. Gemini noted subtle behavior in `--providers` path (preset_metadata gets 5 keys not 7 → optional_set falls back to empty → all rendered as REQUIRED — benign, consistent with semantics, but CHG narrative line 376 says "single PROVIDERS section" which is doc tweak for follow-up). | Claude Opus 4.7 |
| 2026-05-08 | **Status**: Proposed → Approved. Plan-review round 6 (codex-only re-dispatch): codex **9.1 PASS** (was 8.8; both R5 findings RESOLVED — line 98 unconditional warnings list rewritten with explicit per-signal-type routing rules; line 86 missing-auth severity split applied). All 4 panel members now PASS individually at ≥9.0: gemini 9.2 (R2), codex 9.1 (R6), glm 9.0 (R3), deepseek 9.0 (R4). Mean **9.075**. Gate met after 6 plan-review rounds — codex was the toughest reviewer, finding real defects each round (registry plumbing, warning schema, synthetic branches, REQUIRED/OPTIONAL fatality, preset_metadata schema, cmd_doctor wiring, auth name drift, requested-semantics regression, wrong-mode fatality, helper name drift, line 98 unconditional warnings list, line 86 missing-auth severity). Codex's 2 minor R6 advisories adopted (Surface row 4 now mentions `health_results_ok` exit-code threading; methodology Step 3 corrected to acknowledge `cmd_review --check-providers` as formatter co-consumer). Ready to implement. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 5 (codex-only re-dispatch): codex 8.8 FAIL (was 7.8; #2 RESOLVED — helper name unified to `wrapper_auth_check`; #1 PARTIALLY — wrapper_auth_check spec + A4c test align severity, but Architectural fix A summary at line 98 still listed `auth-file-mode-warning` in unconditional `warnings`). Round-6 fix: replaced fix-A summary with explicit routing rules per signal type (timeout-sanity → always warnings; env-pollution → always warnings; wrapper-auth-MISSING/WRONG-MODE → REQUIRED `issues` / OPTIONAL `warnings` via metadata-aware demotion). Also tightened case-4 (missing-auth) at line 86 with same severity split (per codex R5 advisory). | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 4 (2-provider re-dispatch — gemini PASS R2 / glm PASS R3 already): codex 7.8 FAIL (was 6.8; all 3 R3 blockers RESOLVED but 2 NEW R4 blockers), deepseek **9.0 PASS** (was 8.55; auth name conflict RESOLVED, TRN-1007 phantom now real-fixed, A1-A17 mapped). Round-5 fixes for codex's 2 R4 blockers: (1) **Wrong-mode auth fatality alignment** — `providers/bin/deepseek:22-29` runtime-refuses wrong-perm with `exit 1`, but my CHG had it as warning-only. Aligned: REQUIRED provider with `mode_ok: False` → `issues` (FATAL); OPTIONAL → `warnings` (demoted). A4c updated to assert both severity paths. (2) **Helper name drift** — line 263 methodology said `auth_file_check`; canonical is `wrapper_auth_check`. Fixed. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 3 (3-provider re-dispatch — gemini already PASSed at 9.2 in R2): glm **9.0 PASS** (was 8.90; R2 B1 RESOLVED), codex 6.8 FAIL (was 6.9; 3 concrete catches), deepseek 8.55 FAIL (was 8.20; new A1-vs-Fix-F name conflict + reasserted "TRN-1007 phantom" — which turned out to be REAL: my TRN-3021 branch was created off stale local main pre-PR-#67-merge, so TRN-1007 was missing from the branch). **Round-4 fixes**: (1) **TRN-3021 branch rebased onto current origin/main** — TRN-1007 now present, references resolve. Deepseek correctly identified the missing file across all 3 rounds; my "false positive" dismissal was wrong. Methodology gap: should have verified `git status` against `origin/main` before R1 dispatch. (2) Codex R3 #1 (REQUIRED/OPTIONAL fatality wiring): RESOLVED — `cmd_doctor` now explicitly calls `health_results_ok(health, preset_metadata=preset_metadata)`; `health_results_ok`'s new `preset_metadata` param defaults to None (per glm R3 advisory) preserving cmd_review existing call sites. (3) Codex R3 #2 + deepseek R3 #1 (`auth_files_status` vs `auth` name conflict): RESOLVED — global replace `auth_files_status` → `auth`, canonical throughout. (4) Codex R3 #3 (`requested` semantics regression in metadata snippet): RESOLVED — snippet now preserves caller's literal `requested` input; comment clarifies "Existing 5 keys' semantics unchanged". | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 2 (4-provider panel re-dispatch): gemini **9.2 PASS** (was 8.6; all 4 R1 blockers RESOLVED), glm 8.90 FAIL (was 8.05; new R2 blocker), deepseek 8.20 FAIL (was 7.15; advisories), codex 6.9 FAIL (was 6.5; 2 new R2 blockers). Mean 8.30. **All R1 blockers RESOLVED** across all 4 reviewers. **3 reviewers independently confirmed the same R2 blocker**: my v2 CHG promised the formatter reads `preset_metadata.providers`/`.optional_providers`, but `resolve_preset_providers` returns `{requested, resolved, source, task_type, skipped_optional_providers}` — neither claimed key exists. **Round-3 fixes**: (1) extend `resolve_preset_providers` to additionally return `providers` and `optional_providers` keys (Surface 4b) — all 3 reviewers' shared blocker; (2) make `health_results_ok` metadata-aware (codex R2 #1) — REQUIRED provider issues fatal, OPTIONAL demoted to warnings; (3) fix `auth` vs `auth` schema-name conflict (codex R2 advisory) — `auth` is canonical; (4) fix example output inconsistency (deepseek R2 advisory #3) — REQUIRED-deepseek-missing-auth now ❌ fail / exit 1, separate `claude-code` row added showing OPTIONAL-warning case; (5) make `detect_env_pollution` filter rule explicit (deepseek R2 advisory #4) — flag iff matches clearlist AND NOT `_is_essential`; (6) sort env keys alphabetically (gemini R2 A1); (7) tests use clean `base_env` baseline (gemini R2 A2). 5 new acceptance criteria added (A13-A17). | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 1 (4-provider panel, 3-of-4 FAIL): glm 8.05 PASS-with-conditions, gemini 8.6 FAIL, deepseek 7.15 FAIL, codex 6.5 FAIL (mean 7.58). Universal pushback. **Round 2 architectural rewrite** to address 6 cross-confirmed concerns: (1) **`format_health_results` shared with `cmd_review --check-providers`** (glm B1 + codex advisory + gemini Step 3) → parameterized via `verbose=False` default that preserves existing format for co-consumer; (2) **Auth env-var precedence** (universal — verified at `providers/bin/deepseek:10` and `providers/bin/openrouter:10`, env first then file with mode 600/400) → `wrapper_auth_check` returns `{source: "env"\|"file"\|"missing", mode_ok}`, A4/A4b/A4c cover the 3 paths; (3) **REQUIRED/OPTIONAL metadata** discarded at line 1487 (universal) → thread `resolve_review_providers`'s 2nd tuple element through to formatter; (4) **TRN-3020 single-source violation** (glm B2 + gemini B3) → hardcoded `{deepseek, openrouter}` for v1 explicitly tagged tech-debt with TRN-3030 follow-up CHG cited; (5) **Output format backwards-compat** (gemini B4) → first line per provider stays `{provider}: OK - {executable} (timeout Ns)` even in verbose mode; CHANGELOG entry now `### Changed` not just `### Added`; (6) **Warning schema unsafe** (codex #3 — `health_results_ok` fails on any non-ok at line 468-469) → new separate `warnings: list[str]` field; `issues` reserved for fatal. Plus 2 codex unique fixes: synthetic-error branches at 425/440 covered via factored `_make_health_result` helper (codex #4); shlex.join for CLI rendering (codex advisory). Plus advisories adopted: 60s as named constant `_MIN_TIMEOUT_WARNING_SECONDS` (gemini A1 + deepseek), env value redaction to first 12 chars + "…" (glm A4), boundary test `timeout == 60` not flagged (deepseek). Net delta grows from ~+200 to ~+250 lines (factored helper + parameterization + 5 new tests). Deepseek's "TRN-1007 doesn't exist" blocker dismissed as false positive (they ran `af search` without `--root`). | Claude Opus 4.7 |

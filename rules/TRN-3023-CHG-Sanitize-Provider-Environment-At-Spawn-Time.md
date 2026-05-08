# CHG-3023: Sanitize Provider Environment at Spawn Time

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #62)
**Priority:** Medium
**Change Type:** Feature (additive — no behavior change for users without polluted env)
**Closes:** #62
**References:** TRN-3000 (CLI-backend lessons from OpenClaw); TRN-3020 (registry as single source of truth — *not* extended by this CHG)

---

## What

Add **spawn-time environment sanitization** for provider subprocesses in `scripts/codex.py:run_provider`. Strip a small fixed set of known-problematic env-var patterns before invoking each provider CLI. Preserve a fixed set of universal essentials regardless of clear patterns. **No per-provider configuration in this CHG** — defer that to a follow-up if real need surfaces.

This is the **minimum viable env-sanitization slice** that addresses issue #62's documented pain (`OPENAI_BASE_URL` leak from `direnv` silently redirecting codex CLI). Round-1 plan-review (4-provider panel, all FAILed at mean 7.64) revealed that the original "extend registry with per-provider env_clear/env_allow" design had a critical plumbing gap (`scripts/codex.py` has zero refs to `providers/registry.json`) and added unnecessary speculative features. This v2 design is narrower and ships the core fix.

Concretely:

1. **`scripts/codex.py`** — add three constants and one helper:
   - `_UNIVERSAL_ENV_KEEP_LITERAL`: set of literal env keys always preserved (`PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `TERM`, `SHELL`, `TZ`, `TMPDIR`, `XDG_RUNTIME_DIR`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `SSH_AUTH_SOCK`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `PWD`).
   - `_UNIVERSAL_ENV_KEEP_GLOB`: set of fnmatch patterns always preserved (`LC_*`, `GIT_*`).
   - `_DEFAULT_ENV_CLEAR_PATTERNS`: list of fnmatch patterns to strip (`*_BASE_URL`, `*_API_BASE`, `*_API_HOST`, `OTEL_*`, `TRINITY_DISABLE_DISPATCH`). `*_API_HOST` is included as defense-in-depth alongside `*_BASE_URL` / `*_API_BASE` — if it turns out to be a no-op for all current providers (deepseek round-2 A2 question), the only cost is one extra fnmatch check per spawn (negligible).
   - `build_provider_env(base_env=None) -> dict[str, str]`: builds the sanitized env dict.

2. **`scripts/codex.py:run_provider`** — change `subprocess.Popen(...)` at line 1095 from no-`env` (inherits full parent) to `env=build_provider_env()`.

3. **`tests/test_provider_env.py` (NEW)** — 10 unit tests:
   - `OPENAI_BASE_URL` set in parent env is NOT in spawned env
   - `ANTHROPIC_BASE_URL` ditto
   - `OTEL_EXPORTER_OTLP_ENDPOINT` ditto (wildcard match)
   - `TRINITY_DISABLE_DISPATCH` ditto
   - `OPENAI_API_KEY` set in parent IS in spawned env (auth survives)
   - `PATH`, `HOME`, `LANG`, `LC_ALL`, `SSH_AUTH_SOCK`, `HTTPS_PROXY`, `XDG_RUNTIME_DIR`, `GIT_SSH_COMMAND` all preserved (one test per literal+glob pair, parameterized)
   - Empty-string-valued env var matching clear pattern is stripped
   - `base_env=None` default resolves to `os.environ` at call time (no mutable-default antipattern)
   - `build_provider_env()` returns `dict[str, str]` (right type for `Popen`)

### Algorithm

```python
import fnmatch
import os

def build_provider_env(base_env=None):
    """Build a sanitized env dict for spawning provider CLIs.

    Strips known-problematic patterns (vendor *_BASE_URL overrides,
    OTEL_* telemetry leakage, TRINITY_DISABLE_DISPATCH from caller's
    shell). Preserves a fixed set of universal essentials regardless
    of any clear pattern. Returns a fresh dict suitable for Popen's
    env= parameter.

    Universal essentials (always preserved):
      Literal keys: PATH, HOME, USER, LOGNAME, LANG, TERM, SHELL, TZ,
        TMPDIR, XDG_RUNTIME_DIR, XDG_CONFIG_HOME, XDG_CACHE_HOME,
        XDG_DATA_HOME, SSH_AUTH_SOCK, HTTP_PROXY, HTTPS_PROXY,
        NO_PROXY, PWD.
      Glob patterns: LC_*, GIT_*.

    Default clearlist (stripped unless in essentials):
      *_BASE_URL, *_API_BASE, *_API_HOST, OTEL_*, TRINITY_DISABLE_DISPATCH.

    Patterns use fnmatch.fnmatchcase (case-sensitive — POSIX env
    names ARE case-sensitive even on macOS/Windows).
    """
    if base_env is None:
        base_env = os.environ
    sanitized = {}
    for key, value in base_env.items():
        if _is_essential(key):
            sanitized[key] = value
            continue
        if _matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS):
            continue  # strip
        sanitized[key] = value
    return sanitized


def _is_essential(key):
    if key in _UNIVERSAL_ENV_KEEP_LITERAL:
        return True
    return _matches_any(key, _UNIVERSAL_ENV_KEEP_GLOB)


def _matches_any(key, patterns):
    return any(fnmatch.fnmatchcase(key, pat) for pat in patterns)
```

Essentials are checked **before** the clearlist, so they always survive even if a future clearlist pattern would otherwise match them.

### What's NOT in this CHG (deliberately deferred per panel feedback)

- **Per-provider `env_clear` / `env_allow` config in registry/codex.json** — deferred to follow-up CHG (TRN-3028, to be filed if/when a real need surfaces). The 4-provider plan-review panel (round 1) flagged this as the source of a critical plumbing gap (`scripts/codex.py` has zero refs to `providers/registry.json`; runtime reads `~/.codex/trinity.json`) and as speculative scope. None of the 6 currently-shipped providers needs an exotic env-var passthrough today; the hardcoded `_DEFAULT_ENV_CLEAR_PATTERNS` covers the documented pain (issue #62).
- **`provider_doctor` reporting on env pollution** — that's TRN-3021 / issue #38 territory.
- **Hermetic-by-default / strict allowlist mode** — explicitly deferred per #62 alternatives. This CHG is "strip a small known-bad set, keep everything else"; future CHG can flip to allowlist if/when each provider's env-var requirements are empirically known.
- **Container isolation** — explicitly rejected in #62 ("heaviest hammer").
- **Sanitizing `cmd_doctor` and other subprocess sites** — these don't spawn provider CLIs (audit at codex.py:82/534/681/725 confirmed: git/git-show/gh/git-cat-file, all internal tooling). Doctor uses `shutil.which` for binary existence checks (codex.py:372-438), no subprocess. Round-1 panel correction: my original §Step-3 reasoning was factually wrong; the truth is *better* — `run_provider` is the **sole** provider-spawn site in the codebase.

## Why

`scripts/codex.py:run_provider` calls `subprocess.Popen` with no `env=` argument (line 1095, current main). Default is to inherit the parent's full env. Two confirmed harms:

1. **Wrong-endpoint reviews**: `OPENAI_BASE_URL=https://corp-proxy.internal/v1` set by an unrelated `direnv` flow silently redirects codex's API calls. Same pattern for `ANTHROPIC_BASE_URL`, `GOOGLE_API_BASE`. Either fails opaquely (cert mismatch) or — worse — succeeds against an unintended endpoint.
2. **Telemetry leakage / interference**: `OTEL_EXPORTER_OTLP_ENDPOINT` and other `OTEL_*` vars from the parent shell get inherited by every spawned provider.

Issue #62 documents the concrete user scenario. OpenClaw addresses this in `extensions/anthropic/cli-shared.ts` via `CLAUDE_CLI_CLEAR_ENV` — Trinity's CLI-backend equivalent.

`TRINITY_DISABLE_DISPATCH` is included in the default clearlist. Wrapper coverage (verified via `grep -n TRINITY_DISABLE_DISPATCH providers/bin/*`):

- `providers/bin/claude-code:19` — explicitly sets `TRINITY_DISABLE_DISPATCH="1"` for its inner Claude exec. That assignment happens AFTER `build_provider_env` runs (the helper sanitizes the env passed to `Popen` which spawns the wrapper; the wrapper script then re-sets the var for its own child). `tests/test_anthropic_compat_wrappers.py:299` asserts this. So stripping at spawn time doesn't break nested-disable behavior.
- `providers/bin/openrouter`, `providers/bin/deepseek` — neither references `TRINITY_DISABLE_DISPATCH`. They're compat wrappers (Anthropic-protocol shim against different endpoints), not Trinity-aware. They never read this var, so stripping is irrelevant to them.
- The remaining direct-CLI providers (`glm`, `codex`, `gemini`) are external CLIs that don't know about Trinity.

Net: unconditional strip is safe across all 6 providers. Only one wrapper re-injects, and it does so AFTER sanitization. (Round-2 deepseek A1 advisory verified.)

## Impact

### Surfaces touched

| # | Surface | Edit |
|---|----|----|
| 1 | `scripts/codex.py` | Add 3 constants + `build_provider_env` + 2 small helpers (~50 lines). Modify line 1095 `Popen` call to pass `env=build_provider_env()` (1-line change). |
| 2 | `tests/test_provider_env.py` (NEW) | 10 unit tests (~120 lines) covering essentials preservation, clearlist stripping, edge cases, type contract. |

Total: 1 new file, 1 modified. Net delta ~+170 lines. Pure additive; compression ratio is acknowledged-low (deepseek round-1 B2). Mitigations: narrow scope (no registry/install.py changes), no speculative features, every line traceable to issue #62 or panel-adopted finding.

### Behavior change

| Pre-CHG | Post-CHG |
|---------|----------|
| Provider subprocesses inherit full parent env | Inherit parent env minus default clearlist |
| `OPENAI_BASE_URL` from direnv silently redirects codex | Stripped before spawn |
| `OTEL_*` leaks | Stripped |
| `OPENAI_API_KEY` survives | Same — never in default clearlist |
| `PATH`, `HOME`, `SSH_AUTH_SOCK`, `HTTPS_PROXY` survive | Same |

**Expected user-visible impact**: zero for users without polluted env. Users WITH polluted env get more reproducible reviews. No user has reported needing a now-cleared var to be passed through, so no escape-hatch is shipped — if such a need surfaces, file as TRN-3028.

### CI impact

- New `test_provider_env.py` runs in `make test` (auto-discovered). 10 tests, all unit-level, no integration overhead.
- No CI workflow changes.
- `make coverage` slightly increases coverage on `scripts/codex.py` (the new helper is fully tested).

### Backwards compatibility

- No config schema changes. Older Trinity → no impact.
- A user with `OPENAI_BASE_URL` set who *intends* it to flow through (e.g., genuinely using a corporate Azure-OpenAI proxy) will see the var stripped after this CHG and need to invoke their corp endpoint differently. **This is intentional**: the var was previously flowing silently; now it's blocked silently. If anyone reports breakage, TRN-3028 (per-provider escape hatch) becomes the immediate priority. Acceptable risk for the documented majority case where the leak is unintentional.

### Rollback

Revert this PR. `subprocess.Popen` reverts to default (inherit full env). No other state to clean up. Clean rollback.

## Acceptance Criteria

| # | Check | How |
|---|-------|-----|
| A1 | `OPENAI_BASE_URL` in parent env is NOT in `build_provider_env()` output | Unit test |
| A2 | `OPENAI_API_KEY` in parent env IS in `build_provider_env()` output | Unit test |
| A3 | `OTEL_EXPORTER_OTLP_ENDPOINT` in parent env is NOT in output (wildcard match) | Unit test |
| A4 | `TRINITY_DISABLE_DISPATCH` in parent env is NOT in output | Unit test |
| A5 | All 18 literal essentials + 2 glob essentials preserved (parameterized over PATH, HOME, USER, LANG, TERM, SHELL, TZ, TMPDIR, SSH_AUTH_SOCK, HTTPS_PROXY, XDG_RUNTIME_DIR, LC_ALL, LC_TIME, GIT_SSH_COMMAND, etc.) | Unit tests |
| A6 | Empty-string-valued var matching clear pattern is stripped (not preserved as `""`) | Unit test |
| A7 | `base_env=None` default resolves at call time (mutable-default antipattern guard) | Unit test asserting two calls with different `os.environ` snapshots return different results |
| A8 | `build_provider_env()` return type is `dict[str, str]` | Unit test |
| A9 | `run_provider` passes `env=build_provider_env()` to `Popen` | Smoke: grep `scripts/codex.py` for `env=build_provider_env` |
| A10 | Existing `make test`, `make lint`, `make coverage ≥80%`, `af validate` all pass | Local + CI |
| A11 | Manual smoke: `OPENAI_BASE_URL=https://example.invalid/v1 trinity review --providers codex --scope tests/` does NOT redirect codex's API calls (review either runs normally or fails for an unrelated reason) | Manual on local; documented in PR body |

## Authority

Standalone single-slice CHG, same shape as TRN-2026 / TRN-3020. Operator defaults: identity `ryosaeba1985`, branch `codex/trn-3023-env-sanitization`, plan-review and code-review via Trinity panel with **all active providers PASS individually at ≥9.0** gate (PR #60 lesson).

**Round 2+ panel composition**: 4-provider attempt (gemini was available in round 1; will retry). If gemini quota exhausts mid-round, falls back to 3-panel.

### Code-review prompt addendum (6-step methodology rule)

From PR #60 / #61 / #64. Applied to THIS CHG:

1. **Trace caller flows**: `cmd_review` → `run_providers` → `run_provider` (codex.py:1081) → `Popen(env=build_provider_env())` (line 1095). End-to-end. **No registry plumbing**, no signature changes elsewhere.
2. **Read writer schemas**: `Popen`'s `env` parameter requires `dict[str, str]`. `build_provider_env` returns `dict[str, str]`. Test A8 asserts the type contract.
3. **Sibling registration sites**: `run_provider` is the **sole** provider-spawn site (round-1 panel verified via grep of all subprocess.* calls in codex.py). No other site to update.
4. **Sibling helpers**: `build_provider_env` is fully self-contained — no shared state with other helpers, no module-level mutation. `_is_essential` and `_matches_any` are private to the module.
5. **Comment-stated invariants**: docstring states "preserves universal essentials regardless of clear patterns" — paired with parametrized A5 tests covering all 18 literals + 2 globs.
6. **Backwards-compat / older-tag matrix**: no install.sh changes, no registry changes, no schema changes. Cross-version-pin install (TRN-3020 §"Probe" path) unaffected.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3, with PR #60/#61/#64 6-step methodology rule embedded. **Original v1 design** had per-provider `env_clear` / `env_allow` extending the registry schema. | Claude Opus 4.7 |
| 2026-05-08 | Code-review round 1 (4-provider panel): gemini **9.8 PASS**, deepseek **9.45 PASS**, codex **9.3 PASS**, glm **9.27 PASS**. Mean 9.46. **Both gates met** (plan-review 9.24, code-review 9.46). Adopted shared advisory: promote `import fnmatch` from inside `_matches_any` to module-level (3 of 4 reviewers flagged as style consistency with the existing import block). 22/22 unit tests pass after the change. No blocking findings; remaining advisories (test patch granularity nit, docstring brevity nit, CHG long-term retention question) noted but not adopted. | Claude Opus 4.7 |
| 2026-05-08 | **Status**: Proposed → Approved. Plan-review round 3 (deepseek re-dispatch with necessity-justified compression framing, per CLD-1800 §"Code Evolution Weights": "net positive must be justified by necessity"): deepseek **9.00 PASS** (was 7.70 — score moved from 2/10 to 6/10 on compression dimension after operator clarified the framing). All 4 panel members now PASS individually at ≥9.0: gemini 9.5, codex 9.4, glm 9.05, deepseek 9.0 (mean 9.24). Gate met. Plus deepseek R2 advisories adopted: A1 — TRINITY_DISABLE_DISPATCH wrapper coverage documented per-provider (only `providers/bin/claude-code:19` sets it; openrouter/deepseek don't reference; glm/codex/gemini are external CLIs); A2 — `*_API_HOST` defense-in-depth rationale documented. Ready to implement. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 1 (4-provider panel, **all FAILed**): glm 6.35, gemini 8.30, deepseek 8.30, codex 7.6 (mean 7.64). Universal pushback. **Round 2 substantial rewrite**: (1) Drop per-provider env_clear/env_allow entirely → no registry changes, no .agents/trinity.codex.json changes, no plumbing chain through cmd_review/run_providers/run_provider. Resolves all 4 reviewers' B1 (registry plumbing gap) by making the question moot. (2) Drop env_allow escape hatch → defer to follow-up TRN-3028 if real need surfaces. Addresses deepseek B2 (compression ratio) by narrowing scope. (3) Strip `TRINITY_DISABLE_DISPATCH` unconditionally — `providers/bin/claude-code` re-sets it for its own inner exec AFTER sanitization. Resolves gemini B1 / glm B3 / codex C. (4) Expand universal-essentials to include `TMPDIR`, `XDG_RUNTIME_DIR`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `SSH_AUTH_SOCK`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `LOGNAME`, `PWD`, plus `LC_*` and `GIT_*` glob patterns. Resolves gemini B2 / glm B4. (5) Use `fnmatch.fnmatchcase` (case-sensitive) per gemini A2 / glm A2. (6) Document `LC_*` / `GIT_*` as globs in essentials, requiring `_is_essential` to do `fnmatch` not `key in SET`. Per deepseek A2. (7) `base_env=None` default arg per codex A3 (no mutable-default antipattern). (8) Correct factually-wrong §Step-3 doctor claim — confirmed: `run_provider` is the sole provider-spawn site; doctor uses `shutil.which` only. Per all 4 reviewers' A1. (9) Add A11 manual smoke acceptance criterion. (10) Net code delta drops from ~+150 to ~+170 (test expansion offsets implementation simplification). | Claude Opus 4.7 |

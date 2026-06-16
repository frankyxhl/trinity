# SOP-1006: Provider Model IDs — Pinning and the `[1m]` Convention

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-06
**Last reviewed:** 2026-05-06
**Status:** Active
**Related:** TRN-2005 (CHG: Pin trinity-codex to gpt-5.5), TRN-2009 (CHG: Remove zsh dependency)

---

## What Is It?

How Trinity pins the LLM model identifier per provider, what conventions providers use to name model variants (notably the **`[<context-window>]` bracket suffix** for context-length tiers, e.g. `deepseek-v4-pro[1m]`), and how to update model IDs safely.

---

## Why

Each provider exposes multiple model variants:

| Variant axis | Examples |
|--------------|----------|
| Capability tier | `deepseek-v4-pro` vs `deepseek-v4-flash`; `gpt-5.5` vs `gpt-5.5-mini` |
| Context-window tier | `deepseek-v4-pro` (default) vs `deepseek-v4-pro[1m]` (1M-context) |
| Modality | `gemini-3.1-pro-preview`, `gemini-3.1-flash-preview` |
| Date/snapshot | `claude-opus-4-7`, `claude-opus-4-7[1m]` |

If Trinity defers to the user's CLI default (`~/.codex/config.toml`, `~/.deepseek/config`, etc.), behaviour is non-deterministic across machines and across user reconfigurations — the same `/trinity codex "x"` could pick `gpt-5.4` on one box and `gpt-5.5-mini` on another. We pin explicitly to make `make install` produce the same provider behaviour everywhere.

---

## When to Use

- Bumping a provider's model ID after vendor announces a new tier or snapshot (e.g., DeepSeek announces 1M-context, Codex pins move from GPT-5.4 → GPT-5.5).
- Pinning a previously-unpinned provider for the first time, when CLI-default drift starts producing surprises across machines.
- Reviewing whether existing pins still match current vendor docs (cadence: per evolve cycle, signal in TRN-1800).

## When NOT to Use

- Cosmetic edits to a model name (e.g., adding a snapshot date that the provider treats as a synonym) — bump VERSION instead, no SOP required.
- Provider behaviour change that lives entirely in the agent `.delta.md` prompt (system message, session resume flag) — that's a doc-only change.
- Trying to *unpin* a provider (revert to CLI default) — re-run the routing decision from TRN-1000; pinning vs unpinning is a different question than which value to pin to.

---

## The `[1m]` Suffix Convention

**`[1m]` is a literal model-ID suffix denoting the 1M-context-window tier of the base model.** It is NOT an ANSI escape (`\033[1m` for bold) and must NEVER be stripped during copy-paste from docs.

This convention is shared across multiple Anthropic-API-compatible providers. Examples observed in the wild:

- `claude-opus-4-7[1m]` — Anthropic's 1M-context Opus 4.7 (this is the model ID for the Claude Opus running this very SOP author)
- `deepseek-v4-pro[1m]` — DeepSeek's 1M-context DeepSeek V4 Pro

Providers that follow this convention use the bare name (`<base>`) for the standard-context tier and `<base>[1m]` for the extended-context tier, both reachable via the same `ANTHROPIC_MODEL` env var.

### Shell-quoting safety

Square brackets are special to the shell only inside an unquoted glob pattern (`ls foo[ab]`) or a `[ ... ]`/`[[ ... ]]` test command. Inside double-quoted assignment they are **literal**:

```sh
ANTHROPIC_MODEL="deepseek-v4-pro[1m]"   # OK — quoted, brackets literal
ANTHROPIC_MODEL=deepseek-v4-pro[1m]     # WRONG — unquoted, shell tries to glob
ANTHROPIC_MODEL='deepseek-v4-pro[1m]'   # OK — single-quoted, also literal
```

Trinity's wrappers always double-quote the assignment (see `providers/bin/deepseek` line 43). When editing, **never remove the quotes**.

### Common mistakes (rejected)

| Mistake | Why wrong |
|---------|-----------|
| Strip `[1m]` because "it looks like an ANSI escape" | It's a literal suffix; stripping silently downgrades to standard-context tier |
| `ANTHROPIC_MODEL=deepseek-v4-pro\[1m\]` | Backslash escape works but is unidiomatic; just quote |
| `ANTHROPIC_MODEL="deepseek-v4-pro 1m"` | Space-separated isn't the convention; provider rejects |
| URL-encode brackets to `%5B1m%5D` | Env vars are not URLs; provider sees the literal `%5B...` and rejects |

---

## Where Model IDs Are Pinned

Single source of truth per provider (post-TRN-3020 / TRN-3027):

| Provider | Model pin location | Pinned value (as of 2026-05-08) |
|----------|--------------------|----------------------------------|
| `codex` | `providers/registry.json` → `providers.codex.cli` | `codex exec --skip-git-repo-check -m gpt-5.5` (TRN-2005) |
| `gemini` | `providers/gemini.delta.md` `### New session` invocation (registry deferred — TRN-3025) | `gemini-3.1-pro-preview` |
| `glm` | `providers/registry.json` → `providers.glm.cli` + `.agents/trinity.codex.json` + `providers/glm.delta.md` | Claude Code install + Codex review: `droid exec --auto medium --model custom:GLM-5.2` (BYOK custom model — Z.AI; `--reasoning-effort` dropped, unsupported for `custom:` models) |
| `deepseek` | Model: `providers/bin/deepseek` env block. Bin path: `providers/registry.json` → `providers.deepseek.cli`. (Env-var registry shape — TRN-3026) | `ANTHROPIC_MODEL="deepseek-v4-pro[1m]"`, `ANTHROPIC_SMALL_FAST_MODEL="deepseek-v4-flash"` |
| `openrouter` | Model: `providers/bin/openrouter` env block. Bin path: `providers/registry.json` → `providers.openrouter.cli`. (Env-var registry shape — TRN-3026) | `ANTHROPIC_MODEL="qwen/qwen3.6-plus:free"`, `ANTHROPIC_SMALL_FAST_MODEL="qwen/qwen3.6-plus:free"` |

**Three patterns**:

- **Registry-managed native CLIs** (codex, glm): model is part of the `cli` string in `providers/registry.json`. The `Makefile install` target and `install.sh` both consume the registry via `scripts/install.py`; do NOT edit Makefile or install.sh `register` lines for these — they derive from the registry.
- **Registry-deferred native CLI** (gemini): registered separately in `Makefile` and `install.sh` as `gemini -p` (no model flag in the registered CLI). The model is selected inside the `.delta.md` prompt (`gemini -m <model>` invocation in the `### New session` block). Gemini joins the registry once TRN-3025 lands a canonical `cli` value.
- **Anthropic-compat wrappers** (deepseek, openrouter, claude-code): model lives in `ANTHROPIC_MODEL` env var inside `providers/bin/<name>`. The registry stores the bin-script wrapper path, not the model.

---

## Steps

The exact procedure depends on which pin location the provider uses. **Section A** covers registry-managed native-CLI providers (codex, glm). **Section A-bis** covers gemini (registry-deferred). **Section B** covers Anthropic-compat wrappers (deepseek, openrouter, claude-code). **Section C** covers verification after `make install`.

### A. Registry-managed native-CLI providers (codex, glm)

1. Edit `providers/registry.json` → `providers.<name>.cli` field. The `Makefile install` target and `install.sh` both read this file via `scripts/install.py` — do NOT also edit `register` lines in those files (they no longer hardcode CLI strings for codex/glm post-TRN-3020).
2. If the provider has caller-side flags in its `.delta.md` or in `.agents/trinity.codex.json`, update there too.
3. Run `make build` (regenerates `providers/<name>.md` if `.delta.md` changed).
4. Run `make verify-built` (must pass).
5. Update any test asserting the registered `cli` string (search `tests/` for the old value, including `tests/test_install_sh.sh` T11 and `tests/test_codex_adapter.py` registry assertions).
6. CHANGELOG `[Unreleased]` entry.
7. Commit, bump VERSION (TRN-1003), `make release-prep`, push.
8. Re-run `make install` against `HOME=$(mktemp -d)` to confirm the registered `cli` matches what's in `providers/registry.json`.

### A-bis. Gemini (registry-deferred until TRN-3025)

Gemini is registered separately in `Makefile` (line ~63) and `install.sh` (line ~96) as `gemini -p`. The model itself is selected inside the `.delta.md` prompt, not in the registered CLI string.

1. Edit `providers/gemini.delta.md` — update the model identifier in the `### New session` invocation (e.g. `gemini -m gemini-3.1-pro-preview -p ...`).
2. Run `make build` (regenerates `providers/gemini.md`).
3. Run `make verify-built` (must pass).
4. Update any test asserting the gemini model string.
5. CHANGELOG `[Unreleased]` entry.
6. Commit, bump VERSION, `make release-prep`, push.
7. Re-run `make install` to refresh `~/.claude/agents/trinity-gemini.md`.

When TRN-3025 lands, this section folds back into Section A.

### B. Anthropic-compat providers (deepseek, openrouter)

1. Update `ANTHROPIC_MODEL` (and `ANTHROPIC_SMALL_FAST_MODEL` if applicable) in `providers/bin/<provider>`.
2. Update the matching assertion in `tests/test_anthropic_compat_wrappers.py` (`test_t1_<provider>_…`).
3. Run `.venv/bin/pytest tests/test_anthropic_compat_wrappers.py -q` (must pass).
4. CHANGELOG `[Unreleased]` entry — note the model name **including any `[1m]` suffix verbatim** (markdown's auto-link / footnote handling won't touch text inside ` ` ` code spans, so wrap the value in backticks).
5. Commit, bump VERSION, `make release-prep`, push.
6. Re-run `make install` to refresh `~/.claude/skills/trinity/bin/<provider>`.

### C. Verification after `make install`

```bash
# Confirm wrapper carries the expected env values
grep "ANTHROPIC_MODEL\|ANTHROPIC_SMALL_FAST_MODEL" ~/.claude/skills/trinity/bin/deepseek

# Smoke-test a real dispatch (consumes API quota — small prompt only)
~/.claude/skills/trinity/bin/deepseek -p "Reply with exactly: trinity-ok"
```

---

## Guard Rails

- **Never strip the `[…]` suffix** when copying from provider docs. If you see `[1m]`, it stays.
- **Never write the model ID unquoted** in a shell context. Always use `"…"` or `'…'`.
- **Never edit `providers/<name>.md` directly** for model changes — those are generated from `<name>.delta.md` (TRN-2004). For deepseek/openrouter, the model lives in `providers/bin/<name>`, not the agent .md.
- **Never edit Makefile or install.sh `register` lines** for native-CLI model bumps — they derive from `providers/registry.json` via `scripts/install.py` (post-TRN-3020). Edit the registry instead.
- **One provider per PR** when changing models. Don't bundle a deepseek pin change with an openrouter pin change unless the trigger is the same upstream event.
- **Provider docs URL** belongs in the CHANGELOG entry, so the rationale ("upstream announced the 1M tier") is recoverable.

---

## Examples

### 2026-04-26 — DeepSeek pinned to 1M-context tier

```diff
-ANTHROPIC_MODEL="deepseek-v4-pro" \
+ANTHROPIC_MODEL="deepseek-v4-pro[1m]" \
```

Tracked in `providers/bin/deepseek`, regression assertion in `tests/test_anthropic_compat_wrappers.py:test_t1_deepseek_env_key_sets_anthropic_env_and_passes_argv`. Released as v2.0.2.

### 2026-03-26 — Codex pinned to GPT-5.5 (TRN-2005)

```diff
-codex exec --skip-git-repo-check
+codex exec --skip-git-repo-check -m gpt-5.5
```

Tracked in `Makefile` install target and `install.sh` register call.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | TRN-3027: amended pin-location table + Section A steps + Guard Rails to reflect `providers/registry.json` as authoritative source for native-CLI providers (codex, glm) post-TRN-3020 | Claude Opus 4.7 |
| 2026-05-06 | Update GLM pin location/value for GLM-5.1 plus explicit highest supported reasoning effort | Codex |
| 2026-04-26 | Initial version — bracket-suffix convention, pin locations, update steps | Claude Opus 4.7 |

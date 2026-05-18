# PRP-2008: Remove Zsh Dependency from Trinity Providers

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Last updated:** 2026-04-26
**Last reviewed:** 2026-04-26
**Status:** Approved
**Reviewed by:**
- Round 1 (2026-04-26): Codex 7.6/10 FIX, Gemini 8.6/10 FIX, GLM 7.4/10 FIX, DeepSeek 6.8/10 FIX. Convergent blockers: (1) generated `.md` vs `.delta.md`, (2) missing `mkdir -p .../bin/`, (3) `run_<provider>` callers preservation, (4) stat portability + empty-`$PERM` handling, (5) error-message wording, (6) test-stub `exec` semantics, (7) `--resume` argv ordering test, (8) legacy-migration test.
- Round 2 (2026-04-26): Codex 8.9/10 PASS, Gemini 9.8/10 PASS, GLM 8.8/10 PASS, DeepSeek 10/10 PASS. All blockers verified resolved; no new blocking issues.
**Related:** TRN-2002 (Remote Install Script), TRN-2004 (Provider Files Refactor), TRN-1005 (SOP Install)

---

## What Is It?

Replace the two `.zshrc`-defined wrapper functions (`deepseek_cy`, `openrouter_cy`) — which today register as the `cli` for the `deepseek` and `openrouter` providers — with portable POSIX shell scripts shipped inside the trinity repo.

After this change, a fresh user can install trinity (`install.sh`) and use every registered provider with **no shell-rc edits** of any kind.

---

## Problem

1. **Sharing trinity is broken for two of five providers.** `~/.claude/trinity.json` registers `deepseek_cy -p` and `openrouter_cy -p` as the dispatch `cli`. These names resolve only inside the maintainer's `~/.zshrc`. A new user who follows `install.sh` ends up with two providers that fail at first dispatch with `command not found`.

2. **Dead-code fallback in agent .md.** `providers/deepseek.md` and `providers/openrouter.md` carry a `Setup` block with a `command -v <name>_cy` check and an inline `claude --dangerously-skip-permissions` fallback. Per Trinity's actual dispatch contract (`SKILL.md` §Dispatch), the worker reads its agent .md for protocol instructions but the **`cli` field in `trinity.json` is what gets executed verbatim**. The fallback never runs. It misleads readers into thinking it does.

3. **Two near-identical wrappers, copy-paste-ready for growth.** Both functions perform the same five steps: load API key from `~/.secrets/<provider>_api_key` (env-var override), set `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `CLAUDE_CONFIG_DIR`, exec `claude --dangerously-skip-permissions "$@"`. Any future Anthropic-API-compatible endpoint (Z.ai, Moonshot, Kimi, etc.) will be tempted to copy a third one into `.zshrc`.

---

## Decision Drivers

This PRP follows a four-model consultation (Codex high-effort, Gemini, GLM, DeepSeek) on three candidate approaches. All four converged on the **thin path** below.

Convergent findings:

- The `cli` field is the actual execution surface; the agent `.md` Setup block is read-but-not-used for dispatch routing. Any redesign must touch the surface that actually runs.
- A schema rethink (`shape: native | anthropic-compat | openai-compat`) is the wrong altitude: per-provider quirks (Codex `model_reasoning_effort`, Codex `resume` subcommand, Gemini `-r <index>` resume, DeepSeek 600 s timeout, JSONL trace-marker session lookup) do not factor into a 3-element enum. The redesign would either bloat into `adapter / resume_strategy / session_strategy / effort_strategy` discriminators, or push those quirks back into the agent `.md` and re-fragment the contract.
- A new `trinity-exec` Python dispatcher replacing `cli` strings is a ~200-LoC change to remove ~12 lines of zsh and one `cli` field — net-negative compression.
- The thin path (POSIX scripts in repo + install rewrites `cli` → absolute path) eliminates the zsh dependency with zero schema change, zero new abstraction, zero migration path, and is independent of any future architectural cleanup (e.g. moving provider config into agent `.md` frontmatter — explicitly deferred).

---

## Considered Alternatives

| # | Approach | Status | Reason |
|---|----------|--------|--------|
| A | Document the zsh dependency; ship a `trinity-shell-init` snippet users source | Rejected | Doesn't fix the problem; blesses it. |
| B | New Python dispatcher `trinity-exec <provider>` with `shape` discriminator in `trinity.json` | Rejected | 4-of-4 reviewer consensus: wrong altitude, leaky abstraction, breaking migration, premature `openai-compat`, doesn't address the actual dispatch surface (.md Setup). |
| C | Thin POSIX scripts in `providers/bin/`; `install.sh` writes absolute paths into `trinity.json` | **Accepted** | Smallest change that fixes the share story. Independent of future architectural rethink. |
| D | Eliminate `trinity.json` providers map; move shape into agent `.md` frontmatter as single source of truth | Deferred | Coherent design but breaks the `Config Overlay` global/project merge story (SKILL.md §Config Overlay). Out of scope for this PRP — track separately if pursued. |

---

## Proposed Solution

### 1. New scripts in repo: `providers/bin/`

Two POSIX `sh` scripts (no bashisms, no zshisms), checked into the repo:

- `providers/bin/deepseek` — wraps `claude --dangerously-skip-permissions` with DeepSeek env vars
- `providers/bin/openrouter` — wraps `claude --dangerously-skip-permissions` with OpenRouter env vars

Final shape of `providers/bin/deepseek`:

```sh
#!/bin/sh
# providers/bin/deepseek — Anthropic-compat wrapper for DeepSeek V4.
# Loads API key from $DEEPSEEK_API_KEY (preferred) or ~/.secrets/deepseek_api_key.
# Refuses to read key files with perm > 0600.
set -eu

KEY="${DEEPSEEK_API_KEY:-}"
KEY_FILE="${HOME}/.secrets/deepseek_api_key"

if [ -z "$KEY" ] && [ -f "$KEY_FILE" ]; then
    # Determine mode in three-octal form; tolerate exotic filesystems.
    # BSD stat (macOS, FreeBSD): -f '%Lp'; GNU stat (Linux): -c '%a'.
    PERM=$(stat -f '%Lp' "$KEY_FILE" 2>/dev/null \
        || stat -c '%a' "$KEY_FILE" 2>/dev/null \
        || echo unknown)
    case "$PERM" in
        600|400) ;;
        unknown)
            echo "trinity-deepseek: cannot stat $KEY_FILE — refusing to read for safety." >&2
            exit 1 ;;
        *)
            echo "trinity-deepseek: refuse to read $KEY_FILE (perm $PERM, expected 600 or 400). Run: chmod 600 $KEY_FILE" >&2
            exit 1 ;;
    esac
    KEY=$(cat "$KEY_FILE")
fi

if [ -z "$KEY" ]; then
    echo "trinity-deepseek: no API key. Set \$DEEPSEEK_API_KEY or write ~/.secrets/deepseek_api_key (mode 600)." >&2
    exit 1
fi

CLAUDE_CONFIG_DIR="${HOME}/.claude-deepseek" \
ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
ANTHROPIC_AUTH_TOKEN="$KEY" \
ANTHROPIC_API_KEY="$KEY" \
ANTHROPIC_MODEL="deepseek-v4-pro" \
ANTHROPIC_SMALL_FAST_MODEL="deepseek-v4-flash" \
API_TIMEOUT_MS="600000" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1" \
exec claude --dangerously-skip-permissions "$@"
```

`providers/bin/openrouter` is structurally identical with OpenRouter's `BASE_URL`, model defaults, and key-file path.

**Key precedence (declared explicitly):** environment variable `<PROVIDER>_API_KEY` wins over `~/.secrets/<provider>_api_key`. 12-factor convention; lets ad-hoc invocations (`DEEPSEEK_API_KEY=xxx providers/bin/deepseek …`) override the file.

**Key-file permission check:** the script `stat`s the file and refuses any mode > 0400 unless it's exactly `0600`. Hard error — reading a world-readable secret silently is a footgun. The `|| echo unknown` terminator ensures the `case` runs even if both `stat` invocations fail (exotic filesystems, NFS, sshfs); `unknown` falls through to a refuse-with-message branch instead of a silent `set -e` abort.

**Why `exec`:** wrapper replaces itself with `claude` so signals propagate and `ps` stays clean.

**Why no bashisms:** `/bin/sh` is everywhere; minimal containers may lack bash.

**Stat portability matrix:**

| OS | Tool | Format flag |
|----|------|-------------|
| macOS (Darwin) | BSD `stat` | `-f '%Lp'` (✓ verified outputs `600`/`400`/`644`) |
| FreeBSD | BSD `stat` | `-f '%Lp'` (same) |
| Linux (glibc/musl) | GNU `stat` | `-c '%a'` |
| anything else | n/a | `echo unknown` → refuse |

### 2. `install.sh` changes

Concrete diff:

```diff
@@ install.sh: directory creation block @@
 mkdir -p "${HOME}/.claude/skills/trinity/scripts"
+mkdir -p "${HOME}/.claude/skills/trinity/bin"
 mkdir -p "${HOME}/.claude/agents"

@@ install.sh: download block @@
 _download "providers/openrouter.md"   "${HOME}/.claude/agents/trinity-openrouter.md"
 _download "providers/deepseek.md"     "${HOME}/.claude/agents/trinity-deepseek.md"
+_download "providers/bin/deepseek"    "${HOME}/.claude/skills/trinity/bin/deepseek"
+_download "providers/bin/openrouter"  "${HOME}/.claude/skills/trinity/bin/openrouter"
+chmod +x "${HOME}/.claude/skills/trinity/bin/deepseek" \
+         "${HOME}/.claude/skills/trinity/bin/openrouter"

@@ install.sh: provider registration block @@
 python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register openrouter \
-    --cli "openrouter_cy -p" \
+    --cli "${HOME}/.claude/skills/trinity/bin/openrouter -p" \
     --global-config "${HOME}/.claude/trinity.json"
 python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register deepseek \
-    --cli "deepseek_cy -p" \
+    --cli "${HOME}/.claude/skills/trinity/bin/deepseek -p" \
     --global-config "${HOME}/.claude/trinity.json"
```

Notes:
- `glm`, `codex`, `gemini` registrations unchanged — already PATH binaries with no zsh dependency.
- `-p` is kept in the registered `cli` because the agent worker invokes the wrapper as `run_<provider> -p "$MARKED_PROMPT"`. The `cli` field is the canonical "first form" shown in `/trinity status` (matches today's `gemini -p` registration shape).
- `install.py` already uses `fcntl.flock` for atomic JSON updates (`scripts/install.py:55-78`); concurrent installs are safe.

### 3. `Makefile` `install` target

Mirror the same wiring locally. The `install` target must also create the `bin/` dir, copy the two scripts, set `+x`, and re-register the two providers with absolute paths. (TRN-2002 documented this drift risk; we accept it again with explicit symmetry.)

### 4. Agent template (`.delta.md`) edits — NOT generated `.md`

`providers/deepseek.md` and `providers/openrouter.md` are **generated files** produced by `scripts/build_providers.sh` from `providers/<name>.delta.md` + `providers/_base/*.md` partials. `make verify-built` (run inside `make test` and `release-prep`) hashes the generated output against the source — direct edits to the generated `.md` will fail CI.

All template edits land in the `.delta.md` files; `make build` regenerates the `.md`.

**`providers/deepseek.delta.md` Setup block — before/after:**

```diff
 ### Setup (run once before new or resume)

-Define the CLI function and session directory:
+Define the CLI entry function and session directory.
+`run_deepseek` calls the wrapper script installed by install.sh / make install
+(repo source: providers/bin/deepseek). The wrapper handles env injection,
+key-file loading from ~/.secrets/deepseek_api_key (mode 600), and
+precedence (DEEPSEEK_API_KEY env var wins over file).
+
 ```bash
-# CLI function — uses wrapper if available, otherwise portable env approach
 run_deepseek() {
-  if command -v deepseek_cy >/dev/null 2>&1; then
-    deepseek_cy "$@"
-  else
-    local key
-    key="$(cat ~/.secrets/deepseek_api_key 2>/dev/null)"
-    if [ -z "$key" ]; then key="${DEEPSEEK_API_KEY:-}"; fi
-    if [ -z "$key" ]; then
-      echo "ERROR: no DeepSeek API key found. Set DEEPSEEK_API_KEY or create ~/.secrets/deepseek_api_key" >&2
-      return 1
-    fi
-    CLAUDE_CONFIG_DIR="$HOME/.claude-deepseek" \
-    ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
-    ANTHROPIC_AUTH_TOKEN="$key" \
-    ANTHROPIC_API_KEY="$key" \
-    ANTHROPIC_MODEL="deepseek-v4-pro" \
-    ANTHROPIC_SMALL_FAST_MODEL="deepseek-v4-flash" \
-    API_TIMEOUT_MS="600000" \
-    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1" \
-    claude --dangerously-skip-permissions "$@"
-  fi
+  "$HOME/.claude/skills/trinity/bin/deepseek" "$@"
 }

 # Session directory (scoped to project)
 PROJECT_SLUG=$(echo "$PROJECT_DIR" | sed 's|/|-|g; s|^-||')
 SESSION_DIR="$HOME/.claude-deepseek/projects/${PROJECT_SLUG}"
 ```
```

**Frontmatter `description` cleanup** — drop the `deepseek_cy` reference:

```diff
 description: |
-  Worker agent for DeepSeek V4 (via anthropic_cli wrapper).
-  Uses deepseek_cy (claude --dangerously-skip-permissions with DeepSeek backend).
+  Worker agent for DeepSeek V4. Wraps `claude --dangerously-skip-permissions`
+  with DeepSeek's Anthropic-compatible endpoint. API key from
+  $DEEPSEEK_API_KEY or ~/.secrets/deepseek_api_key (mode 600).
   Default model: deepseek-v4-pro. Supports session resume via --resume.
```

**`providers/openrouter.delta.md`** — structurally identical change, with OpenRouter env values.

**Caller sections (`### New session`, `### Resume session`, common-tail rules)** — unchanged. They keep calling `run_deepseek -p` / `run_deepseek --resume <id> -p`; the function signature is preserved.

After both `.delta.md` edits: `make build` (regenerates `providers/<name>.md`) → `make verify-built` (must pass).

### 5. README / SKILL.md docs

- Add a short note to `README.md` Quick Start: "DeepSeek and OpenRouter providers expect `~/.secrets/<provider>_api_key` (mode 600) or `<PROVIDER>_API_KEY` env var."
- `SKILL.md` `## Config Overlay` example — no changes (doesn't show deepseek/openrouter today).

---

## Scope

**In scope:**

- New `providers/bin/deepseek` and `providers/bin/openrouter` (POSIX sh, ~30 lines each)
- `install.sh` — download bin scripts, `chmod +x`, register absolute path as `cli`
- `Makefile` `install` target — same wiring locally
- `providers/deepseek.md` and `providers/openrouter.md` — cleanup `Setup` block
- `README.md` — Quick Start key-file note
- `tests/` — new test file `tests/test_anthropic_compat_wrappers.py` covering: missing-key error, env-overrides-file precedence, perm-check refusal, exec-replaces-shell behavior (smoke), `install.sh` registers absolute paths
- `rules/TRN-0000-REF-Document-Index.md` — add TRN-2008 row, TRN-2009 row
- `rules/TRN-2009-CHG-Remove-Zsh-Dependency.md` — implementation CHG (separate doc, drafted in Phase 5)

**Out of scope:**

- Python `trinity-exec` dispatcher (alternative B, rejected)
- `shape` discriminator in `trinity.json` schema
- `openai-compat` shape — no current consumer
- Moving provider config into agent `.md` frontmatter (alternative D, deferred)
- Changing `glm`, `codex`, `gemini` registrations (no zsh dependency)
- Migrating Codex `--reasoning-effort`, Gemini `-r`, DeepSeek timeout into config — those stay in the worker .md per current contract
- Uninstall script
- Windows support

---

## Design Decisions

**DD-1 — POSIX `sh` not bash.**
The wrappers use `/bin/sh` with no bash-only syntax (no `[[`, no arrays, no `$'…'` ANSI-C quoting). Justification: portability to minimal containers; the wrappers are simple enough that bash buys nothing.

**DD-2 — `exec claude` not `claude` + `wait`.**
Replacing the shell with the `claude` process avoids a stranded parent shell, propagates signals cleanly, and removes one entry from `ps` output.

**DD-3 — Permission check is a hard refuse; accept `0600` and `0400`.**
Mode > 0600 on a key file is a real footgun. Failing closed is the safer default. Both `0600` (rw owner) and `0400` (read-only owner) are accepted — `0400` is strictly safer than `0600`. Anything else (including unreadable / unstattable files) is refused with a stderr message.

**DD-4 — Env wins over file.**
Standard 12-factor precedence. Lets ad-hoc overrides without editing the file.

**DD-5 — Keep `run_<provider>` function in the agent template; simplify it to call the bin script.**
Don't change the dispatcher contract. The worker calls `run_deepseek -p "$MARKED_PROMPT"` and `run_deepseek --resume <id> -p "<prompt>"`; that signature stays. The function body collapses from ~25 lines to one line: `"$HOME/.claude/skills/trinity/bin/deepseek" "$@"`. This isolates env handling in the bin script (testable, portable) without touching call sites.

**DD-6 — Keep `-p` baked into the registered `cli`.**
The `cli` field in `trinity.json` is the canonical "first form" shown in `/trinity status`. Today gemini/openrouter/deepseek all register `<wrapper> -p`; preserving the shape prevents UX drift and matches what the worker actually invokes (`run_<provider> -p ...`). Resume safety is unaffected because the dispatcher calls through `run_<provider>`, not by templating `<cli>` itself.

**DD-7 — Keep the `cli` schema as-is.**
Don't touch `trinity.json`'s shape. Only the *values* of two `cli` strings change (zshrc-function-name → absolute path). All existing readers (`discover.py`, `install.py`, dispatcher) keep working with no migration code.

**DD-8 — Don't delete `~/.claude/trinity.json`'s `installed: true` field.**
Existing flag is harmless; keep writing it for compatibility with any reader that keys off it.

---

## Test Cases

All new tests live in `tests/test_anthropic_compat_wrappers.py`. Tests run the wrapper scripts directly with a `claude` stub injected via PATH-prepend (no real network calls).

**Stub mechanism (concrete):**

A small Python script written to `tmp_path/bin/claude` records `sys.argv[1:]` and selected `os.environ` keys to a file (e.g. `tmp_path/claude.invoked.json`), then exits `0`. The test prepends `tmp_path/bin` to `PATH` before exec'ing the wrapper. Because the wrapper does `exec claude …`, the stub becomes the leaf process and the recording file is the source of truth for assertions. This pattern handles the `exec`-replaces-shell semantics correctly (no fork; the stub IS the process).

| # | Test | Expected |
|---|------|----------|
| T1 | Run `providers/bin/deepseek arg1 arg2` with `DEEPSEEK_API_KEY=xxx` set | Stub `claude` records argv `['--dangerously-skip-permissions', 'arg1', 'arg2']`; env has `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `ANTHROPIC_AUTH_TOKEN=xxx`, `ANTHROPIC_MODEL=deepseek-v4-pro`, `ANTHROPIC_SMALL_FAST_MODEL=deepseek-v4-flash`, `API_TIMEOUT_MS=600000`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CONFIG_DIR` ends in `.claude-deepseek`; exit 0 |
| T2 | No env, `~/.secrets/deepseek_api_key` exists with mode 600 and content `from-file` | Stub recorded with `ANTHROPIC_AUTH_TOKEN=from-file`; exit 0 |
| T3 | Env `from-env`, file `from-file` (mode 600) | Stub recorded with `ANTHROPIC_AUTH_TOKEN=from-env` (env wins); exit 0 |
| T4 | No env, no file | Exit 1; stderr matches `no API key` |
| T5 | No env, file mode 644 | Exit 1; stderr matches `refuse to read .* perm 644 .* expected 600 or 400` |
| T6 | No env, file mode 600 but empty | Exit 1; stderr matches `no API key` |
| T6b | No env, file mode 400 (read-only owner) | Stub recorded with token from file; exit 0 (DD-3 accepts 400) |
| T7 | Same T1–T6b for `providers/bin/openrouter` (different base URL, model, key file path) | Same expected outcomes; OpenRouter env: `BASE_URL=https://openrouter.ai/api`, `MODEL=qwen/qwen3.6-plus:free` |
| T8 | Wrapper invoked as `<bin>/deepseek --resume sess123 -p "hello"` (simulating worker resume) | Stub argv = `['--dangerously-skip-permissions', '--resume', 'sess123', '-p', 'hello']` (correct argv ordering, `-p` after `--resume`, no double-`-p`) |
| T9 | `install.sh` against local server (TRINITY_BASE_URL) | `~/.claude/trinity.json` `providers.deepseek.cli` == `${HOME}/.claude/skills/trinity/bin/deepseek -p`; same shape for openrouter; both bin scripts present and `os.access(.., os.X_OK)` true |
| T10 | `install.sh` run twice (idempotent) | Second run produces byte-identical `trinity.json` for these two providers; bin scripts still executable |
| T11 | Pre-existing `~/.claude/trinity.json` with legacy `"cli": "deepseek_cy -p"`, then `install.sh` runs | Post-install `cli` == absolute-path form; legacy value overwritten; other providers untouched (regression: legacy → new migration) |
| T12 | `make install` (local path) — same outcome as T9 + T11 | Pass |
| T13 | Wrapper run with `KEY_FILE` on a path where `stat -f` AND `stat -c` both fail (simulated by replacing `stat` on PATH with a stub returning exit 1) | Exit 1; stderr matches `cannot stat .* refusing to read for safety` (covers the `unknown` case in PERM resolution) |
| T14 | `make build` after editing `providers/deepseek.delta.md` and `providers/openrouter.delta.md` | `make verify-built` passes; generated `providers/deepseek.md` and `providers/openrouter.md` contain `"$HOME/.claude/skills/trinity/bin/deepseek" "$@"` and no `command -v deepseek_cy` line |

Tests are pytest with `tmp_path` for `HOME` redirection. Pattern follows `tests/test_install.py` (existing precedent for `tmp_path` + `--global-config` injection).

---

## Risk

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `stat -f` (BSD) vs `stat -c` (GNU) split | Medium (Linux users) | Try BSD first, fall back to GNU, then `|| echo unknown` terminator; T13 covers the `unknown` branch |
| `set -eu` trips on unset `HOME` | Very low | If `HOME` is unset the rest of trinity is broken anyway — fail loudly is correct |
| Concurrent installs corrupt `trinity.json` | Very low | `install.py atomic_update` uses `fcntl.flock` (`scripts/install.py:55-78`) — already exercised by `test_concurrent_register_no_corruption` |
| User has the old zsh function defined AND the new script registered | Low | New `cli` is an absolute path — PATH/function lookup never happens. Old function silently unused; user can delete `.zshrc` lines at leisure |
| Migration: existing `trinity.json` has `deepseek_cy -p` | Medium | Re-running `install.sh` / `make install` overwrites the registration. T11 covers it. Documented in CHG TRN-2009. Not auto-rewritten on first dispatch (would surprise users) |
| `chmod +x` failure in `install.sh` (e.g., noexec mount) | Very low | `set -eE` aborts; trap reports the failing file |
| Editing generated `providers/<name>.md` directly bypasses `make verify-built` | Medium | §4 explicitly directs edits at `.delta.md`; T14 asserts `make verify-built` passes after `.delta.md` edits |
| Future Anthropic-compat provider author copies an old `_cy` function from history | Low | CHG TRN-2009 + this PRP serve as the canonical pattern; bin script header comment names the pattern |
| User has key file at non-default path (e.g., `~/keys/deepseek.txt`) | Low | Out of scope today — env var (`DEEPSEEK_API_KEY`) is the documented escape hatch. Future enhancement could read `DEEPSEEK_API_KEY_FILE` |

---

## Open Questions

All resolved in Round 1 review (Codex / Gemini / GLM / DeepSeek unanimous):

- ~~OQ-1~~ — **Resolved (No)**: wrappers are transparent passthroughs; `claude --help` is what users actually need.
- ~~OQ-2~~ — **Resolved (Yes)**: accept mode `0400` in addition to `0600`. Folded into DD-3.
- ~~OQ-3~~ — **Resolved (No)**: out of scope; existing `install.py unregister` covers user-driven removal. CHG TRN-2009 will document the command.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-04-26 | Initial draft | Claude Opus 4.7 |
| 2026-04-26 | Round 2 revision per 4-model strict review: §1 stat handling + portability matrix + accept 400; §2 concrete diff incl. mkdir -p bin/; §3 Makefile parity explicit; §4 edits target .delta.md (NOT generated .md), keep `run_<provider>` function; DD-3 widened to 600 OR 400; DD-5/6/7/8 split for clarity; tests T6b/T8/T11/T13/T14 added; risks expanded; OQs resolved | Claude Opus 4.7 |

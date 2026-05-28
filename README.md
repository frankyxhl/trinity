# Trinity — Multi-Model Orchestration

Dispatch tasks to any LLM (GLM, Codex, Gemini, Claude Code, DeepSeek, OpenRouter, or your own) from your AI coding host. Trinity runs as a skill in Claude Code and as a skill / plugin in Codex; providers run in the background as sub-agents or direct CLI calls. Sessions persist across turns. Health monitoring tells you if they're alive.

The name comes from 三位一体 — not a fixed count, but a philosophy: all AIs united, working together. Whoever runs Trinity is the Leader. Any external LLM with a CLI is a Member. Any host that can spawn sub-agents or shell out to a CLI can be the Leader.

---

## Table of Contents

- [If You Are an AI](#if-you-are-an-ai)
- [What Trinity Does](#what-trinity-does)
- [Install](#install)
  - [Step 1: Install the skill](#step-1-install-the-skill)
  - [Step 2: Install providers](#step-2-install-providers)
  - [Step 3: Configure global defaults (optional)](#step-3-configure-global-defaults-optional)
- [Codex Compatibility](#codex-compatibility)
- [Command Reference](#command-reference)
- [Usage Guide](#usage-guide)
  - [Single dispatch](#single-dispatch)
  - [Multi-provider parallel](#multi-provider-parallel)
  - [Named instances](#named-instances)
  - [Parallel same-provider](#parallel-same-provider)
  - [Review presets](#review-presets)
  - [Plan mode](#plan-mode)
  - [Health monitoring](#health-monitoring)
  - [Session management](#session-management)
- [Architecture](#architecture)
- [Adding a Provider](#adding-a-provider)
- [Troubleshooting](#troubleshooting)

---

## If You Are an AI

> This section is for LLM agents (Claude, GPT, Gemini, etc.) installing Trinity on behalf of a user.

**You can install Trinity in one Bash call — no git clone required.**

### Step 1: Run the installer

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
```

This downloads all skill files to `~/.claude/` and registers the seven default providers (glm, minimax, codex, gemini, openrouter, deepseek, claude-code) in `~/.claude/trinity.json`. Expected output ends with:

```
Trinity 3.2.0 installed to ~/.claude/
```

If the command fails, check stderr for `trinity-install: failed downloading <file>` — that tells you exactly which file 404'd.

### Step 2: Tell the user to restart Claude Code

Trinity's skill (`SKILL.md`) is loaded by Claude Code at startup. The install takes effect after restart. Tell the user:

> "Trinity is installed. Please restart Claude Code, then run `/trinity status` to confirm all providers are registered."

### Step 3: Verify (after restart)

```
/trinity status
```

Expected output: glm, minimax, codex, gemini, openrouter, deepseek, and claude-code all show ✅ usable. If any show ⚠️, run `/trinity install <provider>` to repair.

### What was installed

| Location | Contents |
|----------|----------|
| `~/.claude/skills/trinity/SKILL.md` | Trinity skill — loaded by Claude Code |
| `~/.claude/skills/trinity/scripts/` | Python session/config/discover/install scripts |
| `~/.claude/agents/trinity-glm.md` | GLM worker agent |
| `~/.claude/agents/trinity-minimax.md` | MiniMax 2.7 worker agent |
| `~/.claude/agents/trinity-codex.md` | Codex worker agent |
| `~/.claude/agents/trinity-gemini.md` | Gemini worker agent |
| `~/.claude/agents/trinity-openrouter.md` | OpenRouter worker agent |
| `~/.claude/agents/trinity-deepseek.md` | DeepSeek V4 worker agent |
| `~/.claude/agents/trinity-claude-code.md` | Claude Code worker agent |
| `~/.claude/skills/trinity/bin/deepseek` | DeepSeek `claude --dangerously-skip-permissions` wrapper (env injection + key-file loader) |
| `~/.claude/skills/trinity/bin/openrouter` | OpenRouter wrapper (same shape) |
| `~/.claude/skills/trinity/bin/claude-code` | Isolated nested Claude Code wrapper (`--model sonnet --effort high`) |
| `~/.claude/trinity.json` | Global provider registry |

---

## What Trinity Does

- **Dispatch** tasks to external LLMs running in the background — you keep working while they run
- **Session continuity** — each provider instance remembers its conversation across calls
- **Provider auto-discovery** — add new providers by dropping a config entry + agent file; no skill editing required
- **Review presets** — one keyword (`review`, `fast-review`, `deep-review`) fans a task out to a configured provider set in parallel
- **Health monitoring** — heartbeat checks tell you if agents are alive, stalled, or timed out
- **Install command** — `/trinity install codex` sets up the CLI, agent file, config, and smoke test in one step
- **Plan mode** — draw a sequence diagram, confirm, then auto-dispatch in dependency order
- **Codex adapter** — a terminal `trinity review` that runs the same multi-provider review without Claude Code

---

## Install

### Step 1: Install the skill

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
```

This downloads all skill files directly to `~/.claude/` — no git clone required. To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=3.2.0 bash
```

**Or, if you have the repo cloned:**
```bash
make install
```

### Step 2: Install providers

**Using the install command (recommended):**
```
/trinity install codex
/trinity install gemini
/trinity install glm
```

Each install command:
1. Checks if the CLI is already in PATH
2. If not, tries Homebrew → npm → pip in order
3. Copies the agent template to `~/.claude/agents/trinity-<provider>.md`
4. Registers the provider in `~/.claude/trinity.json`
5. Runs a smoke test to verify everything works
6. Rolls back atomically if any step fails

**Wrapper-based providers** (`openrouter`, `deepseek`, `claude-code`) don't have a package install path — they use small POSIX shell wrappers shipped in `providers/bin/` and installed to `~/.claude/skills/trinity/bin/`. `openrouter` and `deepseek` point the `claude` binary at Anthropic-compatible endpoints. `claude-code` starts an isolated nested Claude Code process with Trinity dispatch disabled, defaulting to `--model sonnet --effort high`. `install.sh` and `make install` set them up automatically; no `~/.zshrc` edits required.

The Anthropic-compatible wrappers expect an API key, in this order of precedence:
1. **Environment variable** — `DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY`
2. **Key file** — `~/.secrets/<provider>_api_key` with mode `600` (or `400`); the wrapper refuses anything more permissive

```bash
# Either set an env var in your shell rc:
export DEEPSEEK_API_KEY=sk-...

# Or write the key to a file (safer for unattended use):
mkdir -p ~/.secrets
echo "sk-..." > ~/.secrets/deepseek_api_key
chmod 600 ~/.secrets/deepseek_api_key
```

**Or install manually:**

```bash
# Codex
cp trinity/providers/codex.md ~/.claude/agents/trinity-codex.md

# Gemini
cp trinity/providers/gemini.md ~/.claude/agents/trinity-gemini.md

# GLM
cp trinity/providers/glm.md ~/.claude/agents/trinity-glm.md

# MiniMax 2.7
cp trinity/providers/minimax.md ~/.claude/agents/trinity-minimax.md

# OpenRouter
cp trinity/providers/openrouter.md ~/.claude/agents/trinity-openrouter.md

# DeepSeek V4
cp trinity/providers/deepseek.md ~/.claude/agents/trinity-deepseek.md

# Claude Code
cp trinity/providers/claude-code.md ~/.claude/agents/trinity-claude-code.md

# Wrapper bin scripts (deepseek + openrouter + claude-code)
mkdir -p ~/.claude/skills/trinity/bin
cp trinity/providers/bin/deepseek   ~/.claude/skills/trinity/bin/deepseek
cp trinity/providers/bin/openrouter ~/.claude/skills/trinity/bin/openrouter
cp trinity/providers/bin/claude-code ~/.claude/skills/trinity/bin/claude-code
chmod +x ~/.claude/skills/trinity/bin/deepseek ~/.claude/skills/trinity/bin/openrouter ~/.claude/skills/trinity/bin/claude-code
```

Then create `~/.claude/trinity.json`:
```json
{
  "providers": {
    "codex":      { "cli": "codex exec --skip-git-repo-check -m gpt-5.5", "installed": true },
    "gemini":     { "cli": "gemini -p",                        "installed": true },
    "glm":        { "cli": "droid exec --auto medium --model glm-5.1 --reasoning-effort high", "installed": true },
    "minimax":    { "cli": "droid exec --auto medium --model minimax-m2.7 --reasoning-effort high", "installed": true },
    "openrouter":  { "cli": "/Users/<you>/.claude/skills/trinity/bin/openrouter -p",  "installed": true },
    "deepseek":    { "cli": "/Users/<you>/.claude/skills/trinity/bin/deepseek -p",    "installed": true },
    "claude-code": { "cli": "/Users/<you>/.claude/skills/trinity/bin/claude-code -p", "installed": true }
  },
  "defaults": {
    "heartbeat_interval": 120,
    "timeout": { "tdd": 600, "review": 360, "general": 1200 }
  }
}
```

To use review presets via the Claude Code skill, add them to the same file:

```json
{
  "presets": {
    "review":      { "providers": ["glm", "gemini", "deepseek"], "optional_providers": ["codex", "claude-code"] },
    "fast-review": { "providers": ["glm", "deepseek"] },
    "deep-review": { "providers": ["glm", "gemini", "deepseek"], "optional_providers": ["codex", "claude-code"] }
  },
  "preset_aliases": { "r": "review", "fr": "fast-review", "dr": "deep-review" }
}
```

### Step 3: Configure global defaults (optional)

Edit `~/.claude/trinity.json` to set your preferred heartbeat interval and timeout thresholds. Per-project overrides go in `.claude/trinity.json` at the project root.

---

## Codex Compatibility

Trinity also ships a Codex adapter that adds a terminal `trinity` command for
multi-provider code review. It does not change the Claude Code install path.

### Install

From a cloned repo:

```bash
make install-codex
```

| Location | Contents |
|----------|----------|
| `~/.codex/skills/trinity/SKILL.md`           | Codex-specific Trinity skill |
| `~/.codex/skills/trinity/scripts/`           | Shared scripts + Codex wrapper |
| `~/.codex/skills/trinity/bin/deepseek`       | DeepSeek Anthropic-compat wrapper |
| `~/.codex/skills/trinity/trinity.codex.json` | Bundled default Codex config |
| `~/.codex/trinity.json`                      | User-level Codex provider config |
| `~/.local/bin/trinity`                       | Terminal wrapper |

The default config (`.agents/trinity.codex.json`) registers `glm`, `gemini`,
and `deepseek` for direct CLI review and seeds the `review` / `fast-review` /
`deep-review` presets (with `r` / `fr` / `dr` aliases) — same set documented
under [Review presets](#review-presets). `trinity review` chooses providers in
this order: explicit `--providers`, explicit `--preset`,
`review.default_preset`, then legacy `review.default_providers`.

### Provider health

```bash
trinity doctor --providers glm,gemini,deepseek
trinity doctor --preset fast-review
trinity review --check-providers --preset dr
```

Health checks validate config shape, CLI lookup, executable permissions,
timeouts, **wrapper-provider auth files** (env-or-file precedence with mode
600/400 check, mirroring `providers/bin/<wrapper>` behavior), **timeout
sanity** (warns if `< 60s`), **shell env pollution** (lists vars matching
the TRN-3023 spawn-time clearlist — `*_BASE_URL`, `OTEL_*`, etc. — so
operators can audit their `direnv` / shell setup), and the resolved CLI
string per provider. Output now splits **REQUIRED** vs **OPTIONAL** providers
(driven by the active preset's metadata); REQUIRED-provider auth issues are
fatal (exit 1), OPTIONAL-provider issues are demoted to warnings (exit 0).
The first line per provider stays `{provider}: OK - {executable} (timeout Ns)`
so existing `grep` patterns continue to work.

Doctor still does not call the provider, so API-key or quota errors can
still surface during an actual review.

### Run a review

```bash
trinity review --providers glm,gemini,deepseek --scope spikes/hardline
trinity review --preset fast-review --scope spikes/hardline
trinity review --preset dr --scope .
trinity review --base main --head HEAD --providers glm,deepseek
trinity review --pr 21 --preset deep-review
trinity review --sop COR-1602 --rubric COR-1609 --pr 21 --preset deep-review
```

Scope modes:

- **default** — tracked + untracked working-tree changes
- `--base/--head` — committed branch diff (`git diff base...head`) + head snapshot
- `--pr <n>` — `gh pr view` / `gh pr diff` + head snapshot when the commit is local

All modes call provider CLIs directly, run them concurrently up to
`review.max_parallel_providers`, store raw outputs, and write a deterministic
`synthesis.md` under `.trinity/reviews/`. stdout is the review directory path;
Progress is logged to stderr. Interrupted runs leave `incomplete.json` for
cleanup. Optional preset providers with no config entry or no `cli` string
are dropped from the run with a warning recorded in `metadata.json`; once an
optional provider has a `cli` string it is treated like a required provider
for preflight, so any optional or required provider whose CLI is `command
not found`, not executable, or has an invalid timeout fails preflight and
aborts the whole review before any provider runs. This path does not
require Claude Code worker-agent files.

**Strict COR review mode** — pair `--sop COR-1602` with `--rubric COR-1609` to
prepend rubric weights, calibration guidance, the 9.0 PASS threshold, and the
findings / decision-matrix / weighted-average output schema to the prompt.
SOP, rubric, threshold, and schema are recorded in `metadata.json`.

**Structured review output** — when using a preset with `task_type: review`,
Trinity appends a structured-output instruction to the prompt requesting
providers emit a fenced JSON block (`decision`, `weighted_score`, `blocking`,
`advisories`). Providers that comply produce enriched `synthesis.md` output
with per-provider scores and a Findings section. Providers that don't emit
the block continue to work via legacy returncode-based rendering. (#39)

### Check review status

```bash
trinity status              # newest review (default; --latest is reserved for forward-compat)
trinity status --latest     # explicit; same as bare `trinity status` today
```

`trinity status` summarises the most recent review under `.trinity/reviews/`.
With TRN-2018 M1, it shows a **Live state** section for in-progress reviews —
each provider with its current state (`queued`/`running`/`finished`/`failed`/
`timed_out`), pid when running, return code when terminal, and elapsed time:

```text
Latest review: .trinity/reviews/20260516-120000-rules  (started 2m ago)
  Scope: rules/   Mode: working-tree   Preset: fast-review

  Live state:
    glm        running  pid=12345  elapsed 2m 03s
    deepseek   queued

  Providers:
    (no results in metadata)

  Synthesis: missing
  Status: running
```

Provider stdout/stderr stream to `.trinity/reviews/<id>/logs/<provider>.std{out,err}.log`
while the review runs — `tail -f` works on those files for live progress. Stdout
uses a PTY-backed reader so line-buffered CLIs flush progress before exit. The
post-completion `raw/<provider>.txt` is composed from the same logs and remains
backward-compatible. If no reviews exist, `trinity status` exits 0 with `no
reviews found`.

### Update a PR after review fixes

```bash
make pr-update PR=26 MESSAGE="Address review feedback" DRY_RUN=1
make pr-update PR=26 MESSAGE="Address review feedback" REVIEW="Trinity fast-review PASS"
make pr-update PR=26 MESSAGE="Add follow-up fix" MODE=commit REVIEW="Codex found no major issues"
make pr-update PR=26 MESSAGE="Post validation evidence" MODE=comment-only REVIEW="No actionable findings"
```

`make pr-update` runs `scripts/pr-update.sh`. It requires a clean working tree
(no unstaged/untracked files), a configured upstream branch, and staged
changes for `MODE=amend` (default) or `MODE=commit`. It runs `make test`,
`make lint`, and `af validate --root .` before any push or comment.

- `MODE=amend` (default): `git commit --amend --no-edit` + `git push --force-with-lease` to the current upstream branch
- `MODE=commit`: new commit + plain `git push` to the current upstream branch
- `MODE=comment-only`: validate and post the PR comment, no push

Always run `DRY_RUN=1` first to preview. Skip the helper if unrelated local
files are dirty, the PR head changed unexpectedly, you need a custom push
target, or COR-1612/COR-1615 needs more precise per-finding replies. When
`MESSAGE` or `REVIEW` contain `$`, single-quote the value so Make passes it
through unexpanded.

Manual fallback:

```bash
make test && make lint && af validate --root .
git commit --amend --no-edit
git push --force-with-lease fork HEAD:codex/example-branch
gh pr comment 26 --body-file comment.md
```

### Codex repo-local skill and Codex plugin

**Codex repo-local skill** — `.agents/skills/trinity/SKILL.md`. Smoke test:
restart Codex in the repo, then open `/skills` or invoke `$trinity` to
confirm the `trinity` skill loads.

**Codex plugin** — packaged under:

| Path | Purpose |
|------|---------|
| `plugins/trinity/.codex-plugin/plugin.json`      | Local plugin manifest |
| `plugins/trinity/skills/trinity/SKILL.md`        | Plugin-bundled skill |
| `.agents/plugins/marketplace.json`               | Repo marketplace entry |

Smoke test: restart Codex, open `/plugins`, select the repo marketplace, and
confirm the `trinity` plugin appears. After installing it, the bundled skill
becomes available.

**Claude Code regression check**

Claude Code still uses the existing install path. After `make install` or `install.sh`, restart Claude Code and run:

```text
/trinity status
```

Expected result: the command is recognized and registered providers are listed. Provider CLIs that are not installed or authenticated may warn, but Trinity itself must load.

---

## Command Reference

```
/trinity <provider>[:<instance>] "task"          # single dispatch
/trinity <p1>[:<i>] "t1" <p2> "t2"              # multi-provider parallel
/trinity <provider>*N "task"                     # N parallel same-provider
/trinity <preset> "task"                         # dispatch to a preset's provider set
/trinity plan <p1> "t1" <p2> "t2"               # plan with diagram, confirm, execute
/trinity plan "high-level description"           # auto-decompose, confirm, execute
/trinity install <provider>                      # install + register provider
/trinity status                                  # registered providers + presets + sessions
/trinity heartbeat [<instance>]                  # on-demand liveness check
/trinity clear [<instance> | all]                # clear sessions
/trinity help                                    # show this README
```

Reserved subcommands (cannot be used as provider, preset, or alias names):
`status`, `clear`, `plan`, `heartbeat`, `install`, `help`.

Built-in presets (when configured): `review`, `fast-review`, `deep-review`,
with aliases `r`, `fr`, `dr`. See [Review presets](#review-presets).

---

## Usage Guide

### Single dispatch

Send a task to one provider. It runs in the background; you get the result when it's done.

```
/trinity glm "Implement a rate limiter with sliding window algorithm"
```

Trinity validates the provider, spawns a background agent, and confirms:
```
Dispatched:
- GLM → "Implement a rate limiter..." (background)
```

### Multi-provider parallel

Send different tasks to different providers simultaneously.

```
/trinity glm:auth "Implement JWT authentication" codex "Review the auth module for security issues"
```

Both agents run in parallel. Results arrive independently as each completes.

### Named instances

`provider:name` creates a persistent named session. Subsequent calls resume the same conversation.

```
# First call — new session
/trinity glm:auth "Implement user registration with email validation"

# Later — resumes the auth session (GLM remembers the previous work)
/trinity glm:auth "Add password reset to the auth module"
```

### Parallel same-provider

Use `provider*N` to spawn N independent instances of the same provider.

```
/trinity glm*3 "Implement three microservices: auth, order, and payment"
```

Auto-generates instance keys like `glm:a3f2b1`, `glm:c7d8e9`, `glm:f0a1b2`. Each gets an independent session.

### Review presets

A preset expands one keyword into a configured provider set, dispatching the same task to each in parallel.

```
/trinity review      "Review the auth module for security issues"
/trinity fast-review "Skim PR #21 for obvious regressions"
/trinity deep-review "Audit the migration plan against COR-1602"
/trinity r           "Same as review, via short alias"
```

Built-in presets (configurable in `~/.claude/trinity.json` under `presets` /
`preset_aliases`):

| Preset | Required providers | Optional providers | Alias |
|--------|--------------------|--------------------|-------|
| `review` | `glm`, `gemini`, `deepseek` | `codex`, `claude-code` | `r` |
| `fast-review` | `glm`, `deepseek` | none | `fr` |
| `deep-review` | `glm`, `gemini`, `deepseek` | `codex`, `claude-code` | `dr` |

Optional providers are only dispatched when discovery marks them usable;
otherwise Trinity warns and continues with the required set.

The Codex-native review adapter (`trinity review`, see
[Codex Compatibility](#codex-compatibility)) ships these presets out of the
box. For Claude Code, presets are recognized by the dispatcher but must be
declared in your `~/.claude/trinity.json` to be used.

### Plan mode

Visualize task assignments as a sequence diagram before dispatching.

**Manual assignment:**
```
/trinity plan glm:auth "Implement auth" glm:order "Implement orders" codex "Review all code"
```

**Auto-decompose** — describe a goal and Trinity assigns tasks to providers:
```
/trinity plan "Build an e-commerce system with auth, orders, and payment"
```

Trinity analyzes the goal, assigns coding tasks to GLM, review tasks to Codex/Gemini, draws the dependency diagram, and asks you to confirm:

```
User    Claude    GLM:auth   GLM:order   Codex
 │        │          │          │          │
 │─plan──▶│          │          │          │
 │        │──auth───▶│          │          │
 │        │──order──────────────▶│         │
 │        │◀──done───│          │          │
 │        │◀──done──────────────│          │
 │        │──review────────────────────────▶│
 │        │◀──result───────────────────────│
 │◀─done──│          │          │          │

[Execute] [Modify] [Cancel]
```

On Execute: parallel tasks dispatch first; sequential tasks dispatch after their dependencies complete.

### Health monitoring

**On-demand heartbeat:**
```
/trinity heartbeat              # check all active agents
/trinity heartbeat glm:auth     # check one specific agent
```

Output:
```
GLM:auth    🔄 alive    +23 lines   [4m 12s]   Bash: pytest tests/ -v
Codex       ⚠️ possibly stalled  +0 lines  [6m 05s]   Read: auth.py:45-80
```

**Proactive updates:** While agents are running, Trinity automatically checks progress each time you send a message (throttled to once per `heartbeat_interval` per agent) and prepends a status line to the response.

**Timeout alerts:**
- `⚠️ warning` at warn threshold (e.g., review > 6 min)
- `🚨 alert` at max threshold (e.g., review > 10 min) with suggested action

Default thresholds (configurable in `~/.claude/trinity.json`):

| Task type | Warn at | Max at |
|-----------|---------|--------|
| tdd       | 10 min  | 15 min |
| review    | 6 min   | 10 min |
| prp       | 5 min   | 8 min  |
| general   | 10 min  | 20 min |

### Session management

**View all providers and sessions:**
```
/trinity status
```

Shows registered providers (✅ usable / ⚠️ misconfigured) and all active sessions with live heartbeat data.

**Clear sessions:**
```
/trinity clear glm:auth     # clear one instance
/trinity clear glm          # clear glm and all glm:* instances
/trinity clear all          # clear everything
```

Sessions persist in `.claude/trinity.json` (project-scoped). Clearing removes the session state; the next dispatch to that provider starts a new session.

---

## Architecture

```
~/.claude/trinity.json          ← global providers, presets, defaults
.claude/trinity.json            ← project sessions + local overrides

~/.claude/skills/trinity/
  SKILL.md                      ← Trinity skill (Claude reads this)
  scripts/                      ← session, config, discover, install helpers
  bin/                          ← deepseek, openrouter, claude-code wrappers

~/.claude/agents/
  trinity-glm.md                ← GLM worker agent
  trinity-minimax.md            ← MiniMax 2.7 worker agent
  trinity-codex.md              ← Codex worker agent
  trinity-gemini.md             ← Gemini worker agent
  trinity-deepseek.md           ← DeepSeek (Anthropic-compat wrapper)
  trinity-openrouter.md         ← OpenRouter (Anthropic-compat wrapper)
  trinity-claude-code.md        ← isolated nested Claude Code
  trinity-<custom>.md           ← your custom providers
```

**Dispatch flow:**
1. `/trinity <provider> "task"` → Trinity skill (SKILL.md) receives the command
2. Provider discovery: loads `~/.claude/trinity.json` + `.claude/trinity.json`, resolves presets/aliases, verifies agent files
3. Spawns `Agent(subagent_type="general-purpose", run_in_background=true)` pointing to `trinity-<provider>.md`
4. Agent reads instructions from its template, invokes the provider's CLI (`droid exec`, `codex exec`, `gemini -p`, or a wrapper from `bin/`), and manages sessions in `.claude/trinity.json`
5. Agent returns a structured summary when done
6. Trinity captures `output_file` path from the Agent response for health monitoring

**Key design decisions:**
- No tmux, no daemons — pure CLI via Claude's Agent tool
- No external dependencies — works anywhere Claude Code runs
- Provider discovery — new providers added without editing SKILL.md
- Config overlay — global defaults + project overrides
- File locking — `fcntl.flock` prevents concurrent write corruption

---

## Adding a Provider

1. **Create an agent file** following the pattern of existing providers:
   ```bash
   cp trinity/providers/glm.md ~/.claude/agents/trinity-myprovider.md
   # Edit: update name, CLI command, session management for your provider's CLI
   ```

2. **Register in config** (`~/.claude/trinity.json` or `.claude/trinity.json`):
   ```json
   {
     "providers": {
       "myprovider": { "cli": "myprovider-cli", "installed": true }
     }
   }
   ```

3. **Test:**
   ```
   /trinity status             # verify provider shows ✅ usable
   /trinity myprovider "hello" # smoke test
   ```

---

## Troubleshooting

**Provider shows "⚠️ unregistered (missing agent file)"**
The config entry exists but no agent file found. Run `/trinity install <provider>` or copy the agent file manually to `~/.claude/agents/trinity-<provider>.md`.

**Provider shows "⚠️ unregistered (missing config)"**
Agent file exists but no config entry. Add the provider to `~/.claude/trinity.json` under `providers`.

**Agent shows "❌ failed to start" after 30s**
The background agent never wrote to its output file. Check that the CLI tool is installed and authenticated. Run `/trinity install <provider>` to re-verify.

**Session resume fails**
If a session ID has expired, the agent automatically discards it and starts fresh. Use `/trinity clear <provider>` to clean up the stale entry.

**Concurrent writes corrupt trinity.json**
Should not happen — agents use `fcntl.flock`. If it does, inspect the file and repair it manually, then run `/trinity clear all` to start fresh.

**`.claude/` directory doesn't exist**
Trinity creates it automatically on first dispatch. If permission errors occur, run:
```bash
mkdir -p .claude && echo '{}' > .claude/trinity.json
```

---

## Related

- `trinity/SKILL.md` — full skill specification
- `trinity/providers/` — built-in provider agent templates
- `trinity/CHANGELOG.md` — full version history

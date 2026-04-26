# Trinity — Multi-Model Orchestration for Claude Code

Dispatch tasks to any LLM (GLM, Codex, Gemini, or your own) from within Claude Code. Providers run in the background via Claude's Agent tool. Sessions persist across turns. Health monitoring tells you if they're alive.

The name comes from 三位一体 — not a fixed count, but a philosophy: all AIs united, working together. Whoever runs Trinity is the Leader. Any external LLM with a CLI is a Member.

---

## Table of Contents

- [If You Are an AI](#if-you-are-an-ai)
- [What Trinity Does](#what-trinity-does)
- [Install](#install)
  - [Step 1: Install the skill](#step-1-install-the-skill)
  - [Step 2: Install providers](#step-2-install-providers)
  - [Step 3: Configure global defaults (optional)](#step-3-configure-global-defaults-optional)
- [Command Reference](#command-reference)
- [Usage Guide](#usage-guide)
  - [Single dispatch](#single-dispatch)
  - [Multi-provider parallel](#multi-provider-parallel)
  - [Named instances](#named-instances)
  - [Parallel same-provider](#parallel-same-provider)
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

This downloads all skill files to `~/.claude/` and registers the five default providers (glm, codex, gemini, openrouter, deepseek) in `~/.claude/trinity.json`. Expected output ends with:

```
Trinity 1.4.0 installed to ~/.claude/
```

If the command fails, check stderr for `trinity-install: failed downloading <file>` — that tells you exactly which file 404'd.

### Step 2: Tell the user to restart Claude Code

Trinity's skill (`SKILL.md`) is loaded by Claude Code at startup. The install takes effect after restart. Tell the user:

> "Trinity is installed. Please restart Claude Code, then run `/trinity status` to confirm all providers are registered."

### Step 3: Verify (after restart)

```
/trinity status
```

Expected output: glm, codex, gemini, openrouter, and deepseek all show ✅ usable. If any show ⚠️, run `/trinity install <provider>` to repair.

### What was installed

| Location | Contents |
|----------|----------|
| `~/.claude/skills/trinity/SKILL.md` | Trinity skill — loaded by Claude Code |
| `~/.claude/skills/trinity/scripts/` | Python session/config/discover/install scripts |
| `~/.claude/agents/trinity-glm.md` | GLM worker agent |
| `~/.claude/agents/trinity-codex.md` | Codex worker agent |
| `~/.claude/agents/trinity-gemini.md` | Gemini worker agent |
| `~/.claude/agents/trinity-openrouter.md` | OpenRouter worker agent |
| `~/.claude/agents/trinity-deepseek.md` | DeepSeek V4 worker agent |
| `~/.claude/trinity.json` | Global provider registry |

---

## What Trinity Does

- **Dispatch** tasks to external LLMs running in the background — you keep working while they run
- **Session continuity** — each provider instance remembers its conversation across calls
- **Provider auto-discovery** — add new providers by dropping a config entry + agent file; no skill editing required
- **Health monitoring** — heartbeat checks tell you if agents are alive, stalled, or timed out
- **Install command** — `/trinity install codex` sets up the CLI, agent file, config, and smoke test in one step
- **Plan mode** — draw a sequence diagram, confirm, then auto-dispatch in dependency order

---

## Install

### Step 1: Install the skill

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
```

This downloads all skill files directly to `~/.claude/` — no git clone required. To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=1.1.0 bash
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

**Wrapper-based providers** (`openrouter`, `deepseek`) don't have a package install path — they use the `claude` binary pointed at an Anthropic-compatible endpoint via small POSIX shell wrappers shipped in `providers/bin/` and installed to `~/.claude/skills/trinity/bin/`. `install.sh` and `make install` set them up automatically; no `~/.zshrc` edits required.

Each wrapper expects an API key, in this order of precedence:
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

# OpenRouter
cp trinity/providers/openrouter.md ~/.claude/agents/trinity-openrouter.md

# DeepSeek V4
cp trinity/providers/deepseek.md ~/.claude/agents/trinity-deepseek.md
```

Then create `~/.claude/trinity.json`:
```json
{
  "providers": {
    "codex":      { "cli": "codex exec --skip-git-repo-check", "installed": true },
    "gemini":     { "cli": "gemini -p",                        "installed": true },
    "glm":        { "cli": "droid exec --model glm-5",         "installed": true },
    "openrouter": { "cli": "/Users/<you>/.claude/skills/trinity/bin/openrouter -p", "installed": true },
    "deepseek":   { "cli": "/Users/<you>/.claude/skills/trinity/bin/deepseek -p",   "installed": true }
  },
  "defaults": {
    "heartbeat_interval": 120,
    "timeout": { "tdd": 600, "review": 360, "general": 1200 }
  }
}
```

### Step 3: Configure global defaults (optional)

Edit `~/.claude/trinity.json` to set your preferred heartbeat interval and timeout thresholds. Per-project overrides go in `.claude/trinity.json` at the project root.

---

## Command Reference

```
/trinity <provider>[:<instance>] "task"          # single dispatch
/trinity <p1>[:<i>] "t1" <p2> "t2"              # multi-provider parallel
/trinity <provider>*N "task"                     # N parallel same-provider
/trinity plan <p1> "t1" <p2> "t2"               # plan with diagram, confirm, execute
/trinity plan "high-level description"           # auto-decompose, confirm, execute
/trinity install <provider>                      # install + register provider
/trinity status                                  # registered providers + active sessions
/trinity heartbeat [<instance>]                  # on-demand liveness check
/trinity clear [<instance> | all]                # clear sessions
/trinity help                                    # show this README
```

Reserved words (not provider names): `status`, `clear`, `plan`, `heartbeat`, `install`, `help`

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
~/.claude/trinity.json          ← global providers + defaults
.claude/trinity.json            ← project sessions + local overrides

~/.claude/skills/trinity/
  SKILL.md                      ← Trinity skill (Claude reads this)

~/.claude/agents/
  trinity-glm.md                ← GLM worker agent
  trinity-codex.md              ← Codex worker agent
  trinity-gemini.md             ← Gemini worker agent
  trinity-<custom>.md           ← your custom providers
```

**Dispatch flow:**
1. `/trinity glm "task"` → Trinity skill (SKILL.md) receives the command
2. Provider discovery: loads `~/.claude/trinity.json` + `.claude/trinity.json`, verifies agent files
3. Spawns `Agent(subagent_type="general-purpose", run_in_background=true)` pointing to `trinity-glm.md`
4. Agent reads instructions from `trinity-glm.md`, calls `droid exec`, manages sessions in `.claude/trinity.json`
5. Agent returns structured summary when done
6. Trinity captures `output_file` path from Agent response for health monitoring

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

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
- [Documentation](#documentation)
- [Contributing](#contributing)

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
Trinity 3.3.0 installed to ~/.claude/
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
| `~/.claude/agents/trinity-minimax.md` | MiniMax M3 worker agent |
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, test and lint commands,
branch naming, PR expectations, and the release preparation flow.

---

## Install

### Step 1: Install the skill

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
```

This downloads all skill files directly to `~/.claude/` — no git clone required. To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=3.3.0 bash
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

# MiniMax M3
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
    "glm":        { "cli": "droid exec --auto medium --model custom:GLM-5.2", "installed": true },
    "minimax":    { "cli": "droid exec --auto medium --model custom:MiniMax-M3", "installed": true },
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

> **BYOK prerequisite for `glm` and `minimax`.** Both use droid `custom:` models
> (`custom:GLM-5.2`, `custom:MiniMax-M3`), which are **not** in droid's built-in
> catalog. Each requires a matching entry in `~/.factory/settings.json` →
> `customModels` with an **explicit** `id` equal to the value after `--model`
> (without it droid auto-generates an indexed id and dispatch fails). A complete
> entry needs all of `id`, `model`, `baseUrl`, `apiKey`, and `provider` — the
> installer warning only checks `id`, so an entry missing `apiKey`/`provider`
> silences the warning but still fails at dispatch. Example for GLM-5.2 (Z.AI):
> ```json
> {
>   "id": "custom:GLM-5.2",
>   "model": "glm-5.2",
>   "baseUrl": "https://api.z.ai/api/coding/paas/v4",
>   "apiKey": "<your Z.AI coding-plan API key>",
>   "provider": "generic-chat-completion-api"
> }
> ```
> (`custom:MiniMax-M3` is analogous: `baseUrl` `https://api.minimaxi.com/anthropic`,
> `provider` `anthropic`, its own `apiKey`.) The `make install` / `make install-codex`
> installers emit a warning when the `id` is missing; the manual path above does not,
> so add the full entry before first dispatch.

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

## Documentation

- [Command Reference](docs/command-reference.md) — all `/trinity` subcommands at a glance
- [Usage Guide](docs/usage-guide.md) — single dispatch, multi-provider parallel, named instances, review presets, plan mode, health monitoring, session management
- [Codex Compatibility](docs/codex-compatibility.md) — terminal `trinity review`, doctor health checks, live probes, PR update workflow, repo-local skill and plugin
- [Architecture](docs/architecture.md) — file layout, dispatch flow, key design decisions
- [Adding a Provider](docs/adding-a-provider.md) — create an agent file, register in config, test
- [Troubleshooting](docs/troubleshooting.md) — common issues and solutions

---

## Related

- `trinity/SKILL.md` — full skill specification
- `trinity/providers/` — built-in provider agent templates
- `trinity/CHANGELOG.md` — full version history

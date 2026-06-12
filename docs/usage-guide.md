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
[Codex Compatibility](codex-compatibility.md)) ships these presets out of the
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

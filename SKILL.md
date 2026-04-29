---
name: trinity
description: Multi-model orchestration skill. Dispatch tasks to any LLM provider via background sub-agents with auto-discovery, config overlay, session management, and health monitoring. Use when the user says /trinity or wants to delegate work to another model.
metadata:
  short-description: Trinity — Multi-model orchestration
---

# Trinity — Multi-Model Orchestration

Dispatch tasks to external LLM providers via background sub-agents. Providers are auto-discovered from config + agent files. Sessions stored in `.claude/trinity.json`. Health monitoring via output file heartbeat.

## Startup Check (run once per session before first dispatch)

```bash
# 1. Verify python3 is available
command -v python3 >/dev/null 2>&1 || {
  echo "trinity: python3 not found. Install: brew install python3"
  # abort dispatch
}

# 2. Verify scripts are installed and up to date
SCRIPTS_VERSION=$(python3 ~/.claude/skills/trinity/scripts/session.py --version 2>/dev/null)
REQUIRED_VERSION="3.0.0"
if [ "$SCRIPTS_VERSION" != "$REQUIRED_VERSION" ]; then
  echo "trinity: scripts not installed or outdated (found: ${SCRIPTS_VERSION:-none}, need: $REQUIRED_VERSION)"
  echo "Run: make install (from trinity/ repo) or: cp -r trinity/scripts/. ~/.claude/skills/trinity/scripts/"
  # abort dispatch
fi
```

If scripts pass the version check, proceed normally.

## Syntax

```
/trinity <provider>[:<instance>] "task"          # single dispatch
/trinity <p1>[:<i>] "t1" <p2> "t2"              # multi-provider parallel
/trinity <provider>*N "task"                     # N parallel same-provider
/trinity plan <p1> "t1" <p2> "t2"               # plan with diagram, confirm, execute
/trinity plan "high-level description"           # auto-decompose, confirm, execute
/trinity install <provider>                      # install + register provider
/trinity status                                  # sessions + live activity
/trinity heartbeat [<instance>]                  # on-demand liveness check
/trinity clear [<instance> | all]                # clear sessions
/trinity help                                    # show README
```

## Provider Discovery

On every dispatch, resolve available providers:
1. Load `~/.claude/trinity.json` → `providers` map (global)
2. Load `.claude/trinity.json` → `providers` map (project); project entries win on conflict
3. Verify each provider has a matching agent file: `~/.claude/agents/trinity-<name>.md` or `.claude/agents/trinity-<name>.md`

A provider is **usable** only when it has both a config entry AND an agent file.
- Config entry but no agent file → "⚠️ unregistered (missing agent file)" in `/trinity status`; dispatch blocked
- Agent file but no config entry → "⚠️ unregistered (missing config)" in `/trinity status`; dispatch blocked
- Neither → not listed

## Config Overlay

**Merge semantics:**
- `providers`: merged by key; project entry wins on same key. Global providers not overridden remain available.
- `defaults`: shallow merge; project value overrides global for each key. Keys absent in project inherit from global.
- `sessions`: project-only; never in global config.

**Global** `~/.claude/trinity.json`:
```json
{
  "providers": {
    "glm":    { "cli": "droid exec --model glm-5",         "installed": true },
    "codex":  { "cli": "codex exec --skip-git-repo-check", "installed": true },
    "gemini": { "cli": "gemini -p",                        "installed": true }
  },
  "defaults": {
    "heartbeat_interval": 120,
    "timeout": { "tdd": 600, "review": 360, "general": 1200 }
  }
}
```

**Project** `.claude/trinity.json`:
```json
{
  "providers": {
    "local": { "cli": "ollama run llama3", "installed": true }
  },
  "sessions": {
    "glm:auth": {
      "session_id": "...",
      "output_file": "/private/tmp/claude-501/.../tasks/<agentId>.output",
      "start_time": "2026-03-21T01:00:00",
      "task_type": "tdd",
      "last_line_count": null,
      "last_heartbeat": null,
      "stopped": false,
      "last_used": "2026-03-21T01:00:00",
      "task_summary": "JWT auth module"
    }
  }
}
```

Field notes:
- `output_file`: captured from Agent tool response text at dispatch (line matching `output_file: /...`). Cleared when task-notification arrives.
- `last_line_count`: `null` = never checked; integer = JSONL line count at last heartbeat.
- `last_heartbeat`: ISO timestamp of last check. Written back immediately after every heartbeat.
- `stopped`: `true` when stopped. Distinguishes ⏸️ stopped from ❌ failed.
- `task_type`: one of `tdd`, `review`, `prp`, `general`. Used for timeout thresholds.

## Execution Rules

### Dispatch mode (provider detected)

For EACH (provider, task) pair in the arguments:

1. **Parse** — extract base provider and optional instance name
   - `glm` → base=glm, instance=none (key: "glm")
   - `glm:auth` → base=glm, instance=auth (key: "glm:auth")
   - `glm*2` → spawn 2 agents: key "glm:<uuid4-short>" each

2. **Resolve providers** — run provider discovery (see §Provider Discovery)

3. **Validate** — verify provider is usable (has both config entry and agent file)
   - If not usable: report error with reason ("missing agent file" / "missing config"), do NOT spawn

4. **Spawn** — for each validated (provider, task):
   ```
   Agent(
     subagent_type="general-purpose",
     description="{PROVIDER}: {short task description}",
     name="{PROVIDER-INSTANCE}",
     run_in_background=true,
     prompt="""
     You are the trinity-{base} worker agent.
     Read your instructions from ~/.claude/agents/trinity-{base}.md first.
     (Or from .claude/agents/trinity-{base}.md if present in the project.)

     Then execute this task:

     - Provider instance: {key}
     - Project dir: {cwd}
     - Task: {task}
     """
   )
   ```

5. **Capture output_file** — from the Agent tool response text, extract the line matching `output_file: /...`. Record dispatch metadata in `.claude/trinity.json` under `sessions.<key>`:
   ```json
   {
     "session_id": null,
     "output_file": "<captured path>",
     "start_time": "<ISO now>",
     "task_type": "<inferred: tdd|review|prp|general>",
     "last_line_count": null,
     "last_heartbeat": null,
     "stopped": false,
     "last_used": "<ISO now>",
     "task_summary": "<short task description>"
   }
   ```
   Infer `task_type` from task keywords: "review"/"审查" → `review`; "tdd"/"test"/"测试" → `tdd`; "prp"/"proposal" → `prp`; otherwise → `general`.

6. **Confirm** — reply with a brief launch summary:
   ```
   Dispatched:
   - GLM:auth → "实现认证模块" (background)
   - Codex → "review auth 代码" (background)
   ```

7. **On completion** — when task-notification arrives, present the agent's summary to the user, then clear `output_file`, `last_line_count`, `last_heartbeat` from that session entry (keep `session_id` for future resume).

### Proactive progress updates (always active)

**On every user message while any agent has `output_file` set and `stopped: false`:**

Load `heartbeat_interval` from merged config (default: 120s). For each such agent, check if `last_heartbeat` is null OR ≥`heartbeat_interval` seconds have elapsed. If so, run a heartbeat check and prepend results to the response.

This is message-triggered with throttling — not a background timer.

Also check timeout thresholds (§C) on every proactive check.

### Heartbeat mode (`/trinity heartbeat [<instance>]`)

On-demand liveness check. If `<instance>` given, check only that entry; otherwise check all entries with `output_file` set and `stopped: false`.

For each agent to check:

1. **Read output file:**
   ```bash
   wc -l <output_file>           # total JSONL line count
   tail -10 <output_file>        # last 10 lines for parsing
   ```

2. **Handle missing file:**
   - File absent, elapsed < 30s → "🟡 starting"
   - File absent, elapsed ≥ 30s → "❌ failed to start"
   - File present but empty → "🟡 starting (0 lines)"

3. **Parse last activity** from tail output (skip malformed/partial lines):
   - Find last line with `type: "assistant"` → extract text or tool name + input summary
   - Find last line with `type: "user"` and `tool_result` → extract result preview

4. **Liveness signal:**
   - `current_lines > last_line_count` (or last_line_count was null) → "🔄 alive (+N lines)"
   - `current_lines == last_line_count` and elapsed since dispatch > 60s → "⚠️ possibly stalled (no new lines)"
   - Zero delta can be a false positive during long reasoning — report "possibly stalled", not "stuck"

5. **Update `.claude/trinity.json`:** write `last_line_count = current_lines`, `last_heartbeat = now` atomically (fcntl.flock on the project sessions file).

6. **Display:**
   ```
   GLM:auth    🔄 alive    +23 lines   [4m 12s]   Bash: pytest tests/test_auth.py -v
   Codex       ⚠️ possibly stalled  +0 lines  [6m 05s]   Read: auth.py (line 45-80)
   Gemini      ✅ done      —          [2m 10s]   —
   ```

### Timeout alerts (§C)

Load thresholds from merged config `defaults.timeout`. Built-in defaults:

| task_type | warn_at | max_at |
|-----------|---------|--------|
| tdd       | 10 min  | 15 min |
| review    | 6 min   | 10 min |
| prp       | 5 min   | 8 min  |
| general   | 10 min  | 20 min |

On each proactive check or heartbeat, compare `now - start_time` against thresholds:
- At warn_at: `⚠️ GLM:auth review 已跑 6 分钟（预期 <4 分钟）— 最后活动: Read auth.py (2 分钟前)`
- At max_at: `🚨 GLM:auth review 已跑 10 分钟（已超时）— 建议: /trinity clear glm:auth 或继续等待`

### Status mode (`/trinity status`)

Run provider discovery. Display two sections:

**Registered providers:**
```
| Provider | Status    | CLI                              |
|----------|-----------|----------------------------------|
| glm      | ✅ usable  | droid exec --model glm-5         |
| codex    | ✅ usable  | codex exec --skip-git-repo-check |
| gemini   | ⚠️ missing | (agent file not found)           |
```

**Active sessions** (run heartbeat check for each with `output_file` set):
```
| Provider | State         | Duration | Last Activity            | Task            |
|----------|---------------|----------|--------------------------|-----------------|
| glm:auth | 🔄 alive +12  | 4m 12s   | Bash: pytest -v          | TDD auth module |
| codex    | ⚠️ stalled +0  | 6m 05s   | Read: auth.py:45         | Review auth     |
```

If no sessions, show "No active sessions."

### Clear mode (`/trinity clear`)

Synchronous. Operates on `.claude/trinity.json` `sessions` key.

- `/trinity clear glm:auth` → delete "glm:auth" entry, confirm
- `/trinity clear glm` → delete "glm" and all "glm:*" entries, confirm
- `/trinity clear all` → write `{}` to sessions key, confirm

### Parallel mode (`/trinity glm*2 "task"`)

Parse `glm*2` as: spawn 2 agents with base=glm.
Auto-generate instance keys:
```python
import uuid
key = f"glm:{uuid.uuid4().hex[:6]}"
```
Each agent gets its own instance key and independent session.

### Install mode (`/trinity install <provider>`)

**Flow (atomic — all steps must succeed or roll back):**

1. Check `which <provider-cli>` → already in PATH → skip to step 4
2. Try Homebrew: `brew search <provider>` → formula found → `brew install <formula>` → on failure fall through
3. Try npm: `npm install -g <npm-package>` → on failure try pip (glm only) → on all failures: report ❌ + manual install link, abort
4. Copy agent template: `trinity/providers/<provider>.md` → `~/.claude/agents/trinity-<provider>.md`
5. Register in `~/.claude/trinity.json` under `providers.<provider>` (atomic write: read → merge → write)
6. Smoke test (Bash timeout 30s): `<cli> "Reply with exactly: trinity-ok"` → verify response contains `trinity-ok`
7. **On any failure in steps 4–6:** delete `~/.claude/agents/trinity-<provider>.md` if created, remove `providers.<provider>` from config if written, report ❌ with specific step that failed
8. Report ✅ `<provider> installed and verified`

**Built-in install specs:**

| Provider | brew | npm | pip | Prerequisite |
|----------|------|-----|-----|--------------|
| codex  | `brew install codex`* | `npm i -g @openai/codex`      | —                      | OpenAI account    |
| gemini | `brew install gemini-cli`* | `npm i -g @google/gemini-cli` | —             | Google account    |
| glm    | —                     | —                             | `pip install factory-droid` | Factory AI account |

*Brew formula name verified at runtime via `brew search`; if no result or install fails, fall through to npm/pip.

### Plan mode (`/trinity plan`)

Two input modes:

**Manual assignment** — user specifies providers and tasks:
```
/trinity plan glm:auth "实现认证" glm:order "实现订单" codex "review 全部代码"
```

**Auto-decompose** — single string description (no provider specified):
```
/trinity plan "实现电商系统，需要认证、订单、支付三个模块"
```

**Auto-decompose algorithm:**
1. Analyze the description and identify independent sub-tasks
2. Assign each sub-task to a provider based on task type (coding → glm, review → codex/gemini, analysis → any)
3. Identify dependencies (review waits for coding; independent tasks run in parallel)
4. Draw ASCII sequence diagram showing assignment and dependency order
5. Ask user to confirm ([Execute] / [Modify] / [Cancel]) via AskUserQuestion
6. On Execute: dispatch parallel tasks first, then sequential tasks after notifications arrive

**Sequence diagram format:**
```
User    Claude    GLM:auth   GLM:order   Codex
 │        │          │          │          │
 │─plan──▶│          │          │          │
 │        │──auth───▶│          │          │
 │        │──order──────────────▶│         │
 │        │          │          │          │
 │        │◀──done───│          │          │
 │        │◀──done──────────────│          │
 │        │──review────────────────────────▶│
 │        │◀──result───────────────────────│
 │◀─done──│          │          │          │
```

### Help mode (`/trinity help`)

Synchronous. Read `~/.claude/skills/trinity/README.md` and output its full content.

## Error Handling

- Unknown provider → run provider discovery, report "Unknown provider: xxx. Available: <usable list>. Run `/trinity install xxx` to add it."
- Usable providers list empty → "No providers registered. Run `/trinity install <provider>` to get started."
- Missing agent file → "Provider xxx has no agent file. Run `/trinity install xxx` to set it up."
- Missing config entry → "Provider xxx has no config entry. Run `/trinity install xxx` to register it."
- Empty task → "Task cannot be empty"
- `.claude/` doesn't exist → create it with empty `trinity.json`
- `trinity.json` doesn't exist → create with `{}` before first write
- output_file capture fails → log warning, proceed without monitoring for that agent

## Reserved Words

`status`, `clear`, `plan`, `heartbeat`, `install`, and `help` are subcommands, NOT provider names.

## Examples

```
/trinity glm "实现用户认证模块"
/trinity glm:auth "实现认证" codex "review 认证代码"
/trinity glm*2 "分别实现 auth 和 order 模块"
/trinity plan glm:auth "认证" glm:order "订单" codex "review"
/trinity plan "实现电商系统"
/trinity install codex
/trinity install gemini
/trinity status
/trinity heartbeat
/trinity heartbeat glm:auth
/trinity clear glm:auth
/trinity clear all
```

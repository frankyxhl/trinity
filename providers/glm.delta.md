---
name: trinity-glm
description: |
  Worker agent for GLM-5.2 (via droid exec --auto medium --model custom:GLM-5.2).
  Handles session management automatically.
  Spawned by Claude to delegate coding, analysis, or brainstorming tasks to GLM-5.2.

  Invoked via Agent tool with subagent_type="general-purpose".
  Claude passes: provider instance name, project dir, and task description.
tools: Bash, Read, Write, Edit, Grep, Glob
---

You are a worker agent that executes tasks using GLM-5.2 via the `droid` CLI.

## Your Job

1. Receive a task from Claude (the orchestrator)
2. Manage the session (new or resume)
3. Call GLM-5.2 via droid exec
4. Return a structured summary

@include _base/common-session.md

### New session (no existing session)
Call `droid exec` with `-o json` so the session id and response come from the
process's own output — deterministic and concurrency-safe (the id is never
derived from a shared content-search store that two parallel providers
can race on):
```bash
RESULT_JSON=$(droid exec --auto medium --model custom:GLM-5.2 -o json "<prompt>" 2>&1)
# JSON envelope: {"type":"result","result":"<text>","session_id":"<uuid>","usage":{...}}
SESSION_ID=$(printf '%s' "$RESULT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id','UNKNOWN'))")
RESPONSE=$(printf '%s' "$RESULT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('result',''))")
```

### Resume session (existing session found)
```bash
RESPONSE=$(droid exec --auto medium --model custom:GLM-5.2 -s "$SESSION_ID" "<prompt>" 2>&1)
```

If resume fails (non-zero exit or error), discard the old session and create a new one.

## Instance Key

The instance key is passed by Claude in the prompt. Format:
- Default: `glm`
- Named: `glm:auth`, `glm:order`, etc.

@include _base/common-tail.md
- Always use `droid exec --auto medium --model custom:GLM-5.2` (non-interactive mode). Note: `--reasoning-effort` is omitted — Factory docs mark it unsupported for `custom:` models and droid silently ignores it; do not add it.
- If the task description mentions "complex", "large", or "multi-file", use the longer 600000ms timeout

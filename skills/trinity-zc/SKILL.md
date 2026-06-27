---
name: trinity-zc
description: Multi-model orchestration for the ZCode runtime — a runtime-adapted peer of trinity. Dispatches tasks to external LLM providers via Bash background processes (not Agent sub-agents), with a self-managed state machine, provider health checks, and reuse of trinity's provider config, session resume pointers, and review synthesis. Use when the user says /trinity-zc or wants to delegate work to another model from the ZCode runtime.
metadata:
  short-description: trinity-zc — ZCode-optimized multi-model dispatch
  peer-of: trinity
  runtime: zcode
---

# trinity-zc — Multi-Model Orchestration for the ZCode Runtime

Dispatch tasks to external LLM providers via **Bash background processes** with a
self-managed state machine. Reuses trinity's provider configuration, session-resume
pointers, and review-synthesis pipeline, but replaces trinity's Agent-sub-agent dispatch
layer (unreachable in this runtime) with `Bash(run_in_background=true)`.

## Why this skill exists (honest capability statement)

trinity (the `~/.claude/skills/trinity/` skill) dispatches by spawning `Agent(subagent_type="general-purpose", run_in_background=true)` sub-agents. **In the ZCode runtime the `Agent` tool only exposes the read-only `Explore` subagent type** — `general-purpose` background sub-agents cannot be spawned. trinity's native dispatch is therefore unreachable here.

trinity-zc is an honest adaptation: it reaches the same provider backends directly via Bash, and reuses trinity's Python assets for everything that *is* reachable. It is **not** a drop-in replacement for trinity in Claude Code — both skills coexist. Use trinity in Claude Code; use trinity-zc in the ZCode runtime.

## What is reused vs self-built

| Capability | Source |
|------------|--------|
| Provider config + CLI strings | **Reused** — merged `~/.claude/trinity.json` + project `.claude/trinity.json` (identical merge to trinity) |
| Session resume pointers | **Reused** — `~/.claude/skills/trinity/scripts/session.py` (`read`/`write`/`clear`/`heartbeat` CLI) |
| Review synthesis (`synthesis.md`) | **Reused** — `_review.write_synthesis()` via `python3 -c` |
| Structured review parsing (TRN-3022) | **Reused** — `review_schema.parse_structured_review()` |
| Background dispatch execution | **Self-built** — `Bash(run_in_background=true)` (harness isolates the process; no `setsid` needed — it doesn't exist on macOS) |
| Dispatch state machine | **Self-built** — `.claude/trinity-zc.json` (separate file, see §State Store) |
| Heartbeat / timeout | **Self-built** — output-file byte count + time comparison |

## Startup Check (run once per session before first dispatch)

```bash
# 1. python3 present
command -v python3 >/dev/null 2>&1 || { echo "trinity-zc: python3 not found"; exit 1; }

# 2. trinity scripts installed + version (reuse trinity's gate — same scripts)
SCRIPTS_VERSION=$(python3 ~/.claude/skills/trinity/scripts/session.py --version 2>/dev/null)
[ "$SCRIPTS_VERSION" = "3.3.0" ] || {
  echo "trinity-zc: trinity scripts missing/outdated (found ${SCRIPTS_VERSION:-none}, need 3.3.0)"
  echo "Run: make install (trinity repo) or cp -r trinity/scripts/. ~/.claude/skills/trinity/scripts/"
  exit 1
}

# 3. no nested-dispatch guard leak
[ "${TRINITY_DISABLE_DISPATCH:-}" = "1" ] && { echo "trinity-zc: nested dispatch disabled"; exit 1; }
```

If all three pass, proceed.

## Syntax

```
/trinity-zc <provider>[:instance] "task" [provider2 "task2" ...]   # dispatch (background)
/trinity-zc <provider>*N "task"                                      # N parallel same-provider
/trinity-zc review|fast-review|deep-review "task"                    # preset dispatch
/trinity-zc status                                                   # all sessions + provider health
/trinity-zc heartbeat [instance]                                     # on-demand liveness check
/trinity-zc clear [<instance> | all]                                 # remove session entries
/trinity-zc result <instance>                                        # read a finished provider's output
/trinity-zc doctor                                                   # smoke-test all providers
/trinity-zc help
```

## Provider Discovery

On every dispatch and status call, resolve usable providers exactly as trinity does:

1. Load global config `~/.claude/trinity.json` → `providers`, `presets`, `preset_aliases`.
2. Load project overlay `<cwd>/.claude/trinity.json` → project entries **win** on key conflict for `providers`; `presets` replace whole object; `defaults` shallow-merge.
3. For each config provider, verify a matching agent file exists: `~/.claude/agents/trinity-<name>.md` **or** `<cwd>/.claude/agents/trinity-<name>.md`.

A provider is **usable** only with BOTH a config entry AND an agent file. `registry.json` is NOT read at runtime (install-time artifact only) — ignore it. All CLI strings come from the merged config's `providers.<name>.cli`.

Read the merged config with inline Python (no trinity dependency needed beyond json+flock):

```python
import json, os
def load(p):
    try:
        with open(p) as f: return json.load(f)
    except FileNotFoundError: return {}
g = load(os.path.expanduser("~/.claude/trinity.json"))
proj = load(os.path.join(os.getcwd(), ".claude/trinity.json"))
providers = {**g.get("providers",{}), **proj.get("providers",{})}
presets = {**g.get("presets",{}), **proj.get("presets",{})}
```

## Presets

Expand a preset keyword to its provider list (from merged config `presets.<name>.providers`; built-in defaults below if absent). Optional providers are included only when discovery marks them usable.

| Preset | Required | Optional |
|--------|----------|----------|
| `review` | minimax, glm, deepseek | — |
| `fast-review` | glm, deepseek | — |
| `deep-review` | codex, glm, deepseek | — |

(Defaults reflect provider config after gemini/openrouter/claude-code were retired from `~/.claude/trinity.json`. Always read live presets from the merged config — these are fallbacks only.)

## Dispatch Protocol

Parse tokens left-to-right:
1. Built-in subcommand first: `status`, `clear`, `heartbeat`, `result`, `doctor`, `help`.
2. Preset/alias name (`review`/`fast-review`/`deep-review`/`r`/`fr`/`dr`) → expand to providers, dispatch the SAME task to each.
3. Provider syntax: `provider`, `provider:instance`, or `provider*N`.

### For EACH (provider, task) pair:

**1. Parse + validate.** Base provider + optional instance (key = `provider` or `provider:instance`). `provider*N` → N instances with keys `provider:<uuid4-hex-6>`. Verify provider is usable (config + agent file). If not usable, report the reason ("missing agent file" / "missing config") and DO NOT spawn.

**2. Resolve resume pointer.** Query trinity's session store (reused):
```bash
SESSION_ID=$(python3 ~/.claude/skills/trinity/scripts/session.py read "$PWD" "$INSTANCE_KEY")
# prints a session_id, or "NEW"
```

**3. Allocate output file.**
```bash
RUN_DIR="/tmp/trinity-zc/$(uuidgen | cut -c1-8)"
mkdir -p "$RUN_DIR"
OUTPUT_FILE="$RUN_DIR/${INSTANCE_KEY//[:\/]/-}.out"
```

**4. Build the command.** Read `cli` from merged config; expand `~` and `$HOME`. If resume pointer != NEW and the provider supports resume, append the resume flag:
- droid-backed (glm/minimax): `<cli> -s "$SESSION_ID"`
- deepseek wrapper: `<cli> -r` (session resume is wrapper-managed)
- codex: `<cli>` (codex resume is experimental/session-scoped; omit unless explicitly requested)
- others: no resume arg

**5. Spawn via Bash background.** Use `Bash(run_in_background=true)`. The harness's background mode already provides process isolation — do NOT add a trailing `&` inside the block: that double-backgrounds the provider (the harness-tracked shell exits immediately after launch while the provider runs on as an untracked orphan, so the completion notification fires on launch rather than on provider completion). Likewise do NOT wrap in `setsid` (it does not exist on macOS/BSD). Pass `OUTPUT_FILE` via environment, **sanitize the environment before invoking the provider**, capture both streams with a sentinel separator, and record the return code:

```bash
OUTPUT_FILE="<run_dir>/<instance>.out"
export OUTPUT_FILE
# Sanitize the environment (mirror provider_runtime.build_provider_env):
# strip *_BASE_URL, *_API_BASE, *_API_HOST, OTEL_*, TRINITY_DISABLE_DISPATCH, TRINITY_MCP_TOKEN.
# Use env+sed discovery (portable across bash 3.2+/zsh) rather than ${!pat@} indirect
# expansion, which is bash 4+ only and fails on macOS default /bin/bash.
for v in $(env | sed -n 's/^\([A-Z_]*BASE_URL\)=.*/\1/p; s/^\([A-Z_]*API_BASE\)=.*/\1/p; s/^\([A-Z_]*API_HOST\)=.*/\1/p; s/^\(OTEL_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
unset TRINITY_DISABLE_DISPATCH TRINITY_MCP_TOKEN
# Run the provider in the FOREGROUND of this already-backgrounded shell:
bash -c '
  STDOUT=$("$@" 2>"$OUTPUT_FILE.err"); RC=$?
  STDERR=$(cat "$OUTPUT_FILE.err" 2>/dev/null); rm -f "$OUTPUT_FILE.err"
  printf "%s\n%%%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%%%\n%s\n" "$STDOUT" "$STDERR" > "$OUTPUT_FILE"
  echo "$RC" > "$OUTPUT_FILE.rc"
' _ <cli-and-args...>
```

Note on the sentinel escaping: the literal sentinel is `%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%` (it contains double-percent signs). Inside a `printf` format string, every literal `%` must be written as `%%`, so the sentinel appears as `%%%%...%%%%` in the format — four percents at each end produce the two literal percents the sentinel requires. Getting this wrong produces a file the synthesis parser cannot split.

Because the provider runs in the foreground of the harness-backgrounded shell, the harness tracks the provider's lifetime directly — there is no separate wrapper PID to record, and no `$!` to capture. Process cleanup on timeout is handled by the harness killing the backgrounded Bash (which cascades to its foreground child).

**Streaming caveat (heartbeat):** the wrapper above buffers all stdout in `STDOUT` and writes `OUTPUT_FILE` only after the provider exits. For providers that run longer than the first heartbeat interval, this means `OUTPUT_FILE` does not exist (or is empty) mid-run, so the byte-delta heartbeat (§Heartbeat) will report `🟡 starting` / `failed to start` for a healthy long-running review. Two mitigations: (a) treat "no output file yet + elapsed < task-type timeout" as `🔄 running (no output yet)`, not `failed`; (b) for long review tasks, prefer streaming output directly to the file with `> "$OUTPUT_FILE"` (appending the sentinel in a `trap` on EXIT) so byte deltas are observable. The buffered form here is simplest and correct for the completion path; the streaming form is a drop-in when liveness visibility matters.

The sentinel `%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%` MUST match `provider_runtime.raw_output` so `parse_structured_review` can split stdout/stderr back apart. **Do not alter this string.**

**Environment sanitization** (mirror `provider_runtime.build_provider_env`): keep only `PATH, HOME, USER, LOGNAME, LANG, TERM, SHELL, TZ, TMPDIR, XDG_*, SSH_AUTH_SOCK, HTTP(S)_PROXY, NO_PROXY, PWD, LC_*, GIT_*`. Strip `*_BASE_URL`, `*_API_BASE`, `*_API_HOST`, `OTEL_*`, `TRINITY_DISABLE_DISPATCH`, `TRINITY_MCP_TOKEN`.

**6. Record dispatch state** in `.claude/trinity-zc.json` (see §State Store). State = `running`.

**7. Reply with a launch summary.** List each dispatched instance, its task, output file, and the background process marker. Do NOT block waiting for results — the harness re-invokes you when the background process exits.

### On background-completion notification

When the harness notifies that a background Bash finished:
1. Read `$OUTPUT_FILE` and `$OUTPUT_FILE.rc`.
2. Update the session entry: `state` = `done` (rc 0) or `failed` (rc != 0), set `end_time`, `returncode`, `bytes`.
3. If `task_type == review`: parse TRN-3022 structured output via reused `review_schema.parse_structured_review` and present decision/score/blocking findings to the user.
4. Otherwise present a focused summary (not the full raw log).
5. Optionally write the resume pointer for future runs:
   ```bash
   python3 ~/.claude/skills/trinity/scripts/session.py write "$PWD" "$INSTANCE_KEY" "$SESSION_ID" "<task_summary>"
   ```
   (Session ID capture is provider-specific — droid exposes it via `droid search`; for others leave NEW. Resume is best-effort.)

## State Store (`.claude/trinity-zc.json`)

Separate file from trinity's `.claude/trinity.json` to avoid schema collision (trinity flocks its data file and expects a specific `sessions` shape; our richer fields would corrupt its reads).

```json
{
  "sessions": {
    "glm": {
      "provider": "glm",
      "instance": "glm",
      "task": "review FXA-2100 dispatch",
      "task_type": "review",
      "state": "running",
      "cli": "droid exec --auto medium --model custom:GLM-5.2",
      "output_file": "/tmp/trinity-zc/a1b2c3d4/glm.out",
      "start_time": "2026-06-27T20:30:00",
      "end_time": null,
      "returncode": null,
      "last_checked": null,
      "bytes": 0
    }
  }
}
```

States: `running` → `done` | `failed` | `timeout`.

**Atomic writes** (match `session.py:cmd_write` locking): use `fcntl.flock(LOCK_EX)` on the data file itself — open `O_RDWR|O_CREAT`, flock, read+mutate+truncate+rewrite, unlock. Inline Python:

```python
import json, os, fcntl
path = os.path.join(os.getcwd(), ".claude", "trinity-zc.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
with os.fdopen(fd, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    f.seek(0); data = json.loads(f.read() or "{}")
    data.setdefault("sessions", {})[key] = entry   # mutate
    f.seek(0); f.truncate()
    json.dump(data, f, indent=2, ensure_ascii=False); f.write("\n")
    f.flush(); fcntl.flock(f, fcntl.LOCK_UN)
```

## Task-type inference

From task keywords (mirrors trinity): `review`/`审查` → `review`; `tdd`/`test`/`测试` → `tdd`; `prp`/`proposal` → `prp`; else `general`. Sets the timeout threshold.

## Timeout thresholds (per task_type)

| task_type | warn_at | max_at |
|-----------|---------|--------|
| tdd | 10 min | 15 min |
| review | 6 min | 10 min |
| prp | 5 min | 8 min |
| general | 10 min | 20 min |

On each heartbeat/status check, compare `now - start_time`. At `warn_at` report `⚠️ possibly slow`. At `max_at` report `🚨 timed out` and kill the dispatched process. Because step 5 runs the provider in the foreground of the harness-backgrounded Bash (no separate wrapper PID is recorded), the kill path depends on the harness: the orchestrator signals "stop/cancel this background task" to the harness, which terminates the backgrounded Bash process group, cascading to the foreground provider. If the runtime exposes a task/cancel handle (e.g. a background-task id returned by the Bash tool), use that. As a fallback, discover the provider PID by matching the CLI in the process table (`pgrep -f '<provider-cli-token>'`) and `kill -TERM` it, then `kill -9` after 5s if still alive. Do NOT reference `$OUTPUT_FILE.pid` (no such file is written since the P1 double-backgrounding fix) and do NOT use `pkill -g` (its group semantics differ on BSD/macOS).

## Review Synthesis (reused from trinity)

For multi-provider review dispatch, build the trinity-shaped results list and call trinity's `write_synthesis`:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/skills/trinity/scripts')
from pathlib import Path
import _review
results = [
  {'provider':'glm','returncode':0,'raw':'raw/glm.txt','started_at':'...','finished_at':'...'},
  # ... one per provider; 'raw' is relative to review_dir
]
summary, synth_path = _review.write_synthesis(Path('$REVIEW_DIR'), '$SCOPE', results)
print(synth_path)
"
```

Pre-conditions the reused function expects:
- Each `review_dir/raw/<provider>.txt` already written in sentinel format (stdout + `%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%` + stderr) — our dispatch step 5 already does this.
- For TRN-3022 parsing to succeed, the provider's prompt must instruct it to emit a trailing fenced ```` ```json ```` block with `{decision, weighted_score, blocking, advisories, confidence?}`. trinity's `_review_schema_addendum` provides this text; append it to review prompts.

Review-dir layout (matches trinity): `.trinity/reviews/<YYYYMMDD-HHMMSS-slug>/{raw,logs,prompt.md,metadata.json,synthesis.md}`.

## Subcommands

### `status`

Run provider discovery. Show:
1. **Provider health table** — for each usable provider, mark ✅ (recently verified) / ⚠️ (not verified this session) / ❌ (known failed).
2. **Active sessions** — for each `.claude/trinity-zc.json` session with `state == running`: instance, state icon, elapsed, last byte-delta, task. Run a heartbeat read for each.

```
| Provider | Status | CLI                                  |
|----------|--------|--------------------------------------|
| glm      | ✅      | droid exec ... custom:GLM-5.2        |
| codex    | ✅      | codex exec ...                       |

| Instance  | State        | Elapsed | Δbytes | Task              |
|-----------|--------------|---------|--------|-------------------|
| glm       | 🔄 running   | 2m 10s  | +1.2K  | review FXA-2100   |
```

### `heartbeat [<instance>]`

If instance given, check only it; else check all `running` sessions. For each:
1. `wc -c <output_file>` → current bytes; compare to stored `bytes`.
2. Δ > 0 → `🔄 alive (+N bytes)`; Δ == 0 and elapsed > 60s → `⚠️ possibly stalled`.
3. Update `bytes` = current, `last_checked` = now (atomic flock write).
4. Apply timeout thresholds.

### `clear [<instance> | all]`

- `clear glm:auth` → delete that key.
- `clear glm` → delete `glm` and all `glm:*`.
- `clear all` → write `{"sessions": {}}`.
Kill any still-running process group before clearing. Confirm.

### `result <instance>`

Read the finished provider's `output_file`. If `task_type == review`, parse TRN-3022 and show decision/score/blocking. Else show the stdout portion (above the sentinel) as a focused summary.

### `doctor`

Smoke-test EVERY usable provider using trinity's own convention (`SKILL.md:356`): run `<cli> "Reply with exactly: trinity-ok"` with a 30s timeout (macOS lacks `timeout`; use a perl-alarm wrapper) and verify `trinity-ok` appears in output.

```bash
smoke() {
  local name="$1"; shift
  local out rc
  out=$(perl -e 'alarm shift; exec @ARGV' 30 "$@" 2>&1); rc=$?
  printf "%-12s exit=%-3d " "$name" "$rc"
  if echo "$out" | grep -qi "trinity-ok"; then echo "✅ PASS"
  elif [ $rc -eq 142 ] || [ $rc -eq 14 ]; then echo "⏰ TIMEOUT (30s)"   # 142 = 128+SIGALRM(14) under bash cmd-subst; 14 = bare perl SIGALRM
  else echo "❌ FAIL"; echo "$out" | tail -4 | sed 's/^/      | /'; fi
}
```

Note on the timeout status: when `perl ... exec @ARGV` is killed by SIGALRM, bash's command-substitution exit status is `128 + 14 = 142`, not `14`. Check both so the timeout branch is actually reached.

Report a per-provider table. Only providers present in the merged config are tested — gemini/openrouter/claude-code were retired from `~/.claude/trinity.json` (2026-06-27) and are no longer discovered. Flag any provider that returns non-`trinity-ok` output with its stderr tail.

### `help`

Print this SKILL.md's Syntax + architecture-summary sections.

## Error Handling

- Unknown provider → run discovery, report `Unknown provider: X. Usable: <list>.`
- Usable list empty → `No providers registered.` (point to `/trinity install <provider>` in Claude Code; trinity-zc does not install providers itself — it reuses trinity's config).
- Missing agent file / config → report which, point to `trinity install`.
- Empty task → `Task cannot be empty`.
- `output_file` missing at heartbeat: elapsed < 30s → `🟡 starting`; ≥ 30s but still within the task-type timeout (and the dispatch block buffers output until exit) → `🔄 running (buffered, no output yet)` rather than `failed to start`; only treat as `❌ failed to start` if the process is confirmed gone with no output. The buffered dispatch wrapper writes the file only on provider exit (see §Streaming caveat).
- Background process cleanup on timeout/abort: signal the harness to cancel the backgrounded Bash (which cascades to the foreground provider). Fallback: `pgrep -f '<provider-cli-token>'` to find the PID, then `kill -TERM`, wait 5s, `kill -9`. No `$OUTPUT_FILE.pid` is written (P1 fix removed double-backgrounding); no `setsid`/`pkill -g` (absent/unreliable on macOS).

## Out of scope (v1)

- `plan` / auto-decompose mode — not implemented; use explicit provider+task pairs.
- Provider installation — delegated to trinity's `/trinity install` (run in Claude Code).
- Anthropic-transcript JSONL emission — trinity-zc uses plain output files; the reused `session.py heartbeat` will report `no assistant activity` for our output files, which is fine (we track liveness via byte deltas, not transcript parsing).

## Reserved Words

`status`, `clear`, `heartbeat`, `result`, `doctor`, `help` are subcommands, not provider/preset names. A token that is both a provider and a preset/alias is an ambiguity error.

## Examples

```
/trinity-zc glm "review FXA-2100 dispatch logic"
/trinity-zc glm:auth "实现认证模块" codex "review 认证代码"
/trinity-zc glm*2 "并行实现 auth 和 order 模块"
/trinity-zc fast-review "review PR #242 changes"
/trinity-zc status
/trinity-zc heartbeat glm:auth
/trinity-zc result glm
/trinity-zc clear glm:auth
/trinity-zc doctor
```

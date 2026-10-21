# CHG-3056: Codex and OpenCode Dispatch Adapters

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Date:** 2026-10-20
**Last updated:** 2026-10-21
**Last reviewed:** 2026-10-20
**Status:** Proposed
**Requested by:** @frankyxhl
**Priority:** High
**Change Type:** Normal
**Related:** docs/contracts/dispatch-core.md (DSP-*), docs/method/spec-provider-adapters.md (ADP-*), TRN-1006

---

## What

The dispatch core (`bin/trinity call` → `scripts/trinity_core`) gets two new adapters, `codex` and `opencode`, a few new call options, and an optional memory gate. Base: 4.0.2, which has only the `claude-code` adapter. Target version 4.1.0.

Goal: every one-shot model run can go through `bin/trinity call`. Hand-written Codex `run.sh` wrappers and tmux-driven OpenCode runs become one command each, journaled.

Evidence for every harness shape below: probes of 2026-10-20 (codex-cli 0.162.1, opencode 1.19.0), stored as fixtures in `tests/fixtures/oneshot/`.

## Why

- Operators copy a 20-line `run.sh` per Codex run (31 copies on 2026-10-20) to get: a fixed `CODEX_HOME`, `-s read-only|workspace-write`, `-o <answer file>`, a memory gate before start, and `start/end/rc/out.jsonl/err.txt` files for its watcher.
- OpenCode runs today go through an interactive tmux pane plus a screen-scraping watcher; `opencode run` already exits on its own and streams JSON.

## Contract

IDs are `ONE-nnn`. Every requirement is observable from outside the process (CLI result line, journal, error log, files, the argv and env a fake harness records). Requirements not listed here keep their current DSP/ADP behaviour.

### Profiles

| ID | Requirement |
| --- | --- |
| ONE-001 | A `codex` profile has `adapter: "codex"`, `model` (required), `effort` (optional: `none`, `low`, `medium`, `high`, `xhigh`), `sandbox` (required: exactly `read-only` or `workspace-write`), `codex_home` (required, a path; a leading `~` expands to `HOME`; a relative path is resolved once against the caller's working directory, and that absolute path is used for preflight, the child and readback), `binary` (optional, default `codex`, looked up on `PATH`), `env_pass` (optional list of extra environment variable names), `gate` (optional: `none`, `light`, `heavy`; default `none`). A codex profile missing `model`, `sandbox` or `codex_home`, or with any other `sandbox` or `effort` value, makes `call` return `bad_request` and write nothing. |
| ONE-002 | An `opencode` profile has `adapter: "opencode"`, `model` (required, `provider/model`), `variant` (optional), `opencode_config` (required, a path, resolved like `codex_home` in ONE-001), `binary` (optional, default `opencode`), `env_pass`, `gate` as in ONE-001. Missing `model` or `opencode_config` → `bad_request`, nothing written. |
| ONE-003 | An `env_pass` name that the journal redaction treats as secret-shaped (contains a segment such as `key`, `token`, `secret`, `password`, `auth`) makes the profile invalid → `bad_request`. |

### Call options (`bin/trinity call`)

| ID | Requirement |
| --- | --- |
| ONE-010 | `--prompt TEXT` and `--prompt-file PATH` (repeatable) are mutually exclusive; exactly one form is required. Files are read as UTF-8 and joined in the given order with nothing added between them (the same bytes as `cat a b`). A missing or unreadable file → `bad_request`, nothing written. |
| ONE-011 | `--output PATH`: after the call, `PATH` holds the final answer text of the call (ONE-032, ONE-052, and for `claude-code` the `result` text of the final result record). The result line has `output_kind: "file"` and `output_ref` = the absolute path. When there is no final answer the file is not created and `output_kind` stays `none`. The answer text never enters the journal. An `--output` path that resolves (following links) to a file inside Trinity's journal directory → `bad_request`, nothing written. |
| ONE-012 | `--log-dir DIR`: the directory is created if missing. After the call it holds `start` and `end` (Unix seconds), `rc.txt` (`rc=<harness exit code>`, or `rc=none` when no harness process started), `out.jsonl` (the child's stdout), `err.txt` (the child's stderr) and, when a gate ran, `gate.txt` (the latest gate reading, one line `gate=<g> level=<n> free=<pct> swap_mb=<n> load5=<x> decision=<d>`). Each line of `out.jsonl` and `err.txt` is passed through the journal redaction function before it is written. Every file is mode 600 and is written only as a regular file: a name that already exists as a link or a non-regular file is not written. If `DIR` exists and is not a directory, or cannot be created → `bad_request`, nothing written. A failure writing any of these files after the call adds one error-log line `{error: "log_unwritable", run, node}` and one stderr line; the result line and its exit class are unchanged. When the gate refused (ONE-065), `gate.txt` is written with `decision=refused` and every reading value as `na`. |
| ONE-013 | `--time-s N` sets `limits.time_s` (a positive number, else `bad_request`). |
| ONE-014 | `--gate none|light|heavy` overrides the profile's `gate` for this call. |
| ONE-015 | `--model M` overrides the profile's `model` for this call; the `node` record's `model` is the model actually passed to the harness. For `opencode` the override is checked like the profile model (ONE-041). |
| ONE-016 | Without any new option, a `claude-code` call behaves exactly as in 4.0.2 (same argv, env, journal lines and result). |

### Session ids (DSP-020 layer b for capture adapters)

| ID | Requirement |
| --- | --- |
| ONE-020 | For `session: new` the core does not pre-assign an id to a `codex` or `opencode` call: the `node` record holds `session: {id: null, mode: "new", source: "pending"}`. |
| ONE-021 | The adapter reports the first id it sees (codex: `thread_id` of the `thread.started` event; opencode: `sessionID` of the first event) through a callback before reading further events; the core then appends one `session` line `{kind: "session", run, node, id, source: "captured", t}`. The result's `session_id` is that id. |
| ONE-022 | If no id is seen by the end, DSP-020 applies unchanged: a `session` line with `source: "session_unknown"`, an `ok` end becomes `harness_error`, `session_id` is null. |
| ONE-023 | For `--session ID` the node records `{id: ID, mode: "continue", source: "caller"}` and the harness is started on that id (ONE-030, ONE-050). A reported id that differs is journaled as a `captured` session line (DSP-020). |

### Codex adapter

| ID | Requirement |
| --- | --- |
| ONE-030 | argv, new session: `[<binary>, "exec", "-m", MODEL, ("-c", "model_reasoning_effort=\"EFFORT\"" when effort is set), "-s", SANDBOX, "--skip-git-repo-check", "--json", ("-o", OUTPUT when --output is given), PROMPT]`. Continue: `[<binary>, "exec", "-s", SANDBOX, "resume", "-m", MODEL, ("-c", …), "--skip-git-repo-check", "--json", ("-o", OUTPUT), ID, PROMPT]`. No other flag is ever added; in particular never `--dangerously-bypass-approvals-and-sandbox`, `--full-auto` or `-s danger-full-access`. stdin is `/dev/null`; the working directory is the call's `cwd`. |
| ONE-031 | The child environment is the existing allow-list plus `CODEX_HOME` = the profile's `codex_home`, plus the profile's `env_pass` names that are set, plus `TRINITY_GUARD`. Nothing else. `CODEX_HOME` and `TRINITY_GUARD` are set after `env_pass`, so an `env_pass` name never overrides them. |
| ONE-032 | The final answer is the `text` of the last `item.completed` event whose `item.type` is `agent_message`. |
| ONE-033 | Usage comes from the last `turn.completed` event: `input_tokens` → `input_tokens`, `output_tokens` → `output_tokens`, `cached_input_tokens` → `cache_read_input_tokens`, `cache_write_input_tokens` → `cache_creation_input_tokens`. No `turn.completed` → usage absent (ADP-011). |
| ONE-034 | Exit class, in this order: interrupt → `interrupted`; `time_s` reached → `timeout` (process group killed, ADP-009); exit code ≠ 0 with stderr containing `no rollout found for thread id` → `session_not_found`; an `error` or `turn.failed` event, or a non-zero exit, whose message matches an auth marker (`401`, `unauthorized`, `not logged in`, case-insensitive) → `auth_error`; matches a quota marker (`429`, `rate limit`, `usage limit`, `quota`) → `quota_exhausted`; every marker matches only as a whole word (`item_4290` and `/tmp/run-1401` match none); exit code 0 and last event `turn.completed` → `ok` (subject to ONE-035); exit code 0 with a last event `turn.failed` or any `error` event → `harness_error`; anything else → `unknown`. |
| ONE-035 | Readback before an `ok` stands: exactly one file `CODEX_HOME/sessions/**/rollout-*-<session id>.jsonl` exists; its last `turn_context` record has `payload.model` equal to the model passed and `payload.sandbox_policy.type` equal to the profile's `sandbox`. A difference → `harness_error` plus one error-log line `{error: "model_mismatch" or "sandbox_mismatch", run, node}`; no file or no `turn_context` → `harness_error` plus `{error: "readback_missing", run, node}`. |

### Preflight (after the `queued` node line, before the gate and the harness)

| ID | Requirement |
| --- | --- |
| ONE-040 | `codex`: `codex_home` must be an existing directory and `binary` must resolve on `PATH`; otherwise the node ends `queued → failed` with `profile_refused` and no harness process starts. |
| ONE-041 | `opencode`: `binary` must resolve on `PATH`, `opencode_config` must be an existing file, and the model must appear as an exact whole line in the output of `[<binary>, "models"]` (run with a 60 s limit). Otherwise the node ends `queued → failed` with `profile_refused`, plus a check line `{kind: "check", check: "model", decision: "refused", …}` when the model was the cause; no `run` process starts and nothing is billed. |

### OpenCode adapter

| ID | Requirement |
| --- | --- |
| ONE-050 | argv: `[<binary>, "run", "--format", "json", "-m", MODEL, ("--variant", V), ("-s", ID for a continue), "--dir", CWD, PROMPT]`. Never `--auto`, never `--share`, never `--attach`. stdin is `/dev/null`. |
| ONE-051 | The child environment is the allow-list plus `OPENCODE_CONFIG` = the profile's `opencode_config`, plus `XDG_DATA_HOME` and `XDG_CONFIG_HOME` when set, plus `env_pass`, plus `TRINITY_GUARD`. `OPENCODE_CONFIG` and `TRINITY_GUARD` are set after `env_pass`, so an `env_pass` name never overrides them. |
| ONE-052 | The final answer is the concatenated `part.text` of the `text` events after the last `step_start` event. |
| ONE-053 | Usage is the sum over this call's `step_finish` events: `part.tokens.input` → `input_tokens`, `output` → `output_tokens`, `total` → `tokens`, `cache.read` → `cache_read_input_tokens`, `cache.write` → `cache_creation_input_tokens`, `part.cost` → `cost_usd`. `cost_usd` joins the journal's usage whitelist (numbers only). No `step_finish` → usage absent. |
| ONE-054 | Exit class, in this order: interrupt → `interrupted`; `time_s` reached → `timeout` (process group killed); exit code ≠ 0 with stderr (ANSI codes removed) containing `Session not found` → `session_not_found`; an `error` event whose name or message matches the auth markers of ONE-034 → `auth_error`, the quota markers → `quota_exhausted`, otherwise → `unknown`; exit code 0 and the last `step_finish` has `part.reason == "stop"` → `ok` (subject to ONE-055); exit code 0 and a `tool_use` part with `state.status == "error"` whose `state.error` mentions a rejected permission → `harness_error` plus one error-log line `{error: "permission_rejected", run, node}`; exit code 0 with any other last `step_finish` reason → `harness_error`; no `step_finish` → `unknown`. **Exit code 0 alone is never `ok`** (probe p6: a permission auto-reject exits 0). |
| ONE-055 | Readback before an `ok` stands: in `$XDG_DATA_HOME/opencode/opencode.db` (default `~/.local/share/opencode/opencode.db`), opened with a plain connection whose first statement is `PRAGMA query_only=ON` (never a write; no `mode=ro` URI open, which fails on a WAL database without its -shm file under some SQLite builds), the `session` row with the captured id has a `model` JSON whose `providerID + "/" + id` equals the model passed. A difference → `harness_error` + `{error: "model_mismatch", run, node}`; no row or unreadable database → `harness_error` + `{error: "readback_missing", run, node}`. |

### Memory gate (core, after preflight, before the adapter)

| ID | Requirement |
| --- | --- |
| ONE-060 | Gate `none` (the default): no reading, no check line. Every 4.0.2 call is unchanged. |
| ONE-061 | Gate `light` passes when pressure level ≤ 2 and 5-minute load < 30. Gate `heavy` passes when pressure level = 1, free ≥ 40 % and swap used < 1800 MB. (Numbers: the operators' start-gate thresholds as of 2026-10-20.) |
| ONE-062 | Readings: 5-minute load from `os.getloadavg()`. macOS: level `sysctl -n kern.memorystatus_vm_pressure_level`, free from `memory_pressure` ("free percentage"), swap from `sysctl -n vm.swapusage` ("used"). Linux: free = `MemAvailable / MemTotal` from `/proc/meminfo`, swap = `SwapTotal − SwapFree`, level from `/proc/pressure/memory` `some avg60` (< 10 → 1, < 40 → 2, else 4). If the environment variable `TRINITY_GATE_READINGS` names a file, the readings come from that JSON file (`{level, free_pct, swap_mb, load5}`) instead, re-read at every poll (test seam, like `TRINITY_HEARTBEAT_POLL_S`). |
| ONE-063 | The gate re-reads every `TRINITY_GATE_POLL_S` seconds (default 20). It appends a check line `{kind: "check", run, node, check: "memory_gate", gate, level, free_pct, swap_mb, load5, decision, t}` on the first reading and whenever the decision changes; decisions are `wait`, `go`, `stop`, `refused`. |
| ONE-064 | Waiting counts against `time_s`. When `time_s` runs out while waiting: a check line with `decision: "stop"`, the node ends `queued → failed` with `timeout`, and no harness process starts. A reading that says `go` when the time left is `<= 0` is handled the same way (check line `decision: "stop"`, `timeout`, no harness): the adapter never receives a `time_s` of zero or less. Deadline, time left and time spent waiting use one monotonic clock. Without `time_s` the gate waits until it passes or the caller interrupts. |
| ONE-065 | A reading that cannot be taken (missing tool or file, unparsable output, a missing key in the test file, a value that is not a finite number) → check line `decision: "refused"`, node `queued → failed` with `check_failed`, no harness. The gate never treats an unreadable value as passing. |

### Unchanged

The result line shape, journal version, nesting guard, heartbeat rows (both new adapters declare `stdout`, default stall limit 660 s, as `claude-code`), and the kill rule DSP-012: a node with no new events is shown stuck after its stall limit, never killed; only `time_s` or an interrupt ends a running harness.

## Acceptance

Every ONE-id has at least one test in `tests/test_one_*.py` that drives `bin/trinity` as a subprocess with fake `codex` / `opencode` binaries replaying the fixtures in `tests/fixtures/oneshot/`. Real-model acceptance is an end-to-end run against the real `codex` and `opencode` CLIs (cases A1–C3).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-10-20 | Initial contract | trinity |
| 2026-10-21 | ONE-064: a `go` reading with no time left is a stop; the adapter never gets `time_s <= 0`; one monotonic clock for the gate wait | trinity |
| 2026-10-21 | Clarifications from the release review: ONE-001/002 relative paths resolved once; ONE-011 `--output` must not resolve into the journal directory; ONE-012 regular files only, `DIR` failures, `log_unwritable`, `gate.txt` on a refused gate; ONE-031/051 reserved variables set after `env_pass`; ONE-055 SQLite read-only open; ONE-065 non-finite values are unreadable | trinity |
| 2026-10-21 | Expert review fixes (D2775): ONE-034 markers match whole words; ONE-055 readback uses a query_only connection, not a mode=ro open; a harness that has exited is drained for the grace period and, if a child still holds its output, its process group is killed; the call ends by the harness's own result, not `timeout` | trinity |

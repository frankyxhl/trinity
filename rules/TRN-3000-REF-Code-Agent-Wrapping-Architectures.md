# REF-3000: External Coding Agent Wrapping — CLI Backend vs ACP/ACPX

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Active
**Source research:** `openclaw_code_agent_wrapping_research.md` (root of repo, untracked) — primary source, written 2026-05-07. Read it for full source-code links into OpenClaw's repo.

---

## What this REF is

A reference doc capturing how external coding agents (Claude Code, Codex, Gemini CLI, etc.) can be wrapped by an orchestrator like Trinity, distilled from a study of OpenClaw's architecture. It records **what Trinity adopts, what it deliberately doesn't, and why**, so future contributors don't re-litigate the architectural choice every time the topic comes up.

This is a **decision record + architectural map**, not a how-to. For implementation, see the issues this REF informs (TRN-3020 / 3021 / 3022 / 3023 / 3024 / TRN-issue #55).

---

## Two architectures for wrapping a coding agent

OpenClaw exposes both. They are **not** alternatives — they're stacked layers with different responsibilities:

### 1. CLI backend (text-fallback layer)

Treats the agent's CLI as a **configurable subprocess**: spawn `claude -p ...` or `codex exec ...`, pass a system prompt via file/append, parse JSONL/text from stdout, save vendor session id.

Responsibilities and ceiling:
- ✅ Cheap to wrap (matches subprocess-spawn semantics already in Trinity)
- ✅ One-shot or short multi-turn fine
- ✅ Per-provider quirks (input mode, output format, system prompt injection) live in **per-plugin config** rather than orchestrator core
- ❌ No structured tool-call events — must scrape stdout
- ❌ No mid-session controls (status/cancel/setMode) beyond OS-level signals
- ❌ No harness-side execution (file edit, bash)
- ❌ Resume is a "saved session id you re-pass on the CLI" — fragile across auth/system-prompt changes

OpenClaw entry points worth knowing:
- `src/plugins/cli-backend.types.ts` — the `CliBackendPlugin` shape
- `src/agents/cli-runner/{prepare,helpers,execute}.ts` — runner core
- `extensions/anthropic/cli-backend.ts`, `extensions/openai/cli-backend.ts` — vendor plugins
- `src/agents/cli-runner/bundle-mcp*.ts` — OpenClaw's loopback MCP overlay, recorded here as rejected for Trinity peer review

### 2. ACP / ACPX (structured external-harness layer)

Treats the agent as an **external coding harness session** speaking a JSON-RPC-style protocol. OpenClaw's `AcpRuntime` interface gives the orchestrator: `ensureSession`, `runTurn`, `getStatus`, `setMode`, `setConfigOption`, `cancel`, `close`. Events come back as `text_delta | status | tool_call | done | error`.

Responsibilities and ceiling:
- ✅ Structured everything — events, controls, tool calls, status — no stdout grep
- ✅ Persistent sessions with crash reconnect, named sessions, prompt queueing
- ✅ Mid-session model/permissions/timeout changes
- ✅ Conversation/thread binding so events stream into a chat UI
- ✅ Harness-side code execution (file edit, bash) is part of the contract
- ❌ Vendor must ship an ACP adapter (Claude Code does; Codex does; many others don't)
- ❌ Orchestrator complexity jumps — separate control plane, session manager, runtime registry
- ❌ Sandbox boundary moves: ACP runs on host, not inside orchestrator's sandbox

OpenClaw entry points worth knowing:
- `src/acp/runtime/types.ts` — the `AcpRuntime` interface
- `extensions/acpx/{register.runtime.ts,src/service.ts,src/runtime.ts}` — the bundled ACPX backend
- `src/acp/control-plane/manager.core.ts` — `initializeSession` + `runTurn` orchestration
- `src/agents/acp-spawn.ts` — `/acp spawn` flow
- `acpx` repo: https://github.com/openclaw/acpx (the headless ACP client itself)

---

## Trinity's position: stay CLI-backend, adopt OpenClaw's CLI-backend engineering quality

Trinity's product is **multi-provider review/code panel** — N providers, single turn each, write findings, die. ACP's killer features map onto a different product (long-running coding harnesses with mid-session control). Wasted capacity table:

| ACP capability | Trinity need? | Reason |
|----|----|----|
| Structured protocol vs stdout scrape | low — JSONL is tractable | Reviews fit in a single JSONL stream |
| Persistent session + crash reconnect | none | 60-second reviews don't need recovery |
| Mid-session controls (model/timeout/permissions/cancel) | none — single turn | Review runs to completion or is killed wholesale |
| Conversation/thread binding to chat UI | none | Trinity is CLI, not a chat product |
| Harness-side code execution (file edit/bash) | **negative** | Review providers MUST NOT modify files |
| Multi-turn with state | none | Reviews are stateless |
| Status query mid-run | low — JSONL streaming gives the same | |
| Loopback MCP for orchestrator tools | **not wanted** | Withdrawn by maintainer decision in #168; Trinity keeps independent parallel reviews followed by synthesis |

**Decision (2026-05-08, updated 2026-05-30)**: Trinity stays on the
CLI-backend architecture. The former "loopback MCP for peer findings" idea
(TRN-3024 / issue #63) was withdrawn in #168 as over-engineered for Trinity.

Re-evaluation triggers — switch to ACP would only make sense if Trinity adds:
- A "long-running coding session with Claude Code" feature (multi-turn iteratively-fix-this-PR)
- A chat UI that wants to stream agent events live
- A background-coding-agent feature with hour-scale runs and operator status/cancel controls

None of these are on Trinity's roadmap as of 2026-05-08.

---

## What Trinity adopts from OpenClaw's CLI-backend layer

Even staying CLI-backend, Trinity's current implementation lags OpenClaw's CLI-backend engineering quality on several axes. The 6 open issues below each correspond to a OpenClaw-validated improvement:

| Trinity issue | OpenClaw analog | What translates |
|----|----|----|
| **#37 TRN-3020** consolidate provider config | `CliBackendPlugin` type (`src/plugins/cli-backend.types.ts`) — one struct per provider with `command`, `args`, `output`, `input`, `session`, `bundleMcp`, etc. | Trinity's `providers.<name>` grows from `{cli, supports_resume, resume_arg, timeout}` to plugin-shape; per-provider quirks leave `cmd_review` and live in config |
| **#38 TRN-3021** doctor preflight expansion | OpenClaw's `prepareCliRunContext` validates auth/workspace/skills/MCP at start | Doctor does the equivalent batch of preflight checks; *reports* pollution that #62 *prevents* |
| **#39 TRN-3022** normalize review result schema | OpenClaw's stream-json parser gives a uniform event shape regardless of vendor dialect | One canonical Trinity finding schema; vendor parsers normalize into it |
| **#55** richer summary output | OpenClaw streams partial deltas to the UI live | Per-provider live progress instead of "60 seconds of black, then everything" |
| **#62 TRN-3023** spawn-time env sanitization | `CLAUDE_CLI_CLEAR_ENV` (`extensions/anthropic/cli-shared.ts`) | Per-provider env-allowlist + clearlist at spawn so reviews are reproducible across machines |
| **#63 TRN-3024** peer findings via loopback MCP | `bundleMcp: true` + `bundleMcpMode: claude-config-file\|codex-config-overrides` (`src/agents/cli-runner/bundle-mcp*.ts`) | Withdrawn in #168; do not implement MCP for Trinity peer review |

**Order matters.** TRN-3020 is the keystone — once provider config is plugin-shaped, the other five slot in cleanly. Doing them out of order means refactoring each when 3020 lands.

---

## What Trinity does NOT adopt from OpenClaw

Recording these explicitly so they don't surface as "obviously good ideas" in future evolve cycles:

- **ACP/ACPX runtime, AcpRuntime interface, session manager, /acp spawn flow, runtime backend registry** — see Trinity's-position table above. Wasted complexity for a non-multi-turn product.
- **Conversation / thread binding** — Trinity isn't a chat product. Channel/binding work belongs to a different layer if Trinity ever grows a UI.
- **Permission profiles, mode switching mid-session** — review providers do not get harness tools; mode switch is meaningless for a single-turn run.
- **Background-task framework** — Trinity already runs providers in parallel via `concurrent.futures`; OpenClaw's background-task framework is built around long-running ACP sessions, which Trinity doesn't have.
- **Vendor-specific config-file synthesis** — OpenClaw synthesizes Claude plugin dirs (`--plugin-dir`) for skills visibility; Trinity doesn't have a skills concept and shouldn't grow one.

If a future contributor wants to revisit any of these, **the burden is on them to show a Trinity-side product need**, not just "OpenClaw does it."

---

## Source pointer

Full source-code links into OpenClaw's repo, vendor-by-vendor injection differences, and pseudocode for both Claude CLI and Codex CLI wrapping live in:

- `openclaw_code_agent_wrapping_research.md` (root of repo, in Chinese, untracked artifact). Treat it as the primary reference; this REF distills the trinity-relevant decisions.

If that file is ever lost, the OpenClaw repo entry points to grep are:

```bash
# CLI backend
rg "registerCliBackend|CliBackendPlugin|prepareCliRunContext|executePreparedCliRun" src extensions
rg "bundleMcp|claude-config-file|codex-config-overrides" src extensions

# ACP / ACPX
rg "AcpRuntime|registerAcpRuntimeBackend|ensureSession|runTurn|consumeAcpTurnStream" src extensions/acpx
rg "sessions_spawn|acp-spawn|getAcpSessionManager" src/agents src/acp
```

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-30 | Updated TRN-3024 references after #168 withdrew loopback MCP as over-engineered for Trinity; retained independent parallel review as the baseline | Codex |
| 2026-05-08 | Initial REF distilled from `openclaw_code_agent_wrapping_research.md` study; records decision to stay CLI-backend and adopt OpenClaw's CLI-backend engineering patterns via TRN-3020 → TRN-3024 + issue #55 | Claude Opus 4.7 |

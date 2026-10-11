# Component spec: provider adapters (提供方适配) — draft 0.1

Status: **draft, WO-001 boundary spec.** Requirements are unverified. Full contract + acceptance cases are WO-002.
Laws that bind this component: LAW-01, 04, 05, 07, 08 (METHOD.md §3).

## 1. Purpose

Turn one Trinity call into one harness invocation, and report back: session id, final output, exit class, and a pointer to the raw transcript.

## 2. Scope

In:

- One adapter per harness family. Target set:

| Adapter | Harness | Billing | Today (forge/main) | Change |
| --- | --- | --- | --- | --- |
| claude-code | `claude -p` (isolated config dir) | subscription via setup-token | wrapper, sonnet/high, no token selection | read token from profile (A/B/C) |
| codex | `codex exec` / `experimental resume` | subscription | `gpt-5.6-sol` pinned in registry | model from profile |
| droid (glm, minimax) | `droid exec --auto medium` | subscription | GLM-5.2 / MiniMax-M3 pinned | model from profile; reconcile with installed LiteLLM bridge glm (RSK-01) |
| agy | `agy` (Antigravity) | subscription | agy-opus wrapper with run lock | keep |
| anthropic-compat | `claude` pointed at a compatible endpoint | metered | deepseek, openrouter wrappers | one adapter, endpoint from profile |
| opencode | `opencode` (Go, e.g. `opencode-go/deepseek-v4.1-flash`) | subscription | absent | **new** |
| deepseek-api | DeepSeek HTTP API direct | metered | via anthropic-compat only | **new or folded into anthropic-compat** (OPEN-A3) |
| gemini | `gemini -p` | — | agent files, no registry entry | **remove** |

- New session and continue session.
- Reporting: start, session id known, heartbeat source, end, exit class.

Out:

- Choosing which profile to use (profiles component).
- Quota and lock checks (dispatch core).
- Writing the journal (adapter emits events; the core writes them).
- Retry policy (dispatch core / orchestrator owns retries; one retry owner, CraftCode §16.1).

## 3. Boundary contract (draft)

Input (from dispatch core): resolved profile (no secret values, only a credential source reference), `session` = `new` or a session id, prompt text (or prompt file), working dir, time limit, stall limit, run id + node id.

Output: `session_id`, `final_text` (or pointer), `exit_class`, `transcript_ref` (path + optional offset), `usage` (tokens/cost if the harness reports it, else null), timestamps.

| ID | Requirement |
| --- | --- |
| ADP-001 | Every adapter accepts the same input shape and returns the same output shape. |
| ADP-002 | `exit_class` is one of: `ok`, `harness_error`, `auth_error`, `quota_exhausted`, `timeout`, `interrupted`, `session_not_found`, `unknown`. `unknown` is allowed but journaled with raw stderr tail. |
| ADP-003 | `session=new` returns the new session id, found by an exact marker or harness-reported id — never by newest-mtime (keeps TRINITY-2004 fix). |
| ADP-004 | `session=<id>` on a missing/expired session returns `session_not_found`; the adapter does **not** silently start a new session (today's "discard and create new" moves up to the caller, so the journal shows it). |
| ADP-005 | Credentials are passed by env or file read inside the wrapper process; never on argv; never echoed. |
| ADP-006 | The child process env is built from an allow-list (existing `build_provider_env`), plus only the profile's declared variables. |
| ADP-007 | The child gets the recursion guard (`TRINITY_DISABLE_DISPATCH=1` or equivalent) unless the run allows nesting. |
| ADP-008 | Each adapter declares its heartbeat source (transcript file growth, stdout, or process alive) and a default stall limit. |
| ADP-009 | On timeout or interrupt, the adapter kills only the process group it started and reports partial output (existing `terminate_process_group`). |
| ADP-010 | Model id comes from the profile; the adapter refuses an id on the retired list. |
| ADP-011 | `usage` is reported when the harness exposes it; adapters never estimate tokens and label the estimate as real. |

## 4. Environment assumptions

- Vendor CLIs installed and logged in where the harness needs login (opencode Go login done on bajie and wukong, frank-todo 10-10).
- claude-code profiles: token files exist at the profile's credential source with mode 600/400.
- Session transcripts are written by the vendor to known places (`session_path.py` today knows the claude-family slugs).
- macOS + Linux; POSIX sh wrappers (no zsh, TRN-2009).

## 5. Risks

| ID | Risk |
| --- | --- |
| ADP-R1 | Vendor CLI flag changes (codex `experimental resume`, droid `-s`) break resume silently. |
| ADP-R2 | `claude -p` with an OAuth setup-token behaves differently from the isolated-config login (smoke 14:15: only the token path worked). |
| ADP-R3 | opencode transcript/session format unknown to Trinity today; heartbeat and events may be stdout-only. |
| ADP-R4 | Anthropic-compat endpoints accept the request but ignore model/effort fields. |
| ADP-R5 | Folding deepseek-api into anthropic-compat hides its own error classes (rate limit vs balance). |
| ADP-R6 | Removing gemini breaks users who still have `trinity-gemini.md` installed; installer must clean or warn. |

## 6. Open items

| ID | Question |
| --- | --- |
| OPEN-A1 | Does each adapter stay a markdown agent file (sub-agent prose + shell), or become Python code called by one generic agent? (LAW-01 favours code.) |
| OPEN-A2 | opencode: session id source and resume flag; transcript location. Needs a probe before WO-002. |
| OPEN-A3 | deepseek "both billing modes": is subscription = OpenCode Go and metered = direct API? Then deepseek-api is just a profile of anthropic-compat. |
| OPEN-A4 | codex "current models": which ids (mockup `gpt-6.1-sol`; fleet uses Sol/Luna/Astra)? Who updates them (TRN-1006)? |
| OPEN-A5 | Keep `openrouter`? Not named in the plan. |
| OPEN-A6 | Where per-adapter stall limits come from (adapter default vs profile override). |

## 7. Verification to define in WO-002 (not done)

Per adapter: new session, continue session, missing session, bad credential, timeout kill, recursion guard present, no secret in argv/journal, retired model refused. Mark each case adapter-specific or shared.

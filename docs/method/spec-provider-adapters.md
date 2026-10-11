# Component spec: provider adapters (提供方适配) — draft 0.2

Status: **draft, WO-001 boundary spec.** Requirements are unverified. Reader contract: `../contracts/transcript-reader.md`; call contract: `../contracts/dispatch-core.md`.
Terms: METHOD.md §2. Laws that bind this component: LAW-01, 04, 05, 07, 08, 11.

## 1. Purpose

Each adapter has two jobs for one harness:

1. **Call:** turn one Trinity call into one harness invocation and report back session id, final output pointer, exit class, harness type and transcript ref.
2. **Read:** on demand, turn that harness's native transcript (via ref) into the unified event schema (`prompt`, `thinking`, `tool`, `output`, `heartbeat`).

## 2. Scope

In — one adapter per harness family (provider names map per METHOD §2.1):

| Adapter | Harness | Billing | At baseline | Change |
| --- | --- | --- | --- | --- |
| claude-code | `claude -p` (isolated config dir) | subscription via setup-token | wrapper, fixed model/effort, one login | credential and model from profile (one profile per account) |
| codex | `codex exec` / `exec resume` | subscription | model id pinned in registry | model from profile (vendor's current models) |
| droid | `droid exec --auto medium` (glm, minimax) | subscription | model ids pinned | model from profile; glm path re-specified in WO-002 (RSK-01) |
| agy | Antigravity CLI | subscription | wrapper with run lock | keep |
| anthropic-compat | `claude` pointed at a compatible endpoint | metered | deepseek and openrouter wrappers | one adapter; endpoint and model from profile; openrouter is a profile of it |
| opencode | `opencode` | subscription | absent | **new** |
| deepseek-api | DeepSeek HTTP API direct | metered | only via anthropic-compat | **new or a profile of anthropic-compat** (OPEN-A3) |
| gemini | `gemini -p` | — | agent files present, no registry entry | **remove**; installer cleans or warns (ADP-R6) |

Also in: new session and continue session; call-time reporting (start, session id, heartbeat source, end, exit class); per-harness transcript reader.

Out:

- Choosing the profile (profiles spec).
- Quota and lock checks, heartbeat rows, retries (dispatch core, METHOD §5).
- Writing the journal: the adapter returns fields; the core writes them.

## 3. Boundary contract (draft)

Call input (from the core): resolved profile (credential *source* only), `session` = `new` (with a pre-assigned id when the adapter can take one, ADP-016) or a session id, prompt text or prompt file, working dir, time limit, stall limit, run id + node id.

Call output: `harness` (adapter name), `session_id`, `output_ref` (pointer to final output in the transcript), `exit_class`, `transcript_ref` (path + offset or hash), `usage` (or absent), start/end times.

| ID | Requirement |
| --- | --- |
| ADP-001 | Every adapter accepts the same input shape and returns the same output shape, including `harness`. |
| ADP-002 | `exit_class` is one value from the closed list in DSP-010 (`contracts/dispatch-core.md` §4); that table says which classes an adapter sets and which only the core sets. `unknown` comes with the last 2 KB of stderr, redacted as in ADP-012, in the core's error log (a store in METHOD §7), never in the journal. |
| ADP-003 | `session=new` returns the new session id: the pre-assigned one, or one captured by an exact marker or a harness-reported id, reported to the core as soon as seen — never by newest-mtime (keeps the existing trace-marker fix). No id → the adapter reports none, and the core applies `session_unknown` (DSP-020). |
| ADP-004 | `session=<id>` on a missing/expired session returns `session_not_found`; the adapter never starts a new session in its place (CHK-007). |
| ADP-005 | Credentials are passed by env or by a file read inside the wrapper process; never on argv; never echoed. Observable: a process listing during a call shows no credential value. |
| ADP-006 | The child env is built from an allow-list (existing `build_provider_env`) plus only the profile's declared variables. |
| ADP-007 | The child gets the recursion guard (`TRINITY_DISABLE_DISPATCH=1` or equivalent) unless the run allows nesting. |
| ADP-008 | Each adapter declares its heartbeat source (transcript growth, stdout, or process alive) and a default stall limit in seconds; a profile may override it (OPEN-A6). |
| ADP-009 | On timeout or interrupt the adapter kills only the process group it started and reports partial output (existing `terminate_process_group`). |
| ADP-010 | Model id comes from the profile; an id on the retired list is refused before any process starts (list and mechanism specified in WO-002). |
| ADP-011 | `usage` is copied from what the harness reports. If the harness reports nothing, `usage` is **absent** (not 0, not an estimate). |
| ADP-012 | **Reader.** Each adapter has one reader: input `transcript_ref`; output an ordered list of unified events `{t, type ∈ prompt|thinking|tool|output|heartbeat, text, raw_ref}`. It runs on demand (when a view asks), never at journal-write time. Lines it does not understand become `output` events marked `raw`, never dropped. It redacts secret-pattern matches before returning text. Full reader contract: RDR-001..015. |
| ADP-013 | **Honest thinking.** When the harness gives thinking only as a summary or encrypted, the reader returns it with `thinking_form = summary | encrypted | absent`, and never presents it as full text. |
| ADP-014 | **Gone transcripts.** If the transcript at the ref no longer exists, the reader returns `gone` with the time it was found missing and, when the profile states vendor retention (PRF-009), the expected expiry time. |
| ADP-015 | A repeated identical call (same prompt, same session) is a new call: new node, new output; the adapter never returns a cached earlier answer. |
| ADP-016 | **Session-id source per harness** (DSP-020), in the table below. "Pre-assign" = the adapter passes Trinity's id to the harness; "capture" = it reads the id from the harness's first output that carries one. Pre-assign: claude-code, anthropic-compat (both wrappers), deepseek-api. Capture: codex, droid, agy, opencode. Capture follows DSP-020 layers (b) first-stream-event id and (c) one session file in a per-call session directory; the "If no" column names both where (c) exists. Each capture source (the event field) is confirmed by fixture before the adapter is built. Evidence is the installed CLI's own `--help`, re-checked when the CLI version changes (ADP-R1). |

| Harness (adapter) | CLI + version | Evidence (`--help`) | New session takes caller id? | If no, id comes from | Resume accepts |
| --- | --- | --- | --- | --- | --- |
| Claude Code (claude-code) | `claude` 2.1.296 | `--session-id <uuid>  Use a specific session ID for the conversation (must be a valid UUID)` | yes (UUID) | — | `-r, --resume [value]` by session id |
| GLM wrapper (anthropic-compat) | shell wrapper over `claude` 2.1.296 via a local Anthropic-compatible bridge | wrapper ends `exec claude … --model glm-5.3 "$@"`: every caller flag passes through | yes (`--session-id`, passed through) | — | `--resume <id>` (passed through) |
| DeepSeek wrapper (anthropic-compat) | shell wrapper over `claude` 2.1.296 with DeepSeek's Anthropic-compatible endpoint | wrapper ends `exec claude … "$@"`: every caller flag passes through | yes (`--session-id`, passed through) | — | `--resume <id>` (passed through) |
| DeepSeek direct API (deepseek-api) | no CLI: Trinity is the HTTP client of the vendor API | — | yes: Trinity mints the id (UUID v4); the vendor API keeps no session | — | Trinity replays its own transcript (RDR-015) |
| Codex (codex) | `codex-cli` 0.160.0 | no id or name flag in `exec --help` (`--thread-source` is a source classification, not an id); `--json  Print events to stdout as JSONL` | no | (b) thread id in the first `--json` event (confirm by fixture); (c) per-call `CODEX_HOME` (never with `--ephemeral`, which writes no session file): the one `sessions/…/rollout-<time>-<uuid>.jsonl` file, whose line 1 is `type: session_meta` with `payload.id` (checked on a real rollout) | `exec resume [SESSION_ID]`: "Conversation/session id (UUID) or thread name" |
| droid (glm, minimax profiles) | `droid` 0.223.0 | `exec --help`: `-s, --session-id <id>  Existing session to continue (requires a prompt)`; no flag names a new session | no | (b) session id in `-o, --output-format` JSON output (confirm by fixture); (c) per-call session directory: to probe | `exec -s, --session-id <id>` |
| agy (agy) | `agy` 1.3.3 | no session-id flag in `--help`; `--conversation  Resume a previous conversation by ID` | no | (b) conversation id in `--output-format json` / `stream-json` output (confirm by fixture); (c) per-call session directory: to probe | `--conversation <id>` |
| OpenCode (opencode) | `opencode` 1.18.32 | `run --help`: `-s, --session  session id to continue`; no flag names a new session | no | (b) session id in `run --format json` raw events (confirm by fixture, OPEN-A2); (c) per-call session directory: to probe | `run -s, --session <id>` |

## 4. Environment assumptions

- Vendor CLIs installed and logged in where the harness needs login, on each host that runs them.
- Credential files exist at the profile's credential source with mode 600/400.
- Transcripts are written by the vendor to locations the reader can find (today `session_path.py` knows the claude-family slugs).
- macOS + Linux; POSIX sh wrappers, no zsh (TRN-2009).

## 5. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| ADP-R1 | Vendor CLI flag changes (codex `experimental resume` is now `exec resume`; droid `-s`) break resume silently | ADP-004 case per adapter (WO-002) |
| ADP-R2 | `claude -p` with a setup-token behaves differently from the isolated-config login | claude-code new + continue cases per profile (WO-002) |
| ADP-R3 | opencode session id / transcript format unknown today; heartbeat may be stdout-only | OPEN-A2 probe before WO-002 |
| ADP-R4 | Compatible endpoints accept the request but ignore model/effort fields | none yet; candidate: compare reported model in usage |
| ADP-R5 | Folding deepseek-api into anthropic-compat hides its own error classes (rate limit vs balance) | OPEN-A3; ADP-002 mapping test |
| ADP-R6 | Removing gemini breaks users with an old gemini agent installed | installer test in WO-002 |
| ADP-R7 | A reader shows summary thinking as full thinking | ADP-013 |
| ADP-R8 | A per-call session directory (DSP-020 layer c) lacks the profile's login or config, so the harness fails or runs under the wrong account; or it holds a copy of the login (for codex, `auth.json` in `CODEX_HOME`), which puts a credential file under Trinity's state directory and lets a token refresh written to the copy drift from the profile's real login | per-adapter fixture before build settles a link or read-only mount, never a copy; profile-check case per capture adapter |

## 6. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-A1 | Adapters as markdown agent files or core code? | **Decided by SCO-08/NG-06:** adapters are core code; agent files become thin front-end shims |
| OPEN-A2 | opencode: session id source, resume flag, transcript location | Open — probe before WO-002 |
| OPEN-A3 | deepseek both billing modes: subscription via opencode, metered via direct API — is deepseek-api then only a profile of anthropic-compat? | Open — WO-002 |
| OPEN-A4 | Which codex model ids are current, and who updates them (TRN-1006) | Open — WO-002 |
| OPEN-A5 | Ship an openrouter example profile? (adapter question settled: it is an anthropic-compat profile) | Open — WO-002 |
| OPEN-A6 | Default stall limits per adapter, and whether profiles may override | Open — WO-002 |

## 7. Verification to define in WO-002 (not done)

Per adapter: new session, continue session, missing session, bad credential, timeout kill, recursion guard present, no secret in argv/journal, retired model refused, usage absent when unreported, reader on a fixture transcript (all five event types, unknown line kept, summary thinking labelled, deleted transcript → `gone`).

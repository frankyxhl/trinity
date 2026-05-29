# PRP-3024: Loopback MCP Bridge for Peer-Finding Exchange

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-29
**Last reviewed:** (plan-review pending)
**Status:** Draft
**Reviewed by:** (pending)
**Related:** TRN-1000, TRN-1007, TRN-1008, TRN-2019, TRN-3000, TRN-3020, TRN-3023, GitHub issues #63, #137

---

## What Is It?

A loopback MCP (Model Context Protocol) bridge that Trinity starts at the top of `cmd_review` and exposes to each spawned provider via that provider's own MCP-config injection mechanism. The server publishes a small set of orchestration-aware read-only tools the provider can call mid-review, enabling cross-provider awareness without changing the parallel-dispatch model.

This PRP defines the v1 architecture, scope caps, provider support matrix, security model, and slice order for the full feature under parent issue #63. Each slice ships as its own CHG and PR.

---

## Problem

Trinity panel reviews currently run the N selected providers as **independent parallel monologues** — each provider sees the same prompt and the same diff, then writes its own `raw/<provider>.txt`. They never see each other's findings, so the synthesis step is the first (and only) place cross-provider comparison happens.

**Concrete evidence (PR #60)**: A 4-provider plan-review on PR #60 scored 9.3 mean across all 4 providers — every one of them PASSed. The Codex GitHub bot then surfaced 7 consecutive bugs the panel had missed. Root cause: each panel provider reviewed the diff in isolation. The bot, by contrast, traces caller flows and writer schemas — exactly because it can read the surrounding code.

A loopback MCP bridge lets provider B query "what's provider A worried about so far?" and either cross-check it (catching false alarms) or extend it (catching the bug A noticed but didn't fully chase). This converts the current "N parallel scoresheets" pattern into one where late-arriving providers raise the panel's hit-rate.

**Alternatives considered** (recorded in issue #63, reproduced here for PRP completeness):

| Alternative | Why rejected |
|---|---|
| **Status quo** — synthesis-only aggregation | Providers never see each other; methodology rule (PR #60 5-step) hits a ceiling because each provider is still reviewing in isolation |
| **Two-pass review** — everyone runs once, then again with peer findings in prompt | Doubles cost and latency; loopback MCP gives the same signal incrementally |
| **Pass peer findings as static prompt** | Only works for findings already complete before run-start; defeats the parallel-execution win |

---

## Scope

### In scope (v1)

**Four read-only MCP tools**, exposed as MCP tools callable by providers during their review turn:

| Tool name | What it returns | Data source |
|---|---|---|
| `trinity__current_scope` | Structured JSON re-read of files/diff hunks under review, including `diff --git` output and changed-file list from the review input. This duplicates prompt content intentionally so a provider can re-index scope by file path after a long reasoning/tool chain without reparsing its prompt. | Review input assembled by `cmd_review` before provider dispatch |
| `trinity__peer_findings_so_far` | Concatenation of completed `raw/<other-provider>.txt` output for providers that have already completed their turn. If no peer output has completed yet, returns `"status": "empty"` rather than blocking. | `review_dir/raw/` directory, read at call time; Slice A must read only completed provider artifacts |
| `trinity__prior_review_summary` | Structured summary (`synthesis.md` + `metadata.json` key fields) from the immediately prior review on this exact scope, if one exists. Scope matching is exact string equality against `metadata.json.input.scope`; no prefix or fuzzy matching in v1. Review directories with missing or malformed `metadata.json` are skipped; if no valid prior match remains, return `"status": "empty"`. | `.trinity/reviews/<prior_timestamp>-<scope>/` directory, resolved by exact metadata scope |
| `trinity__methodology_rule` | The current methodology rule text from TRN-1007 §4 Methodology (`### §4. Methodology (PR #60 / #61 / #64-derived 6-step rule)`), as a callable tool that providers can invoke programmatically | Read from `rules/TRN-1007-SOP-PR-Readiness.md` at MCP server start by matching the first heading whose line starts with `### §4. Methodology`; server startup fails with a clear error if the heading is missing; v1 may cache it for the review lifetime |

`trinity__peer_findings_so_far` is opportunistic in v1: Trinity still dispatches providers in parallel, and no provider is delayed just to create peer findings. The tool becomes useful when provider runtimes naturally differ, when a provider calls it later in its turn, or in the Slice F regression fixture where the test may deliberately stagger provider start times to make the peer-signal path observable. Slice A must expose only completed peer output: parent-side capture writes to a temp path and atomically renames to `raw/<provider>.txt` after provider exit, or uses an equivalent `.done` sentinel; in-progress partial bytes are not returned by the MCP tool. Concurrent calls return a snapshot of the completed outputs visible at call start, which is safe because completed artifacts appear atomically.

`trinity__methodology_rule` intentionally points to TRN-1007 rather than the historical TRN-3020 origin text. TRN-3020 introduced the 5-step prompt addendum, while later PR #60 / #61 / #64 lessons promoted the current aggregate method into TRN-1007 §4. Future edits to TRN-1007 §4 must preserve the `### §4. Methodology` heading prefix or update Slice A's lookup marker in the same PR.

**Tool response shape** — all tools return a JSON object with at minimum:
- `"status"` — `"ok"`, `"empty"` (no data available, not an error), or `"error"` for recoverable tool-level failures
- `"data"` — the payload (string for methodology_rule, object/array for the others), or null for `"error"`
- `"error"` — null for `"ok"` / `"empty"`; error message string for `"error"`

**Protocol and transports**: The MCP server exposes one shared read-only tool registry behind provider-specific HTTP transport adapters. Slice A must implement an async server core and document the exact MCP protocol version(s) it supports. Baseline targets: MCP `2024-11-05` for the HTTP SSE adapter and MCP `2025-03-26` for the streamable HTTP adapter, unless Slice A records a newer stable protocol version supported by the confirmed-v1 providers.

- **HTTP SSE adapter**: Required for providers whose current CLI supports MCP via an SSE URL. MCP over HTTP SSE uses a long-lived SSE stream for server-to-client messages and a separate POST endpoint for client-to-server requests. The server MUST be capable of holding concurrent SSE connections while accepting POST messages — a single-threaded synchronous handler cannot serve MCP/SSE.
- **Streamable HTTP adapter**: Required for Codex. Current Codex CLI exposes `codex mcp add --url` as a streamable HTTP MCP server path, so Slice C must attach Codex to a streamable HTTP endpoint (for example `http://127.0.0.1:<port>/mcp`) rather than an SSE-only `/sse` endpoint.
- **Endpoint requirement**: Slice A must serve both `/sse` and `/mcp` simultaneously on the same loopback port so Slice B and Slice C can run in the same review process.

Each tool is exposed as an MCP tool (request/response) rather than a resource — the provider invokes it via its own MCP SDK or tool-use mechanism, not via a static URL fetch.

**Security model**:
- Bind address: `127.0.0.1` only (loopback; never exposes to LAN/WAN)
- Port: OS-allocated ephemeral port (port 0; read back from the bound socket before writing the provider config)
- Authentication: Bearer token, generated at server start as a random 32-character hex string, passed to provider configs via environment variable `TRINITY_MCP_TOKEN`
- Termination: MCP server process is killed on `cmd_review` exit (both normal completion and SIGTERM/SIGINT/cancel); SIGTERM handler in the parent kills the MCP server subprocess before cleaning up provider process groups
- No TLS (loopback-only; bearer token provides auth; unencrypted localhost is acceptable per threat model)
- Request rate-limiting: v1 has no explicit rate limit. The server uses an async-capable HTTP framework or stdlib-compatible async server chosen in Slice A; a new dependency such as `aiohttp` must be justified against TRN-3000's CLI-backend minimalism. Each provider runs a single review turn with sequential tool calls within that turn, so concurrent tool-call volume is bounded by the number of in-flight providers.

**Write-tool exclusion (v1 hard boundary)**: The MCP server exposes **no write tools**. Providers cannot:
- Write to `raw/<provider>.txt` via MCP (Trinity's parent-side file writer owns this channel)
- Modify `metadata.json`, scope files, or any other review artifact
- Influence other providers' review sessions

This boundary is enforced at the tool-registration level — the server constructs only the four tool objects above. No dynamic tool registration path exists in v1.

### Out of scope (v1)

- Write tools (MCP or otherwise) — entire surface deferred
- Cross-review history beyond the immediate prior review summary
- Fuzzy or prefix scope matching for prior-review lookup
- Tool-call telemetry / logging of which provider called which tool when
- Dynamic provider registration or capability discovery through MCP
- Broadcast/diffusion of findings to not-yet-started providers (they discover via `trinity__peer_findings_so_far` at their start time)
- Rate limiting, server health APIs, or monitoring endpoints
- Non-loopback deployment (the server is intentionally bound to 127.0.0.1)

---

## Proposed Solution

### Architecture

```
cmd_review start
      │
      ├── 1. resolve review input (scope, diff, etc.)
      ├── 2. start loopback MCP server
      │         │
      │         ├── bind 127.0.0.1:<ephemeral-port>
      │         ├── generate TRINITY_MCP_TOKEN (32-char hex)
      │         ├── export as env var for all provider configurations
      │         ├── register 4 read-only tools
      │         └── serve until SIGTERM / review-complete
      │
      ├── 3. for each provider in provider list:
      │         inject MCP config (provider-specific mechanism)
      │         dispatch provider
      │
      ├── 4. wait for all providers (parallel)
      │         │
      │         └── providers call trinity__peer_findings_so_far
      │             during their turn → read completed raw/<other>.txt outputs
      │
      ├── 5. kill MCP server
      ├── 6. clear TRINITY_MCP_TOKEN from parent env
      ├── 7. write synthesis
      └── 8. cleanup / exit
```

### Provider Injection Matrix

Each provider needs MCP configuration injected into its environment before the CLI is invoked. The mechanism varies per provider:

| Provider | MCP injection mechanism | Status | Details |
|---|---|---|---|
| **claude-code** | Temp config file + `--mcp-config` flag | **Confirmed** (Slice B) | Write a temp `claude-config.json` with a `mcpServers.trinity` entry pointing at `http://127.0.0.1:<port>/sse` with `Authorization: Bearer <token>` header. Pass via `--mcp-config <tempfile>`. Temp file cleaned up in `at_exit` handler. |
| **codex** | Inline `-c mcp_servers.trinity.url=...` + `-c mcp_servers.trinity.bearer_token_env_var=TRINITY_MCP_TOKEN` config overrides | **Confirmed** (Slice C) | Attach to the streamable HTTP endpoint, not `/sse`. Pass the URL and bearer-token env-var name as supported Codex config keys, for example `-c mcp_servers.trinity.url="http://127.0.0.1:<port>/mcp"` and `-c mcp_servers.trinity.bearer_token_env_var="TRINITY_MCP_TOKEN"`. Do not use an unsupported `headers` object. If Slice C chooses `env_http_headers` or `http_headers` instead, it must prove the key is accepted by the installed Codex CLI and avoid leaking the raw token into logs. |
| **gemini** | **Unconfirmed in v1** — subject to Spike (Slice E) | Needs investigation | Gemini CLI (`gemini -p`) does not natively support MCP injection. Options: (a) wrap in a temp config that gemini's MCP subsystem reads; (b) extend gemini provider doc to note that gemini receives peer findings via a static prompt appendix instead of live MCP; (c) skip gemini for v1 and document as a limitation. |
| **glm** | **Unconfirmed in v1** — subject to Spike (Slice E) | Needs investigation | GLM via `droid exec` does not advertise MCP support. The `droid` CLI may reject unrecognized config keys. Likely outcome: GLM v1 receives peer findings as a static prompt appendix, not live MCP. |
| **openrouter** | **Unconfirmed in v1** — subject to Spike (Slice E) | Needs investigation | OpenRouter via `claude -p` backend wrapper inherits Claude's MCP config mechanism (temp config file + `--mcp-config`). However, OpenRouter's Anthropic-compatible endpoint may not support MCP tools in the API. The wrapper's `--mcp-config` flag would pass syntactically but the remote endpoint may ignore MCP tool declarations. |
| **deepseek** | **Unconfirmed in v1** — subject to Spike (Slice E) | Needs investigation | DeepSeek via `claude -p` backend wrapper inherits Claude's MCP config mechanism (temp config file + `--mcp-config`), with the same caveat as openrouter: the remote Anthropic-compatible endpoint may not support MCP tools. |

**Confirmed-v1 providers** (known working MCP injection): claude-code (Slice B), codex (Slice C). These two are the minimum viable set for the validation regression fixture (Slice F).

**Spike-needed providers**: gemini, glm, openrouter, deepseek (Spike, Slice E). The spike determines per-provider injection mode or documents the limitation. Slices B and C do not block on the spike.

### Security Model

1. **Loopback-only bind**: `127.0.0.1` hardcoded in server start; `aiohttp` or an equivalent async HTTP/SSE framework configured with `host="127.0.0.1"`. No IPv6 loopback (`::1`) in v1 — scoped to IPv4 loopback only.

2. **Ephemeral port**: `socket.bind(("127.0.0.1", 0))` → `getsockname()` to read actual port. The port value is embedded in each provider's MCP config at injection time.

3. **Bearer token**: Generated via `os.urandom(16).hex()` (32-character hex string) at server start. Stored in `os.environ["TRINITY_MCP_TOKEN"]` for the lifetime of `cmd_review`. Every incoming HTTP request to the MCP server checks `Authorization: Bearer <token>`. Mismatch or missing header → 401 response.

   **Token exposure by provider injection mode** — the token is unavoidably present in provider subprocess environments and may appear in temp config files or process argv depending on the provider:

   | Provider | Token medium | Risk |
   |---|---|---|
   | claude-code | Written to temp `claude-config.json` (on disk during review) | Low — private temp directory, mode 0600, cleaned up on exit |
   | codex | Environment variable `TRINITY_MCP_TOKEN`; Codex config argv contains only `url` and `bearer_token_env_var` key name | Low — raw token is not embedded in process argv; env is scoped to provider subprocess tree |
   | gemini/glm/openrouter/deepseek | Environment variable `TRINITY_MCP_TOKEN` (inherited by subprocess) | Low — env is scoped to provider subprocess tree |

   **Mitigations**:
   - Temp config files written to a private directory (`<review_dir>/mcp_config/`, mode 0700), cleaned up in `at_exit` handler.
   - Temp config files created with mode 0600.
   - Logging explicitly excludes config contents and bearer token values (log the config path, never the payload).
   - MCP server code never writes the token to review artifacts (`metadata.json`, `synthesis.md`, `raw/*.txt`). Provider LLM output is not filtered for token-like strings in v1; the token's short lifetime and loopback-only scope limit residual risk if a provider echoes its config.
   - Process-argv exposure is avoided for confirmed-v1 providers wherever the CLI supports bearer-token env indirection. Any future provider that requires raw-token argv exposure must document that exception and rely on the token's short lifetime (single `cmd_review` run).
   - MCP injection runs after TRN-3023 provider-environment sanitization, or `TRINITY_MCP_TOKEN` is explicitly preserved by the sanitizer. Slice A must add a regression test so future sanitizer broadening cannot strip the MCP token silently.
   - Parent cleanup deletes `os.environ["TRINITY_MCP_TOKEN"]` after the MCP server is stopped, even on cancel paths.

4. **Cleanup on exit/cancel**: The MCP server runs as a subprocess of the `cmd_review` parent. On normal exit, the parent sends SIGTERM and waits up to 5 seconds for graceful shutdown, then SIGKILL. On SIGTERM/SIGINT to the parent (user cancel), the signal handler:
   - Sets a `cancel` flag so running providers know they were cancelled (existing TRN-2019 pattern)
   - Sends SIGTERM to the MCP server subprocess
   - Continues existing cleanup (provider process-group termination)
   - The MCP server's own SIGTERM handler responds with 503 on any in-flight requests and exits

5. **No TLS**: Loopback-only + bearer token is sufficient for v1. Threat model: an attacker already on the machine with network access to `127.0.0.1` could guess the token — but that attacker already has broader access (env vars, filesystem, process list). Adding TLS would increase complexity (self-signed cert generation at server start) without materially improving the security posture for a local-only, read-only service.

### Slice Order and Dependency Graph

Parent issue #63 tracks the umbrella feature. Six child issues (including this PRP) implement it in order:

Slice letters are mnemonic, not a contiguous taxonomy: there is no Slice D in this plan. The remaining-provider investigation is named Spike E to preserve the issue split already filed under #141, and Slice F remains the final enablement/test slice under #142.

```
#137 (PRP)  ← THIS ISSUE
  │
  ├── #138 (Slice A) — MCP server lifecycle + 4 read-only tools
  │     Depends on: #137 (PRP approved)
  │     Delivers: scripts/mcp_loopback.py, MCP server start/stop in cmd_review
  │
  ├── #139 (Slice B) — claude-code injection
  │     Depends on: #138 (MCP server exists)
  │     Delivers: temp claude-config.json synthesis, --mcp-config injection in claude-code provider spawn code in scripts/codex.py
  │
  ├── #140 (Slice C) — Codex injection
  │     Depends on: #138 (MCP server exists)
  │     Note: #142 integration-tests this slice; #142 is not a merge gate for #140
  │     Delivers: streamable HTTP MCP config injection in codex provider spawn code in scripts/codex.py
  │
  ├── #141 (Spike E) — remaining provider support matrix
  │     Depends on: #138 (server exists to test against)
  │     Delivers: documentation of injection mode or static-prompt-fallback for gemini, glm, openrouter, deepseek
  │
  └── #142 (Slice F) — test/final enablement
        Depends on: #139, #140 (at least two confirmed-v1 providers working)
        Delivers: PR #60 regression fixture, final docs, CHANGELOG, parent #63 close
```

**Dependency graph**:

```
#137 ──→ #138 ──→ #139 ──→ #142 ──→ closes #63
  │               │
  │               └──→ #140 ──→ #142
  │
  └──→ #141 (spike, parallel with #139/#140; result feeds #142)
```

- Slices B and C (#139, #140) can be implemented in parallel after #138 lands.
- Spike E (#141) can run in parallel with B/C but its findings feed into #142 for the remaining providers' injection mechanism.
- #142 (final enablement) gates on at least two confirmed-v1 providers working (claude-code + codex).
- #142 is the only slice that closes parent #63.

### Validation Strategy

**Unit tests per slice**: Each CHG adds tests for its own deliverable:
- Slice A: MCP server lifecycle (start, tool registration, auth rejection, shutdown)
- Slice B: claude-config temp file generation, `--mcp-config` flag structure, cleanup, and provider-spawn wiring in `scripts/codex.py`
- Slice C: codex streamable HTTP config override generation, bearer-token env-var wiring, rejection of unsupported `headers` object configs, and provider-spawn wiring in `scripts/codex.py`
- Spike E: no tests (investigation only)
- Slice F: end-to-end regression fixture

**PR #60 regression fixture (Slice F)**: A test that replays the PR #60 diff under the new bridge with a 2-provider panel (claude-code + codex). Acceptance criterion: at least 1 of the 7 missed bugs from PR #60's Codex bot post-merge is caught by at least one provider that used the loopback MCP tools.

The seven PR #60 target bugs are sourced from TRN-2028's change history for PR #60 Codex bot rounds 1-7:

1. Interrupted review directories can have `incomplete.json` without `metadata.json`, and `trinity status` must still render them.
2. Cleanup payloads use the writer schema field `result`, not `status`.
3. `cmd_status` must resolve the repository root like sibling subcommands instead of reading `args.root` directly.
4. New subcommands must be reserved in preset-alias collision checks.
5. Failed orchestration status must render as `failed`, not `interrupted (failed)`, in the incomplete-only path.
6. The same failed-status rendering rule must apply in the metadata-present + incomplete path.
7. Same-second review directories must use an mtime tiebreaker rather than raw lexicographic directory-name order.

The fixture:
1. Checks out the PR #60 base commit, applies the PR #60 diff programmatically
2. Runs `trinity review --providers claude-code,codex --scope <pr60-scope>` with the loopback bridge enabled; the fixture may stagger provider start times or use a deterministic provider delay so `trinity__peer_findings_so_far` has observable peer output
3. Runs the same review again with the bridge disabled (control)
4. Asserts that the bridge-enabled run catches at least 1 finding that the bridge-disabled run misses, AND that the finding corresponds to one of the 7 documented missed bugs

This is the primary validation gate for the entire feature — proving that the bridge actually improves catch rate.

**Additional regression gates**:
- `make test` — all existing tests must remain green across all slices
- `make coverage` — TOTAL ≥ 80% across slices A–F
- `af validate --root .` — clean across all slices
- `make verify-built` — clean (if touching provider build artifacts)

---

## Test / Coverage Expectations

| Slice | Test additions | Coverage impact | Verification |
|---|---|---|---|
| A | 3–5 unit tests on MCP server + `cmd_review` lifecycle wiring | `scripts/codex.py` coverage may drop ~0.5% if startup/shutdown integration branches are not covered immediately | `pytest tests/` green |
| B | 2–3 unit tests on config file synthesis | net-neutral | `pytest tests/` green |
| C | 2–3 unit tests on Codex streamable HTTP config overrides | net-neutral | `pytest tests/` green |
| E | 0 (spike only) | unchanged | Spike report only |
| F | PR #60 regression fixture (1 test, ~80 lines) | codex.py coverage recovers as integration points become covered | Fixture passes with ≥1 bug caught |

**Slice A** additionally:
```bash
.venv/bin/pytest tests/test_mcp_loopback.py -v   # 3-5 server lifecycle tests
```

**Slice F** additionally:
```bash
.venv/bin/pytest tests/test_pr60_regression.py -v   # bridge-enabled > bridge-disabled catch rate
```

---

## Acceptance

- [ ] `rules/TRN-3024-PRP-Loopback-MCP-Bridge.md` exists and is plan-reviewed under fast-review tier (2-provider panel, both individual ≥9.5, no blocking findings).
- [ ] PRP explicitly bounds v1 to the four listed read-only tools; no MCP write tools present.
- [ ] PRP defines the five follow-up slice dependency graph (#138–#142) under parent #63, promoted by this PRP (#137).
- [ ] PRP documents security model (127.0.0.1, ephemeral port, bearer token, cleanup).
- [ ] PRP includes validation strategy gated on PR #60 regression fixture (≥1 of 7 missed bugs caught).
- [ ] PRP enumerates per-provider injection status (claude-code confirmed, codex confirmed, others TBD per spike).
- [ ] `af validate --root .` is clean on the PRP commit.
- [ ] `make verify-built` passes on the PRP commit; this is expected to be trivial for this docs-only PRP because no generated build artifacts are touched.

---

## Out of Scope / Deferred

- MCP write tools in any form
- Cross-review history beyond the immediate prior review
- Tool-call telemetry / access logging
- Rate limiting or server health endpoints
- IPv6 loopback support
- TLS / HTTPS for the MCP server
- Dynamic tool registration (tools are static for v1)
- Provider authentication beyond bearer token (no per-provider API keys)
- Non-loopback deployment (network-facing server)
- Gemini in the confirmed-injection set (deferred to Spike E; gemini's model card limitation is separate from injection mechanism)
- Generating `.agents/trinity.codex.json` or registry changes for MCP configuration (the injection is ephemeral — written at `cmd_review` start, cleaned up at exit — not persisted to config files)
- Broad telemetry (request counts, timing, error rates) — deferred to post-v1 engineering

---

## Authority Chain

- GitHub issue #63 — umbrella tracker for the full loopback MCP bridge feature
- This PRP (TRN-3024) — promotes #63 to a project PRP for `af`-tracked governance
- GitHub issue #137 — this PRP's tracking issue (spike / slice plan)
- GitHub issue #138 — Slice A: MCP server lifecycle + tools
- GitHub issue #139 — Slice B: claude-code injection
- GitHub issue #140 — Slice C: Codex injection
- GitHub issue #141 — Spike: remaining provider support matrix
- GitHub issue #142 — Slice F: test/final enablement, closes #63

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-29 | Initial draft promoting #63 content into a TRN PRP with architecture, provider matrix, slice order, security model, and validation strategy | Assembly |

# Changelog

## [Unreleased]

### Added
- `rules/TRN-3024-PRP-Loopback-MCP-Bridge.md` — Loopback MCP bridge PRP defining four read-only tools, provider injection matrix, slice order (#138–#142), security model, and PR #60 regression validation strategy. Closes #137, parent track #63.
- `scripts/mcp_loopback.py` — loopback MCP server lifecycle and four read-only tools: `trinity__current_scope`, `trinity__peer_findings_so_far`, `trinity__prior_review_summary`, and `trinity__methodology_rule`. Bearer-token auth, SSE and streamable HTTP transports, ephemeral port on 127.0.0.1, and lifecycle cleanup. Tests in `tests/test_mcp_loopback.py`. Closes #138, parent track #63.
- `scripts/codex.py` — claude-code loopback MCP injection: `_write_claude_code_mcp_config` temp config generation, `--mcp-config` flag injection in `run_provider`, and env-wiring through `run_providers`. Tests in `tests/test_codex_review_dispatch.py`. Closes #139, parent track #63.
- `scripts/codex.py` — codex loopback MCP injection (Slice C): `_build_codex_mcp_args` and `_insert_codex_mcp_args` for `-c mcp_servers.*` config overrides on the `codex exec` command line, plus `_codex_loopback_mcp_enabled` guard. Tests in `tests/test_codex_review_dispatch.py`. Closes #140, parent track #63.
- `tests/test_mcp_loopback_regression.py` — PR #60 regression fixture: BUG_TARGETS constant documenting all 7 missed-bug targets, deterministic peer-findings harness exercising the loopback MCP bridge, loopback-disabled control, and end-to-end cmd_review integration test. PASS criterion: ≥1 of the 7 bugs is surfaced through the loopback-enabled panel path. Closes #142, parent track #63.
### Docs
- Operator docs for loopback MCP enablement: supported providers (claude-code, codex), config flags (`enable_loopback_mcp`), and injection modes (claude-code: `--mcp-config` temp file; codex: `-c mcp_servers.*` overrides). See README §Configuration → Loopback MCP Bridge.
- TRN-2018 M1 — review status observability. `trinity status` now renders a
  live `Live state:` section when reading M1 metadata, showing each provider
  in `queued` / `running` / `finished` / `failed` / `timed_out` state with
  `pid`, `rc`, and elapsed seconds (when set). Pre-M1 metadata still renders
  via the legacy `Providers:` section unchanged. `metadata.json` is now
  written by `init_metadata` before `run_providers` and updated atomically
  via `_review_metadata.update_provider_state` as each provider transitions
  through its lifecycle, so observers no longer have to wait for the entire
  review to finish to see state.
- Incremental `logs/<provider>.std{out,err}.log` files written during
  `trinity review`. Stdout streams through a PTY-backed reader so
  line-buffered child processes flush progress before exit; stderr streams
  to its own log file. The existing `raw/<provider>.txt` artifact is composed
  from these logs after completion and preserves the `_STDERR_SENTINEL`
  boundary contract (TRN-3022 coupling).
- `trinity session-path <provider>[:<instance>]` — resolve absolute JSONL
  transcript path for a Trinity session. Unblocks token-efficiency audits
  and replay debugging. Closes #108.
- `rules/TRN-1209-REF-Multi-Agent-Loop-Config.md` — instantiates COR-1622
  parameter schema for trinity. Single source of truth for loop bindings
  (`<repo>`, `<consent-signal>`, `<panel-providers>`, `<wakeup-tool>`, etc.)
  plus trinity-only extension bindings (`$AGENT_GH_LOGIN`, `$TRUSTED_REACTOR`,
  concurrent-PR cap N≤2, agent-branch prefix regex, CLARIFY round-counter
  cap, fast-review-tier providers). CHG-3039.
- `rules/TRN-3039-CHG-Align-With-Promoted-PKG.md` — records the alignment
  rationale and surfaces.

### Changed
- TRN-3044 — TRN-1008 now requires an explicit Review Completion Gate before
  a PR can be called done or mergeable. The gate records `CLEAN` / `WAIT` /
  `BLOCKED` for the current head SHA, requires paginated GitHub reviews and
  thread-aware review state, treats stale bot reviews and unresolved non-outdated review
  threads as blockers, and adds a bounded no-wakeup fallback for runtimes without
  `ScheduleWakeup`. The §7 post-push closure checklist expands to 6 items
  to record the gate state, and TRN-1209 now clarifies bot-actor API login
  matching for current-head evidence. Pure-docs PRs skipped by workflow
  `paths-ignore` record `CI=N/A (paths-ignore)` when no required checks are
  configured.
- `install-manifest.json` — new manifest-driven install file listing. Both
  `install.sh` and `make install` read provider/script/bin file lists from
  this single source of truth instead of maintaining hardcoded, drift-prone
  copies. Add a new provider or script by editing `install-manifest.json`
  alone; both consumers pick it up automatically. The old TRN-1801
  install-list parity-diff check is subsumed by the manifest — drift between
  the two consumers is no longer possible by construction. Closes #79.
- TRN-3043 — designated `.agents/skills/trinity/SKILL.md` as the source of
  truth for the Codex skill text and made `plugins/trinity/skills/trinity/SKILL.md`
  a build-time copy. New `scripts/build_codex_skill.sh` wired into
  `make build` and `make verify-built`; pre-commit hook now also enforces
  byte-identity between the two copies. Both files remain on disk for
  packaging portability. Closes #76.
### Removed

- `dev/pr_update.py` and its 333-LoC test companion `tests/test_pr_update.py`. Replaced by `scripts/pr-update.sh` (~30 lines) driven from the same `make pr-update` target. Closes #74.
- `scripts/_compat.py` — new shared module exposing the guarded `fcntl`
  import. On `ImportError` (e.g. Windows), prints the existing
  unsupported-platform message to stderr and exits 1. Duplicated inline
  guards in `scripts/session.py` and `scripts/install.py` replaced
  with dual-mode `from ._compat import fcntl` / `from _compat import fcntl`
  imports, and the curl installer now downloads the shared helper alongside
  the other Python scripts. No behavioral change to lock call sites. Closes #78.
- TRN-3042 — TRN-1008 plan-review now requires GLM + DeepSeek + MiniMax
  (`trinity-minimax` added as the third plan reviewer). Code-review remains
  GLM + DeepSeek unless explicitly overridden. Worker routing is now
  role-split: implementation work goes to GLM; test-code work goes to
  DeepSeek. TRN-1209 bindings updated in lockstep.
- TRN-2018 M1 — `trinity status` (and `trinity status --latest`) behavior
  change: missing or empty `.trinity/reviews/` directory now exits **0**
  with `no reviews found` on **stdout** (was: exit 1 with
  `no reviews dir at <path>` / `no reviews under <path>` on stderr). Per
  CHG-2018 §Status Command contract.
- TRN-2018 M1 — `make_review_dir` (scripts/codex.py:1261) now creates
  `logs/` alongside `raw/` when constructing the review directory.
- TRN-2018 M1 — interrupted reviews (`KeyboardInterrupt` / `ReviewInterrupted`)
  now leave both `metadata.json` (init-time state with `status=running` and
  `provider_states` for each selected provider) and `incomplete.json`
  (cleanup status). Previously: interrupted reviews left only `incomplete.json`.
  `_print_review_summary` continues to surface `incomplete.json`'s status as
  the top-level verdict, so this change is internal to the artifact layout.
- `scripts/_version.py` — new shared module exposing `load_version()`. The
  identical inlined `_load_version()` helper that lived in `scripts/session.py`,
  `scripts/config.py`, `scripts/discover.py`, `scripts/install.py`, and
  `scripts/codex.py` (5 copies × ~8 lines each = ~40 LoC) is gone; each call
  site now imports `load_version` from `_version` (dual-mode: direct script
  exec + package import). Pure DRY refactor — no behavior change, same
  importlib mechanism for reading `scripts/__init__.py`. Closes #77.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` adopts PKG `COR-1617 §11
  Retrospective` (alfred v1.16.0). NEW `### 11. Retrospective` subsection
  inserted before Loop restart; existing `### 11. Loop restart` renumbered
  to `### 12.`. §Steps numbered list goes from 12 → 13 entries. §0 mapping
  table drops the `(no trinity equivalent)` row + "Phase 11 Retrospective
  NOT adopted" overlay. Body §11 → §12 renumbering across §1, §1.5, §2,
  §10, §12, §Guard Rails, §Failure Modes (~17 occurrences); §Examples and
  §Change History rows preserve historical §11 references. Trinity overlay
  on §11: codex-catch metric uses TRN-1209 `<bot-actors>` binding
  (`chatgpt-codex-connector[bot]`). §11 fires on ANY §10 (B) merge-watch
  wake that observes `mergedAt != null`, with two execution shapes split
  on `current_branch == watched_branch`: (i) on-watched-branch — full
  Steps 1-4 + cleanup + arm §12 (canonical State A); (ii) off-watched-
  branch — read-only inline (Steps 1-3, no cleanup, no §12-arm) to
  preserve active-work cancellation when the orchestrator has moved to a
  new agent-prefix branch. State B's mergeable-handoff still defers §11
  (PR not merged); once merge observed, retro runs via path (i) or (ii).
  Closes #83.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` aligned with the promoted
  PKG multi-agent loop family (COR-1615/1617/1618/1619/1620/1621/1622).
  New §0 "Relationship to PKG cluster" prologue maps every overlapping
  section to its owning COR doc and lists trinity-only overlays
  explicitly (§1.5 comprehension check; §10/§11 dual-state mergeable-gate;
  §11 State-B 3-branch guard; CHG-3037 wake-prompt-refs; CHG-3038
  round-counter; fast-review tier ≥9.5). Per-section "Shared with
  COR-XXXX" annotations added under each header that overlaps PKG.
  §Related list updated. CHG-3039.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1.5 CLARIFY workflow now
  uses comment-based dialogue (operator replies via new comment, not body
  edit) to avoid §1 rocket-gate body-edit invalidation. §1 rocket-gate prose
  documents the existing `commented` exemption explicitly. §Threat Model
  extended for comment-spoofing/spam analysis. Closes #100.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — §11 gains a mermaid
  `flowchart TD` visualizing the dual-state entry-precondition flow:
  stop-marker FIRST guard, three accepted branch states (a) `main` /
  (b) watched-branch token / (c) agent-prefix branch, with branch (c)
  expanded into all THREE conjunctive decision nodes (regex
  `^(codex|claude)/` + open-PR check + own-PR-mergeable check). PR #109
  R4 caught the wake prompt silently dropping conditions (2)+(3); the
  diagram now makes the 3-condition requirement visually obvious. Shares
  vocabulary with the §1 mermaid (ALL-CAPS node IDs, no-op exits, enter
  phase 1). Closes #111.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — §Failure Modes (b)
  counter-mechanism amendment + (f) active-work cancellation guard
  extended to cover §10 merge-watch counter dual-format + §10(B)
  procedure prose now documents extraction from both formats. CHG-3037's
  initial amendment only covered §1 idle-retry counter (`idle wake <N>
  of 12`); merge-watch counter (`merge_watch_count=<N> of 24` ref-style
  vs `merge-watch wake N of 24 for branch <BRANCH_NAME>` legacy inline)
  now both accepted formats. Closes the post-merge codex-bot finding on
  PR #114.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — §11 State-B git-branch
  guard branch (c) regex broadened from `^codex/` to `^(codex|claude)/` to
  accept Claude orchestrator branches alongside Codex (historical
  convention). Reflects reality: this repo's PRs are authored by either
  family. §2 branch hygiene + §11 branch-base policy parameterized to
  `<agent-prefix>/<slug>`. Multi-condition guard (open PR + own mergeable)
  unchanged.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — wake prompts refactored
  from inline FIRST/SECOND/THIRD pseudocode to § references (CHG-3037).
  New §Guard Rails entry "Wake-procedure duty" mandates orchestrator MUST
  Read referenced § literally on each wake. §Failure Modes (b)/(c) amended
  for dual-format support (ref-style + legacy inline). Eliminates the
  prompt-drift bug class caught in PR #109 R4. Closes #112.
- `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` — Decision Tree gains routing
  entries for TRN-1007 (PR Readiness), TRN-1008 (Multi-Agent Review Loop),
  TRN-1009 (Issue Filing). New `## Coverage audit` section with `comm -23`
  drift-detection snippet (every TRN-NNNN-SOP file must have a routing
  entry). Pre-existing staleness fixed: `pytest trinity/tests/` →
  `pytest tests/`; §What Is It? scope updated. Closes #104.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — §10 split into parallel
  mergeable-handoff trigger + merge-watch loop; §11 entry precondition relaxed
  to dual-state (A: post-merge, B: post-mergeable-handoff); §1 phase 1 gains
  orchestrator-side concurrent-PR cap (N≤2, fail-closed); §2 branch hygiene
  notes State-B rebase-cost; §Failure Modes adds "Mergeable-but-revoked"
  subsection. Closes #106.
- `rules/TRN-2002-PRP-Remote-Install-Script.md`, `rules/TRN-2008-PRP-Remove-Zsh-Dependency.md`,
  `rules/TRN-2010-PRP-Codex-Review-Adapter.md` — archived to `rules/archive/`. These PRP
  documents covered completed CHG work (TRN-2003, TRN-2009, TRN-2011 respectively) and were
  superseded by the corresponding implementation records. The active `rules/` directory is
  now uncluttered while preserving full git history via `--follow` on the archive paths.
  Closes #75.

### Added
- `providers/minimax.delta.md` + `providers/minimax.md` (auto-built) — new trinity-minimax worker provider backed by MiniMax 2.7 via `droid exec --model minimax-m2.7`. Mirrors the GLM-5.1 wiring; second non-Anthropic non-OpenAI voice for review/dispatch. Closes #103.
- `rules/TRN-1009-SOP-Issue-Filing.md` — canonical checklist for filing GitHub
  issues in `frankyxhl/trinity`: identity gate, `[Kind]:` title format,
  8-heading Blueprint intake body, `- [ ]` AC-checkbox gotcha, post-filing
  `/blueprint` round-trip, and 🚀-on-body placement. Standardizes the bot
  conventions surfaced by issues #55/#84/#88/#100. Closes #89.
- `trinity doctor` now surfaces wrapper-provider auth state (env-or-file
  precedence with mode 600/400 check, mirroring `providers/bin/<wrapper>`),
  timeout sanity warnings (timeout < 60s), shell env pollution from the
  TRN-3023 clearlist (so operators can audit `direnv` setups), and the
  resolved CLI string per provider. Required-provider auth issues are fatal
  (exit 1); optional-provider issues are demoted to warnings (exit 0). (#38)
- `resolve_preset_providers` returns `providers` (REQUIRED) and
  `optional_providers` keys in its metadata dict alongside the existing 5;
  doctor uses these to render REQUIRED/OPTIONAL split.
- `rules/TRN-1007-SOP-PR-Readiness.md` — gate checklist run by the author
  before opening a PR. Closes the documentation-drift gap PR #61 and PR #64
  surfaced (CHG passes panel + bot review but README/CHANGELOG drifts
  silently). Each new CHG's Acceptance Criteria table now references the
  relevant SOP sections by default. (#65)
- Structured review output schema (TRN-3022): providers may emit a fenced
  JSON block (`decision`, `weighted_score`, `blocking`, `advisories`) at
  the end of review output. Synthesis enriches the Status column with
  scores and renders a per-provider Findings section when structured data
  is present. Free-form providers continue to work via legacy returncode
  fallback. The addendum is code-side, gated on `task_type == "review"`.
  Closes #39. Foundation for #55.
- Synthesis aggregate summary (TRN-3028): `synthesis.md` now opens with a
  `## Summary` block (verdict, provider counts, mean score, blocking +
  advisory totals, convergence). `trinity review` also prints a one-line
  stderr summary on completion. Builds on TRN-3022 structured output.
  Closes #55.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` — captures the
  end-to-end orchestrator loop developed across PRs #66-#72: auto-pick →
  branch hygiene → plan → 4-provider plan-review (TRN-1800 weights,
  all-individual ≥9.0) → worker dispatch heuristic → verify → PR open
  → CI/bot/code-review panel iterate → triage → handoff. Drafted at
  TRN-12xx scope; intended for COR-1200 promotion once stable.
- `scripts/scan_rocket_issues.sh` — single-call GraphQL label-narrower
  for the TRN-1008 §1 rocket-gate Phase 1 scan (TRN-3029, CHG-3029).
  Returns OPEN issues with `blueprint-ready` label currently present;
  per-candidate `verify_rocket_eligibility` (REST) is authoritative for
  the full 5-check gate. Splitting narrowing from truth-checking avoids
  GraphQL nested-connection truncation bugs (reactions, timeline,
  labels) that any one-shot scanner would hit. Bash 3.2 compat; jq
  required. Installed to `~/.claude/skills/trinity/scripts/`.
- `tests/test_scan_rocket_issues.sh` — 8 mocked-`gh` test cases
  (T1a-T1h) covering label-presence, pagination, REPO discovery
  failure, `gh api` failure mid-pagination, empty repo, missing `jq`,
  and 100+ issues forcing pagination. (TRN-3029, #85)

### Changed
- `scripts/codex.py` — `STRICT_REVIEW_DECISION_RULE` parameterized per template
  (decoupled from fast-review-tier 9.5 default). Strict COR-1602/COR-1609
  reviews now correctly PASS at the template's `pass_threshold: 9.0`.
  Closes #98.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1 + NEW §1.5 + §5 + §7 + §8 + §Guard Rails + §Failure
  Modes + §Threat Model — orchestrator-discipline bundle: (1) §5
  worker dispatch is now DEFAULT (orchestrator-direct reserved for
  explicit exceptions list); (2) NEW §1.5 comprehension check (6-point
  rubric, PROCEED/CLARIFY/REJECT outcomes) inserts between Phase 1
  rocket-gate and Phase 2 branch hygiene; (3) §Guard Rails wait-state
  guard rule (no "I'll wait" without armed wake) + §7 5-item post-
  push closure-checklist + §8 entry-gate verification. **Operator-
  visible**: orchestrator dispatches more work to workers; reads
  unclear issues critically before branching; ensures every R-push
  has all 5 closure artifacts (reply on bot threads, 👍/👎, wake
  armed, status surfaced) before declaring complete. CHG-3033
  (PR #N). Closes #91, #92, #94.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1 rocket-gate now
  evaluates a 5th check (TRN-3029, CHG-3029): `blueprint-ready` label
  currently present AND most-recent `LABELED` event has `actor.login`
  ∈ `{iterwheel-blueprint[bot], $TRUSTED_REACTOR}`. Two-layer gate:
  intake quality (label) + consent (🚀). Mermaid `V` node and
  fail-closed prose use generic "all checks (see spec table)" wording
  — single source of truth. Bypass clause amended count-free: live
  chat input subsumes both consent and intake-quality signals.
  §Threat Model extended with the new attack/defense pair plus the
  bot-timing-race note. Closes #85.
- `rules/TRN-1006-SOP-Provider-Model-IDs.md` amended (TRN-3027): pin-location
  table now references `providers/registry.json` as authoritative for
  native-CLI providers (codex, glm); Section A steps replace "edit Makefile
  + install.sh register lines" with "edit `providers/registry.json`" — the
  install layer derives both from the registry post-TRN-3020. Wrapper
  providers (deepseek, openrouter, claude-code) keep model pins in
  `providers/bin/<name>` env blocks until TRN-3026 lands.
- `tests/test_install_sh.sh` path-sanity guard switched from a deny-list
  (`*' '*|*'?'*|*'#'*`) to a positive allow-list (`[A-Za-z0-9._/+-]+`).
  Catches `[`, `]`, `*`, `;`, `&`, `(`, `)`, quotes, `\`, `%`, and
  non-ASCII paths that bash globbing or `file://` URL parsing trip on.
  TRN-2027. (#57)
- `format_health_results` gains a `verbose` parameter (default False) plus
  `env_pollution` and `preset_metadata` kwargs. `cmd_doctor` calls with
  `verbose=True`; `cmd_review --check-providers` continues to use the
  default and emits the existing single-line format unchanged.
  First line per provider is still `{provider}: OK - {executable} (timeout Ns)`
  for grep compatibility. (TRN-3021)
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §1 / new §11 — phase 1
  self-drives via `ScheduleWakeup` idle-with-retry (1800s wake, matches §8
  "no work pending" cadence rule); explicit §11 Loop restart step (60s wake,
  §8 hard floor) replaces §10's informal "Move to phase 1" line. §Failure
  Modes gains "ScheduleWakeup unavailable / loop stop conditions" subsection
  covering 5 cases. **After a PR is handed off, the orchestrator
  automatically resumes picking without waiting for a cron tick.** External
  `/loop 10m` cron becomes optional. CHG-3030 (PR #90). Closes #90.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §10 merge-watch loop —
  fixes two correctness bugs from PR #93 R7 codex-bot review: (1)
  active-work cancellation: merge-watch wake's `prompt=` now embeds
  watched-branch token; mismatch on wake → wake is no-op (no auto-
  switch-and-pull). (2) Cap extended: `merge-watch wake N of 12` (270s
  × 12 = 54min) → `N of 24` (1800s × 24 = 12h) so async / branch-
  protected merges complete naturally. **Operator-visible**: merge-
  watch tolerates user-directed picks during the wait + waits up to
  12h for late merges (was ~54min, then silent abandonment). CHG-3031
  (PR #96). Closes #95.
- `rules/TRN-1008-SOP-Multi-Agent-Review-Loop.md` §4 + §8 panel rules:
  4 providers (gemini + codex + glm + deepseek) → 2 providers (glm +
  deepseek); PASS gate raised from "all-individual ≥9.0" to "both
  individual ≥9.5". §Failure Modes "≥3 viable providers" tiering
  replaced with 2-provider availability rule (no fall-through).
  §Guard Rails count-free per R17 SSOT. Codex's code-review
  contribution preserved via post-push bot
  (`chatgpt-codex-connector[bot]`); trinity-gemini signal lost
  (accepted tradeoff). **Operator-visible**: future panels run 2
  providers + ≥9.5 gate; expected ≥1 more R-iteration on average
  vs prior 4-provider/9.0 (PR #87 R3 9.0/9.0 would have been FIX
  under new rule). CHG-3032 (PR #97). Closes #88; supersedes #86.

## [3.2.0] - 2026-05-07

### Added
- `claude-code` is now a first-class Claude Code provider. `make install` and
  `install.sh` install `trinity-claude-code.md`, register
  `~/.claude/skills/trinity/bin/claude-code -p`, and ship an isolated nested
  Claude Code wrapper that disables Trinity recursion, uses separate
  `CLAUDE_CONFIG_DIR`, disables slash commands, and defaults to
  `--model sonnet --effort high`.

### Changed
- GLM now uses Droid Core `glm-5.1` with explicit highest supported reasoning
  effort: `--reasoning-effort high`. Claude Code installs keep
  `--auto medium` for normal development tasks, while Codex-native review
  config stays read-only and only changes the model/effort flags.
- `README.md` refreshed to track current SKILL behavior: documents preset
  dispatch (`/trinity review|fast-review|deep-review` plus `r`/`fr`/`dr`
  aliases) in the Command Reference and a new "Review presets" section, adds
  a `presets` / `preset_aliases` snippet to the manual `~/.claude/trinity.json`
  example, updates the Architecture diagram to include `scripts/`, `bin/`, and
  the deepseek/openrouter/claude-code agent files, and restructures the Codex
  Compatibility section into Install / Provider health / Run a review /
  Update a PR / Repo-local skill & plugin subsections without dropping
  concrete examples.

## [3.1.1] - 2026-05-06

### Fixed
- README install-version examples now match the release version, and the release metadata gate covers README examples via `make bump`, `make release-prep`, and tests.

## [3.1.0] - 2026-05-06

### Added
- Codex-native review adapter: `.agents/trinity.codex.json`, `scripts/codex.py`, `bin/trinity`, and `make install-codex` install a `trinity review --providers glm,gemini,deepseek` workflow under `~/.codex/` / `~/.local/bin`. The wrapper collects tracked plus untracked git changes, saves raw provider outputs, and writes deterministic review synthesis markdown without using Claude Code worker-agent runtime.
- `rules/TRN-2010-PRP-Codex-Review-Adapter.md` and `rules/TRN-2011-CHG-Codex-Review-Adapter.md` document the approved design and implementation record. New tests cover Codex config/install/review behavior plus Claude Code compatibility.
- `trinity doctor` and `trinity review --check-providers` preflight Codex review providers for config shape, command lookup, executable permissions, and timeout values before review dispatch.
- `trinity review --base <base> --head <head>` and `trinity review --pr <number>` add committed branch / GitHub PR review modes for Codex-native Trinity review.
- Codex config now seeds `review`, `fast-review`, and `deep-review` preset definitions plus `r`/`fr`/`dr` aliases, and `make install-codex` preserves those sections in `~/.codex/trinity.json`.
- `trinity review --preset <name>` and `trinity doctor --preset <name>` now resolve review presets and aliases, use `review.default_preset` by default, preserve `review.default_providers` as the compatibility fallback, and record skipped optional providers in review metadata.
- Strict COR review mode: `trinity review --sop COR-1602 --rubric COR-1609` prepends COR-1609 weights, COR-1611 calibration guidance, PASS threshold, and required output schema to Codex-native reviews.
- `make pr-update` and `dev/pr_update.py` add a guarded PR update helper that validates, amends or commits, pushes, and comments with verification evidence.
- Codex-native review dispatch now runs selected providers concurrently up to `review.max_parallel_providers`, logs progress on stderr, cleans up provider process groups on timeout or interrupt, writes `incomplete.json` for partial reviews, and adds review-only prompt guidance.

### Fixed
- Backfilled validator-required sections and change-history tables in older TRN docs (`TRN-1001` through `TRN-1005`, `TRN-2002`, `TRN-2003`), bringing `af validate --root .` to 0 issues.
- Codex review provider calls now use a short prompt-file handoff instead of passing the full rendered review prompt as argv, avoiding OS argument-length failures on large diffs.
- Codex DeepSeek review config now uses the installed `~/.codex/skills/trinity/bin/deepseek -p` wrapper instead of the locally rejected `droid exec --model deepseek-v4-pro[1m]` alias.
- Committed PR branches can now be reviewed without relying on dirty working-tree diffs, avoiding misleading "(no tracked or untracked git diff)" review prompts after changes are already committed.
- Duplicate Codex review provider selections are rejected before creating a review directory so one provider result cannot overwrite another.
- Local Claude Code state is ignored so `.claude/` runtime files do not leak into project commits.

## [3.0.0] - 2026-04-29

### Added
- Codex compatibility packaging: repo-local skill at `.agents/skills/trinity/SKILL.md`, local plugin manifest at `plugins/trinity/.codex-plugin/plugin.json`, bundled plugin skill at `plugins/trinity/skills/trinity/SKILL.md`, and repo marketplace entry at `.agents/plugins/marketplace.json`. Added `tests/test_codex_compat.py` to validate the import surfaces and README smoke-check documentation while preserving the existing Claude Code install path.

## [2.0.5] - 2026-04-26

### Fixed
- `Makefile` `bump` target: replace BSD-only `sed -i ''` with portable `perl -i -pe` for both `__version__` (in `scripts/__init__.py`) and `REQUIRED_VERSION` (in `SKILL.md`) rewrites. The prior form failed on Linux because GNU sed treats `''` as the input file path — a Linux maintainer running `make bump` would have hit the same trap class as the v2.0.0 stat-order incident. Found by the first run of the TRN-1801 evolve cycle (signal: cross-platform shell trap grep). Pre-existing version pins were already in sync (VERSION=2.0.3 / `__version__=2.0.3` / `REQUIRED_VERSION=2.0.3`), so this is preventive, not a fix-after-incident. New `tests/test_make_bump.sh` adds two regression cases — T1 verifies `perl -i -pe` rewrites both pin files and preserves unrelated lines; T2 is a static guard that fails if anyone re-introduces `sed -i ''` in the bump target. Wired into `make test`.
- `rules/TRN-1006-SOP-Provider-Model-IDs.md`: backfill canonical SOP structure — add `Last reviewed` metadata, `## When to Use`, `## When NOT to Use`, and rename `## Steps — Updating a Model ID` to `## Steps` with a one-line preamble (the suffix tripped `af validate`'s exact-match section check). Brings the SOP added in v2.0.3 to the same shape as TRN-1801 / TRN-1000.
- Metadata backfill across 8 PRJ docs flagged by `af validate`: `TRN-1004-SOP-Release.md` and `TRN-1005-SOP-Install.md` now carry `Last reviewed: 2026-04-26`; `TRN-2003/2004/2005/2006/2007/2009-CHG-*.md` now carry both `Last updated` (matching their original `Date`) and `Last reviewed: 2026-04-26`. Drops `af validate` issue count from 43 → 24.
- `rules/TRN-1003-SOP-Version-Bump.md` line 24: replace stale "BSD `sed -i ''` syntax" note with the new portable `perl -i -pe` form and a pointer to `tests/test_make_bump.sh`. Caught by Codex in the §5 Reviewer A gate on the diff — active-SOP drift would have left a future contributor reading "never invoke `make bump` from CI" while the actual implementation was already cross-platform. Added `Last reviewed` while touching the metadata.

### Notes
- First run of the TRN-1801 evolve cycle. Four-reviewer gate met (Codex 9.1 / DeepSeek 9.5 / GLM 9.2 / Gemini 9.3, mean 9.275, all PASS ≥9.0). Codex initially returned 8.4/FAIL on the diff (caught the TRN-1003:24 active-SOP drift blocker that lead missed); resolved by C5 patch then re-gated to PASS. Shipped as merged PR #14. Skipped C3 (TRN-1001/1002/1003/1004 structural-section retrofit) — atomicity rule splits it into 16 sub-candidates, deferred for a future cycle.
- **v2.0.4 was skipped.** A `v2.0.4` tag was pushed to origin pointing at the cycle-1 PR-merge commit (where VERSION was still 2.0.3), without the `Release v2.0.4` commit having reached origin. CI's `verify` job correctly rejected the mismatch (TRN-2007 working as designed — no GitHub Release was published). Per TRN-1801 guard rail "fix forward with a patch bump, do not force-push the tag," the cycle ships as v2.0.5. The dead `v2.0.4` tag remains on origin with no Release attached.

## [2.0.3] - 2026-04-26
### Added
- `rules/TRN-1800-REF-Evolution-Philosophy.md` — PRJ-layer override of COR-1800 for the trinity repo. Defines trinity-specific behaviour baseline (the union of `make test` / `make verify-built` / `make lint` / `install.sh` share-readiness against tmp HOME / Linux CI parity / dispatch sample), and overrides COR-1800's code-evolution and document-evolution weight tables plus the signal-source table with trinity-specific axes (cross-platform parity, generated-vs-source build via `_base/`, `Makefile`↔`install.sh` provider-parity, model-ID drift vs vendor docs).
- `rules/TRN-1801-SOP-Evolve-Trinity.md` — concrete evolve loop wired to TRN-1800. Six-step Signal → Candidate → Evaluation → Implementation → Review → PR cycle; signal-collection commands are runnable shell snippets (build drift, provider parity, BSD/GNU shell traps, model-ID drift, install.sh smoke against `mktemp -d`, CHANGELOG `[Unreleased]` lag, SOP↔code drift, `af validate`); surface taxonomy distinguishes single-purpose files vs multi-section docs vs symmetric multi-file refactors (the two recognised symmetric classes are `_base/*.md` → 5-provider cascade and the two Anthropic-compat `bin/` wrappers); guard rails explicitly call out the v2.0.0 stat-order class of macOS-only-test-passes-but-Linux-CI-fails bug. Mirrors the CLD-1800/1801 shape used in the `~/.claude/` repo.
- `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` decision tree: paths 6 (TRN-1006 model-ID pinning) and 7 (TRN-1801 evolve cycle) added with explicit trigger phrases ("run evolve", "audit trinity", "bump model"); existing feature/incident/TDD paths shifted to 8/9/10. Future sessions reach the new SOPs from a cold start via `af read TRN-1000`.

### Fixed
- `rules/TRN-1801-SOP-Evolve-Trinity.md` §1 parity-diff command produced false positives — Makefile uses TAB indent + `$(HOME)` while install.sh uses 4-space indent + `${HOME}`, so a literal `diff` reported every line as drift even when parity was fine. Now normalised via a `_norm` shell function (`sed -E 's/^[[:space:]]+//; s/\$\(HOME\)/${HOME}/g'`) before sort. Caught by DeepSeek in Round-1 of the 3-model strict review on the docs.
- `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` metadata: `Last updated` and `Last reviewed` were stuck at 2026-03-21 despite multiple 2026-04-26 edits to the decision tree. Bumped to current date. Caught by Codex in the same review.
### Changed
- `providers/bin/deepseek`: pin `ANTHROPIC_MODEL` to `deepseek-v4-pro[1m]` (1M-context tier) instead of the bare `deepseek-v4-pro` (default-context tier). The `[1m]` suffix is a literal model-ID convention for the 1M-context variant — same shape as Anthropic's `claude-opus-4-7[1m]` — NOT an ANSI escape. Regression assertion in `tests/test_anthropic_compat_wrappers.py::test_t1_deepseek_env_key_sets_anthropic_env_and_passes_argv` guards future copy-paste from accidentally stripping the suffix. `ANTHROPIC_SMALL_FAST_MODEL` stays at `deepseek-v4-flash` (small-fast tier rarely needs 1M context).
- New SOP `rules/TRN-1006-SOP-Provider-Model-IDs.md` documenting the `[1m]` suffix convention, where each provider's model ID is pinned (native-CLI providers vs Anthropic-compat wrappers), and the update workflow with shell-quoting guard rails.

### Fixed
- `README.md`: refresh stale version examples (`Trinity 1.4.0` → `2.0.1`, `TRINITY_VERSION=1.1.0` → `2.0.1`) and document the new `bin/` wrappers shipped in v2.0.0. The "What was installed" table now lists `~/.claude/skills/trinity/bin/{deepseek,openrouter}`. The "Or install manually" block was actively misleading on v2.0.0 — it omitted the `mkdir -p .../bin/`, `cp providers/bin/*`, and `chmod +x` steps, so anyone copying it ended up with broken DeepSeek/OpenRouter providers (no wrapper script to invoke). The manual `trinity.json` example also picks up the `-m gpt-5.5` codex pin (TRN-2005, shipped in v1.6.0) that was never reflected.

## [2.0.1] - 2026-04-26
### Fixed
- `providers/bin/{deepseek,openrouter}`: swap `stat` invocation order — try GNU `stat -c '%a'` first, fall back to BSD `stat -f '%Lp'`. The original BSD-first order broke on Linux because GNU `stat`'s `-f` is `--file-system` (filesystem-info mode, not format-string), which returns exit 0 with a multi-line block of filesystem stats, so the `||` fallback never fires and `PERM` ends up as multi-line garbage that fails the `case 600|400)` match. All key-file paths refused with a confusing "perm <multiline> 600" message. macOS local tests passed because BSD stat's `-f '%Lp'` works there. Caught by the v2.0.0 release CI on Linux runner — TRN-2007's verify/publish split prevented a broken release from being published. After the swap: GNU `-c '%a'` is the unambiguous primary path (Linux); BSD `-c` is invalid and fails fast (macOS), letting the `-f '%Lp'` fallback return the right value. Existing tests T2/T5/T6/T6b/T7 are the regression — they were the ones that failed on Linux CI and now pass on both platforms.

## [2.0.0] - 2026-04-26
### Changed (BREAKING for re-install)
- **Removed `.zshrc` dependency from `deepseek` and `openrouter` providers** (TRN-2008 PRP / TRN-2009 CHG). Both providers now use portable POSIX `sh` wrappers shipped at `providers/bin/{deepseek,openrouter}` and installed to `~/.claude/skills/trinity/bin/` by `install.sh` and `make install`. Fresh users no longer need to copy any shell-rc snippet to use these providers. API key resolves from `$<PROVIDER>_API_KEY` (env wins, 12-factor) or `~/.secrets/<provider>_api_key` (mode `0600` or `0400`; anything more permissive is hard-refused with a stderr message). The wrappers `exec claude --dangerously-skip-permissions "$@"` so signals propagate cleanly. **Migration:** existing users with `"cli": "deepseek_cy -p"` / `"openrouter_cy -p"` in `~/.claude/trinity.json` MUST re-run `install.sh` (or `make install`) — it overwrites those two `cli` entries to absolute-path form. After re-install, the legacy `deepseek_cy` / `openrouter_cy` zsh functions in `.zshrc` are no longer reached and can be deleted at leisure. Other providers (`glm`, `codex`, `gemini`) untouched. Approved per COR-1602 strict review (4 reviewers, converged in 2 iterations: Codex 8.9, Gemini 9.8, GLM 8.8, DeepSeek 10.0) plus a final GLM implementation review. New `tests/test_anthropic_compat_wrappers.py` (17 cases) covering env precedence, perm-check refusal, mode-400 acceptance, `--resume` argv ordering, and the BSD/GNU `stat`-fails-on-exotic-FS branch; new T9 + T11 in `tests/test_install_sh.sh` covering bin-script install + legacy migration. PR #13.

### Fixed
- `.github/workflows/release.yml` `Publish GitHub Release` step: when a `push.tags` event finds a release already published (Path A duplicate-trigger or Path B re-run), the step exits cleanly (exit 0) instead of failing with "Release already exists". Surfaced on the v1.8.0 end-to-end run — TRN-2007 D11's PAT path re-triggers the workflow on every Path A push (PAT-pushed tags fire workflows; GITHUB_TOKEN-pushed ones don't, which the original review missed). The `workflow_dispatch` retry path still fails loud on existing release (operator explicitly asked to re-publish; tell them it's already done). Trade-off documented inline: a maintainer admin-bypass force-push to a tag with a stale release will silently skip publish — the tag-protection ruleset's "Restrict updates" rule narrows the risk window. Multi-model review on the initial fix (Codex PASS / Gemini FAIL on force-push concern) → log message neutralized + 5 T11 assertions covering control-flow placement, not just string presence.
- `.github/workflows/release.yml`: new `preflight` job short-circuits the duplicate tag-push trigger before `verify`/`publish` run (issue #11). Prior fix exited cleanly at the publish step but still burned ~3 min on `verify` (checkout + setup-uv + install + verify-built + test + lint + extract-notes). Preflight runs a single ~5s `gh release view` check; on tag-push events for already-published tags it sets `skip=true` and both `verify` and `publish` are skipped via `if: needs.preflight.outputs.skip != 'true'`. `workflow_dispatch` events bypass the preflight check entirely (operator intent: run it). The publish step's in-script `EVENT_NAME == push` exit-0 branch is retained as defense-in-depth for the race window between preflight and publish. New T12 (9 assertions) + T1/T11 updates (3 changes) cover the new job structure (103/103 total).

## [1.8.0] - 2026-04-26
### Added
- **One-click release** via Actions UI (TRN-2007). The `workflow_dispatch` trigger on `release.yml` now accepts an optional `tag_name` input; leaving it empty derives `vX.Y.Z` from the `VERSION` file on the dispatched ref, creates and pushes the tag, then publishes — all in one workflow run. Click "Run workflow" from the Actions tab on `main` and you're done. A new main-only guard rejects one-click attempts from feature branches; the explicit-`tag_name` retry path remains unchanged. TRN-1004 SOP restructured into Path A (one-click) / Path B (tag push CLI) / Path C (retry).
- **2-job verify/publish split + concurrency + env-mapping hardening** (TRN-2007 D9–D12, post multi-model review). The release workflow is now `verify` (read-only, runs verify-built/test/lint/extract-notes/upload-artifact — third-party actions like `astral-sh/setup-uv` cannot push tags) → `publish` (write, only first-party actions, downloads artifact, creates+pushes tag, calls `gh release create`). New `concurrency: { group: release, cancel-in-progress: false }` prevents simultaneous dispatches from racing. All `${{ github.* }}` references in `run:` blocks moved to `env:` mapping. `gh release create` scoped via explicit `--repo "$GITHUB_REPOSITORY"`. New `tests/test_release_workflow.sh` T10 (12 assertions) + T11 (17 assertions) cover all of the above (81/81 total).

### Changed
- `.github/workflows/release.yml`: bump action pins to Node 24 majors — `actions/checkout@v4`→`@v6`, `actions/upload-artifact@v4`→`@v5`, `astral-sh/setup-uv@v5`→`@v6`. Resolves Node 20 deprecation annotation surfaced on the v1.7.0 release run. setup-uv@v8 was skipped because it removed floating major tags (`@v8` no longer resolves) — staying on `@v6` keeps the workflow low-maintenance. `tests/test_release_workflow.sh` assertions updated.

### Fixed
- `.github/workflows/release.yml`: add `cache-dependency-glob: 'Makefile'` to the `setup-uv` step. Resolves the "No file matched to [**/uv.lock,**/requirements*.txt]. The cache will never get invalidated." annotation surfaced on the v1.7.0 release run. Trinity has neither `uv.lock` nor `requirements*.txt`; deps live in `Makefile` (`uv pip install pytest ruff`), so that file is the right cache key.

## [1.7.0] - 2026-04-26
### Added
- `.github/workflows/release.yml`: tag-push triggers automated GitHub Release publish (TRN-2006). Strict semver glob `v[0-9]+.[0-9]+.[0-9]+` for trigger; `workflow_dispatch` with `tag_name` input for manual retry. Defense-in-depth tag/VERSION validation, tag-must-be-on-main check, CHANGELOG section extraction (fail on empty), least-privilege permissions (global `contents: read`, only the publish job gets `contents: write`). No third-party publish actions — direct `gh release create` only.
- `make release-prep`: local-only target replacing `make release`. Runs verify-built/test/lint, stages 4 metadata files, commits `Release vX.Y.Z`, creates local tag. Does NOT push, does NOT publish. CI handles the publish on tag push.
- `tests/test_release_workflow.sh`: 52 assertions covering workflow structure, semver regex, CHANGELOG awk extractor (4 fixture cases: full / last / missing / header-only), tag↔VERSION matcher (whitespace-trim + leading-`v` handling), Makefile invariants. Wired into `make test`.

### Changed
- `make setup`: uv → pip fallback. Local devs and macOS keep using uv (faster); CI installs uv via `astral-sh/setup-uv@v5`. If neither, falls back to stdlib `python3 -m venv` + `pip`.
- TRN-1003 step 4: now references `make release-prep` instead of `make release`. Adds explicit warning that `make bump` uses BSD `sed -i ''` and must NEVER run in CI.
- TRN-1004: full rewrite for the new flow (PR-merge → `release-prep` → tag push → CI publishes). Documents `workflow_dispatch` as the only sanctioned retry path.
- TRN-1000 decision tree path 4 wording.

### Removed
- `make release`: deleted (not deprecated). Calling it now prints `make: *** No rule to make target 'release'` — intended footgun-prevention.

### Notes for users
- **One-time setup required**: protect the `v[0-9]+.[0-9]+.[0-9]+` tag pattern in repo settings → Rules → Rulesets, restricting create/update/delete to maintainers. Without this, anyone with write access can publish a release by pushing a tag.
- The release workflow uses the workflow-issued `GITHUB_TOKEN` only — no PAT, no OIDC, no secrets. Supply chain is `actions/checkout@v4` + `astral-sh/setup-uv@v5` + `actions/upload-artifact@v4` + direct `gh` calls.

## [1.6.0] - 2026-04-26
### Changed
- `trinity-codex`: pin model to `gpt-5.5` via `-m gpt-5.5` on every `codex exec` / `codex exec resume` call (TRN-2005). Default codex CLI registration in `Makefile` and `install.sh` now includes the flag, so `make install` / remote `install.sh` produce a deterministic codex provider regardless of the user's local `~/.codex/config.toml` default model.
- `trinity-codex` agent prose: GPT-5.4 → GPT-5.5.

### Notes for users
- **Requires codex-cli ≥ 0.125** (when `gpt-5.5` became available). Older CLIs will fail with "unknown model"; upgrade codex-cli before reinstalling Trinity.
- **Reinstall recommended** to pick up the pinned `-m gpt-5.5` flag in `~/.claude/trinity.json` and the refreshed `trinity-codex.md` agent file.

## [1.5.0] - 2026-04-25
### Changed
- **Provider templates now built from shared partials** (TRN-2004). `providers/*.md` are generated from `providers/_base/{common-session,common-tail,family-wrapper}.md` + `providers/<name>.delta.md` via `scripts/build_providers.sh`. Single source of truth, single edit propagates to all 5 providers. Source LOC reduced ~200 lines; install footprint and runtime behavior unchanged.

### Fixed
- `trinity-codex`: replace `-c reasoning.effort=high` (silently ignored by codex-cli 0.124+) with `-c model_reasoning_effort=$EFFORT`. Default `xhigh`. Per-prompt `EFFORT=<level>` override parsing (valid values: `none`, `low`, `medium`, `high`, `xhigh`).
- `trinity-openrouter` / `trinity-deepseek`: replace race-unsafe `ls -t | head -1` JSONL selector with prompt-marker grep (`TRINITY_TRACE`). Bash 3.2 compatible (works on macOS default `/bin/bash`); robust under sub-second concurrent dispatches in the same project.
- All 5 providers: lifted "If the provider produces code, verify it looks reasonable before returning" rule into common partial — previously inconsistent (codex/glm only).

### Added
- `make build`: regenerate `providers/*.md` from partials.
- `make verify-built`: assert committed providers match generated output (drift gate). Runs as part of `make test` and `make release`.
- `make install-hooks`: install pre-commit hook that runs `verify-built`.
- `tests/test_build_providers.sh`: 96 assertions (T1 determinism, T2 frontmatter, T3 trailing LF, T4 partial invariants, T5 no stale `@include`, T6 semantic section presence + H3-under-H2 hierarchy walker, T7 drift sentinels for the 3 bundled fixes).
- SOP updates: TRN-1003 notes `make build` runs in `make bump`; TRN-1004 adds `make verify-built` prerequisite.

### Notes for users
- **Reinstall recommended** to pick up the three bundled bug fixes — especially the codex reasoning-effort fix, which silently degraded Codex output on 1.4.0.
- **Local hand-patches will be overwritten on reinstall.** If you previously hand-patched `~/.claude/agents/trinity-codex.md` or `trinity-deepseek.md`, the upstream fixes subsume those patches; reinstalling 1.5.0 overwrites your local edits (intended behavior).

## [1.4.0] - 2026-04-24
### Added
- DeepSeek V4 provider (default model: `deepseek-v4-pro`, 1M context, session resume via `claude --resume`)

### Fixed
- `install.sh`: download + register `openrouter` provider (missing since v1.3.0)
- `providers/codex.md`: replace removed `-r xhigh` short flag with `-c reasoning.effort=high` (codex CLI 0.124+ dropped the short form)

## [1.3.0] - 2026-04-04
### Added
- `session.py heartbeat <output_file>`: parse JSONL output files and report agent activity
- OpenRouter provider with portable `run_openrouter()` fallback (no custom wrapper required)
- 6 new heartbeat tests (46 total)

### Changed
- Release SOPs (TRN-1003, TRN-1004): require code commit before version bump

## [1.2.1] - 2026-04-03
### Fixed
- Include heartbeat code in release (v1.2.0 only had version-bump files)

## [1.2.0] - 2026-04-01
### Added
- `session.py heartbeat <output_file>`: parse JSONL output files and report agent activity, replacing inline Python snippets

## [1.1.1] - 2026-03-22
### Added
- README: "If You Are an AI" installation guide for LLM agents

## [1.1.0] - 2026-03-22
### Added
- Remote install script (`install.sh`): `curl -fsSL .../install.sh | bash`
- Shell test suite (`tests/test_install_sh.sh`): 8 integration tests (T1-T7, T3b)
- Default provider registration (glm, codex, gemini) on install via `install.py register`
- trinity-gemini: specify `--model gemini-3.1-pro-preview` for all CLI calls
- 2 new session tests (whitespace-only file, corrupt JSON) — 40 pytest tests total

## [1.0.0] - 2026-03-21
### Added
- Initial release: session.py, config.py, discover.py, install.py
- Provider templates: glm, codex, gemini
- SKILL.md with full /trinity command set
- 38 pytest tests

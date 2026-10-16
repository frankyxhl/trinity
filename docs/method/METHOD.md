# Trinity 法式 (Method Specification) — draft 0.3 · method basis: CraftCode v0.1

Status: **draft, WO-001 + WO-002 (contracts).** Nothing here is accepted or verified.
Baseline: Trinity 3.3.0 — the public `main` plus later commits not yet public — decided, see OPEN-01.

This file states what every Trinity component must agree on: scope, terms, rules, risks, open items. Component boundaries are in the four `spec-*.md` files beside it; full component contracts and failure expectations are in `../contracts/` (dispatch core, transcript reader, graph).

## 0. Baseline and sources

- Code baseline: Trinity 3.3.0, i.e. the public `main` plus later commits not yet public; the exact commit is recorded outside this repo. Other copies (an unmerged model-id guard branch, locally installed copies) are **reference input only**; any fix they carry is re-specified from WO-002, not ported.
- Today's shape at the baseline: a host skill (`SKILL.md`) that spawns one background worker per call from generated agent files (`providers/<p>.delta.md` + `providers/_base/*.md`); a registry (`providers/registry.json`: cli, resume flag, timeout per provider); shell wrappers in `providers/bin/`; sessions per instance key in `<project>/.claude/trinity.json` (`scripts/session.py`, `fcntl.flock`); a review pipeline (`scripts/_review.py`, `provider_runtime.py`, per-review `metadata.json`). No run, no parent, no rounds are recorded today.
- Decision record TRN-3000 (stay a CLI backend, not ACP) stands. It means event detail must come from vendor transcripts, not structured events.
- Owner plan for this rework: all harnesses in current use, profiles for multiple accounts, one call path with continue/new session and heavy-lock check, a call-tree journal, CLI and web views with live update, retry rounds shown as ↺, remove gemini.
- A design sketch of the views exists outside the repo; the parts this spec relies on are written out in `spec-tree-view.md`.

## 1. Purpose and scope

**Trinity** lets one orchestrating agent (编排者) hand tasks to other model harnesses, continue or restart their sessions, and leave a call-tree record that a human can read live and replay.

| ID | Scope item | Source |
| --- | --- | --- |
| SCO-01 | Adapters for every harness in current use: claude-code, codex, droid (glm, minimax), agy, anthropic-compat (openrouter; deepseek metered, OPEN-A3), opencode, deepseek-api. Mapping in §2.1 | owner plan |
| SCO-02 | Profiles: named credential + model + billing + retention bundles (e.g. `claude:account-1`); default by lowest current use | owner plan |
| SCO-03 | One common call path: new session or continue session, same for every harness | owner plan |
| SCO-04 | Pre-dispatch check: heavy-job lock (§5) | owner plan |
| SCO-05 | Journal (账本) as a call tree, with rounds (↺) | owner plan |
| SCO-06 | Views over the journal: CLI tree and web page, both live | owner plan |
| SCO-07 | Remove gemini | owner plan |
| SCO-08 | **One core, two front ends**: a standalone CLI and the host skill. Both call the same core (decided, OPEN-02) | owner decision |
| SCO-09 | Review presets and plan mode rebuilt on the journal — **in WO-006**, not earlier (decided, OPEN-09) | owner decision |

Non-goals (this rework):

- NG-01 Not an ACP / long-lived harness control plane (TRN-3000 stands).
- NG-02 Not a scheduler or worker booker: Trinity runs what the orchestrator asks; it does not pick which external worker or work unit runs.
- NG-03 Not an acceptance authority: a review verdict in the journal is evidence, not approval.
- NG-04 No tmux, no daemon required for dispatch. A live view may run a short-lived reader; see spec-tree-view.
- NG-05 Not a secrets manager. Trinity reads credentials that already exist; it never writes, copies or prints them.
- NG-06 Neither front end holds logic of its own: parsing, checks, journal writes and state derivation live in the core.

## 2. Terms (术语)

Component specs use these terms and do not redefine them.

| Term | 中文 | Meaning |
| --- | --- | --- |
| Orchestrator | 编排者 | The agent or human that calls Trinity. The root of a run. |
| Front end | 前端 | A way to call the core: the `trinity` CLI or the host skill (`/trinity`). Holds no logic (NG-06). |
| Core | 核心 | Dispatch path, checks, journal writer, profile resolver and readers; shared by both front ends. |
| Harness | 工具壳 | A vendor CLI or API endpoint that runs a model session (claude, codex, droid, agy, opencode, HTTP API). |
| Adapter | 提供方适配 | Core code that turns one call into one harness invocation and back, and reads that harness's transcripts. One per harness. |
| Provider | 提供方 | Name users type (`codex`, `glm`). Maps to one adapter (§2.1). Kept for compatibility. |
| Profile | profile | A named bundle: provider + credential source + model + billing mode + transcript retention. |
| Profile pack | profile 包 | The private set of real profiles for one deployment. Lives in a separate private repository, never in this repo (LAW-09). |
| Credential source | 凭据来源 | Where a credential is read from: an env var name or a file path. Never the value. |
| Billing mode | 计费 | `subscription` (window/weekly quota) or `metered` (pay per token/request). |
| Session | 会话 | The harness's own conversation id. Continue (续) reuses it; new (新) starts one. |
| Run | 运行 | One orchestrator task and every call made under it. Has a run id. |
| Node | 节点 | One call (one prompt sent to one session) inside a run. Has a node id and a parent. |
| Edge | 边 | A link between nodes. Exactly four kinds: `parent`, `depends`, `round`, `revises` (`contracts/graph.md`). |
| Step | 步骤 | A named role inside a run (author, review, check). A step has one or more rounds. |
| Round | 轮次 | Any attempt at a step. Each round is its own node; a further round is linked by a `round` edge and drawn as ↺; its reason is one of: review rejection, failure, timeout, stuck, manual. |
| Journal | 账本 | Append-only record of runs, nodes, edges, checks and heartbeats. Holds **pointers, never transcript text** (LAW-08). File layout: OPEN-L1. |
| Check record | 检查记录 | Journal record of a pre-dispatch check result (heavy lock) for one node. |
| Transcript | 原始记录 | The vendor's own session record (file or API history). Owned by the vendor, not by Trinity. |
| Ref (pointer) | 指针 | Journal field locating transcript data: path + byte offset or content hash, plus harness type. |
| Reader | 读取器 | Per-harness code that turns a transcript (via ref) into unified events, on demand. |
| Event | 事件 | Unified view item produced by a reader: `prompt`, `thinking`, `tool`, `output`, `heartbeat`. Not stored in the journal. |
| Heartbeat | 心跳 | Evidence a node is alive (transcript growth or process alive). The core writes a heartbeat row (time + source, no text). |
| Stall limit | 停顿上限 | Heartbeat age after which a running node is shown as stuck. |
| Stuck | 卡住 | A running node whose last heartbeat is older than its stall limit, or a queued node on a wait-for cycle (mutual wait, GRF-006). Display state only. |
| Exit class | 结束类别 | Normalised outcome of one call (list in ADP-002). |
| Heavy lock | 重型锁 | A host-wide lock that heavy jobs (full test suites) must hold. |
| Released | 已发布 | See §8 (working definition). |

### 2.1 Provider → adapter mapping

| Provider name | Adapter | Notes |
| --- | --- | --- |
| claude-code (`claude`) | claude-code | profiles per account |
| codex | codex | |
| glm, minimax | droid | one adapter, model from profile |
| agy | agy | |
| deepseek | undecided (OPEN-A3): opencode for subscription + anthropic-compat or deepseek-api for metered | |
| openrouter | anthropic-compat | a profile of that adapter, no own adapter |
| opencode | opencode | **new** |
| deepseek-api | deepseek-api or anthropic-compat profile | OPEN-A3 |
| gemini | — | **removed** (SCO-07) |

## 3. Architecture rules (法)

| ID | Rule |
| --- | --- |
| LAW-01 | **One call path.** Every harness is reached through the same `call(profile, session=new|<id>, prompt, cwd, limits)` contract. Harness differences live only inside its adapter. |
| LAW-02 | **The journal is the only record of runs.** Tree shape, states and numbers in every view, status and retro count come from the journal. Event *detail* comes from readers via journal refs (LAW-08); while a node runs, a view may also show the core's live file for it (DSP-022), which is redacted, removed at node end and never a record. No view keeps its own state of record. |
| LAW-03 | **No in-place edits.** Journal lines are never edited. Corrections are new lines. The only removal is the retention prune of whole runs older than 90 days (LED-013), and every prune is logged. |
| LAW-04 | **No secret in any Trinity output.** Credential values never appear in the journal, logs, argv, prompts or views. Profiles name a credential *source*, not a value. Credential text that reaches a reader through a transcript is caught by pattern redaction (ADP-012), which is best-effort; the WO-002 leak-test fixture defines the bar. |
| LAW-05 | **Model ids are data.** A model id appears in profile data only, never in adapter code or agent prose. Retired ids are refused (mechanism to be specified in WO-002; TRN-1006). |
| LAW-06 | **Fail closed on checks.** If the heavy-lock check cannot get an answer, dispatch stops with a stated reason unless the caller passes an explicit override, which is journaled. |
| LAW-07 | **Recursion guard.** A child harness must not dispatch Trinity again unless the run explicitly allows nesting, and then only up to the run's depth limit (DSP-015); nesting depth is journaled. |
| LAW-08 | **Pointers, never text.** The journal stores ref + harness type only. It never stores prompt, thinking, tool or output text — no per-run option, no archive exception (decided, OPEN-05). |
| LAW-09 | **Deployment facts stay outside the repo.** Real accounts, token locations, status-board locations, lock paths and host names live in the private profile pack, which this repo never names or points to. The repo ships neutral examples only. |
| LAW-10 | **Compatibility.** `/trinity <provider> "task"` and `trinity review` keep working through the rework; presets and plan mode stay as they are until WO-006 rebuilds them (SCO-09). |
| LAW-11 | **Never fake transcript content.** Thinking that the harness gives only as a summary or encrypted is shown labelled as such; a transcript the harness has deleted is shown as gone with a time. |

## 4. Component map (式)

```text
 front ends:  [trinity CLI]        [host skill /trinity]
                    \                   /
                     ▼                 ▼
 core:        [dispatch path + checks (§5)] ──▶ [profile resolver] ──▶ [adapter: call]
                     │                                                     │
                     ▼                                                     ▼
              [journal writer] ◀── session id, heartbeat, exit class ──  harness
                     │                                                     │
                     ▼                                                     ▼
                  journal ─────────────▶ [views: CLI tree, web] ◀── [adapter: reader] ◀── vendor transcript
                  (refs only)               tree/states from journal;  events on click via ref
```

| Component | Spec | Changes for one reason |
| --- | --- | --- |
| Provider adapters (call + reader) | `spec-provider-adapters.md`; reader contract `contracts/transcript-reader.md` | A vendor CLI/API or transcript format changes |
| Profiles | `spec-profiles.md` | Accounts, models, billing, retention change |
| Journal (账本) | `spec-ledger.md`; graph clause `contracts/graph.md` | The record format changes |
| Tree render + live view | `spec-tree-view.md` | Presentation changes |
| Dispatch core | §5 below (summary) + `contracts/dispatch-core.md` | Call path, checks, retry ownership change |
| Front ends | CLI: `spec-tree-view.md` (view commands) + §5 (dispatch commands); skill: §5 | Host or CLI syntax changes; no logic (NG-06) |

## 5. Dispatch core (summary; full contract in `contracts/dispatch-core.md`, settles OPEN-08)

| ID | Requirement |
| --- | --- |
| CHK-001 | **Retired.** Dispatch performs no pre-call quota check. |
| CHK-002 | **Retired.** Dispatch performs no quota staleness or exhaustion gate; a provider 429 follows the existing adapter error path. |
| CHK-003 | A node marked heavy acquires the heavy lock before start and releases it at end; failure to acquire within the lock wait limit (default 1200 s, DSP-008; settles OPEN-11) stops the node before it starts (`queued → failed`, exit class `lock_unavailable`), and a lock check record is written. |
| CHK-004 | An override of CHK-003 is a caller flag, journaled in the check record as a closed `override_reason` code (`owner_approved`, `lock_holder_known`, `other`) plus an optional `override_ref` pointer to the caller's own text — never free text in the journal. |
| CHK-005 | The core sets the recursion guard on every child (ADP-007) and journals nesting depth per node (LAW-07). |
| CHK-006 | The core owns heartbeat rows: it polls the adapter's heartbeat source and appends a heartbeat row (time + source kind) at most once per poll interval (default 15 s, DSP-009; settles OPEN-12), and only when the source shows new evidence. |
| CHK-007 | Session not found (ADP-004) is surfaced to the caller; starting a new session instead is a caller decision and appears as a new node. |
| CHK-008 | Retry ownership: the core does not retry on its own. Retries are caller decisions and appear as new rounds (LED-004); per-class retry owner in DSP-011. |
| CHK-009 | The core owns the error log and prunes its entries older than 90 days in the same pass as the journal prune (LED-013), logging the count in the prune log. |

## 6. Working rules for the pilot (施工)

- WR-01 Every work order names: goal, baseline sha, allowed paths, forbidden changes, acceptance, budget, stop/escalate conditions, deliverables.
- WR-02 The author of a component does not write or change its acceptance cases. WO-002 acceptance cases are written by someone who is neither the contracts author nor the WO-003+ author (OPEN-06).
- WR-03 Every requirement ID — families `SCO`, `NG`, `LAW`, `CHK`, `ADP`, `PRF`, `LED`, `VIEW`, `SUC`, `DSP`, `RDR`, `GRF` — is traced to a test or marked unverified. A requirement whose number is still open is unverified until the number is set. Risks (`RSK`, `ADP-R`, `PRF-R`, `LED-R`, `VIEW-R`, `DSP-R`, `RDR-R`, `GRF-R`) each name the requirement or test meant to catch them, or say "none yet".
- WR-04 Work happens on a non-public pilot branch. A public release (§8) is **exported as one new commit on top of the public default branch**, whose tree is the release tree; the pilot branch's history, earlier commit messages and author fields are never pushed. Public history is never rewritten. The public commit message carries only the version and a neutral summary (no work-order ids, names or paths); in the docs, work-order ids are plan stage names and may appear; its author and committer are the project's public identity, never a personal address. Before export, a secret and private-reference scan over the exported tree and the commit message must find nothing. The export is a release-time action.
- WR-05 Retro per work order: wall time, rejection rounds, defects, human minutes, filed in the method project's retro record (outside this repo).

## 7. Environment limits and comparison record

Environment limits (each spec has its detail):

- Hosts: macOS and Linux; POSIX `sh` wrappers (TRN-2009); a filesystem with working `flock`. Up to two hosts; one run stays on one host (OPEN-L4).
- Harnesses: vendor CLIs installed and logged in; credential files mode 600/400.
- Stores and the boundaries they can carry:
  - **Journal store** (local file, append under exclusive lock): can carry one-line atomic appends and whole-run pruning; cannot carry cross-host writes or transactions across runs.
  - **Error log** (local file, core-owned): holds the redacted stderr tail for `unknown` exits (ADP-002); same redaction as readers (ADP-012); pruned at 90 days by the core (CHK-009).
  - **Prune log** (local file, core-owned): one line per prune of journal runs or error-log entries; never pruned (LED-013).
  - **Vendor transcript stores** (vendor-owned): readable by path, retention set by the vendor and noted per profile (PRF-009); Trinity cannot guarantee they still exist, so readers report "gone" (LAW-11).
- Views: UTF-8 terminal; local browser; the web view binds to localhost only.

Comparison record: for each work order, the retro records wall time, rejection rounds, defects and human minutes. The comparison is against the same metrics for comparable units run by the existing development process (the standard multi-review process and its shortened variant) over the same period. The record lives in the method project's retro file, outside this repo (WR-05).

## 8. Release semantics (发布语义) — working definition

A Trinity release is an **annotated version tag on the public default branch** whose `VERSION` file equals the tag, and for which `install.sh` with that version installs exactly the tagged tree; the tagged commit is the export commit of WR-04. A merge to a branch, a push to a non-public branch, or a local install is not a release. Refinement (changelog rules, who may tag, rollback) stays OPEN-10, WO-006.

## 9. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| RSK-01 | Reference copies (unmerged guard branch, installed copies) diverge from the baseline; fixes they carry get ported unreviewed | Baseline decided (OPEN-01); retired-id guard and glm wrapper re-specified in WO-002 (LAW-05, ADP-010) |
| RSK-02 | Credential leak through journal, argv, env dumps or the web view | LAW-04, LAW-08, ADP-005/006, VIEW-006; leak test in WO-002 |
| RSK-03 | Vendor transcript formats change without notice | ADP-012 (unknown lines → raw events, not dropped) |
| RSK-04 | Quota read is stale | CHK-002, PRF-004 |
| RSK-05 | Journal grows large | LAW-08 (refs only), LED-013 (90-day prune) |
| RSK-06 | Concurrent writers corrupt the journal | LED-006, LED-007 |
| RSK-07 | Scope creep: about ten features in the plan | One end-to-end path first (OPEN-07); SCO-09 deferred to WO-006 |
| RSK-08 | Deployment facts leak into the public repo, including through history or commit metadata | LAW-09; WR-04 single-commit export + scan |
| RSK-09 | Changing harness set, profile model and views at once hides what helped | One change class per work order (WR-01) |
| RSK-10 | "Stuck" judged wrong (busy session, no transcript growth) | Per-adapter stall limit (ADP-008); stuck is display only (LED-005, VIEW-003), never an automatic kill |
| RSK-11 | Readers show partial thinking as if complete | LAW-11, ADP-013, VIEW-011, RDR-005 |
| RSK-12 | Two nodes wait on each other forever | GRF-010 (no `depends` on an ancestor), GRF-006 (wait-for cycle marked stuck, handed to a person) |

## 10. Open items (未决事项)

| ID | Question | Status / needed by | Owner |
| --- | --- | --- | --- |
| OPEN-01 | Baseline | **Decided:** Trinity 3.3.0 as stated in §0; other copies reference only | owner |
| OPEN-02 | Trinity shape | **Decided:** one core, two front ends (SCO-08) | owner |
| OPEN-03 | Public repo | **Decided:** the repo goes public; no tokens, account names, emails, host names or deployment paths in it (LAW-09, WR-04) | owner |
| OPEN-04 | Profile pack location | **Decided:** separate private repository (LAW-09); format is OPEN-P5 | owner |
| OPEN-05 | Journal content and retention | **Decided:** refs + harness type only, never text (LAW-08); journal rows kept 90 days (LED-013); transcript retention per profile (PRF-009) | owner |
| OPEN-06 | Owner of WO-002 acceptance cases (not the WO-003+ author) | **Decided:** an author other than the contracts author and the WO-003+ author (WR-02) | project lead |
| OPEN-07 | First end-to-end path (suggest: claude-code, one account profile, new session, one child, journal + CLI tree) | Open — WO-004 | project lead |
| OPEN-08 | Dispatch core full contract (call signature, error classes) beyond the §5 summary | **Closed:** `contracts/dispatch-core.md` (DSP-001..023) | author + reviewer |
| OPEN-09 | Presets and plan mode | **Decided:** rebuilt on the journal in WO-006 (SCO-09) | owner |
| OPEN-10 | Release semantics refinement beyond §8 | Open — WO-006 | project lead |
| OPEN-11 | Heavy-lock wait limit (CHK-003) | **Closed:** default 1200 s; a caller may set 0 to 3600 s; the wait does not count against the call time limit (DSP-008) | author + reviewer |
| OPEN-12 | Heartbeat poll interval (CHK-006) | **Closed:** 15 s; a stall limit below 60 s is refused (DSP-009) | author + reviewer |
| OPEN-13 | How to cite the method text | **Decided:** named once, by title and version, in this file's first line; no other citation | owner |

Component open items: adapters OPEN-A1..A6, profiles OPEN-P1..P5, journal OPEN-L1..L5, views OPEN-V1..V5 (see each spec; decided ones are marked there).

## 11. Success conditions for the pilot

- SUC-01 A run with ≥2 nodes is dispatched through one profile, journaled, and shown in the CLI tree with correct parents, sessions (new/continued) and states.
- SUC-02 A further round shows as ↺ with its reason, from journal data only; a wait-for cycle shows as stuck (mutual wait).
- SUC-03 A scan over the journal and both views finds no credential value from the leak-test fixture and no transcript text in the journal.
- SUC-04 Retro numbers per work order exist and can be compared as §7 describes.

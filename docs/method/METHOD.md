# Trinity 法式 (Method Specification) — draft 0.1

Status: **draft, WO-001 (CraftCode §14.2 stage 1)**. Nothing here is accepted or verified.
Baseline: Trinity `forge/main` 019e354 (3.3.0). CraftCode v0.1 @ 6c7923e.

This file states what every Trinity component must agree on: scope, terms, rules, risks, open items. Component boundaries are in the four `spec-*.md` files beside it.

## 1. Purpose and scope

**Trinity** lets one orchestrating agent (编排者) hand tasks to other model harnesses, continue or restart their sessions, and leave a call-tree record that a human can read live and replay.

In scope for the D2595 rework:

| ID | Scope item | Source |
| --- | --- | --- |
| SCO-01 | Adapters for every harness the fleet runs: claude-code, codex, glm, minimax, agy, deepseek (direct API), opencode (Go), openrouter | D2595 (1), plan |
| SCO-02 | Profiles: named credential + model + billing bundles (e.g. `claude:A/B/C`); default by lowest weekly use | plan, mockup |
| SCO-03 | One common call path: new session or continue session, same for every harness | plan "common wrapper" |
| SCO-04 | Pre-dispatch checks: quota and heavy-job lock | plan |
| SCO-05 | Journal (账本) as a call tree, with retry rounds (↺) | plan, mockup |
| SCO-06 | Two views over the journal: CLI tree and web page, both live | plan, mockup |
| SCO-07 | Remove gemini | plan |

Non-goals (this rework):

- NG-01 Not an ACP / long-lived harness control plane (TRN-3000 stands).
- NG-02 Not a scheduler or seat booker: Trinity does not decide *which* fleet seat or unit runs; it runs what the orchestrator asks.
- NG-03 Not an acceptance authority: a review verdict recorded in the journal is evidence, not approval (CraftCode §8.1).
- NG-04 No tmux, no daemon required for dispatch (README design decision). A live view may need a reader process; see spec-tree-view.
- NG-05 Not a secrets manager. Trinity reads credentials that already exist; it never writes, copies or prints them.

## 2. Terms (术语)

| Term | 中文 | Meaning |
| --- | --- | --- |
| Orchestrator | 编排者 | The agent or human that calls Trinity. The root of a run. |
| Harness | 工具壳 | A vendor CLI or API endpoint that runs a model session (claude, codex, droid, agy, opencode, HTTP API). |
| Adapter | 提供方适配 | Trinity code that turns one call into one harness invocation and back. One per harness. |
| Provider | 提供方 | Name users type (`codex`, `glm`). Maps to one adapter. Kept for compatibility. |
| Profile | profile | A named bundle: provider + credential source + model + billing mode + quota source. Example `claude:B`. |
| Billing mode | 计费 | `subscription` (window/weekly quota) or `metered` (pay per token/request). |
| Session | 会话 | The harness's own conversation id. Continuing (续) reuses it; new (新) starts one. |
| Run | 运行 | One orchestrator task and every call made under it. Has a run id. |
| Node | 节点 | One call (one prompt sent to one session) inside a run. Has a node id and a parent. |
| Step | 步骤 | A named role inside a run (RED author, review, gate). One step can have several rounds. |
| Round | 轮次 | One attempt at a step. A RETURN starts a new round; drawn as ↺. |
| Journal | 账本 | Append-only record of runs, nodes, edges and events. `run-journal.jsonl`. Single source of truth. |
| Event | 事件 | A typed entry under a node: prompt, thinking, tool, output, heartbeat, state. |
| Heartbeat | 心跳 | Evidence that a node is still alive (transcript growth or process alive). |
| Stuck | 卡住 | Running node with no heartbeat for longer than its stall limit. |
| Heavy lock | 重型锁 | A host-wide lock that heavy jobs (full test suites) must hold. |

## 3. Architecture rules (法)

| ID | Rule |
| --- | --- |
| LAW-01 | **One call path.** Every harness is reached through the same `call(profile, session=new|<id>, prompt, cwd, limits)` contract. Harness differences live only inside its adapter. |
| LAW-02 | **The journal is the only record.** CLI tree, web view, status and retro metrics read the journal. No view keeps its own state of record. |
| LAW-03 | **Append, never rewrite.** Journal lines are not edited or deleted by Trinity. Corrections are new lines. |
| LAW-04 | **No secret in any Trinity output.** Credential values never appear in the journal, logs, argv, prompts or views. Profiles name a credential *source*, not a value. |
| LAW-05 | **Model ids are data.** A model id appears in profile data only, never in adapter code or agent prose. Retired ids are refused (TRN-1006 + retired-model guard). |
| LAW-06 | **Fail closed on checks.** If the quota or heavy-lock check cannot get an answer, dispatch stops with a stated reason unless the caller passes an explicit override that is journaled. |
| LAW-07 | **Recursion guard.** A child harness must not dispatch Trinity again unless the run explicitly allows nesting; nesting depth is journaled. |
| LAW-08 | **Raw transcripts stay where the vendor puts them.** The journal stores pointers (path + byte offset or hash), not copies, unless a node is explicitly archived. |
| LAW-09 | **Fleet facts stay outside the core.** Paths such as fleet token dirs, quota boards and lock files come from a fleet profile pack, not hard-coded in Trinity. |
| LAW-10 | **Compatibility.** `/trinity <provider> "task"` and `trinity review` keep working through the rework, or their removal is a recorded decision. |

## 4. Component map (式)

```text
orchestrator ──call──▶ [dispatch core] ──▶ [profile resolver] ──▶ [adapter: claude|codex|droid|agy|opencode|api]
                          │   ▲                 │ quota/lock checks
                          ▼   │                 ▼
                        [journal writer] ◀── events from adapter (start, session id, heartbeat, end)
                          │
                          ▼
                    run-journal.jsonl ──▶ [tree render: CLI]   [web view + live]
```

| Component | Spec file | Changes for one reason |
| --- | --- | --- |
| Provider adapters | `spec-provider-adapters.md` | A vendor CLI/API changes |
| Profiles | `spec-profiles.md` | Accounts, models, billing, quota sources change |
| Journal (账本) | `spec-ledger.md` | The record format changes |
| Tree render + live view | `spec-tree-view.md` | Presentation changes |

The dispatch core (call path, checks, journal writes) is the 组装 between them; its contract is WO-002 work and is listed as an open item, not specified here.

## 5. Working rules for the pilot (施工)

- WR-01 Every work order names: goal, baseline sha, allowed paths, forbidden changes, acceptance, budget, stop/escalate conditions, deliverables (CraftCode §8.2).
- WR-02 The author of a component does not write or change its acceptance cases (§8.1). WO-002 acceptance cases get an owner other than the WO-003+ author.
- WR-03 Each requirement ID in the specs (`ADP-*`, `PRF-*`, `LED-*`, `VIEW-*`) is traced to a test or marked unverified (§6.7).
- WR-04 Branch `pilot/trinity` on forge only. No GitHub push until Q3 is decided.
- WR-05 Retro per work order: wall time, RETURNs, defects, human minutes (CraftCode §15.1), filed in ~/Projects/craftcode.

## 6. Risks

| ID | Risk | Why it matters | Mitigation idea (not decided) |
| --- | --- | --- | --- |
| RSK-01 | Three diverging Trinity copies (forge/main, retired-model-guard branch, installed `~/.claude`) | Specs written against the wrong baseline | Decide baseline (OPEN-01) before WO-002; installed glm bridge wrapper must be brought into git or dropped |
| RSK-02 | Credential leak through journal, argv, env dumps or the web view | Fleet tokens are high value | LAW-04; env built from allow-list (existing `build_provider_env`); leak test in WO-002 |
| RSK-03 | Vendor transcript formats change without notice | Live view and thinking events break silently | Adapters own parsing; unknown lines kept as raw events, not dropped |
| RSK-04 | Quota read is stale (usage.bob board was stale 10-11) | Wrong profile picked, account hits limit mid-run | Quota source carries its read time; stale reads count as unknown (LAW-06) |
| RSK-05 | Journal grows large (thinking + tool events) | Slow views, disk use, privacy | Pointers not copies (LAW-08); retention rule (OPEN-05) |
| RSK-06 | Concurrent writers (parallel children) corrupt the journal | Broken tree | Single-line appends under a lock; each line self-contained JSON |
| RSK-07 | Scope creep: plan lists ~10 features | Pilot never finishes WO-004 | §14.1: one end-to-end path first (OPEN-07) |
| RSK-08 | Fleet-specific facts leak into a repo that may go public | Exposes paths, account names | LAW-09; profile pack outside repo |
| RSK-09 | Changing harness set, profile model and views at once | §14.1 warns: can't attribute effects | Sequence the work orders; one change class per WO |
| RSK-10 | "Stuck" judged wrong (busy session with no transcript growth) | Wrong retry, killed good work | Stall limit per adapter; stuck is a display state, never an automatic kill |

## 7. Open items (未决事项)

| ID | Question | Needed by | Owner |
| --- | --- | --- | --- |
| OPEN-01 | Baseline: forge/main 3.3.0 alone, or + retired-model-guard branch? Is the installed `bin/glm` bridge wrapper canonical? | WO-002 | pfc / Frank |
| OPEN-02 | Trinity shape: skill-in-host only, standalone CLI, or one core with both front ends? (mockup implies a standalone `trinity` CLI) | WO-002 | Frank |
| OPEN-03 | Public repo plan (GitHub later?) and therefore what must stay out of the repo | WO-002 | Frank |
| OPEN-04 | Where the fleet profile pack lives and who maintains it | WO-002 | pfc |
| OPEN-05 | Journal retention, and whether thinking text is indexed or only pointed to | WO-002 | Frank |
| OPEN-06 | Owner of WO-002 acceptance cases (not the WO-003+ author) | WO-002 | pfc |
| OPEN-07 | First end-to-end path for WO-004 (suggest: claude-code profile B, new session, one child, journal + CLI tree) | WO-003 | pfc |
| OPEN-08 | Dispatch core contract (call signature, error classes, retry owner) | WO-002 | author + reviewer |
| OPEN-09 | Keep `/trinity` review presets and plan mode as-is, or rebuild them on the journal? | WO-002 | Frank |
| OPEN-10 | Release semantics: what "released" means for Trinity (forge tag? install.sh version? fleet `~/.claude` install?) — CraftCode WO-001 asks for 发布语义 | WO-006 | pfc |

## 8. Success conditions for the pilot (§14.1 stage 1)

- SUC-01 A run with ≥2 nodes is dispatched through one profile, journaled, and shown in the CLI tree with correct parents, sessions (new/continued) and states.
- SUC-02 A RETURN round shows as ↺ with its reason, from journal data only.
- SUC-03 A leak scan over journal + views finds no credential value.
- SUC-04 Retro numbers per WO exist and can be compared with the full chain and D2592 fast lane (D2595 (1)).

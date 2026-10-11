# Component spec: journal / call-tree ledger (账本) — draft 0.1

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Laws that bind this component: LAW-02, 03, 04, 08 (METHOD.md §3).

## 1. Purpose

Record every run, call and retry as a tree, so that views, status, resume and retro numbers all come from one place: `run-journal.jsonl` (mockup footer).

## 2. Scope

In:

- Record kinds: `run` (start/end), `node` (one call), `edge` (parent → child; retry ↺ with reason), `event` (prompt, thinking, tool, output, heartbeat, state change), `check` (quota/lock result for a node).
- Append API used by the dispatch core; read API used by views and metrics.
- Pointers to raw vendor transcripts (LAW-08).

Out:

- Rendering (tree-view component).
- Parsing vendor transcripts into events — adapters do that; the ledger stores what it is given.
- Acceptance decisions (NG-03); a verdict is just an output event.

## 3. Record shape (draft, field names not final)

Every line is one self-contained JSON object:

```json
{"v":1,"kind":"node","run":"r-…","node":"n-…","parent":"n-…|null",
 "step":"review","round":1,"label":"独立审查",
 "profile":"codex","profile_reason":"named","model":"…",
 "session":{"id":"…","mode":"new|continue"},
 "state":"running","t":"2026-10-11T07:18:30Z"}
```

```json
{"v":1,"kind":"edge","run":"r-…","from":"n-…","to":"n-…","type":"child|retry","reason":"QUAL RETURN: …"}
```

```json
{"v":1,"kind":"event","run":"r-…","node":"n-…","type":"tool","t":"…","text":"…","ref":{"path":"…","offset":1234}}
```

## 4. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| LED-001 | Append-only. Trinity never edits or deletes a line; a correction is a new line that names the line it corrects. |
| LED-002 | Node ids and run ids are generated, unique, and stable; display labels (any language) are never used as keys (READ R5). |
| LED-003 | Every node has exactly one parent except the run root; a parent always exists earlier in the file. |
| LED-004 | A retry is a new node in the same step with `round = previous + 1` and a `retry` edge carrying the reason. Rounds of one step can use different profiles (mockup: round 3 switched to opencode, D1594). |
| LED-005 | Node state moves only along: `queued → running → (done | failed | interrupted)`; `stuck` is derived by readers from heartbeat age, not written as final state. |
| LED-006 | Each line is written by a single `write()` of one line under an exclusive lock, so parallel children cannot interleave (RSK-06). |
| LED-007 | A partial last line (crash mid-write) is skipped by readers and reported, never fatal. |
| LED-008 | No credential value is ever written. Event text that matches a secret pattern is redacted before append; redaction itself is journaled. |
| LED-009 | Thinking/prompt text may be stored as pointer only (LAW-08); the choice is per run and recorded in the run line (OPEN-L2). |
| LED-010 | The ledger alone is enough to rebuild: the tree, each node's wall time, token totals where reported, rounds and retry reasons, and the §15.1 counts (RETURNs per step). |
| LED-011 | Format carries a version `v`; readers refuse unknown major versions with a clear error. |

## 5. Environment assumptions

- Local filesystem with working `flock` (today's `session.py` already depends on it).
- One host per run. Cross-host runs (bajie ↔ wukong) are not covered (OPEN-L4).
- Vendor transcripts at the pointed path stay readable for the retention period (CraftCode §6.6: an invariant needs a storage assumption).

## 6. Risks

| ID | Risk |
| --- | --- |
| LED-R1 | Pointers rot: vendor rotates or deletes transcripts, so `show --events` loses detail. |
| LED-R2 | File grows without bound on long runs with many events. |
| LED-R3 | Redaction misses a secret in tool output (e.g. env dump in a child's tool call). |
| LED-R4 | Two orchestrators write the same run id (copy-paste, resume across hosts). |
| LED-R5 | Today's `.claude/trinity.json` sessions and per-review `metadata.json` stay as parallel records, breaking LAW-02. |

## 7. Open items

| ID | Question |
| --- | --- |
| OPEN-L1 | Journal location: per project (`.claude/trinity/runs/<run>.jsonl`), per host, or both? One file per run or one global file? |
| OPEN-L2 | Store thinking text, or pointer only? Privacy and size (METHOD OPEN-05). |
| OPEN-L3 | Migrate `trinity.json` sessions and review `metadata.json` into the journal, or keep them as derived caches? |
| OPEN-L4 | Cross-host runs: needed for the pilot? |
| OPEN-L5 | Retention and archive rule. |

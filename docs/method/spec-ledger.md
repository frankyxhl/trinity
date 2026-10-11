# Component spec: journal / call-tree ledger (账本) — draft 0.2

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Terms: METHOD.md §2. Laws that bind this component: LAW-02, 03, 04, 08.

## 1. Purpose

Record every run, call, round, check and heartbeat as a tree, so that views, status, resume and retro numbers all come from one place. The journal holds **pointers and metadata, never transcript text** (LAW-08).

## 2. Scope

In:

- Record kinds: `run` (start/end), `node` (one call), `edge` (`depends`, `round` with reason, `revises`; the `parent` edge is the node's own `parent` field — `../contracts/graph.md`), `check` (quota/lock result), `heartbeat` (time + source kind), `state` (node state change). Prune lines go to a separate prune log, not the journal (LED-013).
- Append API used by the core; read API used by views and metrics.
- 90-day retention prune.

Out:

- Rendering (tree-view spec).
- Reading transcripts into events (adapter readers, ADP-012).
- Acceptance decisions (NG-03); a verdict is only a pointer to output.

## 3. Record shape (draft, field names not final)

Every line is one self-contained JSON object. No line has a free-text field holding prompt, thinking, tool or output content.

```json
{"v":1,"kind":"node","run":"r-…","node":"n-…","parent":"n-…|null",
 "step":"review","round":1,"label":"review","depth":0,
 "harness":"codex","profile":"codex","profile_reason":"named","model":"…",
 "session":{"id":"…|null","mode":"new|continue","source":"assigned|caller|null"},
 "transcript_ref":{"path":"…","offset":0},"t":"…"}
```

```json
{"v":1,"kind":"state","run":"r-…","node":"n-…","state":"queued|running|done|failed|interrupted","exit_class":"ok","output_kind":"commit|verdict|none","output_ref":{"path":"…","offset":1234},"usage":{"tokens":48000},"t":"…"}
```

```json
{"v":1,"kind":"edge","run":"r-…","from":"n-…","to":"n-…","type":"round","reason":"review_rejection","reason_ref":{"path":"…","offset":88}}
```

A `round` edge runs `from` the new round `to` the round before it; `revises` likewise runs from the later node to the earlier one (GRF-004, GRF-007).

```json
{"v":1,"kind":"check","run":"r-…","node":"n-…","check":"quota","result":"ok|unknown|exhausted|override","source_kind":"vendor_cli","read_at":"…","t":"…"}
```

```json
{"v":1,"kind":"check","run":"r-…","node":"n-…","check":"quota","result":"override","override_reason":"source_outage","override_ref":{"path":"…","offset":0},"t":"…"}
```

```json
{"v":1,"kind":"check","run":"r-…","node":"n-…","check":"heavy_lock","result":"ok|unavailable|override","waited_s":12,"t":"…"}
```

```json
{"v":1,"kind":"check","run":"r-…","node":"n-…","check":"dependency","result":"waiting|ok|failed|cycle","target":"n-…","members":["n-…"],"t":"…"}
```

```json
{"v":1,"kind":"session","run":"r-…","node":"n-…","id":"…|null","source":"captured|session_unknown","t":"…"}
```

```json
{"v":1,"kind":"heartbeat","run":"r-…","node":"n-…","source":"transcript_growth","t":"…"}
```

## 4. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| LED-001 | No in-place edits. A correction is a new line naming the line it corrects. The only removal is the retention prune (LED-013). |
| LED-002 | Run ids and node ids are generated, unique, stable and flat: an id never encodes parent, position, step or round. Display labels (any language) are never keys (GRF-001). |
| LED-003 | In every run present in the journal, each node has exactly one parent except the run root, and the parent appears earlier. Pruning removes whole runs only, so this holds after a prune. |
| LED-004 | A further attempt at a step is a new node with `round = previous + 1` and a `round` edge whose `reason` is one of `review_rejection`, `failure`, `timeout`, `stuck`, `manual` (with an optional `reason_ref` pointer to the rejection text). The core assigns the round number under the journal lock (DSP-018). Rounds of one step may use different profiles (a step may switch author after repeated rejection); a round on another profile is a new session (PRF-010). |
| LED-005 | Node state moves only along `queued → running → (done | failed | interrupted)`, or `queued → failed` when a pre-start stop ends the node (exit class `check_failed`, `lock_unavailable`, `profile_refused` or `dependency_failed`), or `queued → interrupted` when a caller or person cancels a node that has not started (DSP-013). `stuck` is never written; readers derive it from heartbeat age and stall limit. |
| LED-006 | Each line is written by one `write()` of one line under an exclusive lock, so parallel children cannot interleave. |
| LED-007 | A partial last line (crash mid-write) is skipped by readers and reported, never fatal. |
| LED-008 | No credential value is ever written. Since no text field exists (LED-009), redaction duty sits with the readers (ADP-012), not the journal. |
| LED-009 | The journal stores `transcript_ref`, `output_ref`, `reason_ref` and `harness` only — never prompt, thinking, tool or output text. No per-run option (decided, OPEN-05). |
| LED-010 | The journal alone is enough to rebuild the tree, each node's wall time, reported token totals, rounds and retry reasons, and the per-step count of rejection rounds. |
| LED-011 | Format carries a version `v`; readers refuse unknown major versions with a clear error naming the version found and the versions supported. A line with no `v` is a defect: reported by line number and skipped, never guessed. |
| LED-012 | A repeated call is always a new node; two calls are never merged, even with identical prompt and session. Two `node` records with the same node id are a defect (state, check and heartbeat lines repeat the id by design): readers keep the first and report the second. |
| LED-013 | **Retention: 90 days.** A prune removes whole runs whose end time — or, for a run with no end record, its last record time — is older than 90 days, and appends a `prune` line (run ids, count, time) to a separate prune log that is itself never pruned. The same pass prunes the error log (CHK-009). Edges are pruned with their run; an edge never points into another run (GRF-002). |
| LED-014 | `check` and `heartbeat` lines are written by the core (CHK-001..006); every quota `check` line names result, source kind and read time; every heavy-lock `check` line names result and wait time; every dependency `check` line names result and target node, and a `cycle` result also names its `members` (DSP-007, GRF-006); an `override` result carries a closed `override_reason` code and an optional `override_ref` pointer (CHK-004), never free text. `node` lines carry nesting `depth` (CHK-005). |
| LED-015 | `output_kind` is a closed enum (`commit`, `verdict`, `none`), never free text; the commit id or verdict word itself is read from `output_ref` on demand. |
| LED-016 | A ref whose path the redaction function's shape kinds (RDR-008 kinds 1–7) would change is stored as `{"withheld": "secret_pattern"}`, never as the path (RDR-014). |
| LED-017 | A node's session id is the one in its `node` record, or, if that is `null` or a later `session` line names another, the last `session` line's id. `session_unknown` (id `null`) is final for that node. The core writes `session` lines only per DSP-020. |

## 5. Environment assumptions

- Local filesystem with working `flock` (the baseline's session store already depends on it).
- One host per run. Runs on two hosts write two separate journals (OPEN-L4).
- Vendor transcripts at a ref may disappear on the vendor's schedule (PRF-009); the journal does not depend on them for tree, states or numbers.

## 6. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| LED-R1 | Refs rot when vendors delete transcripts; event detail is lost | ADP-014 / VIEW-008 show "gone + when"; tree unaffected (LED-010) |
| LED-R2 | Journal growth on long runs | LED-009 (no text), LED-013 (90-day prune) |
| LED-R3 | A secret appears in transcript text and reaches a view | ADP-012 reader redaction; leak test in WO-002 |
| LED-R4 | Two orchestrators write the same run id | LED-002 generated ids; LED-012 duplicate detection |
| LED-R5 | The baseline's session store and per-review `metadata.json` stay as parallel records, breaking LAW-02 | OPEN-L3 |

## 7. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-L1 | Journal location and layout: per project, per host; one file per run or one global file | Open — WO-002 |
| OPEN-L2 | Store thinking text or pointer only? | **Decided:** pointer only (LED-009) |
| OPEN-L3 | Migrate the session store and review metadata into the journal, or keep them as derived caches? | Open — WO-002 |
| OPEN-L4 | Cross-host runs needed for the pilot? | Open — WO-002 (assumed no) |
| OPEN-L5 | Retention | **Decided:** 90 days for journal rows (LED-013); transcripts per profile (PRF-009) |

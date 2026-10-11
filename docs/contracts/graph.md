# Contract: graph clause (图结构条款) — draft 0.1

Status: **draft, WO-002 contract.** Requirements are unverified until the independent acceptance cases exist.
Terms: `../method/METHOD.md` §2. Binds: LAW-02, 03; LED-002..005; VIEW-003, 004. Writer: dispatch core (`dispatch-core.md`).

## 1. Purpose

Fix the shape of the journal's graph so that every view, count and retro number reads it the same way: flat ids, exactly four edge kinds, loops unrolled in the journal and folded in the view, and a mutual wait handed to a person.

## 2. Contract

| ID | Requirement |
| --- | --- |
| GRF-001 | **Flat ids.** Work orders and call nodes have flat ids: `WO-007`, never `WO-002.3`; `n-<generated>`, never `n-<parent>.<k>`. An id never encodes parent, position, step or round (LED-002). All structure lives in edges. |
| GRF-002 | **Exactly four edge kinds:** `parent`, `depends`, `round`, `revises`. No other kind is written or read. Every edge joins two nodes of the same run. |
| GRF-003 | **`parent`** — the call tree. Every node except the run root has exactly one, carried in its own `node` record (`parent` field), pointing to an earlier node (LED-003). It is the only edge the tree layout uses. |
| GRF-004 | **`round`** — the retry / round back-edge. From round *k* to round *k + 1* of the same step, with a reason (LED-004). Both rounds have the same parent and step. A loop is **unrolled** in the journal — one node per round, each with its own session, profile and state — and **folded** in the view into one step line with ↺ (VIEW-004). The `to` node is always appended after the `from` node, so rounds never form a cycle in the journal. |
| GRF-005 | **`depends`** — `from` may not start until `to` is `done` (DSP-007). If `to` ends `failed` or `interrupted`, `from` ends `dependency_failed`. It is the only kind whose target may still be queued, so it is the only kind that can form a cycle. |
| GRF-006 | **Mutual wait.** On every `depends` append the core checks the run's `depends` edges among nodes not yet ended. If a cycle exists, every node on it gets a dependency `check` line with result `cycle`, every waiting call on it returns `dependency_cycle`, and the nodes stay `queued`. Views show them as stuck ("互相等待", derived, never written — LED-005). Trinity never chooses a node to drop; a person interrupts one (DSP-013), and its dependents then end `dependency_failed`. |
| GRF-007 | **`revises`** — the `from` node's output supersedes the `to` node's output, for a later node in another step (for example a fix after a review). `to` must be earlier. The `to` node is unchanged (LAW-03); views mark its output as superseded. Within one step, `round` already says this; `revises` is not added on top of `round`. |
| GRF-008 | **Views.** The tree is drawn from `parent` only. Rounds fold per GRF-004. `depends` and `revises` are listed in node detail, in both directions. Stuck from either cause is derived by the one shared state function (VIEW-003, NG-06). |
| GRF-009 | **Counts from edges.** Rejection rounds per step = `round` edges with reason `review_rejection`; supersessions = `revises` edges; blocked time = from the dependency `waiting` line to start. All from the journal alone (LED-010). |

## 3. Cross-check against an existing delegation graph

The four kinds were checked against a delegation graph already in use by the method project (one table of nodes, one table of edges, plus a free-text log). Relations found there, and how they map:

| Relation in that graph | Covered by | Why no fifth kind is needed |
| --- | --- | --- |
| Delegation (from → to, with a watch, a state and open/close dates) | `parent` + node states + heartbeats | The watch is a monitoring duty, which heartbeats and the stuck rule already carry; open/close are state times. |
| Standing "reports to" between workers | not an edge | Trinity nodes are calls, not workers; who ran a call is the node's profile, an attribute. |
| Blocked by / depends on | `depends` | Same meaning. |
| Superseded / replaced by a later order | `revises` (across steps) or `round` (same step) | Same meaning; the earlier node stays readable. |
| Hand-off of a task to another worker | `round` on another profile (LED-004, PRF-010) | A hand-off is another attempt at the same step by someone else. |
| Escalation to a person | not an edge | An exit class or the stuck state hands work to a person; the person's next action is a new node. |
| Cancelled | state `interrupted` | A state, not a relation. |
| Reopened | `round` | A new attempt at the same step. |

Two differences are deliberate: that graph edits an edge's state in place, while this journal only appends (LAW-03); and that graph has no rule for mutual waits, while GRF-006 gives one.

## 4. Failure expectations

| Situation | Expected outcome |
| --- | --- |
| A writer emits a fifth edge kind | Readers report the line as a defect and skip it (like LED-012 duplicates); the tree is unaffected. |
| An edge points into another run | `bad_request` at call time (DSP-003); a journal line like that is reported as a defect. |
| A `round` or `revises` that would point forward in time | `bad_request` (DSP-003). |
| A `depends` cycle | GRF-006: stuck, handed to a person, never broken automatically. |
| A run with 20 rounds of one step | 20 nodes in the journal; one folded line in the view ("第 20 轮 · 退回 M 次"). |

## 5. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| GRF-R1 | `revises` and `round` used for the same thing, double-counting supersessions | GRF-007 (not both within a step) |
| GRF-R2 | Cycle check cost on large runs | Check covers only nodes not yet ended in one run |
| GRF-R3 | A cross-run relation is needed later (a run revising an earlier run's output) | GRF-002 forbids it for now; revisit with a decision, not a fifth kind by drift |

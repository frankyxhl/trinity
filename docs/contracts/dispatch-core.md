# Contract: dispatch core (调用核心) — draft 0.2

Status: **draft 0.2, WO-002 contract.** Requirements are unverified until the independent acceptance cases exist. Settles OPEN-08, OPEN-11, OPEN-12.
Terms: `../method/METHOD.md` §2. Binds: LAW-01, 02, 04, 06, 07, 08; CHK-001..009. Graph rules: `graph.md`. Reader: `transcript-reader.md`.

## 1. Purpose

The one call path (LAW-01). Both front ends hand a request to `call`; the core validates it, resolves the profile, writes the node, runs the checks, hands the call to the adapter, and records the outcome. The core never retries on its own (CHK-008).

## 2. Call signature

```text
call(request) -> result

request = {
  run:           "new" | "r-…",
  parent:        "n-…" | null,            # null only for the run root
  step:          "<step label>",          # display label, never a key (LED-002); limits DSP-017
  label:         "<node label>" | null,   # display only; limits DSP-017
  profile:       "<profile name>" | null, # exactly one of profile / provider
  provider:      "<provider name>" | null,# provider only → default pick (PRF-005)
  session:       "new" | "<session id>",
  prompt:        {text: "…"} | {file: "<path>"},
  cwd:           "<path>",
  heavy:         false,
  limits:        {time_s?, stall_s?, lock_wait_s?},
  round_of:      {node: "n-…", reason: <round reason>, reason_ref?} | null,  # names the step; number and edge target: DSP-018
  depends:       ["n-…", …],              # 0..32 ids; never an ancestor (GRF-010)
  revises:       "n-…" | null,
  override:      {check: "quota" | "heavy_lock", reason: <override code>, ref?} | null,
  allow_nesting: false | true | {max_depth: 1..5} # true = max_depth 2; set on the run root only; children inherit (DSP-015)
}

result = {
  run, node | null, exit_class,
  session_id | null, output_kind, output_ref | null, transcript_ref | null,
  usage?, started_at | null, ended_at,
  journal_complete: true | false
}
```

Round reasons: `review_rejection`, `failure`, `timeout`, `stuck`, `manual` (LED-004). Override codes: `owner_approved`, `source_outage`, `lock_holder_known`, `other` (CHK-004). Prompt text and the prompt file path are passed to the adapter only; neither is journaled (LAW-08).

## 3. Contract

| ID | Requirement |
| --- | --- |
| DSP-001 | Both front ends call `call` with the shape above and get the result shape above; neither front end adds, drops or reinterprets a field (NG-06). |
| DSP-002 | **Order.** (1) validate the request; (2) resolve the profile; (3) under the journal lock: assign the round number (DSP-018), append the `node` record (state `queued`) and its edges, release the lock; (4) profile check; (5) dependency gate; (6) quota check; (7) heavy lock; (8) adapter call (`running`); (9) end state. The journal lock is held for one append (or one read-assign-append in step 3) only, never across a check, a wait or the harness call (LED-006). A stop at step 1, or a journal failure at step 3, writes no node; a stop at steps 4–7 ends the node `queued → failed` with the class in §4 — except `dependency_cycle`, which leaves it `queued` (GRF-006). |
| DSP-003 | **Validation** (step 1) refuses with `bad_request` and writes nothing: both or neither of profile/provider; unknown profile or provider; `parent`, `round_of`, `depends` or `revises` naming a node not in this run; `round_of` whose node is not of the same step and parent; `revises` naming a node that is not earlier; continuing a session under a profile other than the one that created it (PRF-010); an override without a code from the closed list; `stall_s` below 60; `lock_wait_s` above 3600; `depends` naming an ancestor of the new node (GRF-010) or more than 32 targets; `revises` naming a node of the same step or a node not yet ended (GRF-007); `max_depth` outside 1..5 or set below the run root; a `step` or `label` breaking DSP-017. |
| DSP-004 | **Recursion guard.** When the guard is set in the calling environment and the run does not allow nesting, or the new call's depth would exceed the run's `max_depth` (DSP-015), `call` returns `nesting_refused`, writes no node, and appends one error-log line holding run id, depth and limit (no text), so refusals are countable (LAW-07). The guard environment carries only non-secret values: run id, calling node id, depth, `max_depth`, journal root. |
| DSP-005 | **Journal fails closed.** If the journal lock or the `node` append fails, nothing starts and `call` returns `journal_unavailable` (one error-log line). If an append fails after the harness started, the core still waits for the harness, returns its real exit class with `journal_complete: false`, and writes one error-log line; the view then shows the node running until its stall limit, then stuck. |
| DSP-006 | **Profile.** A named profile is used as named; provider only → default pick (PRF-005); continue → the session's own profile, found from the journal node that holds that session id; if none is found the caller must name the profile. A disabled profile, a credential file with wide mode (PRF-003) or a retired model id (ADP-010) ends the node `profile_refused`. If the default pick finds no candidate, the node has `profile: null` and one quota `check` line per skipped candidate, and ends `check_failed`. |
| DSP-007 | **Dependency gate.** The node starts only when every `depends` target is `done`. While waiting it stays `queued` with a dependency `check` line `waiting`; the core re-reads the journal every poll interval (DSP-009). A target that ends `failed` or `interrupted` ends this node `dependency_failed`: the process that writes the target's end line also appends `queued → failed` (`dependency_failed`) for every queued node that depends on it, transitively, in the same pass; a waiting call sees that line on its next poll and returns. A wait-for cycle is handled by GRF-006 and returns `dependency_cycle`. The wait has no limit of its own; it ends when the targets end, a cycle is found, or the caller interrupts. This is a gate on one call, not scheduling (NG-02). |
| DSP-008 | **Heavy-lock wait limit (OPEN-11): default 1200 s.** A caller may set `lock_wait_s` from 0 to 3600. The wait does not count against `time_s`. The lock `check` line records `waited_s`; the lock records the holding node id (no text). Two cases end `lock_unavailable` at once, without waiting: the holder is an ancestor of the new node (it cannot release before this call returns; check line `holder: ancestor`), and the lock location is unreachable. Reason for 1200 s: the heavy lock guards full test suites, which take minutes to about a quarter hour; waiting longer than one such run plus margin means the holder is likely hung or forgotten, which a person should look at rather than a queue growing behind it. |
| DSP-009 | **Heartbeat poll interval (OPEN-12): 15 s.** The core polls the adapter's heartbeat source every 15 s and appends a `heartbeat` row only when the source shows new evidence since the last row (CHK-006). A stall limit below 60 s is refused (DSP-003). Reason: stall limits are minutes; 15 s gives at least four polls inside the smallest allowed stall limit, so one late poll never makes a node look stuck; the live view lags the journal by at most one interval; worst-case growth is 240 rows per running node per hour (about 25 KB), pruned at 90 days. |
| DSP-010 | **Exit classes — complete list** in §4. Every result carries exactly one. No other value is ever written or returned. |
| DSP-011 | **Retry owner** per class is the "who retries" column of §4. The core never retries; a retry is a new call with `round_of` set, which becomes a new node and a `round` edge (LED-004). Advice for callers: after two consecutive rounds of one step ending in the same non-`ok` class, hand the step to a person. |
| DSP-012 | **Kill rule.** The core ends a running harness only on `time_s` (adapter kills its own process group, ADP-009) or on interrupt. Stuck is never a reason to kill (RSK-10). |
| DSP-013 | **Interrupt.** A caller or person may interrupt a node: running → adapter kills its process group, state `interrupted`; queued → state `interrupted` with no process started (LED-005). Interrupt is the only way a person breaks a wait-for cycle (GRF-006); its dependents then end per DSP-007. |
| DSP-014 | **Overrides** apply to the quota check and the heavy lock only, and never to `profile_refused`, the dependency gate, the recursion guard or the journal. An override writes the check line with result `override`, the code and the optional `override_ref` (CHK-004). |
| DSP-015 | **Nesting depth limit.** The run root has depth 0; a call made from inside a depth-*d* harness has depth *d* + 1. Nesting is off unless the root request sets `allow_nesting: {max_depth: N}`, N from 1 to 5, default 2 when `allow_nesting: true` is given without a number. Children inherit the root's value through the guard environment and cannot raise it. A call at depth N + 1 is `nesting_refused` (DSP-004). Reason: two levels cover an orchestrator whose worker delegates once more; deeper chains are harder to watch than to restructure. |
| DSP-016 | **Quota-read timeout: 10 s.** A quota read that gives no answer within 10 s counts as unknown (CHK-002) and ends the node `check_failed`. Reason: every quota source is a status call or a local file read that answers in well under a second when healthy; 10 s rides out a slow vendor CLI start without leaving the caller hanging. |
| DSP-017 | **Caller-text limits.** `step` and `label` are 1–64 characters, printable, no control characters, and must pass the redaction function (RDR-008) unchanged; a value it would change is refused (`bad_request`, naming the field), never stored masked. No other caller field holds text: refs are pointers, the override reason is a code. A journal line is at most 4 KiB; a request whose node line or any edge or check line would exceed that is refused at validation. Reason: labels are display names, and a bound per line keeps the journal a small index (LAW-08). |
| DSP-018 | **Round numbers.** Under the journal lock, the core gives the new node round = (highest round already recorded for that parent and step) + 1, and points its `round` edge at the node that holds that highest round — whatever node `round_of` named. `round_of` identifies the step and parent and carries the reason only. Two concurrent retries therefore get consecutive numbers, each edge pointing at the round just before it. |
| DSP-019 | **One clock.** Every time the core reads — ages, freshness, stall, lock wait, quota timeout, retention, prune — comes from one clock function (wall and monotonic) that a test can replace. Production code never reads the system clock elsewhere. |
| DSP-020 | **Session id (owner rule).** Trinity pre-assigns the node id (step 3). For `session: new`: when the adapter can take a caller-chosen session id (ADP-016), the core generates one (UUID v4), passes it to the adapter, and records it in the `node` record (`source: assigned`) before the harness starts. Otherwise the adapter captures the id from the harness's first output that carries it (a harness-reported id or exact marker, never the newest file, ADP-003), and the core appends a `session` line (`source: captured`, LED-017) as soon as the adapter reports it, while the harness still runs. If neither yields an id by the end, the core appends a `session` line with `source: session_unknown`, and the node can never end in success: a harness end that would be `ok` is recorded as `harness_error` (output ref kept), and `result.session_id` is `null`. For `session: <id>` (continue), the node records that id (`source: caller`); if the harness reports a different id, the core appends a `session` line with the reported id (`source: captured`), and later continues use that one (DSP-006 finds either). Reason: an id taken from the newest file can belong to a parallel call; a node with no id cannot be continued, resumed or matched to its transcript. |
| DSP-021 | **Resume (OPEN-D1, decided).** `trinity resume <run>/<node> "<prompt>"` is sugar for `call` with that node's run, session id, profile, step and parent; nothing else differs (same validation, checks, journal lines; round number per DSP-018). Resuming a node whose session is `session_unknown` is `bad_request`. |

## 4. Exit classes (complete list)

"Set by" is who decides the class. "Journal" is what the journal holds afterwards. "Who retries" names who may make the next attempt and in what form; "—" means a retry is not the right response.

| Class | Set by | Cause | Journal | Who retries |
| --- | --- | --- | --- | --- |
| `ok` | adapter | harness ended normally | state `done` | — |
| `bad_request` | core | request invalid (DSP-003) | nothing | caller fixes the request; not a round |
| `nesting_refused` | core | recursion guard set and nesting not allowed, or depth over `max_depth` (DSP-004, DSP-015) | no node; one error-log line (run, depth, limit) | — (the child sees it in its own output) |
| `journal_unavailable` | core | journal lock/append failed before the node, or unknown major version (LED-011) | nothing; one error-log line | person fixes the store; then the caller calls again |
| `profile_refused` | core | profile disabled, wide credential mode, retired model id (DSP-006) | node, `queued → failed` | person fixes the profile; caller may use another profile as a new round (`failure`) |
| `check_failed` | core | quota unknown (including no answer within 10 s, DSP-016) or exhausted (CHK-002), or no default candidate (PRF-005) | node, quota check line(s), `queued → failed` | caller: another profile as a new round, later, or an override with a code |
| `lock_unavailable` | core | heavy lock not acquired within `lock_wait_s`, held by an ancestor, or its location unreachable (DSP-008) | node, lock check line with `waited_s`, `queued → failed` | caller later as a new round (`failure`); person checks the holder |
| `dependency_failed` | core | a `depends` target ended `failed` or `interrupted` (DSP-007) | node, dependency check line naming the target id, `queued → failed` | caller: retry the target first, then this step as a new round |
| `dependency_cycle` | core | the node is on a wait-for cycle (GRF-006): only through nesting, or a defective journal | node, edges, dependency check line `cycle` naming the members; state stays `queued` (shown stuck) | person: interrupts one node of the cycle (DSP-013); never the core |
| `quota_exhausted` | adapter | vendor reported quota or rate limit during the run | `running → failed` | caller: another profile as a new round (new session, PRF-010), or later |
| `auth_error` | adapter | credential rejected | `running → failed` | person fixes the credential; caller must not retry on the same profile |
| `session_not_found` | adapter | continue on a missing or expired session (ADP-004) | `running → failed` | caller: `session: new` as a new round (`failure`), CHK-007 |
| `timeout` | adapter | `time_s` reached; process group killed (ADP-009) | `running → failed`, partial `output_ref` if any | caller: a new round (`timeout`), possibly with a larger `time_s` |
| `interrupted` | core | caller or person interrupt (DSP-013) | `running → interrupted` or `queued → interrupted` | caller decides; a retry is a new round (`manual`) |
| `harness_error` | adapter, or core under DSP-020 | harness exited with a recognised error, or ended normally with no session id (`session_unknown`, DSP-020) | `running → failed` | caller: a new round (`failure`); repeated → person (DSP-011) |
| `unknown` | adapter | anything not recognised | `running → failed`; redacted stderr tail in the error log (ADP-002) | person reads the error log; caller may retry once |

## 5. Failure expectations

| Situation | Expected outcome |
| --- | --- |
| Core process dies while a node runs | No end line is written; heartbeats stop; the node shows stuck after its stall limit; a person interrupts it (a new `state` line). The harness process may outlive the core; nothing kills it automatically. |
| Two calls append at once | Lines never interleave (LED-006); both nodes recorded. |
| Quota source down | `check_failed` (fail closed, LAW-06) unless overridden with `source_outage`. |
| Heavy-lock holder hung | Waiters end `lock_unavailable` after 1200 s by default; no waiter takes the lock by force. A heavy nested child under a heavy ancestor ends at once instead. |
| Quota source hangs | No answer within 10 s → unknown → `check_failed`; the CLI returns. |
| A `depends` target never ends | The dependent stays queued with a `waiting` check line until the target ends or someone interrupts; no timer ends it. |
| A nested child names its running ancestor in `depends` | `bad_request` at validation (GRF-010); nothing waits. |
| An indirect wait loop through nesting (a nested child waits on a node that waits on the child's ancestor) | Every waiting call on the loop returns `dependency_cycle`; the nodes stay queued, shown stuck with the member list; a person interrupts one; its dependents end `dependency_failed` (DSP-007); the ancestor then continues. |
| Too deep a nesting chain | `nesting_refused` at depth `max_depth` + 1, one error-log line; sibling branches unaffected. |
| Credential value in harness stderr | Only in the error log, redacted (ADP-002); never in the journal or result. |
| Harness never reports a session id | `session` line `session_unknown`; node ends `failed` (`harness_error`) even if the harness ended normally; it cannot be resumed (DSP-020, DSP-021). |
| Journal on a newer major version | `journal_unavailable`; nothing written in the old format. |

## 6. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| DSP-R1 | A front end builds its own request rules and drifts from the other | DSP-001, NG-06 |
| DSP-R2 | A call blocks forever on a `depends` target | DSP-007 waiting line visible; interrupt (DSP-013) |
| DSP-R3 | Overrides become routine and hide real quota stops | DSP-014 closed codes; overrides countable from the journal |
| DSP-R4 | 1200 s is wrong for a project with longer suites | `lock_wait_s` per call up to 3600 |

## 7. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-D1 | Is `trinity resume <run>/<node>` sugar for `call` with that node's session, profile, step and parent (OPEN-V4)? | **Decided: yes** (owner) — DSP-021 |

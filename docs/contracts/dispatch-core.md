# Contract: dispatch core (调用核心) — draft 0.1

Status: **draft, WO-002 contract.** Requirements are unverified until the independent acceptance cases exist. Settles OPEN-08, OPEN-11, OPEN-12.
Terms: `../method/METHOD.md` §2. Binds: LAW-01, 02, 04, 06, 07, 08; CHK-001..009. Graph rules: `graph.md`. Reader: `transcript-reader.md`.

## 1. Purpose

The one call path (LAW-01). Both front ends hand a request to `call`; the core validates it, resolves the profile, writes the node, runs the checks, hands the call to the adapter, and records the outcome. The core never retries on its own (CHK-008).

## 2. Call signature

```text
call(request) -> result

request = {
  run:           "new" | "r-…",
  parent:        "n-…" | null,            # null only for the run root
  step:          "<step label>",          # display label, never a key (LED-002)
  profile:       "<profile name>" | null, # exactly one of profile / provider
  provider:      "<provider name>" | null,# provider only → default pick (PRF-005)
  session:       "new" | "<session id>",
  prompt:        {text: "…"} | {file: "<path>"},
  cwd:           "<path>",
  heavy:         false,
  limits:        {time_s?, stall_s?, lock_wait_s?},
  round_of:      {node: "n-…", reason: <round reason>, reason_ref?} | null,
  depends:       ["n-…", …],              # may be empty
  revises:       "n-…" | null,
  override:      {check: "quota" | "heavy_lock", reason: <override code>, ref?} | null,
  allow_nesting: false
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
| DSP-002 | **Order.** (1) validate the request; (2) take the journal lock; (3) resolve the profile; (4) append the `node` record (state `queued`) and its edges; (5) profile check; (6) dependency gate; (7) quota check; (8) heavy lock; (9) adapter call (`running`); (10) end state. A stop at step 1–2 writes no node; a stop at step 5–8 ends the node `queued → failed` with the class in §4. |
| DSP-003 | **Validation** (step 1) refuses with `bad_request` and writes nothing: both or neither of profile/provider; unknown profile or provider; `parent`, `round_of`, `depends` or `revises` naming a node not in this run; `round_of` whose node is not of the same step and parent; `revises` naming a node that is not earlier; continuing a session under a profile other than the one that created it (PRF-010); an override without a code from the closed list; `stall_s` below 60; `lock_wait_s` above 3600. |
| DSP-004 | **Recursion guard.** When the guard is set in the calling environment and the run does not allow nesting, `call` returns `nesting_refused` and writes nothing (LAW-07). |
| DSP-005 | **Journal fails closed.** If the journal lock or the `node` append fails, nothing starts and `call` returns `journal_unavailable` (one error-log line). If an append fails after the harness started, the core still waits for the harness, returns its real exit class with `journal_complete: false`, and writes one error-log line; the view then shows the node running until its stall limit, then stuck. |
| DSP-006 | **Profile.** A named profile is used as named; provider only → default pick (PRF-005); continue → the session's own profile, found from the journal node that holds that session id; if none is found the caller must name the profile. A disabled profile, a credential file with wide mode (PRF-003) or a retired model id (ADP-010) ends the node `profile_refused`. If the default pick finds no candidate, the node has `profile: null` and one quota `check` line per skipped candidate, and ends `check_failed`. |
| DSP-007 | **Dependency gate.** The node starts only when every `depends` target is `done`. While waiting it stays `queued` with a dependency `check` line `waiting`; the core re-reads the journal every poll interval (DSP-009). A target that ends `failed` or `interrupted` ends this node `dependency_failed`. A cycle is handled by GRF-006 and returns `dependency_cycle`. The wait has no limit of its own; it ends when the targets end, a cycle is found, or the caller interrupts. This is a gate on one call, not scheduling (NG-02). |
| DSP-008 | **Heavy-lock wait limit (OPEN-11): default 1200 s.** A caller may set `lock_wait_s` from 0 to 3600. The wait does not count against `time_s`. The lock `check` line records `waited_s`. Reason: the heavy lock guards full test suites, which take minutes to about a quarter hour; waiting longer than one such run plus margin means the holder is likely hung or forgotten, which a person should look at rather than a queue growing behind it. |
| DSP-009 | **Heartbeat poll interval (OPEN-12): 15 s.** The core polls the adapter's heartbeat source every 15 s and appends a `heartbeat` row only when the source shows new evidence since the last row (CHK-006). A stall limit below 60 s is refused (DSP-003). Reason: stall limits are minutes; 15 s gives at least four polls inside the smallest allowed stall limit, so one late poll never makes a node look stuck; the live view lags the journal by at most one interval; worst-case growth is 240 rows per running node per hour (about 25 KB), pruned at 90 days. |
| DSP-010 | **Exit classes — complete list** in §4. Every result carries exactly one. No other value is ever written or returned. |
| DSP-011 | **Retry owner** per class is the "who retries" column of §4. The core never retries; a retry is a new call with `round_of` set, which becomes a new node and a `round` edge (LED-004). Advice for callers: after two consecutive rounds of one step ending in the same non-`ok` class, hand the step to a person. |
| DSP-012 | **Kill rule.** The core ends a running harness only on `time_s` (adapter kills its own process group, ADP-009) or on interrupt. Stuck is never a reason to kill (RSK-10). |
| DSP-013 | **Interrupt.** A caller or person may interrupt a node: running → adapter kills its process group, state `interrupted`; queued → state `interrupted` with no process started (LED-005). Interrupt is the only way a person breaks a dependency cycle (GRF-006). |
| DSP-014 | **Overrides** apply to the quota check and the heavy lock only, and never to `profile_refused`, the dependency gate, the recursion guard or the journal. An override writes the check line with result `override`, the code and the optional `override_ref` (CHK-004). |

## 4. Exit classes (complete list)

"Set by" is who decides the class. "Journal" is what the journal holds afterwards. "Who retries" names who may make the next attempt and in what form; "—" means a retry is not the right response.

| Class | Set by | Cause | Journal | Who retries |
| --- | --- | --- | --- | --- |
| `ok` | adapter | harness ended normally | state `done` | — |
| `bad_request` | core | request invalid (DSP-003) | nothing | caller fixes the request; not a round |
| `nesting_refused` | core | recursion guard set, nesting not allowed (DSP-004) | nothing | — (the child sees it in its own output) |
| `journal_unavailable` | core | journal lock/append failed before the node, or unknown major version (LED-011) | nothing; one error-log line | person fixes the store; then the caller calls again |
| `profile_refused` | core | profile disabled, wide credential mode, retired model id (DSP-006) | node, `queued → failed` | person fixes the profile; caller may use another profile as a new round (`failure`) |
| `check_failed` | core | quota unknown or exhausted (CHK-002), or no default candidate (PRF-005) | node, quota check line(s), `queued → failed` | caller: another profile as a new round, later, or an override with a code |
| `lock_unavailable` | core | heavy lock not acquired within `lock_wait_s` (DSP-008) | node, lock check line with `waited_s`, `queued → failed` | caller later as a new round (`failure`); person checks the holder |
| `dependency_failed` | core | a `depends` target ended `failed` or `interrupted` (DSP-007) | node, dependency check line naming the target id, `queued → failed` | caller: retry the target first, then this step as a new round |
| `dependency_cycle` | core | the node is on a `depends` cycle (GRF-006) | node, edges, dependency check line `cycle`; state stays `queued` (shown stuck) | person: interrupts one node of the cycle (DSP-013); never the core |
| `quota_exhausted` | adapter | vendor reported quota or rate limit during the run | `running → failed` | caller: another profile as a new round (new session, PRF-010), or later |
| `auth_error` | adapter | credential rejected | `running → failed` | person fixes the credential; caller must not retry on the same profile |
| `session_not_found` | adapter | continue on a missing or expired session (ADP-004) | `running → failed` | caller: `session: new` as a new round (`failure`), CHK-007 |
| `timeout` | adapter | `time_s` reached; process group killed (ADP-009) | `running → failed`, partial `output_ref` if any | caller: a new round (`timeout`), possibly with a larger `time_s` |
| `interrupted` | core | caller or person interrupt (DSP-013) | `running → interrupted` or `queued → interrupted` | caller decides; a retry is a new round (`manual`) |
| `harness_error` | adapter | harness exited with a recognised error | `running → failed` | caller: a new round (`failure`); repeated → person (DSP-011) |
| `unknown` | adapter | anything not recognised | `running → failed`; redacted stderr tail in the error log (ADP-002) | person reads the error log; caller may retry once |

## 5. Failure expectations

| Situation | Expected outcome |
| --- | --- |
| Core process dies while a node runs | No end line is written; heartbeats stop; the node shows stuck after its stall limit; a person interrupts it (a new `state` line). The harness process may outlive the core; nothing kills it automatically. |
| Two calls append at once | Lines never interleave (LED-006); both nodes recorded. |
| Quota source down | `check_failed` (fail closed, LAW-06) unless overridden with `source_outage`. |
| Heavy-lock holder hung | Waiters end `lock_unavailable` after 1200 s by default; no waiter takes the lock by force. |
| A `depends` target never ends | The dependent stays queued with a `waiting` check line until the target ends or someone interrupts; no timer ends it. |
| Two nodes wait on each other | Both calls return `dependency_cycle`; both nodes stay queued, shown stuck; a person interrupts one, the other then ends `dependency_failed`. |
| Credential value in harness stderr | Only in the error log, redacted (ADP-002); never in the journal or result. |
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
| OPEN-D1 | Is `trinity resume <run>/<node>` sugar for `call` with that node's session, profile, step and parent (OPEN-V4)? | Open — proposed yes; owner to confirm scope |

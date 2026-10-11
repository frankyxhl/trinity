# Acceptance cases for the Trinity rework (ACC-001 .. ACC-157, plus GRAPH.md and LEAK.md)

Written by an author who did not write the contracts and who may not be changed by the contracts' author. Code that follows these specs must pass every case. Files:

| File | Cases |
| --- | --- |
| `ACCEPTANCE.md` (this file) | conventions, end-to-end path, ledger, profiles, adapters, dispatch core, reader, views, coverage table, spec gaps |
| `GRAPH.md` | ACC-300 .. ACC-323: nesting, depth limit, loops, revises, depends, mutual wait |
| `LEAK.md` | ACC-200 .. ACC-224: credential leak set, honest thinking, deleted transcripts |

## 0. Conventions

### 0.1 Case format

Every case has: an id, the requirement ids it covers, **Given / When / Then**, the **Observable** that decides pass or fail, and **Fails if** (the failure signature, including the expected refusal or error for negative cases). A case passes only when every Then line holds. A case that cannot be run is a failure, not a skip, unless the report marks it "not applicable" with a reason and the reviewer accepts the reason.

### 0.2 Logical field names

The journal's field names are not final. Cases use logical names and the contract binds the spelling: `run`, `node`, `parent`, `step`, `round`, `depth`, `harness`, `profile`, `profile_reason`, `session{id,mode}`, `transcript_ref`, `output_ref`, `state`, `exit_class`, `output_kind`, `usage`, `edge{kind,from,to,reason}`, `check`, `heartbeat`. Edge kinds are `parent`, `depends`, `round`, `revises` (the earlier draft's `child` is `parent`, `retry` is `round`). A `round` edge runs from the later node to the earlier one (depends on contract fix P1-1; the contract text must say so).

Marker "depends on contract fix <id>" means the case is written against the behaviour the independent review names; until the contract says so the case is expected to fail the contract, not the implementation.

### 0.3 Seams the cases rely on

A case needs these to be runnable. If the contract offers a different mechanism, it must say so in writing and the case's Then lines stay the same.

| Seam | What it is |
| --- | --- |
| S-1 | Journal, state, error-log and cache locations can be moved under a temporary root. |
| S-2 | An injectable clock (wall and monotonic) for age, freshness, stall, retention and prune tests. |
| S-3 | Fake harness executables found through the search path, one per adapter (see 0.4). |
| S-4 | A quota source stub per profile: value, read time, failure, hang. |
| S-5 | The heavy-lock location and wait limit can be set. |
| S-6 | Heartbeat poll interval, stall limit, freshness limit, depth limit and live-update target can be set per test. |
| S-7 | Views can be pointed at a journal file that no run is writing. |

### 0.4 Test doubles

- **DBL-H (fake harness)**: an executable that follows a script. It records its argv, its environment variable *names* and its working directory to a capture file; writes a native transcript in the format of the adapter under test; can exit with any code, sleep, hang, spawn a grandchild, write given bytes to stdout and stderr, and report or withhold usage.
- **DBL-Q (quota stub)**: returns a scripted value with a read time, or fails, or hangs.
- **DBL-C (clock)**: seam S-2.
- **Reader fixtures**: per adapter, a transcript file with all five event types, summary and encrypted thinking, unknown lines, and a deleted-file variant.
- **Sampler**: records the complete argument list of every process of a child tree every 10 ms.
- **Scanner and secrets**: defined in `LEAK.md` (L0, L1).

### 0.5 Parametrisation

`ADAPTERS` = claude-code, codex, droid (also run once for each of its model profiles), agy, anthropic-compat, opencode, deepseek-api. When the contract folds deepseek-api into anthropic-compat as a profile, the deepseek cases run on that profile. Cases marked **[per adapter]** run once per entry and the report shows an adapter-by-case grid (ACC-083).

### 0.6 Public-repo rule

These files contain no tokens, accounts, host names, paths of any deployment, work-order or decision numbers, or clock times. Durations only. Fixture secrets are fake and built at test time.

---

## 1. First end-to-end path

### ACC-001 One profile, new session, one child, journal and CLI tree
Covers: SUC-01, SCO-03, SCO-05, SCO-06, SCO-08, LED-010, VIEW-001, ADP-003, PRF-006
Given: one neutral example profile for the claude-code adapter (subscription billing, quota stub reporting 20% used, fresh), DBL-H scripted for a root call and one child call, a clean temporary root.
When: through the CLI, the caller makes the root call with `session=new`, and the root's task makes one child call; both finish; then `trinity tree <run>` runs.
Then: the journal holds one run start and end, two nodes (root depth 0, child depth 1 with exactly one `parent` edge to the root), a quota check record before each node, at least one heartbeat row per node that ran longer than one poll interval, state lines `queued -> running -> done`, `exit_class` ok, `profile_reason` recorded; the tree shows two lines with correct indentation, 新 session mark with a short id for both, state glyph done, wall time, tokens, exit class and output kind; the journal contains none of the fixture's prompt, thinking, tool or output text.
Observable: parsed journal; the tree text; marker-string scan of the journal.
Fails if: a node missing, a wrong parent, session shown as 续, a number not equal to the journal's, or any text in the journal.

### ACC-002 The same path through the other front end
Covers: SCO-08, NG-06, LAW-01
Given: ACC-001's setup.
When: the identical task is run once through the CLI and once through the host skill entry.
Then: the two journals are equal after masking run ids, node ids and times; the two trees are equal; exit status equal.
Observable: normalised diff of the two journals and trees.
Fails if: any difference in records, order of records, checks or numbers.

### ACC-003 A further round shows as ↺ with its reason, from the journal only
Covers: SUC-02, LED-004, VIEW-004
Given: ACC-001's run, then a caller-issued retry of the child with reason `review_rejection`.
When: the tree is rendered, then every transcript is deleted, then the tree is rendered again.
Then: the child step shows as a folded line "第 2 轮 · 退回 1 次"; expanded, round 2 carries ↺ and its reason; the two renderings are byte-equal.
Observable: both renderings.
Fails if: the reason needs the transcript, or the renderings differ.

### ACC-004 Retro numbers from the journal alone
Covers: SUC-04, LED-010, LAW-02
Given: a scripted run with known truth: 7 nodes, 2 rounds for one step, one rejection, wall times 12 s, 8 s, 30 s, 5 s, 5 s, 9 s, 41 s, usage on 6 of 7 nodes (total 214,000 tokens).
When: the metrics command (or library call) computes wall time per node, token total, rounds, retry reasons and per-step rejection counts.
Then: every figure equals the known truth; the token total is marked partial; no figure is read from anywhere but the journal.
Observable: metrics output against the table; the run repeated with all other files removed gives the same output.
Fails if: any figure differs, partial not marked, or a figure disappears when other files are removed.

---

## 2. Journal (ledger)

### ACC-010 Append-only
Covers: LED-001, LAW-03
Given: a journal with N lines and a recorded hash of its bytes.
When: ten further operations run (new node, state change, edge, check, heartbeat, correction, a view session, a reader call, a rebuild, a failed call).
Then: after each operation the old bytes are an exact prefix of the new file.
Observable: prefix hash equality after each step.
Fails if: any earlier byte changes; any operation rewrites the file in place (including a rename-over).

### ACC-011 A correction is a new line that names its target
Covers: LED-001, LAW-03
Given: a node line with a wrong field value.
When: the caller corrects it.
Then: a new line is appended that names the line it corrects; the old line is unchanged; readers show the corrected value and can show the history; correcting a line that does not exist is refused.
Observable: file diff (one new line); reader output; refusal text.
Fails if: the old line changes, the reader shows the old value, or a dangling correction is stored.

### ACC-012 Ids are generated, unique and stable
Covers: LED-002, LED-R4
Given: two orchestrator processes writing different runs into one journal location, 1,000 nodes each, with 20% identical labels.
When: both finish.
Then: all run ids and node ids are distinct across the journal; no id is derived from a label; ids are identical when the journal is read twice and after a restart.
Observable: set sizes; two reads compared.
Fails if: a collision, or an id that changes.

### ACC-013 Record kinds and required fields
Covers: LED-014, SCO-05
Given: a run exercising every kind: run start/end, node, state, edge, check (quota), check (heavy lock), heartbeat.
When: the journal is parsed.
Then: every line is one JSON object with a version field; each kind carries the fields the contract lists; no kind carries a free-text field holding prompt, thinking, tool or output content; prune lines are absent from the journal.
Observable: schema validation of every line; absence of prune lines.
Fails if: an unknown kind, a missing required field, or a prune line in the journal.

### ACC-014 Retry reasons are a closed set
Covers: LED-004
Given: retry edges requested with each of `review_rejection`, `failure`, `timeout`, `stuck`, `manual`, plus `other`, an empty reason and a missing reason.
When: each is written.
Then: the five are accepted (with an optional pointer to the rejection text); the other three are refused with a stated reason; a pointer is a ref, not text.
Observable: edges written; refusals.
Fails if: a sixth value or an empty reason is stored.

### ACC-015 Round numbers are previous + 1, even under a race
Covers: LED-004, LED-006
Given: a step at round 2; two callers submit the next attempt at the same moment.
When: both write.
Then: the results are rounds 3 and 4 in some order, never two round 3 nodes; the number is assigned by the core under the journal lock (highest existing round of the step + 1), not taken from the caller; each new attempt has its own `round` edge, from the new node to the node holding the round number just before it in assigned order (round 4 points at round 3, round 3 at round 2), whatever node the caller named in `round_of`.
Observable: round numbers and edges.
Fails if: a duplicate round number, a lost attempt, a caller-chosen number, or both new nodes pointing at the same earlier node.
Depends on contract fix P2-6 (who assigns the number and which node the edge targets).

### ACC-016 State machine
Covers: LED-005, DSP-013, RSK-10
Given: a node in each state.
When: every transition is attempted.
Then: only these are accepted (LED-005): `queued -> running`, `running -> done`, `running -> failed`, `running -> interrupted`, `queued -> failed` when a pre-start stop ends the node (exit class `check_failed`, `lock_unavailable`, `profile_refused` or `dependency_failed`; any other class on this transition is refused), and `queued -> interrupted` (a cancel before start, DSP-013, no process started); every other transition is refused, including any move out of `done`, `failed` or `interrupted` and `queued -> done`; a value `stuck` is refused as a state; after a stall limit passes with no heartbeat, the journal still holds no `stuck` line.
Observable: accepted and refused sets; journal scan for `stuck`.
Fails if: any other transition lands, or a `stuck` state is written.

### ACC-017 Parallel writers never interleave
Covers: LED-006, RSK-06
Given: 16 child processes, each writing 200 lines of mixed kinds with sizes from 100 bytes to 3 KB.
When: they run concurrently.
Then: 3,200 lines exist, each a complete valid JSON object ending in a newline; no line is split or merged.
Observable: line count and per-line parse.
Fails if: any partial or merged line, or a lost line.

### ACC-018 A partial last line is skipped, reported, and not glued to
Covers: LED-007
Given: a journal whose last line is cut in the middle (at several offsets, including inside a multi-byte character).
When: a reader loads it, and then a new line is appended by the core.
Then: the reader skips the partial line and reports it; the process does not stop; the next appended line starts on its own line and the partial fragment never merges with it; views still render everything before.
Observable: reader report; parse of the file after the append.
Fails if: a crash, silence, or the appended line parsing as garbage because it joined the fragment.

### ACC-019 Versioning
Covers: LED-011
Given: a journal with `v` = 1 lines; a file with a line `v` = 2; a line without `v`.
When: readers load each.
Then: the v1 file loads; the unknown major version is refused with a clear message naming the version found and the versions supported; a missing version is refused or treated as a defect with a message (the contract binds which, see P2-10), never guessed; for v2 the core returns `journal_unavailable` and writes nothing in the old format.
Observable: messages; journal bytes unchanged.
Fails if: silent acceptance of v2, a stack trace in place of a message, or a line written in v1 form into a v2 file.
Depends on contract fix P2-10 for the missing-`v` outcome.

### ACC-020 No text in the journal
Covers: LED-009, LAW-08
Given: DBL-H emitting marker strings in prompt, thinking, tool and output content.
When: runs finish.
Then: no marker appears in any journal byte; only refs, harness type and enumerated fields appear; there is no option, flag or environment switch that turns text storage on (the test tries `--store-text`-like names the contract lists, and every documented option).
Observable: marker scan; option list scan.
Fails if: a marker is found, or an option exists that stores text.

### ACC-021 A repeated call is a new node
Covers: LED-012, ADP-015
Given: the same prompt sent twice to the same session through the same profile, with DBL-H scripted to give different output each time.
When: both calls finish.
Then: two nodes with different ids; two output refs; the second output is the second script output; no merge, no reuse, no cache hit; usage of each counted separately.
Observable: node count; output refs; DBL-H invocation count 2.
Fails if: one node, one invocation, or the first answer returned twice.

### ACC-022 Duplicate node id is a defect, other kinds repeat ids by design
Covers: LED-012
Given: a journal with two `node` lines carrying the same id, and state, check and heartbeat lines that repeat a node id.
When: loaded.
Then: the first `node` line is kept, the second is reported by id; state, check and heartbeat lines are not reported.
Observable: report.
Fails if: the second replaces the first, or the legitimate repeats are reported.

### ACC-023 Prune at 90 days: the boundary
Covers: LED-013, LAW-03
Given: runs that ended 89 days, 90 days and 91 days before the test clock's now (and one that ended 90 days plus 1 s before), plus a run still running with a last record 1 hour old.
When: the retention prune runs.
Then: the 91-day run and the 90-days-plus-1-s run are removed whole; the 89-day run, the exactly-90-day run (not older than 90 days) and the live run stay; every kept line is byte-identical to before.
Observable: runs present after; byte comparison of kept lines.
Fails if: a partial run remains, a young run is removed, or a kept line changes.

### ACC-024 Prune of a run without an end record
Covers: LED-013
Given: a run that crashed (no end record) whose last record is 100 days old, and another whose last record is 80 days old.
When: the prune runs.
Then: the first is removed whole, the second kept.
Observable: runs present.
Fails if: end time is assumed to be "now" or the start time is used instead of the last record time.

### ACC-025 The prune log is separate and never pruned
Covers: LED-013, LAW-03
Given: a prune that removes 3 runs; a second prune 200 days later by the test clock.
When: the logs are read.
Then: the prune log (a different file from the journal) has a line per prune with run ids, count and time and nothing else; the first line is still present after the second prune; the journal holds no prune line.
Observable: both files.
Fails if: the prune log is pruned, shares the journal file, or carries other content.

### ACC-026 After a prune the journal is still consistent, and writes are not lost during it
Covers: LED-003, LED-013, LED-006
Given: ten runs, four old; a writer appending to a live run continuously.
When: the prune runs concurrently.
Then: every surviving run satisfies the one-parent rule with parents earlier than children; every line appended by the writer during the prune is present afterwards; the tree of every survivor renders.
Observable: invariant check; line counts; renderings.
Fails if: an orphan appears, a live line is lost, or the file is rewritten without the exclusive lock.

### ACC-027 Check and heartbeat lines carry what the contract says
Covers: LED-014, CHK-001, CHK-003, CHK-006
Given: a run with a quota check, a heavy-lock check, a heartbeat, and an override.
When: parsed.
Then: every quota check line names result, source kind and read time; every heavy-lock check line names result and wait time; a heartbeat line has time and source kind and no other content; every node line carries nesting depth.
Observable: field presence per line.
Fails if: any field missing or extra text present.

### ACC-028 `output_kind` is a closed enum and holds no content
Covers: LED-015
Given: nodes whose outputs are a commit id, a verdict word (including the words "approve" and "reject") and nothing.
When: written; then an attempt to write `output_kind` = `approved`, `text` and an empty string.
Then: the three valid kinds are stored with a ref only; the commit id and the verdict word are not in the journal and are read from the ref on demand; the three invalid values are refused.
Observable: journal scan for the commit id and the verdict word; refusals.
Fails if: the id or word is in the journal, or an invalid kind lands.

### ACC-029 A killed writer does not wedge the journal
Covers: LED-006, RSK-06
Given: a writer process killed with SIGKILL while holding the exclusive lock, in the middle of a write.
When: another writer starts.
Then: it gets the lock within a few seconds, appends cleanly (see ACC-018 for the partial line), and the view still renders.
Observable: time to first successful append; file parse.
Fails if: the second writer blocks without bound or the lock needs manual removal.

---

## 3. Profiles

### ACC-050 A profile names a source; the core never reads the value
Covers: PRF-001, NG-05
Given: a profile whose source is an environment variable, and another whose source is a file (mode 600).
When: a call is made with each, with a spy at the adapter boundary and (where the platform allows) a file-access audit of the core process.
Then: the profile object handed to the adapter holds the source, never the value; the core process does not open the credential file or read the variable; the child process does.
Observable: spy capture of the adapter input; audit log of the core process; DBL-H capture proves the child saw it.
Fails if: the value is in the adapter input, or the core process opens the file.

### ACC-051 Listings and journal show name and label only
Covers: PRF-002, SCO-02
Given: three profiles with distinctive source paths and variable names.
When: `trinity profiles` runs and calls are journaled.
Then: output and journal show profile name and label; the paths and variable names appear in neither.
Observable: scan for the distinctive strings.
Fails if: any appears.

### ACC-052 Credential file mode
Covers: PRF-003
Given: credential files with modes 600, 400, 640, 644, 660, 664, 604.
When: each profile is loaded and used.
Then: 600 and 400 are usable; the others make the profile unusable with the reason shown ("mode too wide"); no process starts for an unusable profile; the reason names neither the path nor the value (see ACC-205).
Observable: usability per mode; DBL-H invocation count.
Fails if: a wide mode is accepted, or the reason leaks the path.

### ACC-053 Quota reads carry their time; stale means unknown
Covers: PRF-004, CHK-002
Given: freshness limit 300 s; reads aged 0 s, 299 s, 300 s, 301 s; a profile without a freshness limit.
When: usability is evaluated.
Then: 0, 299 and 300 s are known; 301 s counts as unknown; every read in the journal and in the listing shows its read time; the profile without a freshness limit is refused at load with a message naming the missing field.
Observable: state per age; refusal.
Fails if: 301 s counts as fresh, a read has no time, or a missing limit is defaulted silently.

### ACC-054 Default pick
Covers: PRF-005, SCO-02, NG-02
Given: provider `claude` with profiles at 70%, 20%, 20% (tie), unknown, exhausted and disabled.
When: the caller names only the provider, ten times.
Then: the pick is the lowest known use among enabled, non-exhausted profiles; the tie resolves the same way every time; unknown, exhausted and disabled are never picked; when only those remain, dispatch stops with a stated reason and nothing starts, unless the caller names a profile; the core never picks a profile of another provider.
Observable: the chosen profile across ten runs; DBL-H invocation counts.
Fails if: an excluded profile is picked, the tie flips, or dispatch starts with nothing eligible.

### ACC-055 The reason for the pick is journaled
Covers: PRF-006
Given: three calls: profile named, provider only, and an override of a failed check.
When: they run.
Then: each node line carries `profile_reason` = `named`, `default:lowest-use`, `override` respectively.
Observable: the three values.
Fails if: a value is missing or wrong.

### ACC-056 Model ids live in profile data only; retired ids are refused at load
Covers: PRF-007, LAW-05, ADP-010
Given: (a) the adapter source tree and the front ends; the model ids from the example profile data and a list of retired ids; (b) a pack of 3 profiles where one carries a retired id.
When: (a) a source scan runs; (b) the pack is loaded and `trinity profiles` runs.
Then: (a) no model id literal from the data or the retired list appears in any code, agent file or prose of the product (data files and tests excepted); (b) the retired profile is refused with a message naming the profile and the reason, the other two load and are usable, and a call that names the retired profile starts no process.
Observable: scan hits; usability; DBL-H invocation count.
Fails if: any literal in code, a whole pack refused for one bad profile, or a retired profile callable.

### ACC-057 Layers
Covers: PRF-008, LAW-09
Given: a profile `p` defined in the repository examples (model M1), in a private pack (M2) and in a project override (M3); the pack location supplied by environment variable or config at run time.
When: it is resolved with all three, then without the override, then without the pack location.
Then: M3, then M2, then M1; with no pack location, examples only and no error; the repository (including docs and examples) names no pack location, account, host or token path (a scan with the public-repo rule's patterns finds nothing).
Observable: resolved model; scan.
Fails if: precedence differs, a missing pack is an error, or the repository points at the pack.

### ACC-058 Transcript retention is data on the profile
Covers: PRF-009, ADP-014
Given: profiles stating retention "30 days", "unknown", and a profile missing the field.
When: loaded, and used for a gone-transcript read (ACC-214).
Then: the field takes a duration or `unknown`; a missing field is refused or defaulted to `unknown` as the contract states (never to a number); the reader uses it to compute the expected expiry.
Observable: loaded values; expiry in the reader result.
Fails if: a number is invented.

### ACC-059 A continued session stays on its profile
Covers: PRF-010, SCO-03
Given: a session created under profile P1; P2 has lower use.
When: (a) continue naming P2; (b) continue naming only the provider; (c) continue naming P1.
Then: (a) refused with a stated reason, no process starts; (b) reuses P1 and skips the default pick; (c) continues; a retry round on P2 starts a new session with a new id.
Observable: outcomes; DBL-H invocation counts and profile per node.
Fails if: (a) runs, or (b) chooses P2.

### ACC-060 Disabled profiles
Covers: PRF-005, SCO-02
Given: a disabled profile.
When: named by the caller, and then picked by default.
Then: named: refused with a reason; default: skipped.
Observable: outcomes.
Fails if: the disabled profile runs.

### ACC-061 The profile listing
Covers: SCO-02, PRF-002, PRF-004
Given: profiles with different billing modes, fresh and stale reads, and one default.
When: `trinity profiles` runs.
Then: each row shows name, label, billing, current use with read time (stale or failed reads shown as unknown, not as a number), and the default marker sits on exactly one profile per provider, the one ACC-054 would pick.
Observable: parsed rows.
Fails if: a stale read is shown as a number or two defaults appear.

---

## 4. Provider adapters

### ACC-070 One shape for every adapter, one call path **[per adapter]**
Covers: ADP-001, LAW-01
Given: the same input record for each adapter.
When: the call runs against DBL-H.
Then: each returns the same output field set (harness, session id, output ref, exit class, transcript ref, usage when reported, start and end times) with `harness` equal to the adapter name; static scan: no code outside adapter modules branches on a harness name; dispatch code has a single call entry.
Observable: output schema equality across adapters; scan.
Fails if: a field differs, or harness-specific branches exist outside an adapter.

### ACC-071 Exit classes **[per adapter]**
Covers: ADP-002, DSP-010, LAW-04
Given: DBL-H scripted to behave as: success; generic failure; bad credential; quota or rate message; hang past the time limit; unknown session; unclassifiable output; killed by signal (caller interrupt); and the core-set stops.
When: each runs.
Then: the adapter-set classes are exactly `ok`, `quota_exhausted`, `auth_error`, `session_not_found`, `timeout`, `harness_error`, `unknown`, each mapped from its script; the core-set classes (`bad_request`, `nesting_refused`, `journal_unavailable`, `profile_refused`, `check_failed`, `lock_unavailable`, `dependency_failed`, `dependency_cycle`, `interrupted`) never come from an adapter; every result carries exactly one class from the full 16-class list in DSP-010 and no other value is ever written or returned; `unknown` comes with the last 2 KB of redacted stderr in the error log and nothing in the journal.
Observable: class per script; the set of every class value seen in journal and results is a subset of DSP-010's list; error log; journal scan.
Fails if: a value outside the 16, an adapter returning a core-set class, a wrong mapping, or stderr in the journal.
Note: the contract's adapter spec lists the adapter-set classes inconsistently (review P2-3); this case follows dispatch-core section 4 (depends on contract fix P2-3).

### ACC-072 New session id by marker or reported id, never by newest file **[per adapter]**
Covers: ADP-003, SCO-03
Given: a decoy transcript with a newer modification time written by an unrelated process in the same directory; also two new-session calls started together in the same working directory.
When: the calls finish.
Then: each call returns the id of its own session; the decoy is never taken.
Observable: ids against the scripts; transcript refs against the scripts.
Fails if: a call gets the decoy's id or the other call's id.

### ACC-073 Missing session is surfaced, never replaced **[per adapter]**
Covers: ADP-004, CHK-007
Given: a session id that does not exist or has expired.
When: a continue is requested.
Then: exit class `session_not_found`; no new session is created (the count of sessions in the fixture store is unchanged); the caller sees it; a following explicit new call is a separate new node.
Observable: class; session count; node list.
Fails if: a session appears silently or the class differs.

### ACC-074 Continue session **[per adapter]**
Covers: SCO-03, PRF-010, ADP-001
Given: a finished new-session node.
When: a continue is requested on the same profile.
Then: the same session id comes back, the node records mode `continue`, the tree shows 续 with that short id; a second continue also works.
Observable: ids and mode.
Fails if: a new id appears or the mode is `new`.

### ACC-075 Bad or rotated credential **[per adapter]**
Covers: ADP-002, PRF-R3
Given: DBL-H rejects the credential on the first call and on a continue after a rotation.
When: calls run.
Then: exit class `auth_error`, surfaced to the caller; the core does not retry on its own; no credential value anywhere; the session stays recorded.
Observable: class; invocation count 1.
Fails if: a hidden retry, a different class, or a leaked value.

### ACC-076 Heartbeat source and stall limit declared **[per adapter]**
Covers: ADP-008, CHK-006, DSP-003, DSP-009
Given: each adapter's declaration.
When: loaded; a profile overrides the stall limit for one adapter.
Then: each declares a source in {transcript growth, stdout, process alive} and a default stall limit of at least 60 s (DSP-003, DSP-009); an override below 60 s is refused with `bad_request`; the override replaces the default only for that profile.
Observable: declarations; effective limits.
Fails if: a declaration is missing or an override leaks into other profiles.

### ACC-077 Timeout and interrupt kill only what the adapter started **[per adapter]**
Covers: ADP-009
Given: DBL-H that spawns a grandchild and then hangs; an unrelated process with a similar name started by the test.
When: the time limit passes; and separately an interrupt arrives.
Then: the whole process group the adapter started is gone (child and grandchild); the unrelated process still runs; partial output is reported with class `timeout` or `interrupted`; the product's source holds no name-based kill (`pkill`, `killall`).
Observable: process table before and after; class; scan.
Fails if: a survivor in the group, a casualty outside it, or a name-based kill.

### ACC-078 A retired model id is refused before any process starts **[per adapter]**
Covers: ADP-010, LAW-05
Given: a profile with a retired model id for each adapter.
When: a call is requested.
Then: refused with a message; DBL-H invocation count 0; no node enters `running`.
Observable: count; states.
Fails if: any process starts.

### ACC-079 Usage is copied or absent **[per adapter]**
Covers: ADP-011, VIEW-010
Given: DBL-H reporting 48,000 tokens; DBL-H reporting nothing; DBL-H reporting 0.
When: the calls finish.
Then: 48,000 is recorded; "nothing" leaves `usage` absent (not 0, not null, not an estimate); a reported 0 is recorded as 0; the header total is marked partial in the second case only.
Observable: journal field presence; header.
Fails if: a number appears where nothing was reported.

### ACC-080 Reader: all five event types, in order, with a raw ref **[per adapter]**
Covers: ADP-012, RDR-003, SCO-01
Given: the reader fixture holding prompt, thinking, tool, output and heartbeat events, with known times, plus two events whose line carries no time.
When: the reader returns events.
Then: events come in transcript (file) order with `seq` rising by 1 from 0; each carries `seq`, type, text and a raw ref; `t` is the transcript's own time or `null` (never invented, never filled from a neighbour); the raw ref resolves to the source bytes; event count equals fixture count; no re-sort by time happens.
Observable: seq sequence; `t` values; ref resolution.
Fails if: a type missing, `seq` not rising, events re-ordered by time, a time invented for a null-time event, or a ref that does not resolve.

### ACC-081 Refs that no longer fit the file **[per adapter]**
Covers: ADP-012, ADP-014, RDR-006, RDR-007
Given: a ref whose offset is past the end of the file (truncated or rotated); a ref whose content hash no longer matches the bytes; a file with permissions that deny read; a file that is missing.
When: the reader is asked.
Then: past-the-end offset and hash mismatch each give status `ref_mismatch` with an empty event list and no time field set; permission or read error gives `unreadable`; missing file gives `gone` (ACC-214); never content from a different offset presented as the node's events; an empty event list is never returned with status `ok` for these.
Observable: status per fixture; event list; absence of foreign content.
Fails if: the wrong bytes are shown, status `ok` with no events, a time attached to `ref_mismatch`, or the call crashes.

### ACC-083 Adapter-by-case grid
Covers: SCO-01, SCO-03
Given: the results of ACC-070 to ACC-081, ACC-150 and ACC-209.
When: the report is built.
Then: it holds a full grid of adapters against cases with a verdict in every cell; an adapter or case absent from the grid fails the grid.
Observable: the report file.
Fails if: a cell is empty.

### ACC-084 Gemini is removed
Covers: SCO-07, ADP-R6
Given: the product's registry and a machine with an old gemini agent file already installed.
When: `trinity gemini "task"` is run; the installer is run, then run again.
Then: the registry holds no gemini entry; the call is refused as an unknown provider and no process starts; the installer removes the old agent file or prints a warning naming it, and the second run is quiet and changes nothing; the file is never left callable.
Observable: registry content; invocation count; installer output; second-run diff.
Fails if: gemini still runs, or the old file is left silent and active.

### ACC-085 Provider names and compatibility
Covers: LAW-10, LAW-01, SCO-01
Given: the baseline's recorded command lines and outputs for `/trinity <provider> "task"` (codex, glm, minimax, agy, openrouter, deepseek) and for `trinity review`.
When: replayed against DBL-H.
Then: each provider name resolves to its adapter (glm and minimax to droid; openrouter to anthropic-compat; deepseek per the contract); the recorded invocations still work with the same arguments and produce an equivalent result.
Observable: resolved adapter; replay equivalence.
Fails if: a baseline invocation stops working.

### ACC-086 Compatible endpoints keep their error classes apart
Covers: ADP-002, ADP-R5
Given: an anthropic-compat endpoint double returning (a) a rate-limit reply and (b) an out-of-balance reply; and the same through a deepseek API double.
When: calls run.
Then: each maps to a class in the list; the distinguishing detail (rate limit vs balance) is present, masked, in the error log or the reason shown to the caller; the two are not both `unknown`.
Observable: classes; log detail.
Fails if: the two cannot be told apart.

### ACC-087 Both billing modes of one vendor
Covers: SCO-01, ADP-001, VIEW-010
Given: a vendor reachable by a subscription profile and a metered profile.
When: one call each.
Then: both use the same call path and output shape; the node lines record the billing mode through the profile; the header counts one subscription and one metered node.
Observable: records; header counts.
Fails if: a mode is lost.

---

## 5. Dispatch core

### ACC-110 A quota check precedes every node
Covers: CHK-001, SCO-04, LED-014
Given: a run of three nodes.
When: it runs.
Then: for each node a quota check line (result, source kind, read time) is written before the node enters `running`.
Observable: line order.
Fails if: a node runs without a preceding check.

### ACC-111 Unknown, stale, failed and exhausted all stop the node
Covers: CHK-002, LAW-06, SCO-04
Given: DBL-Q scripted as: source missing; source errors; read older than the limit; value exhausted; value unknown.
When: a node is requested for each.
Then: the node goes `queued -> failed` with exit class `check_failed`, never runs, a check line records the result, the CLI exits non-zero with a stated reason naming the profile and the check (not the source location); with the caller's override flag and reason (ACC-113) it runs.
Observable: states; invocation count 0; message.
Fails if: any case starts a process without an override.

### ACC-112 Heavy lock
Covers: CHK-003, SCO-04, LED-014
Given: two nodes marked heavy and one that is not, with the lock wait limit set to 5 s (seam S-5).
When: the first heavy node holds the lock for 3 s; then for 20 s; and a holder is killed with SIGKILL.
Then: 3 s: the second waits and runs, a lock check line shows its wait time; 20 s: the second goes `queued -> failed` with class `lock_unavailable` after the limit, with a lock check line, never runs; the lock is released at end on success, failure, timeout kill and crash (the next heavy node acquires it within the limit after the holder dies); the non-heavy node never takes the lock.
Observable: states, wait times, lock availability.
Fails if: unbounded waiting, a lock left held, or the non-heavy node blocked.

### ACC-113 Override is a closed code, explicit and recorded
Covers: CHK-004, DSP-003, DSP-014, LAW-06
Given: a failing quota check and a failing lock check.
When: the caller passes an override for the failing check (a) with each code of the closed list (`owner_approved`, `source_outage`, `lock_holder_known`, `other`), optionally with an `override_ref`; (b) with no code; (c) with a code not on the list (for example `because`, an empty string, or a sentence).
Then: (a) the node runs and the check line records result `override`, the code and the ref if given, and no free text; (b) and (c) are refused with `bad_request`, no node is written and no process starts; an `override_ref` is a pointer, not text (see ACC-211).
Observable: check line fields; refusal class; node count.
Fails if: an override works silently, without a code, with an unlisted code, or stores text.

### ACC-114 Heartbeat rows come from the core, at most once per interval
Covers: CHK-006, VIEW-005, LED-014
Given: poll interval 2 s, a node running 30 s on the test clock whose transcript grows for the first 10 s and then stops.
When: the run goes on.
Then: no more than one row per interval; rows exist while there is evidence of life and none after the evidence stops; each row has time and source kind only; views never write rows.
Observable: row count and times; row content.
Fails if: more than one row per interval, rows without evidence, or text in a row.

### ACC-115 The core does not retry on its own
Covers: CHK-008, NG-02
Given: DBL-H that fails, times out and returns `session_not_found` in turn.
When: each call ends.
Then: exactly one invocation each; no further node appears until the caller issues a retry, which then appears as a new round with a reason; the core never switches profile or provider after a failure.
Observable: invocation counts; node list.
Fails if: a second invocation without a caller request.

### ACC-116 Stuck is derived, shown, and never acted on
Covers: LED-005, VIEW-003, RSK-10, NG-06
Given: a running node with stall limit 120 s; heartbeats stop at t0.
When: the test clock moves to t0 + 119 s, + 120 s, + 121 s, + 6 min, and then a heartbeat arrives.
Then: running at 119 s and 120 s (not older than the limit); stuck at 121 s and later with the age shown ("6 分钟无心跳" at 6 min); the process is still alive and untouched; no `stuck` line is written; the CLI and the web derive the state from the same function; after the heartbeat the node shows running again.
Observable: state per time in both views; process table; journal scan.
Fails if: a kill, a written state, a different state per view, or a wrong boundary.

### ACC-117 No daemon, no tmux, no long-lived control connection
Covers: NG-04, NG-01
Given: an environment with no terminal multiplexer on the search path.
When: a full run, a view session and an exit.
Then: the run works; after the last Trinity command exits no Trinity process or listening socket remains (except as ACC-140 allows for a short-lived live reader); no connection to a harness is kept open between calls.
Observable: process and socket table before and after.
Fails if: a residual process, or a failure caused by the missing multiplexer.

### ACC-118 The core never writes, copies or prints credentials
Covers: NG-05
Given: a credential file and variable with known hash, mode and modification time, in a home directory with a recorded file list.
When: a full run completes, including failure paths.
Then: the credential file is byte-identical with the same mode and time; no new file in the temporary root contains the value; nothing printed contains it.
Observable: hashes; scan of the root.
Fails if: any copy, rewrite or print.

### ACC-119 A verdict is evidence, not approval
Covers: NG-03, LED-015
Given: a review node whose output is the word `approve`.
When: recorded and viewed.
Then: the node is `done` with `output_kind` verdict and a ref; no field, state or view marks the unit accepted or merged; the word is read from the ref on demand only.
Observable: journal and view scan for acceptance fields.
Fails if: any acceptance state exists.

### ACC-120 Front ends hold no logic
Covers: NG-06, SCO-08
Given: the core entry replaced by a spy; and the real core.
When: the skill shim and the CLI are given the same arguments.
Then: with the spy, each front end calls the entry once with parsed arguments and does nothing else (no journal write, no check, no state derivation); with the real core the results are identical (ACC-002).
Observable: spy log; absence of side effects.
Fails if: a front end writes, checks or derives anything itself.

### ACC-121 Presets and plan mode are untouched
Covers: LAW-10, SCO-09
Given: the baseline's recorded outputs for the presets and plan mode.
When: replayed.
Then: behaviour equals the baseline; nothing in them reads or writes the journal (they are rebuilt later, not now).
Observable: output equivalence; file access trace.
Fails if: behaviour changed or they touch the journal.

### ACC-122 Fail-closed checks are bounded
Covers: LAW-06, CHK-002
Given: a quota source that hangs; a lock location that is unreachable.
When: a node is requested.
Then: the check gives up after a bounded time (the contract's limit), counts as unknown, the node fails closed with a reason; the CLI does not hang.
Observable: time to the failure; state.
Fails if: unbounded waiting or a start without an answer.
Depends on contract fix P2-10: the contract sets the quota-read timeout; fixture bound 10 s until then.

### ACC-123 Order of the steps in one call
Covers: DSP-002, CHK-001, CHK-002
Given: a call that fails the quota check, a call that fails the heavy lock, a call that is refused at validation, and a call that passes everything; a spy sees each step.
When: they run.
Then: the order is validate, journal lock, profile, node record `queued` with its edges, profile check, dependency gate, quota check, heavy lock, adapter call, end state; a stop at validation or at the lock step leaves no node; a stop at profile check, dependency gate, quota check or heavy lock ends the node `queued -> failed` with the class of that step (exception: a dependency cycle, see ACC-314b and ACC-316), and no later step is reached.
Observable: step trace; node lines.
Fails if: a step runs out of order, a node exists after a validation stop, or a step after the stopping one runs.

### ACC-124 Validation refuses with `bad_request` and writes nothing
Covers: DSP-003, DSP-001
Given: a valid baseline request and these mutations, one each: both profile and provider; neither; unknown profile; unknown provider; `parent` of another run; `round_of` of another run; `round_of` naming a node of another step; `round_of` naming a node with another parent; `depends` of another run; `revises` of a node that is not earlier; continuing a session under a profile other than the one that created it; an override without a code; `stall_s` = 59; `lock_wait_s` = 3601; and, as controls, `stall_s` = 60 and `lock_wait_s` = 3600.
When: each is submitted through both front ends.
Then: each mutation returns `bad_request` with a reason naming the field; the journal is byte-identical afterwards; no process starts; the two controls are accepted; both front ends give the same result for each.
Observable: result class and reason; journal hash; invocation count.
Fails if: a mutation lands, a node or edge is written, or the front ends differ.

### ACC-125 Journal fails closed
Covers: DSP-005, LED-006, LAW-06
Given: (a) the journal directory read-only before the call; (b) the journal lock unobtainable; (c) the journal made unwritable after the harness started (the harness is scripted to run 5 s on the test clock); (d) a journal whose major version is newer.
When: a call is made.
Then: (a), (b) and (d): result class `journal_unavailable`, no process starts, nothing is written, one error-log line (no secret in it); (c): the core still waits for the harness, returns the harness's real exit class with `journal_complete: false`, writes one error-log line, and does not kill the harness; the view then shows the node running until its stall limit and stuck after it.
Observable: result fields; invocation count; error log; view state over time.
Fails if: a process starts in (a), (b) or (d); the harness is killed or abandoned in (c); `journal_complete` is true in (c); or the call hangs.

### ACC-126 Heavy-lock wait limit: the default and its range
Covers: DSP-008, CHK-003, DSP-003
Given: the lock held by a hung holder; no `lock_wait_s` set; then `lock_wait_s` = 0, 3600 and 3601.
When: a heavy node waits for the lock (test clock).
Then: with no value the waiter ends `lock_unavailable` at 1200 s, not before and not after (1199 s still waiting, 1200 s ends); `lock_wait_s` = 0 fails at once when the lock is held; 3600 is accepted; 3601 is refused `bad_request`; the lock check line records `waited_s`; the wait does not count against `time_s` (a node with `time_s` = 60 still waits past 60 s); no waiter takes the lock by force.
Observable: state and time of the end; check line `waited_s`.
Fails if: a different default, a wait limited by `time_s`, a forced take, or a value out of range accepted.
Note: the contract text for this limit differs between the method file ("may lower") and dispatch-core ("0..3600"); this case follows dispatch-core (depends on contract fix P2-1).

### ACC-127 Heartbeat poll interval default and the stall floor
Covers: DSP-009, CHK-006, DSP-003
Given: defaults; a node running 10 minutes on the test clock whose transcript grows for the first 2 minutes; then stall limits 59 s, 60 s.
When: the run goes on.
Then: the core polls every 15 s (poll times 15 s apart, at most one row per poll, a row only when the source shows new evidence since the last row); no row after the evidence stops; at most 240 rows per hour of a continuously growing node; stall 59 s is refused `bad_request`, 60 s accepted; a late single poll never turns a 60 s-limit node to stuck.
Observable: row times; count; refusal.
Fails if: a different default interval, a row per poll without new evidence, or the floor not enforced.

### ACC-128 Overrides cover the quota check and the heavy lock only
Covers: DSP-014, CHK-004, LAW-06
Given: an override code supplied on a call that ends (a) `profile_refused` (wide credential mode), (b) blocked by a failed dependency, (c) refused by the recursion guard, (d) hit by `journal_unavailable`, (e) blocked by the quota check, (f) blocked by the heavy lock.
When: each runs.
Then: (a) to (d) are not overridden: the same class as without the override; no override check line is written for them; (e) and (f) run and write a check line `override` with the code.
Observable: class per case; check lines; invocation counts.
Fails if: any of (a) to (d) starts a process, or (e)/(f) ignore the override.

### ACC-129 Dependency gate: waiting, failed targets, interrupts
Covers: DSP-007, DSP-013, GRF-005, GRF-009
Given: B depends on A; A runs 20 s on the test clock; separately A fails; separately A is interrupted; separately A never ends.
When: B is submitted.
Then: B stays `queued` with a dependency check line `waiting` (written once, not once per poll); the core re-reads the journal every 15 s; when A is `done` B proceeds; when A ends `failed` or `interrupted` B ends `queued -> failed` with `dependency_failed` and the check line names A; with A never ending B keeps waiting with no timer of its own, until A ends or B is interrupted (`queued -> interrupted`, no process started); blocked time (waiting line to start) is derivable from the journal.
Observable: state lines; check lines; harness invocation counts.
Fails if: B starts early, B waits forever after A failed, B times out on its own, or B's wait is not recorded.

### ACC-142 Interrupt of a queued and of a running node
Covers: DSP-013, DSP-012, LED-005
Given: one queued node and one running node (with a grandchild process).
When: a caller interrupts each.
Then: queued: `queued -> interrupted`, no process was started; running: the adapter's process group is killed and the node ends `running -> interrupted`; exit class `interrupted` for both; an interrupt of a `done`, `failed` or `interrupted` node is refused; stuck alone never kills a node (ACC-116).
Observable: state lines; process table.
Fails if: a queued node runs after the interrupt, a survivor remains in the group, or a finished node changes state.

### ACC-143 Profile resolution and its refusals
Covers: DSP-006, PRF-005, PRF-010, ADP-010
Given: (a) a named profile; (b) provider only; (c) a continue whose session is found in the journal; (d) a continue whose session id is in no journal node and no profile named; (e) a disabled profile; (f) a credential file with wide mode; (g) a retired model id; (h) a provider whose default pick finds no candidate (two profiles skipped).
When: each call is made.
Then: (a) is used as named; (b) default pick; (c) the session's own profile is used; (d) the caller must name the profile (`bad_request`, no node); (e), (f), (g) end the node `queued -> failed` with `profile_refused` and no process starts; (h) the node carries `profile: null`, one quota check line per skipped candidate, and ends `check_failed`.
Observable: result class; node `profile` field; check line count; invocation count.
Fails if: any refused profile starts a process, (h) leaves no per-candidate check line, or (d) guesses a profile.

### ACC-144 One class per result, and the retry owner
Covers: DSP-010, DSP-011, CHK-008
Given: a scripted sequence that produces every one of the 16 classes in DSP-010 once.
When: the results and journals are read.
Then: each result carries exactly one class; each class shows the journal effect the class table lists (node and state change, check lines, error-log line or nothing); after any class the core makes no new call by itself; a caller-issued retry is a new node with a `round` edge; two consecutive rounds of one step ending in the same non-`ok` class are listed by the metrics output as "hand to a person" (advice only: the core takes no action).
Observable: class and journal effect per script; node count after each result.
Fails if: a class is missing from the table, a result carries two or none, the journal effect differs from the table, or the core retries.

---

## 5b. Transcript reader (contract: transcript-reader)

### ACC-150 The reader follows the harness field and has one interface **[per adapter]**
Covers: RDR-001, ADP-012
Given: for each adapter a transcript fixture; a transcript of adapter X placed under a node whose journal `harness` is Y.
When: the reader is called for each, and for the swapped case.
Then: the reader is chosen by the node's `harness` field only; every reader returns the same result shape (`status`, `events`, `thinking`, `next_seq`, `redactions`, `found_missing_at`, `expected_expiry`) and the same event shape; for the swapped case the reader does not sniff the file and switch: it returns `unreadable` or `raw` events, never a silently correct parse.
Observable: result schema; swapped result.
Fails if: a reader guesses the format from the file, or a field is missing.

### ACC-151 Reader is on demand and keeps nothing on disk
Covers: RDR-002, LAW-08
Given: a spy on file creation; a node with a transcript.
When: the tree is rendered, then one node's events are requested, then the view is closed.
Then: the reader runs only for the request; no file is created or changed outside the vendor fixture; nothing of its output is in the journal (see ACC-215, ACC-222).
Observable: reader call count; file-creation log.
Fails if: a reader call at tree time, or a file with event text.

### ACC-152 Unknown lines become raw output events
Covers: RDR-004, ADP-012
Given: a transcript with recognisable lines, unknown-kind lines and malformed lines (see ACC-223 for the leak side).
When: read.
Then: every unknown or malformed line is an `output` event with `raw: true`; the count of events equals the count of lines; nothing is dropped; the reader does not raise.
Observable: counts; raw flags.
Fails if: a dropped line or a crash.

### ACC-153 Honest thinking at the reader result
Covers: RDR-005, ADP-013, LAW-11
Given: the four thinking fixtures of ACC-213.
When: the reader returns.
Then: `thinking_form` is `summary`, `encrypted` (with empty `text`, never the ciphertext), `full` only when full text is in the transcript, and the result field `thinking` is `absent` with no thinking events for the no-thinking fixture.
Observable: result fields.
Fails if: a ciphertext in `text`, `full` on a summary, or `present` with no thinking events.

### ACC-154 Gone result fields
Covers: RDR-006, ADP-014, PRF-009
Given: a deleted transcript; profile retention 30 days, and `unknown`.
When: read at a known test-clock time.
Then: `status` is `gone`; `found_missing_at` is the time of this read; `expected_expiry` is node start + 30 days for the first profile and `null` for the second; `events` is empty; no `ref_mismatch` is returned for a missing file.
Observable: result fields.
Fails if: a fabricated expiry, a missing time, or the wrong status.

### ACC-155 Paging and the size limits
Covers: RDR-009, VIEW-R2
Given: a transcript with 5,000 events; one event whose text is 200 KiB; a request for `max_events` = 2000 and one for 2001.
When: read page by page.
Then: no page holds more than 2000 events (a request for 2001 is cut to 2000 or refused `bad_request`, as the contract states); `next_seq` points at the first event of the next page and is `null` on the last; every event is returned exactly once across the pages, in `seq` order; the 200 KiB event comes back cut at 64 KiB with `truncated: true` and its `raw_ref` still resolves to the full bytes; an event of exactly 64 KiB is not marked truncated, one of 64 KiB + 1 byte is.
Observable: page sizes; seq coverage; event text length; truncated flags.
Fails if: an event repeated or lost between pages, a page over 2000, the cut at another size, or `truncated` wrong.

### ACC-156 The reader never changes a transcript and reads a live one
Covers: RDR-011, RDR-010
Given: a transcript being appended to by DBL-H (the last line is half written at the moment of the read); a read-only directory.
When: the reader reads.
Then: events come up to the last complete line; the half line is not returned as an event; the next read from `next_seq` picks up the finished line; the file's bytes, mode, modification time and lock state are unchanged by the reads (the reader opens read-only); heartbeat events come only from markers inside the transcript, and journal heartbeat rows are not reader input (a view may merge them, labelled as journal rows).
Observable: events per read; file hash, mode and mtime before and after; event source labels.
Fails if: a half line shown, the file touched, or a journal row presented as a transcript heartbeat.

### ACC-157 The reader never hands out a credential source
Covers: RDR-012, PRF-002
Given: a profile with a credential path and a variable name; a transcript that mentions the variable name.
When: the reader runs for that node.
Then: neither the path nor the variable name of the profile comes back in `events`, in `raw_ref.path` strategy aside (see ACC-212), or in an error; only redacted text is returned.
Observable: scan of the result.
Fails if: either string appears.

---

## 6. Views

### ACC-130 CLI and web show the same tree
Covers: VIEW-001, LAW-02
Given: six fixture journals: plain, nested, looped, with a stuck node, with a failed node, with a gone transcript.
When: `trinity tree` output and the web view's data are parsed.
Then: nodes, parents, states and numbers are identical for each journal; event detail is excluded from the comparison.
Observable: normalised comparison.
Fails if: any difference.

### ACC-131 Plain output and the ASCII fallback
Covers: VIEW-002
Given: output piped to a file; `--ascii`; and a non-UTF-8 locale.
When: `trinity tree` runs.
Then: no escape sequences in piped output; the glyphs ✓ ● ! ↺ and box lines become ASCII with `--ascii` or the non-UTF-8 locale (no byte above 127); one line per node; works over a non-interactive remote shell.
Observable: byte scan; line count.
Fails if: control sequences in a pipe, or non-ASCII in ASCII mode.

### ACC-132 Five states and the stuck age
Covers: VIEW-003, NG-06
Given: a journal with one node in each of done, running, stuck, failed, interrupted.
When: rendered in both views.
Then: five distinct state marks; the stuck node shows its age; both views call one state-derivation function (a spy or a single definition).
Observable: marks; spy.
Fails if: two derivations exist.

### ACC-133 Live mode reads appended lines only
Covers: VIEW-005, SCO-06
Given: a view open on a run and a spy on process creation and network use by the view.
When: lines are appended to the journal, including heartbeat rows.
Then: the view updates from the appended lines; the view starts no vendor CLI, no `ps`/`pgrep`-like probe, makes no outbound network call; with the journal quiet the view keeps its last state.
Observable: updated output; spy log.
Fails if: any probe or outbound call.

### ACC-134 The web view is local and read-only
Covers: VIEW-006, SCO-06
Given: the web view running on a machine with a non-loopback address.
When: the listening sockets are listed; a connection is tried via the non-loopback address; non-GET requests are sent; the page is opened with no credential.
Then: listening sockets are on 127.0.0.1 or ::1 only; the other address refuses; any request that would change something is refused; the page loads with no credential and sets no cookie.
Observable: socket list; connection results; responses.
Fails if: a wildcard bind, a write endpoint, or a login.

### ACC-135 Event text is text
Covers: VIEW-007
Given: events whose text holds `<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `&lt;b&gt;`, a closing-tag sequence, and node labels, step names and profile labels with the same strings; and for the terminal: ANSI colour codes, a cursor-move, a carriage return that overwrites a line, and an operating-system-command sequence.
When: shown in the web detail pane, in the tree, and by `trinity show --events`.
Then: the web DOM holds the strings as text nodes equal to the input and no element created from them; no script runs; the terminal output holds no live control sequences (they are shown escaped or stripped), so a child's output cannot rewrite earlier lines or touch the terminal's clipboard.
Observable: DOM inspection; byte scan of CLI output for ESC (0x1b) other than the view's own styling.
Fails if: an element appears, a script runs, or a control sequence reaches the terminal.

### ACC-136 Wide characters align
Covers: VIEW-009
Given: a fixture run with 5 Chinese step labels and 5 ASCII labels, plus one with full-width punctuation and one with a label too long to fit.
When: the CLI tree is rendered.
Then: the duration column starts at the same display column on every line (computed with East Asian width); the too-long label is cut without splitting a wide character.
Observable: display column of the duration per line.
Fails if: any line differs.

### ACC-137 Header totals
Covers: VIEW-010, ADP-011
Given: a journal of 6 nodes (2 subscription, 4 metered; 1 running, 1 stuck), 5 with usage and 1 without; then the same with usage on all six; then one node with usage 0.
When: the header is rendered.
Then: elapsed, token total, subscription and metered counts, running and stuck counts equal sums over the journal; the token total is marked partial in the first case only; a reported 0 does not make it partial.
Observable: header text against the table.
Fails if: any figure or marker differs.

### ACC-138 Events load on click
Covers: VIEW-R2, VIEW-001, ADP-012
Given: a journal of 5,000 nodes.
When: the page is opened, then one node is clicked.
Then: the first load makes no event request; the click makes one request for that node; the tree appears within the contract's time bound.
Observable: request log; load time.
Fails if: events are loaded up front.

### ACC-139 `show --events`
Covers: SCO-06, ADP-012, VIEW-011
Given: a node with the five event types.
When: `trinity show <run>/<node> --events` runs.
Then: events are in transcript order (by `seq`) with the labels 提示词 / 思考 / 工具 / 输出 / 心跳 and the transcript ref is printed; a node with no events says so explicitly and a node whose transcript is gone says gone (ACC-214), never both.
Observable: output.
Fails if: events re-ordered, or an ambiguous empty result.

### ACC-140 The live web reader is short-lived
Covers: NG-04, SCO-06
Given: `trinity open <run>` started (the contract chooses a short-lived local reader or a regenerated static page).
When: the page is closed.
Then: the reader process exits within the contract's bound (fixture bound 60 s); with a static page there is no process at all.
Observable: process table.
Fails if: a process outlives the page.

### ACC-141 Live update delay
Covers: SCO-06, VIEW-005
Given: a view on a running node and the contract's target delay D.
When: a state line is appended.
Then: both views show it within D (fixture D = 2 s unless the contract sets another; the contract has to set one).
Observable: measured delay.
Fails if: the delay exceeds D, or no target exists.
Depends on contract fix P2-10 (the contract has to set D).

---

## 7. Coverage table

Every requirement id in the five specs and the three contracts (families SCO, NG, LAW, CHK, ADP, PRF, LED, VIEW, SUC, DSP, RDR, GRF). "Not testable" rows say why. Case ids in `GRAPH.md` are ACC-3nn, in `LEAK.md` ACC-2nn.

### 7.1 Scope and non-goals

| ID | Cases / status |
| --- | --- |
| SCO-01 | 070, 071, 080, 083, 085, 087 |
| SCO-02 | 051, 054, 057, 060, 061 |
| SCO-03 | 001, 072, 073, 074, 059 |
| SCO-04 | 110, 111, 112 |
| SCO-05 | 001, 013, 305 |
| SCO-06 | 133, 134, 138, 139, 140, 141 |
| SCO-07 | 084 |
| SCO-08 | 001, 002, 120 |
| SCO-09 | 121 (checked only as "unchanged and not on the journal"; the rebuild is a later unit) |
| NG-01 | 117 |
| NG-02 | 054, 115 |
| NG-03 | 119 |
| NG-04 | 117, 140 |
| NG-05 | 050, 118, 207, 208 |
| NG-06 | 002, 116, 120, 132 |

### 7.2 Laws

| ID | Cases / status |
| --- | --- |
| LAW-01 | 070, 085 |
| LAW-02 | 004, 130, 319 |
| LAW-03 | 010, 011, 023, 025 |
| LAW-04 | 200 to 225 (all) |
| LAW-05 | 056, 078 |
| LAW-06 | 111, 112, 113, 122 |
| LAW-07 | 302, 303, 304, 316, 323 |
| LAW-08 | 020, 215, 222, 224 |
| LAW-09 | 057 |
| LAW-10 | 085, 121 |
| LAW-11 | 213, 214, 216 |

### 7.3 Dispatch core

| ID | Cases / status |
| --- | --- |
| CHK-001 | 110, 312 |
| CHK-002 | 053, 111, 122 |
| CHK-003 | 112 |
| CHK-004 | 113, 128 |
| CHK-005 | 302, 303, 304 |
| CHK-006 | 114 |
| CHK-007 | 073 |
| CHK-008 | 115, 144, 305, 313 |
| CHK-009 | 221, 025 |

### 7.3b Dispatch-core contract (DSP)

| ID | Cases / status |
| --- | --- |
| DSP-001 | 002, 120, 124 |
| DSP-002 | 123 |
| DSP-003 | 124, 076, 113, 311, 314b, 317 |
| DSP-004 | 303, 304 |
| DSP-005 | 125 |
| DSP-006 | 143, 054, 059 |
| DSP-007 | 129, 312, 313 |
| DSP-008 | 126, 112 |
| DSP-009 | 127, 114 |
| DSP-010 | 071, 144 |
| DSP-011 | 144, 115 |
| DSP-012 | 077, 116, 142 |
| DSP-013 | 142, 129, 016, 314 |
| DSP-014 | 128, 113 |

### 7.3c Transcript-reader contract (RDR)

| ID | Cases / status |
| --- | --- |
| RDR-001 | 150 |
| RDR-002 | 151, 222 |
| RDR-003 | 080, 139 |
| RDR-004 | 152, 223 |
| RDR-005 | 153, 213 |
| RDR-006 | 154, 214 |
| RDR-007 | 081 |
| RDR-008 | 201, 219, 220, 223, 225 |
| RDR-009 | 155 |
| RDR-010 | 156 |
| RDR-011 | 156 |
| RDR-012 | 157, 205 |

### 7.3d Graph contract (GRF)

| ID | Cases / status |
| --- | --- |
| GRF-001 | 300, 301 |
| GRF-002 | 317, 320 |
| GRF-003 | 302, 318 |
| GRF-004 | 305, 306, 309 |
| GRF-005 | 312, 313, 129 |
| GRF-006 | 314, 314b, 315, 316, 322 |
| GRF-007 | 310, 311, 321 |
| GRF-008 | 306, 310, 314, 132 |
| GRF-009 | 305, 307, 129, 319 |

### 7.4 Adapters

| ID | Cases / status |
| --- | --- |
| ADP-001 | 070, 074 |
| ADP-002 | 071, 075, 086, 144, 202, 203, 204 |
| ADP-003 | 072 |
| ADP-004 | 073 |
| ADP-005 | 209 |
| ADP-006 | 209 |
| ADP-007 | 303 |
| ADP-008 | 076, 127 |
| ADP-009 | 077 |
| ADP-010 | 056, 078, 143 |
| ADP-011 | 079, 137 |
| ADP-012 | 080, 081, 150, 152, 201, 220, 222, 223 |
| ADP-013 | 153, 213 |
| ADP-014 | 154, 214, 216, 058, 081 |
| ADP-015 | 021 |

### 7.5 Profiles

| ID | Cases / status |
| --- | --- |
| PRF-001 | 050, 206 |
| PRF-002 | 051, 205 |
| PRF-003 | 052 |
| PRF-004 | 053 |
| PRF-005 | 054, 060, 143 |
| PRF-006 | 055 |
| PRF-007 | 056 |
| PRF-008 | 057 |
| PRF-009 | 058 |
| PRF-010 | 059, 143, 308 |

### 7.6 Journal

| ID | Cases / status |
| --- | --- |
| LED-001 | 010, 011, 310 |
| LED-002 | 012, 300, 301 |
| LED-003 | 026, 302, 311, 317, 318 |
| LED-004 | 014, 015, 305, 307, 308 |
| LED-005 | 016, 116, 142, 312, 313, 314, 315, 316 |
| LED-006 | 015, 017, 026, 029 |
| LED-007 | 018, 318 |
| LED-008 | 218, 224 |
| LED-009 | 020, 215, 224 |
| LED-010 | 004, 300, 319 |
| LED-011 | 019 |
| LED-012 | 021, 022 |
| LED-013 | 023, 024, 025, 026, 221 |
| LED-014 | 013, 027, 110, 112, 114, 302, 304 |
| LED-015 | 028, 119 |

### 7.7 Views

| ID | Cases / status |
| --- | --- |
| VIEW-001 | 130, 138, 306 |
| VIEW-002 | 131 |
| VIEW-003 | 116, 132, 314 |
| VIEW-004 | 003, 306, 307, 309 |
| VIEW-005 | 114, 133, 141 |
| VIEW-006 | 134, 217 |
| VIEW-007 | 135 |
| VIEW-008 | 214 |
| VIEW-009 | 136 |
| VIEW-010 | 079, 137 |
| VIEW-011 | 139, 153, 213 |

### 7.8 Pilot success conditions and process rules

| ID | Cases / status |
| --- | --- |
| SUC-01 | 001 |
| SUC-02 | 003, 305, 306 |
| SUC-03 | 200, 218 |
| SUC-04 | 004, 319 |
| WR-01 | not testable: a document rule about how work orders are written |
| WR-02 | not testable: a rule about who authors cases; honoured by this set's authorship |
| WR-03 | partly: this table is the trace; it is checked by ACC-083 and by a script that lists every requirement id in the specs and fails on an id missing from section 7 |
| WR-04 | not testable here: a release-time export and scan; the scan patterns are the ones in ACC-057 and the public-repo rule of section 0.6, run by the release step |
| WR-05 | not testable: a retro record kept outside the product |

### 7.9 Risk rows (each names the case meant to catch it)

| Risk | Cases |
| --- | --- |
| RSK-01 | 056, 078 |
| RSK-02 | 200 to 225 |
| RSK-03 | 223 |
| RSK-04 | 053, 111 |
| RSK-05 | 023, 224 |
| RSK-06 | 017, 018, 029 |
| RSK-07 | 001 (the one path comes first) |
| RSK-08 | 057 (repository scan; history scan is release-time, see WR-04) |
| RSK-09 | not testable: a planning risk |
| RSK-10 | 016, 116 |
| RSK-11 | 213 |
| RSK-12 | 314, 314b, 316 |
| ADP-R1 | 073 per adapter |
| ADP-R2 | 074 per profile |
| ADP-R3 | 072, 080 for opencode (run once the probe settles the session id source) |
| ADP-R4 | not testable yet: no stable observable; candidate is a compare of the reported model with the requested one |
| ADP-R5 | 086 |
| ADP-R6 | 084 |
| ADP-R7 | 213 |
| PRF-R1 | 053, 111 |
| PRF-R2 | not testable yet: concurrent use of one account has no requirement |
| PRF-R3 | 075 |
| PRF-R4 | 057 |
| PRF-R5 | not testable yet: open question about the pick rule |
| LED-R1 | 214 |
| LED-R2 | 224 |
| LED-R3 | 201 |
| LED-R4 | 012, 022 |
| LED-R5 | not testable here: depends on an open decision about the older session store (see section 8, gap 5) |
| VIEW-R1 | 140 |
| VIEW-R2 | 138 |
| VIEW-R3 | 201, 217 |
| VIEW-R4 | 136 |
| VIEW-R5 | 132 |
| DSP-R1 | 002, 120, 124 |
| DSP-R2 | 129 |
| DSP-R3 | 128 (the metrics output counts overrides by code from the journal) |
| DSP-R4 | 126 |
| RDR-R1 | 220, 225 |
| RDR-R2 | 150 |
| RDR-R3 | 151, 215 |
| GRF-R1 | 321 |
| GRF-R2 | 322 |
| GRF-R3 | 317 |

---

## 8. Gaps in the specs found while writing the cases

These need a decision from the contract author or the project lead. None of them lets a case be dropped; each case states the behaviour it expects until the contract says otherwise.

Status after review R1 (gaps 2, 6, 7, 10 and the open parts of 1 and 3 are contract-side: they stay open here and the cases carry "depends on contract fix <id>").

1. **Free-text fields in the journal.** The override reason is now a closed code (CHK-004, DSP-003; ACC-113). Caller-supplied labels, step names and run names are still text, while LED-009 says no free-text field exists. No length limit or redaction rule is stated (P2-8). ACC-211 expects refuse-or-mask and a limit.
2. **Paths as refs.** `transcript_ref.path` can contain whatever the vendor or the project directory name contains, including a key-shaped string. ACC-212 accepts any of three strategies; the contract must pick one.
3. **Edge kinds.** Settled by the graph contract: four kinds. `depends` on a failed target is settled (`dependency_failed`, DSP-007; ACC-313, ACC-129). `revises` on a queued target is still unspecified (P2-9); ACC-311(d) accepts refusal, or recording only after the target left `queued`. `revises` inside the same step is unspecified; ACC-321 expects refusal.
4. **Stuck.** Closed: the graph contract (GRF-006) shows a mutual wait as stuck, derived and never written. What remains open is the shape of the cycle: `depends` targets must already exist, so a pure `depends` cycle cannot form through `call` (P1-2). ACC-314 is a hand-built journal case; ACC-316 is the nesting deadlock.
5. **The older session store and per-review metadata** (LED-R5, OPEN-L3) are still open; until they are settled there is no case that proves they are derived caches.
6. **Depth limit** has no default or location (P1-7). ACC-304 requires one.
7. **Live update delay** has no target (OPEN-V2, P2-10). ACC-141 requires one. Also open (P2-10): quota-read timeout (ACC-122), missing `v` (ACC-019), exit code for "rendered with defects" (ACC-318).
8. **Clock injection** is assumed (seam S-2); without it the 90-day, freshness and stall cases cannot run. The contracts have not adopted or rejected it in writing (P3-8).
9. **Terminal control sequences.** VIEW-007 covers HTML only; ACC-135 extends the same rule to the terminal, because child output is untrusted there too. Not yet adopted by a contract (P3-8).
10. **Which fields are "length-limited".** ACC-224 assumes a per-line bound; the contract must state it.

# Acceptance cases: call graph, nesting, loops (ACC-300 .. ACC-323)

Companion to `ACCEPTANCE.md` (conventions, test doubles, seams and the coverage table are defined there; read its section 0 first).
Author role: independent case author. The contract author may not change these cases; a case that cannot run because a seam is missing is reported as failed, not skipped.

## G0. Graph model the cases assume

- Nodes and runs have **flat ids**. An id carries no hierarchy and no meaning; the shape of the graph lives only in edges.
- There are exactly four **edge kinds**: `parent` (a call made under another call), `depends` (a node may not start until another node is done), `round` (a back-edge, `from` the further attempt `to` the attempt before it, with a reason; depends on contract fix P1-1, because the contract text currently says the opposite), `revises` (a later node supersedes part of an earlier node's work without being a retry of the same step).
- A loop is **unrolled in the journal** (every attempt is its own node, joined by `round` edges) and **folded in the views** (one line per step with a round count).
- A **mutual wait** is derived as `stuck` and handed to a person. Nothing breaks it automatically. `depends` targets must already exist when a call is made, so a pure cycle of `depends` edges cannot be built through `call`; the two ways a mutual wait exists are (i) a hand-built or damaged journal holding a `depends` cycle, and (ii) a nested child that `depends` on a running ancestor, which cannot end until the child's call returns (depends on contract fix P1-2: the contract must refuse the second form at validation or detect it as a cycle).
- Draft-spec names map as `child` -> `parent`, `retry` -> `round`. Spelling of the kinds is bound by the contract; the behaviour below is not.
- Stuck is derived by readers and never written (the state set in ACC-016 stays closed).

---

### ACC-300 Flat ids carry no structure
Covers: LED-002, LED-003, LED-010
Given: a run with a root, 3 children, 2 grandchildren, built by the fake harness.
When: every node id and run id in a copy of the journal is replaced by a random permutation of unrelated strings (consistently across lines), and the tree is rendered from the copy.
Then: the rendered shape (parents, depths, rounds, states) is identical to the original.
Observable: structural diff of the two renderings, ids masked, is empty. Also: no id in the original journal is a prefix, suffix or concatenation of another id.
Fails if: any rendering difference (shape was being inferred from id text), or an id that embeds its parent's id.

### ACC-301 Display labels are never keys
Covers: LED-002
Given: two nodes with the same label `review`, one node with a label in Chinese, one with a label of 200 characters, one with an empty label.
When: the run is written, read back, and one label is changed by a correction line.
Then: all node ids are distinct, stable across reads and process restarts, and unchanged by the label correction.
Observable: id set before == id set after; count of distinct ids == count of nodes.
Fails if: two nodes merged, an id changed, or a lookup by label returns the wrong node.

### ACC-302 Nesting: child of child, depth recorded
Covers: LAW-07, CHK-005, LED-014, LED-003
Given: a run where the root calls child A, A calls child B, B calls child C (nesting explicitly allowed for the run).
When: the run completes.
Then: root depth 0, A 1, B 2, C 3; each node has exactly one `parent` edge to the node that called it; the parent appears earlier in the journal than each child.
Observable: depth field of each node line; parent-edge targets; line order.
Fails if: any depth is missing or not parent depth + 1, a node has two parents or none (except the root), or a parent line comes after its child.

### ACC-303 Nesting is off by default
Covers: LAW-07, ADP-007, CHK-005
Given: a run started without the allow-nesting option.
When: the child harness (fake) tries to call Trinity again, and the test also inspects the child environment.
Then: the child environment carries the recursion guard; the inner call is refused before any process starts; the refusal is visible to the caller (result class `nesting_refused`).
Observable: guard variable present in the captured child environment; the fake harness invocation count for the inner call is 0; no node is written for the refused call (DSP-004); one error-log line records the refusal with the depth and the reason; CLI exit status of the inner call is non-zero.
Fails if: an inner harness process starts, or the guard is absent, or the refusal leaves no trace in the error log, or a node is written.
Depends on contract fix P2-4 (the contract writes one error-log line for a refusal; until then the contract says "writes nothing" and this case fails the contract).

### ACC-304 Nesting depth limit
Covers: LAW-07, CHK-005, LED-014
Given: nesting allowed with a configured depth limit L (fixture value L = 2; the case is parametrised, and also runs with L = 1 and L = 5).
When: the call chain tries to reach depth L + 1.
Then: depths 0..L run; the call at depth L + 1 is refused before start with a stated reason that names the depth and the limit; no harness process starts for it; the refusal is recorded in the error log (one line, depth and limit; no node is written); sibling branches at allowed depths are unaffected.
Observable: fake harness invocation count for the refused call is 0; the error log holds a line for the refusal with depth L + 1 and limit L, and the journal holds no node for it; CLI exit status non-zero with the reason text; a sibling call at depth L still completes.
Fails if: the (L + 1)th call runs, the refusal is silent (no error-log line), the limit is off by one in either direction, or a refusal in one branch stops other branches.
Note: depends on contract fix P1-7 and P2-4. The contract must state the limit's default and where it is configured, and the refusal class (`nesting_refused` naming depth and limit); if it states "no limit", this case fails the contract, not the implementation.

### ACC-305 Retry rounds are back-edges, unrolled in the ledger
Covers: LED-004, LED-010, CHK-008, SUC-02
Given: one step `review` that is rejected twice and accepted on the third attempt (the caller issues each retry).
When: the run completes.
Then: the journal holds 3 node records for the step with rounds 1, 2, 3; 2 `round` edges, each with `from` = the later node and `to` = the earlier one, each with a reason; the first node is never edited.
Observable: count of nodes with step = review is 3; round numbers are 1,2,3; edge count is 2; reasons are both `review_rejection`; the prefix of the journal that existed before round 2 started is byte-identical afterwards.
Fails if: fewer than 3 node records (attempts overwritten or merged), round numbers skip or repeat, a round edge points forward (`from` the earlier node), or a reason is missing.
Depends on contract fix P1-1 (GRF-004 and the ledger example name the direction).

### ACC-306 Loop folded in the tree view
Covers: VIEW-004, VIEW-001, SUC-02
Given: the journal of ACC-305.
When: `trinity tree <run>` and then `trinity tree <run> --expand review` are run, and the web page is loaded for the same journal.
Then: the default tree shows the step as one line reading "第 3 轮 · 退回 2 次"; the expanded view shows 3 lines, rounds in order, each later one with the ↺ glyph and its reason; the web tree shows the same fold and an amber ring on the step.
Observable: line count of the default tree for that step is 1; expanded count is 3; the exact fold string; ring marker present in the page data for the step.
Fails if: the loop renders as 3 top-level siblings by default, the count is wrong, the reasons are missing on expansion, or the ring is absent.

### ACC-307 Only rejections count as "退回"
Covers: VIEW-004, LED-004
Given: a step with 5 attempts whose reasons are, in order, `failure`, `timeout`, `stuck`, `manual`, `review_rejection`.
When: the tree is folded.
Then: it reads "第 5 轮 · 退回 1 次"; expanded, all five reasons appear in order.
Observable: fold string; the five reason strings in the expansion.
Fails if: M counts anything other than `review_rejection`. A sixth reason value written by a test is refused at write time (see ACC-014).
Extra: with zero rejection rounds but several `failure` rounds, the web step has **no** amber ring (the ring is for rejection only).

### ACC-308 Rounds may switch profile; the session does not carry over
Covers: LED-004, PRF-010
Given: round 1 and 2 on profile P1, round 3 on profile P2 after repeated rejection.
When: the three rounds run.
Then: rounds 1 and 2 may continue the same session; round 3 is a new session with a new session id on P2; the round edge from 3 to 2 still exists.
Observable: session mode and id per node; profile per node; edge present.
Fails if: round 3 continues the session of P1, or the edge is dropped because the profile differs.

### ACC-309 Loop never collapses in the ledger even at scale
Covers: LED-004, LED-010, LED-R2
Given: a step retried 50 times.
When: the journal is read and the tree rendered.
Then: 50 node records exist with rounds 1..50 and 49 round edges; the default tree still shows one line for the step ("第 50 轮 …"); header counters (running, stuck) count real nodes, not folded lines.
Observable: counts; header counters on a fixture where round 50 is running.
Fails if: any round is missing, the fold hides the running state (a step whose last round is running must show running, and a failed earlier round must not make the folded line show failed).

### ACC-310 Revises edge
Covers: LED-001, LED-010, VIEW-001
Given: node C (done, output kind commit) and a later node D created as a revision of C by the caller.
When: the journal is written and rendered.
Then: both nodes remain; a `revises` edge runs from D to C; C is marked as revised in both views and D shows what it revises; D is not counted as a round of C's step and does not change anyone's `parent`.
Observable: edge present with kind `revises`; round numbers unchanged; the rendering contains the marker on C and the reference on D in both CLI and web data.
Fails if: C is hidden, edited or deleted, D appears as a further round, or only one view shows the relation.

### ACC-311 Revises edge refusals
Covers: LED-001, LED-003
Given: a revision request that names (a) itself, (b) a node of another run, (c) a node that does not exist, (d) a node that is still queued, (e) a node of the same step (a round, which already says the same thing).
When: each is attempted.
Then: each is refused with `bad_request` and a stated reason and writes no edge; (d) is either refused or accepted only when the target state is `done`, `failed` or `interrupted`, as the contract states, but never creates a dangling edge; (e) is refused (GRF-007, GRF-R1).
Observable: edge count unchanged; error text names the reason.
Fails if: any of the five writes an edge, or the reader later crashes on a dangling edge.
Depends on contract fix P2-9 for (d); (e) follows GRF-007 and is not yet in DSP-003 (reported to the contract author).

### ACC-312 Depends edge holds a node back
Covers: LED-005, CHK-001, SCO-05
Given: node A submitted first (slow: the fake harness waits 2 s on the test clock), its id known; node B then submitted naming A in `depends` (`depends` can only name an existing node, DSP-003).
When: B is submitted while A runs.
Then: B does not enter `running` before A is `done`; B's check record (quota) is written after A is done, not before; the fake harness for B is not invoked until then.
Observable: ordering of state lines across A and B; harness invocation timestamps.
Fails if: B starts while A runs.

### ACC-313 A failed dependency does not run its dependents
Covers: LED-005, CHK-008, LAW-06
Given: A has been submitted and ended `failed`, or is still running and then fails; B is submitted naming A in `depends`.
When: the core processes B.
Then: B never enters `running`; B ends in a non-running state with a visible reason that names A (the contract binds whether this is `queued -> failed` with a dependency exit class or a blocked-queued display; both accept, a silent start does not); the core does not retry A.
Observable: harness invocation count for B is 0; the tree line for B names A; no new node for A appears.
Fails if: B runs, B hangs in `queued` with no reason shown, or A is retried by the core.

### ACC-314 A `depends` cycle in a journal is stuck and handed to a person
Covers: LED-005, VIEW-003, GRF-006, RSK-10, RSK-12
Given: hand-built journals (a `depends` cycle cannot be created through `call`, because `depends` names an existing node and the graph is built forward): (a) A depends on B and B depends on A; (b) a 3-node cycle A->B->C->A; (c) a self-dependency A->A; every member is `queued` or `running`, none ended.
When: each journal is loaded by the readers, and the dependency check of GRF-006 is run over it.
Then: every member of the cycle is shown `stuck` with the reason "互相等待" (or the contract's wording) in both views, derived and never written; each member's detail lists the other members of the cycle (the contract states what the view lists, P3-7); the check names cycle members and nothing outside the cycle; the CLI exits non-zero with a message that says a person must decide; nothing is killed, cancelled or edited automatically; after a person interrupts one member (a new `state` line), its dependents end `dependency_failed`, and the other members leave the cycle.
Observable: no `stuck` state line in the journal; the rendered tree and the web data carry the same stuck marker and member list (shared derivation, VIEW-003); the message text; states after the interrupt.
Fails if: any member starts, a member is dropped or edited by the core, one view shows stuck and the other does not, a `stuck` state line is written, or the core breaks the cycle on its own.
Note: depends on contract fix P1-2 (GRF-006 as written cannot be reached through `call`; it stays testable here as a defect check on hand-built journals) and P3-7.

### ACC-314b Dependencies that cannot form a cycle are refused at the door
Covers: LED-005, DSP-003, GRF-005, GRF-006
Given: a request whose `depends` names (a) a node that does not exist, (b) the node being created (a self-reference cannot be named: its id is not yet issued), (c) a node of another run, (d) one of its own ancestors, while the ancestor is running (nesting allowed).
When: each is submitted.
Then: (a) and (c) are refused `bad_request`, nothing written; (b) is impossible by construction (the case checks that no way exists to name the new node's own id); (d) is either refused `bad_request` at validation, or accepted and the pair is detected as a cycle at once (both call results `dependency_cycle`, check line `cycle`, shown stuck), as the contract states, never left waiting with no mark.
Observable: result class; check lines; stuck marker.
Fails if: (d) leaves a node waiting silently on an ancestor that waits for it.
Depends on contract fix P1-2.

### ACC-315 Mutual wait is not over-detected
Covers: LED-005, VIEW-003
Given: (a) a diamond: D depends on B and C, which both depend on A; (b) a retry loop: rounds joined by `round` edges; (c) a parent that has a `parent` edge to its child while the child depends on a sibling; (d) two independent chains.
When: each shape is run.
Then: none of them is reported as a mutual wait; all complete normally.
Observable: no stuck marker with the mutual-wait reason; all nodes reach `done`.
Fails if: any shape is flagged. (Round back-edges point backwards by design and are not waits.)

### ACC-316 Nested child waits on its running ancestor
Covers: LED-005, VIEW-003, LAW-07, GRF-006, RSK-12
Given: nesting allowed; root P calls child C (a `parent` edge); C then submits a call whose `depends` names P (still running, and it cannot end until C's call returns); and a variant where it names a higher ancestor (P's parent).
When: the calls are submitted.
Then: the same outcome as ACC-314b(d): refused at validation, or detected at once as a mutual wait with every waiting call returning `dependency_cycle`; the views show the waiting node and the ancestor as stuck with the reason "互相等待" and the member list; the process of P is not touched; a person's interrupt of the waiting node ends it, and P then continues.
Observable: as ACC-314.
Fails if: treated as an ordinary parent/child relationship and left `queued` without a mark, or the ancestor is killed.
Depends on contract fix P1-2.

### ACC-317 Edges stay inside one run
Covers: LED-003, LED-002
Given: two runs R1 and R2 in the same journal location.
When: a `parent`, `depends`, `round` or `revises` edge from a node of R1 to a node of R2 is requested.
Then: it is refused with a stated reason; no edge is written.
Observable: refusal text; edge count unchanged; each run still satisfies the one-parent rule on its own.
Fails if: any cross-run edge is stored.

### ACC-318 The one-parent rule and its detection
Covers: LED-003, LED-007, LED-012
Given: a hand-built journal in which one node has two `parent` edges, another has a parent that appears later in the file, a third has a parent that does not exist.
When: readers load it.
Then: each defect is reported by node id; the reader does not crash; unaffected nodes in the same run still render; for the duplicate-parent case the first edge in file order wins and the second is reported.
Observable: report lines; exit status distinguishes "rendered with defects" from clean (the contract binds the code, P2-10: until it does, any non-zero status that differs from the clean one passes); rendering continues.
Fails if: a crash, a silent acceptance, or the whole run blanked.

### ACC-319 Rebuild from the journal alone
Covers: LED-010, LAW-02, SUC-04
Given: a finished run containing nesting (depth 3), a loop of 3 rounds, a revises edge, one failed node, usage reported on all nodes but one.
When: every transcript file, every view cache and every Trinity state file other than the journal is deleted, and the tree, per-node wall time, reported token total, round counts, retry reasons and the per-step count of rejection rounds are computed from the journal.
Then: all values equal the values the live run displayed; the token total is marked partial because one node reported no usage.
Observable: byte-equal rendering of the default and expanded tree before and after the deletion; metrics record equal.
Fails if: any value depends on a file that is not the journal.

### ACC-320 A fifth edge kind is a defect, not a structure
Covers: GRF-002, LED-003
Given: a hand-built journal with a line of edge kind `blocks` (and one of the old draft names `child`).
When: the readers load it.
Then: each such line is reported as a defect by line and kind and skipped; the tree and counts are unaffected (the skipped edge changes no parent, depth or round); no writer path can create a fifth kind (the edge writer refuses it).
Observable: report; tree before and after adding the lines (equal).
Fails if: a node is placed by the unknown edge, the reader crashes, or the writer accepts the kind.

### ACC-321 `revises` and `round` are not both used inside one step
Covers: GRF-007, GRF-R1, GRF-009
Given: a step with two rounds; a later node in another step revising the second round's output; a request that tries to add `revises` between two rounds of the same step.
When: written and counted.
Then: the cross-step `revises` is accepted; the within-step `revises` is refused (a round already says the same); supersessions counted from `revises` edges equal 1; rejection rounds are counted from `round` edges only; nothing is counted twice.
Observable: edge counts by kind; metric values; refusal text.
Fails if: a within-step `revises` lands, or a supersession is double-counted.
Depends on contract fix: DSP-003 does not yet list the within-step refusal (reported with review item P2-9).

### ACC-322 The cycle check reads one run's unended nodes
Covers: GRF-R2, GRF-006
Given: a journal of 20 runs of 500 nodes each; in one run 10 nodes are unended with `depends` edges, the rest ended; a new `depends` edge is appended to that run.
When: the cycle check runs, measured by files read and lines examined (a spy on the journal reader).
Then: the check examines only edges of that run among nodes not yet ended; it reads no line of another run's nodes beyond locating the run; its cost does not grow when the number of ended nodes in the run grows tenfold.
Observable: lines examined, before and after the tenfold growth.
Fails if: the check scans every run or every ended node.

### ACC-323 A nested heavy child under a heavy ancestor does not wait for its own ancestor's lock
Covers: LAW-07, DSP-008, CHK-003
Given: nesting allowed; a heavy node P holds the heavy lock; its child C is also heavy.
When: C asks for the lock.
Then: C fails at once (not after the 1200 s default) with `lock_unavailable` whose lock check line shows the holder is an ancestor; no waiter takes the lock by force; P is untouched.
Observable: time to the failure; check line.
Fails if: C waits out the limit for a lock its ancestor holds.
Depends on contract fix P3-6 (the contract does not yet say so; if the owner rejects the rule in writing, this case is retired with the reason).

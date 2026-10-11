# Component spec: tree render + live view (树形渲染与实时) — draft 0.2

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Terms: METHOD.md §2. Laws that bind this component: LAW-02, 04, 08, 11.

## 1. Purpose

Show a run's call tree to a human, in a terminal and in a browser, while it runs and afterwards. Tree, states and numbers come from the journal; event detail comes from adapter readers via journal refs, on demand.

## 2. Scope

In — view commands (CLI front end):

| Command | Shows | Data from |
| --- | --- | --- |
| `trinity profiles` | profile list | profiles (no secrets) |
| `trinity tree <run>` | one line per node: state glyph, step, profile/model, session `新/续` + short id, wall time, tokens, exit class + `output_kind` + heartbeat age; the commit id / verdict word is resolved on click via the reader (LED-015) | journal |
| `trinity tree <run> --expand <step>` | the rounds of one step, each with its ↺ reason | journal |
| `trinity show <run>/<node> --events` | time-ordered events: 提示词 / 思考 / 工具 / 输出 / 心跳, plus the transcript ref | reader via ref |
| `trinity open <run>` | the same tree as a local web page: tree left, node detail + events right (events loaded on click) | journal + reader |
| live mode | tree and page update while nodes run | journal appends |

Layout reference: a web page with the tree on the left and the selected node's detail on the right; terminal output is one line per node with box-drawing indent; a step with rejection rounds is folded into one line and gets an amber ring on the web page.

Out:

- Any action that changes a run. `trinity resume <run>/<node> "<prompt>"` is a dispatch command (core, METHOD §5); its result only *appears* here as a new node or round.
- Killing or retrying stuck nodes (RSK-10).

## 3. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| VIEW-001 | Given the same journal bytes, the CLI tree and the web tree show the same nodes, parents, states and numbers. Event detail (`show --events`, web detail pane) is outside this rule: it comes from readers via refs (LAW-02). |
| VIEW-002 | No tmux needed; CLI output is plain lines that work over ssh and in pipes. With `--ascii` (or a non-UTF-8 locale) glyphs ✓ ● ! ↺ and box lines are replaced by ASCII. |
| VIEW-003 | States shown: done, running, stuck, failed, interrupted. Stuck = running and last heartbeat row older than the node's stall limit; the view shows the age ("6 分钟无心跳"). A queued node on a `depends` cycle is also stuck, shown as "互相等待" (GRF-006). Both views use the same core function to derive state (NG-06). |
| VIEW-004 | A step with more than one round renders folded as one line with "第 N 轮 · 退回 M 次" (M = rounds with reason `review_rejection`); expanded, each round shows its ↺ reason. On the web page a step with any rejection round gets the amber ring. |
| VIEW-005 | Live mode reads appended journal lines only (including heartbeat rows written by the core, CHK-006); views never poll vendors or child processes themselves. |
| VIEW-006 | The web view is read-only and binds to 127.0.0.1 only. Observable: no listening socket on a non-loopback address; the page and its data contain no credential value; it requires no credential to open. |
| VIEW-007 | Event text is inserted as text, never as HTML (child output is untrusted). |
| VIEW-008 | When a reader returns `gone`, the view shows "原始记录已不存在 · since <time found missing>" and, if known, "vendor retention ended <time>" (ADP-014). It never shows an empty event list as if the node had no events. |
| VIEW-009 | Terminal columns align with East Asian wide characters. Observable: a fixture run with 5 Chinese step labels and 5 ASCII labels renders with the duration column starting at the same display column on every line. |
| VIEW-010 | Header totals (elapsed, total tokens, subscription/metered count, running/stuck count) are sums over journal records; if any node has no `usage`, the token total is marked "partial". |
| VIEW-011 | Thinking events with `thinking_form = summary` or `encrypted` carry a visible label ("摘要" / "已加密"); absent thinking shows "无思考记录". Never rendered as if complete (LAW-11). |

## 4. Environment assumptions

- UTF-8 terminal (ASCII fallback otherwise); a local browser for `trinity open`.
- The journal file is local and readable by the viewer.
- For the live web view, a short-lived local reader process runs while the page is open (OPEN-V1).

## 5. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| VIEW-R1 | Live web view needs a local server, against "no daemon" (NG-04) if it must stay up | OPEN-V1 (short-lived, exits with the page) |
| VIEW-R2 | Large runs make the web page slow | events loaded on click, not up front (VIEW-001 carve-out) |
| VIEW-R3 | The on-click reader shows transcript text containing a secret | ADP-012 redaction; VIEW-006 loopback only |
| VIEW-R4 | CJK width bugs misalign the CLI tree | VIEW-009 fixture |
| VIEW-R5 | The two views compute "stuck" differently | VIEW-003 shared core function |

## 6. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-V1 | Live web: short-lived local server started by `trinity open`, or a static file regenerated on each append? | Open — WO-002 |
| OPEN-V2 | Live update delay target (seconds from journal append to screen) | Open — WO-002 |
| OPEN-V3 | Shareable page or strictly local? | Open — owner; strictly local until decided (VIEW-006) |
| OPEN-V4 | Is `trinity resume <run>/<node>` in scope for this rework? | Open — WO-002 (dispatch core) |
| OPEN-V5 | One shared state-derivation function for both views | **Decided by NG-06 / VIEW-003:** yes |

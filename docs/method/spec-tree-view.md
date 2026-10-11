# Component spec: tree render + live view (树形渲染与实时) — draft 0.1

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Laws that bind this component: LAW-02, 04, 08 (METHOD.md §3). Reference design: pfc/artifacts/trinity-mockup.html.

## 1. Purpose

Show a run's call tree to a human, in a terminal and in a browser, while it runs and afterwards, using only the journal.

## 2. Scope

In (commands from the mockup):

| Command | Shows |
| --- | --- |
| `trinity profiles` | profile list (profiles component data) |
| `trinity tree <run>` | one line per node: state glyph, step, profile/model, session `新/续` + short id, wall time, tokens, output (commit / verdict / heartbeat age) |
| `trinity tree <run> --expand <step>` | the rounds of one step, each with its ↺ reason |
| `trinity show <run>/<node> --events` | time-ordered events: 提示词 / 思考 / 工具 / 输出 / 心跳, plus the raw transcript pointer |
| `trinity open <run>` | the same tree as a web page: tree on the left, node detail + events on the right |
| live mode | tree and web page update while nodes run |

Out:

- Any action that changes a run. `trinity resume` (mockup) is a dispatch command; it belongs to the dispatch core and only *appears* here as a new node.
- Killing or retrying stuck nodes (RSK-10).

## 3. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| VIEW-001 | CLI tree and web view are built only from the journal (LAW-02); with the same journal bytes they show the same nodes, parents, states and numbers. |
| VIEW-002 | No tmux needed (mockup "不需要 tmux"); CLI output is plain lines that work over ssh and in pipes. Glyphs (✓ ● ! ↺, box lines) have an ASCII fallback. |
| VIEW-003 | States: done, running, stuck, failed (+ interrupted). `stuck` = running and heartbeat older than the node's stall limit; the view shows the age ("6 分钟无心跳"). |
| VIEW-004 | A step with more than one round renders folded as one line with "第 N 轮 · 退回 M 次"; expanded, each round shows its ↺ reason from the retry edge. In the web view a step with any RETURN gets the amber ring. |
| VIEW-005 | Live mode reads appended journal lines; it never polls vendors or child processes itself. Update delay target: OPEN-V2. |
| VIEW-006 | The web view is a local, read-only page; it binds to localhost only and needs no login secret; it shows no credential value (LAW-04). |
| VIEW-007 | Event text is escaped as text (the mockup uses `textContent`; keep that). Child output is untrusted (CraftCode §8.4). |
| VIEW-008 | Missing transcript pointers show "原始记录不可用" instead of failing (LED-R1). |
| VIEW-009 | Mixed-language labels (Chinese step names) align correctly in the terminal (East Asian width). |
| VIEW-010 | Totals in the header (elapsed, total tokens, subscription/metered count, running/stuck count) are sums over journal records, marked partial if any node lacks usage. |

## 4. Environment assumptions

- A terminal with UTF-8; a local browser for `trinity open`.
- The journal file is local and readable by the viewer.
- For live web view, some local reader process exists while the page is open (OPEN-V1).

## 5. Risks

| ID | Risk |
| --- | --- |
| VIEW-R1 | A live web view needs a local server — conflicts with "no daemon" (NG-04) if it must stay up. |
| VIEW-R2 | Large runs (hundreds of events) make the web page slow; the mockup holds all data in one array. |
| VIEW-R3 | Showing thinking text to anyone with the page link exposes prompts (OPEN-05). |
| VIEW-R4 | CJK width bugs misalign the CLI tree. |
| VIEW-R5 | Two views grow different logic (e.g. "stuck" computed differently) and disagree. |

## 6. Open items

| ID | Question |
| --- | --- |
| OPEN-V1 | Live web: short-lived local server started by `trinity open` (exits when the page closes), static file regenerated on each append, or the pfc dashboard? |
| OPEN-V2 | Live update delay target (mockup heartbeat shown as "♥12s"). |
| OPEN-V3 | Should the web page be shareable (e.g. published artifact) or strictly local? |
| OPEN-V4 | Is `trinity resume <run>/<node>` in scope for this rework (it changes the dispatch core)? |
| OPEN-V5 | One shared "derive state" function used by both views (recommended, VIEW-R5). |

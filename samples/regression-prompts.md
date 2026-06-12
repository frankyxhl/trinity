# Trinity — Claude Code Skill Dispatch Regression Prompts

This file is the **manual regression prompt set** for Claude Code's SKILL.md dispatch
paths — the `/trinity ...` command routing, preset expansion, provider resolution,
session management, and reserved-word handling.

TRN-1800 (Evolution Philosophy, §Behavior Baseline) establishes the concept of a
fixed regression sample for behaviour-bearing surfaces. This file is that baseline
for the Claude Code skill dispatch surface, complementing the automated-pytest
coverage that already exists for the Codex adapter (`trinity review`).

---

## When to run

Run these prompts manually whenever a PR touches:
- `SKILL.md` — dispatch syntax, parse order, execution rules, reserved words,
  preset definitions, heartbeat/shape, or error handling
- `providers/_base/` — provider discovery or agent resolution logic consumed
  by the SKILL.md dispatch instructions
- `scripts/session.py` or `scripts/session_path.py` — session key resolution,
  output file capture, or heartbeat mechanics referenced from SKILL.md

Each prompt below says what to type in a Claude Code session and what to look
for in the response. A prompt "passes" when the observed output matches the
pass criteria for every item listed.

Before the first run, ensure:
- `make install` has been run **from the branch/commit under review** so the
  candidate `SKILL.md` and scripts are what gets exercised — installing from a
  clean `main` checkout would smoke-test the baseline skill instead of the
  PR's changed dispatcher
- At least one provider is installed (`/trinity install glm` or equivalent)
- The project directory has a `.claude/trinity.json` with at least one session
  entry for resume tests (run a dispatch first, e.g. `/trinity glm "hello"`)

---

## 1. Single dispatch

**Prompt:**

```
/trinity glm "实现用户认证模块"
```

**Expected route:**
Parse `glm` as bare provider name → no instance → key `"glm"` → provider discovery
validates `glm` is usable (config entry + agent file present) → spawn `Agent(
subagent_type="general-purpose", name="glm", …)` with prompt prefixed by
`~/.claude/agents/trinity-glm.md` → record session entry under `sessions.glm`.

**Pass criteria:**

- [ ] Launch summary shows one entry, e.g. `GLM → 实现用户认证模块 (background)`
- [ ] The task text `实现用户认证模块` appears verbatim in the prompt template
- [ ] `.claude/trinity.json` gains a `sessions.glm` entry with `start_time`,
      `output_file`, `task_type: "general"`, `stopped: false`
- [ ] If `task` contains `review`/`tdd`/`prp` keywords → `task_type` reflects that

---

## 2. Named-instance resume

**Prompt:**

```
/trinity glm:auth "继续实现认证模块"
```

**Expected route:**
Parse `glm:auth` → base=`glm`, instance=`auth` → key `"glm:auth"` → provider
discovery validates `glm` is usable → spawn `Agent(name="glm:auth", …)` with
prompt prefixed by `~/.claude/agents/trinity-glm.md` and referencing key
`"glm:auth"` → if `sessions.glm:auth` already exists, the subagent process
resumes from prior state.

**Pass criteria:**

- [ ] Launch summary shows `GLM:auth → 继续实现认证模块 (background)`
- [ ] The `:auth` instance suffix is preserved in the agent name and session key
- [ ] `.claude/trinity.json` `sessions.glm:auth` is created (or updated if resuming)
- [ ] Consecutive dispatches to `glm:auth` produce the same session key (resume,
      not a new session each time)

---

## 3. `provider*N` parallel

**Prompt:**

```
/trinity glm*2 "分别实现 auth 和 order 模块"
```

**Expected route:**
Parse `glm*2` → base=`glm`, count=`2` → spawn 2 agents with auto-generated
instance keys `glm:<uuid4-hex6>` → each gets its own independent session entry.
Both run the same task text.

**Pass criteria:**

- [ ] Launch summary shows two entries, e.g.:
      ```
      GLM:a1b2c3 → 分别实现 auth 和 order 模块 (background)
      GLM:d4e5f6 → 分别实现 auth 和 order 模块 (background)
      ```
- [ ] `.claude/trinity.json` has two distinct session keys (`glm:a1b2c3`,
      `glm:d4e5f6`) with separate `session_id`, `output_file`, `start_time`
- [ ] Both agents receive the same task text
- [ ] Each agent independently tracks its own heartbeat/progress

---

## 4. Preset expansion — review

**Prompt:**

```
/trinity review "review auth 代码"
```

**Expected route:**
Parse `review` → matched as preset name → expand to required providers
(`glm`, `gemini`, `deepseek`) + optional providers (`codex`, `claude-code`) →
for each usable provider, dispatch the same task `"review auth 代码"` → optional
providers that are missing (config/agent file absent) show a warning and are
skipped.

**Pass criteria:**

- [ ] Launch summary shows dispatch to every **required** provider that is usable,
      e.g. `GLM → review auth 代码 (background)`, `DeepSeek → review auth 代码 (background)`
- [ ] If `gemini` (a **required** provider) has no agent file → the preset
      expansion reports it as a required-provider failure (not an optional
      warning); the run must not silently continue as if the set were complete
- [ ] If `codex`/`claude-code` (optional) are missing → output shows an
      `⚠️ (optional)` warning and dispatch continues with the required set
- [ ] If `codex`/`claude-code` are present → they appear in the dispatch list
- [ ] Each dispatched entry gets the **same task text**
- [ ] `.claude/trinity.json` records a `task_type: "review"` for each dispatched agent

---

## 5. Preset alias — fr (fast-review)

**Prompt:**

```
/trinity fr "quick review of auth code"
```

**Expected route:**
Parse `fr` → alias resolution → `fast-review` preset → required providers
(`glm`, `deepseek`) → dispatch the same task to each usable provider.
No optional providers in fast-review.

**Pass criteria:**

- [ ] Launch summary shows dispatch to `GLM` and `DeepSeek` with task
      `quick review of auth code`
- [ ] No optional-provider warnings (fast-review has no optional list)
- [ ] Same task text sent to both providers

---

## 6. Reserved-word rejection — status

**Prompt:**

```
/trinity status
```

**Expected route:**
Parse `status` → matched as built-in subcommand first (dispatch order rule 1) →
run status mode: provider discovery, display registered providers, configured
presets, and active sessions. The quoted string (if present) is ignored.

**Pass criteria:**

- [ ] Output shows **provider status section** with at least one registered provider
      (e.g. `glm  ✅ usable`)
- [ ] Output shows **preset table** (`review`, `fast-review`, `deep-review`)
- [ ] Output shows **active sessions** (or "No active sessions")
- [ ] No agent is spawned — this is a read-only status check
- [ ] A trailing argument like `/trinity status "do something"` still runs status
      mode and ignores the extraneous text

---

## 7. Reserved-word rejection — clear (with confirmed side effect)

**Prompt:**

```
/trinity clear glm:auth
```

**Expected route:**
Parse `clear` → built-in subcommand → synchronous clear operation on
`.claude/trinity.json` sessions → remove `glm:auth` session key → confirm.

**Pass criteria:**

- [ ] Output confirms deletion, e.g. `Cleared session glm:auth`
- [ ] `.claude/trinity.json` `sessions.glm:auth` no longer exists
- [ ] `/trinity clear all` clears all sessions and confirms

---

## 8. Heartbeat output shape

**Prompt (run after a dispatch is in progress):**

```
/trinity heartbeat
```

(Or `/trinity heartbeat glm:auth` for a single-instance check.)

**Expected route:**
On-demand heartbeat → for each agent with `output_file` set and
`stopped: false`, read the output JSONL file, parse last activity, compare line
counts, display liveness status. Update `last_line_count` and `last_heartbeat`
in `.claude/trinity.json`.

**Pass criteria:**

- [ ] Output uses the expected columnar format, e.g.:
      ```
      GLM:auth    🔄 alive    +23 lines   [4m 12s]   Bash: pytest -v
      ```
- [ ] Each line shows: provider:instance, emoji status, line delta, elapsed time,
      and last activity summary
- [ ] Status emoji is one of: `🔄 alive`, `⚠️ possibly stalled`, `🟡 starting`,
      `❌ failed to start`, `✅ done`
- [ ] `.claude/trinity.json` `last_line_count` and `last_heartbeat` are updated
      for each checked agent
- [ ] A single-instance heartbeat (`/trinity heartbeat glm:auth`) only checks
      that one entry

---

## 9. Multi-provider parallel dispatch

**Prompt:**

```
/trinity glm "实现认证模块" codex "review 认证代码"
```

**Expected route:**
Parse two `(provider, task)` pairs → `glm` dispatched with task
`"实现认证模块"`, `codex` dispatched with task `"review 认证代码"` →
both run as background agents concurrently.

**Pass criteria:**

- [ ] Launch summary shows both entries, e.g.:
      ```
      Dispatched:
      - GLM → 实现认证模块 (background)
      - Codex → review 认证代码 (background)
      ```
- [ ] Each provider independently records a `sessions` entry with the correct
      task text and `task_type`
- [ ] `codex` entry has `task_type: "review"` (keyword match); `glm` entry has
      `task_type: "general"` (or `tdd`/`prp` depending on exact task text)

---

## 10. Unknown provider rejection

**Prompt:**

```
/trinity nonexistent "do something"
```

**Expected route:**
Parse `nonexistent` → not a built-in subcommand, not a preset/alias, not a known
provider → provider discovery runs → `nonexistent` not found → error reported.

**Pass criteria:**

- [ ] Output reports an error: "Unknown provider: nonexistent" (or similar wording)
- [ ] Error lists available providers the user can install instead
- [ ] No agent is spawned
- [ ] No session entry is created

---

## 11. Session output-file resolution (session.py / session_path.py surface)

**Prompt:**

```
/trinity glm "print hello and exit"
```

then, after the launch summary appears:

```
/trinity heartbeat glm
```

**Expected route:**
Dispatch records `sessions.glm.output_file` via the session-path resolution
helpers (`scripts/session.py` / `scripts/session_path.py`) → heartbeat resolves
that same path, reads the transcript, and reports liveness with a line count.

**Pass criteria:**

- [ ] `.claude/trinity.json` `sessions.glm.output_file` is an **absolute path to a
      file that exists on disk** at the time of the heartbeat (not a placeholder,
      not a dangling path)
- [ ] `/trinity heartbeat glm` reads that file successfully — it reports a state
      (`alive`/`stalled`/`done`) plus a `+N lines` delta, with no "file not found"
      or path-resolution error
- [ ] After the agent finishes, a second heartbeat reflects the terminal state
      instead of erroring on the resolved path

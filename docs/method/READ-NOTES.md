# D2595 WO-001 — READ notes

Status: READ step output, 2026-10-11. Author: bench-claude-reviewer-01 (Claude Opus 5.5).
Brief: flow-chief-1/personal/d2595-wo001/AUTHOR-BRIEF-v1.md (sha256 3aabcbf7dff270b3…).
Authority: pfc D2595, D2595-WO001-SEAT-B.

## 1. What I read (pinned versions)

| Input | Version read |
| --- | --- |
| Steward brief | pfc/personal/d2595/wo001-steward-brief.md |
| CraftCode v0.1 | ~/Projects/craftcode main `6c7923e`: §4, §6, §8, §14.1, §14.2, §15.1, §16, App. A (start) |
| CraftCode pilots / templates | `pilots/README.md` (one row: Trinity × CraftCode, "准备 WO-001"); `templates/` is empty (`.gitkeep` only) |
| Trinity | `forge/main` = `019e354` (VERSION 3.3.0), read with `git show forge/main:<path>`. No `git fetch` (see §5) |
| Trinity plan | PFC-2519 rows D2595, D2595-FORGE*, D2595-WO001-SEAT*; pfc/personal/next-session.md "Trinity plan" |
| Mockup | pfc/artifacts/trinity-mockup.html (18 953 bytes, 16:37) |

## 2. What WO-001 is, per CraftCode

- §14.2: WO-001 = "确认范围与发布语义"; deliverable = **边界、术语、风险和未决事项** (boundary, terms, risks, open items).
- §14.1 stage 1 = 建立基线: done when there is a clear scope, success conditions, environment limits and a comparison record.
- WO-002 (contracts + independent acceptance, i.e. full component specs with verification cases) comes **after**. So the component specs written here are *draft boundary specs*, not WO-002 contracts. Each requirement gets a stable ID (§6.7) and is marked **unverified**.
- §4.1 six objects: 法式, 构件规格, 构件实现, 组装方案, 施工工单, 验收与发布记录. WO-001 touches the first two only.
- §15.1 metrics for the retro: wall time, RETURNs, defects (steward brief), from the 15.1 list.

## 3. What Trinity is today (forge/main 3.3.0)

- A Claude Code **skill** (`SKILL.md`, 445 lines) plus a Codex adapter (`scripts/codex.py`, `trinity review`).
- **Dispatch** = the host spawns a background sub-agent from `~/.claude/agents/trinity-<p>.md`; that agent shells out to the provider CLI. Agent files are generated: `providers/<p>.delta.md` + `providers/_base/*.md` via `scripts/build_providers.sh` (`@include`).
- **Registry** `providers/registry.json`: per provider `cli`, `supports_resume`, `resume_arg`, `timeout`. Seven entries: glm, minimax (both `droid exec … custom:GLM-5.2 / MiniMax-M3`), codex (`gpt-5.6-sol`), openrouter, deepseek, claude-code, agy-opus. **gemini has agent files (`providers/gemini*.md`) but no registry entry.**
- **Wrappers** `providers/bin/`: `claude-code` (isolated `CLAUDE_CONFIG_DIR=~/.claude-trinity-claude-code`, `TRINITY_DISABLE_DISPATCH=1`, sonnet/high), `deepseek` and `openrouter` (Anthropic-compatible endpoint via `claude`, key from env or `~/.secrets/*` mode 600/400), `agy-opus` (140 lines, run lock).
- **Sessions**: `<project>/.claude/trinity.json` `sessions` key, `scripts/session.py` read/write/clear/heartbeat under `fcntl.flock`. One session id per *instance key* (`codex`, `codex:review`). No run, no parent, no rounds.
- **Response capture** for the `claude` family: grep a trace marker in the session JSONL (`_base/family-wrapper.md`), because `claude -p` stdout is not used.
- **Review pipeline** (`scripts/_review.py` 1 092 lines, `provider_runtime.py` 609, `_review_metadata.py`): fan-out per preset, PTY capture, env sanitising (`build_provider_env`), per-review `metadata.json` (provider state + results). This is the nearest thing to a journal today; it is per review, flat, not a call tree.
- **Health**: `session.py heartbeat <output_file>` reads the last assistant activity in an agent output file.
- **Decision record** TRN-3000: stay a CLI backend, not ACP. Relevant: it limits what the live view can show (no structured tool events; must read vendor transcripts).
- Rules layer: `rules/TRN-*` (Alfred docs), TRN-1006 Provider Model IDs SOP.

## 4. What the plan changes (D2595 + "Trinity plan")

1. All harnesses, including **OpenCode Go** and **deepseek direct API**, with both billing modes (subscription, pay-per-use).
2. codex → current models (plan text; mockup shows `gpt-6.1-sol`, registry pins `gpt-5.6-sol`).
3. claude-code reads fleet setup-tokens as **profiles A/B/C** (`CLAUDE_CODE_OAUTH_TOKEN` from `~/.claude/fleet-tokens/<acct>.token`; smoke 14:15 OK only this way).
4. **Delete gemini** (official CLI stopped); keep agy.
5. One common wrapper; **continue or new session** per call.
6. **Quota and heavy-lock checks** before dispatch.
7. **Journal = call tree**; web and CLI views; live; RETURN rounds shown as ↺.

Mockup facts I used: `trinity profiles`, `trinity tree <run>`, `trinity tree --expand <step>`, `trinity show <run>/<node> --events`, `trinity resume <run>/<node> "<prompt>"`, `trinity open <run>`; node fields session (new/continued), profile, billing, wall time, tokens, output (commit/verdict); states done/running/stuck/failed; stuck = "6 min no heartbeat"; events typed 提示词/思考/工具/输出/心跳 from the child's raw transcript; footer: **`run-journal.jsonl` is the single source of truth; web and CLI trees are generated from it.**

## 5. Drift and defects found while reading

| # | Finding | Effect on WO-001 |
| --- | --- | --- |
| R1 | Three Trinity copies disagree: `forge/main` (registry glm = droid GLM-5.2), local branch `fix/trinity-retired-model-id-guard` (+10 commits: `codex-deepseek` wrapper, `check_wrapper_models.py`, retired-model guard), and the installed `~/.claude` copy (glm = `~/.claude/skills/trinity/bin/glm`, LiteLLM bridge glm-5.3; that wrapper is in neither git tree). | The method must name **one baseline**. I used forge/main; the open branch must land or be dropped before WO-002. |
| R2 | gemini: agent files present, registry entry absent. | Deletion is half done already; adapter spec lists it as removed. |
| R3 | Model IDs are hard-coded in four places (registry, delta.md, wrappers, mockup). | Profiles spec moves model choice into profile data. |
| R4 | `templates/` in craftcode is empty and App. A is the only spec template. | Specs here follow App. A fields loosely (markdown, not YAML). Template choice is an open item. |
| R5 | Mockup uses Chinese step labels as path keys (`run-0711/独立审查`). | Ledger spec uses stable node ids; labels are display only. |
| P1 | **Process:** the author brief asks this seat to create a worktree, commit and push; this seat's charter forbids worktrees, commits and pushes. Drafts are written to `bench-claude-reviewer-01/personal/d2595-wo001/docs/method/` instead; the steward commits by path. | Reported in RECEIVED (send 635a95a6…). |
| P2 | Brief says "do not touch ~/.citizens"; this seat's home is in ~/.citizens. Output stays inside the seat's own `personal/`. | Same report. |
| P3 | No `git fetch forge` was run (would write refs in ~/Projects/trinity, which is on another branch). forge/main as last fetched = `019e354`. | Steward re-checks forge/main before cutting `pilot/trinity`. |

## 6. Open questions (carried into the specs)

- Q1 Baseline: forge/main 3.3.0, or forge/main + the retired-model-guard branch?
- Q2 Is Trinity still a *skill inside a host* (sub-agent dispatch), or does it become a standalone CLI (`trinity tree/show/resume/open` in the mockup is standalone)? Both, with one core?
- Q3 Which repo is the fleet-facing one: forge pilot/trinity only, or also GitHub frankyxhl/trinity later (D2595-FORGE: "GitHub later")? Public repo must not carry fleet paths/tokens.
- Q4 Where do fleet facts (heavy lock path, quota board, fleet-tokens dir) live — Trinity core or a fleet profile pack outside the repo?
- Q5 Retention and privacy of journals that index thinking/prompts.
- Q6 Who owns WO-002 acceptance cases (CraftCode §8.1: the author must not own them).

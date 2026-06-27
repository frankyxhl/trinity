# CHG-3046: Droid Provider Session ID via `droid exec -o json`

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-06-28
**Last reviewed:** 2026-06-28
**Status:** Approved (§4 plan-review: glm 9.50 / deepseek 9.60 / minimax 9.50 R2 — all ≥9.5, all blocking empty)
**Date:** 2026-06-28
**Requested by:** Frank Xu (issue #263)
**Priority:** High
**Change Type:** Bugfix
**Closes:** #263
**References:** TRN-2004 (provider files refactor); TRN-1008 §3/§4 (CHG + plan-review); TRN-1800 (CODE weights); CLD-1802 (symmetric class)

---

## What

Switch the droid-based providers' (`glm`, `minimax`) new-session extraction from `droid search "<phrase>" --json | sessions[0]['sessionId']` to reading `session_id` and `result` directly from `droid exec -o json`'s own output. The session id then comes from the process's own result — deterministic and concurrency-safe — never from a post-hoc content search.

## Why

`droid search` is a content search across the local session store (substring + typo-tolerant) and does **not** isolate by model or instance. When two droid providers run concurrently in the same project with similar prompts, `sessions[0]` resolves to the *other* provider's session, so both instance keys in `.claude/trinity.json` point at the same droid session and subsequent resumes cross-pollinate context. Surfaced by the 2026-06-27 smoke test: `trinity-glm` (`glm:smoke`) and `trinity-minimax` (`minimax`) dispatched in parallel with near-identical prompts; `trinity.json` stored the **same** id `6acb1418-905c-473d-9929-cce3fcb9d777` for both.

`droid exec -o json` already emits the id directly — probe-confirmed: `{"type":"result","result":"pong","session_id":"8a271321-…","usage":{…}}`. The id + response text are both in that JSON, so the `RESPONSE=` stdout text-capture and the `droid search` lookup both become unnecessary. (The JSONL trace-grep pattern belongs to the claude/deepseek/openrouter family via `family-wrapper.md` and is out of scope here.)

## Scope Justification

`glm` and `minimax` deltas share the identical extraction snippet (symmetric class per CLD-1802). Both must change atomically: fixing one leaves the other still stealing sessions via `droid search`, and a half-fix leaves the two providers' templates divergent for no reason.

## Out of Scope

- Claude-family session-path slug — already fixed in #262 / CHG-3045 (merged).
- Codex transcript resolver (`_resolve_codex` — different layout).
- Resume logic (`droid exec -s "$SESSION_ID"` — unchanged; only new-session extraction changes).
- The `common-session.md` read/write pointer logic (`.claude/trinity.json` CRUD — unchanged).

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `providers/glm.delta.md` New-session extract (~L24-36) | Replace `RESPONSE=$(droid exec …)` + `droid search … sessions[0]` with `RESULT_JSON=$(droid exec … -o json …)` then read `session_id` + `result` from that JSON. |
| 2 | `providers/minimax.delta.md` New-session extract (~L24-36) | Same change (symmetric class — only the `--model custom:…` id differs). |
| 3 | regenerated `providers/glm.md` + `providers/minimax.md` | `make build`; committed in the same commit as the `.delta.md` edits; `make verify-built` clean. |

## Acceptance Criteria

- **A1**: `glm.md` and `minimax.md` new-session flow calls `droid exec … -o json` and reads `session_id` from that JSON (not `droid search`).
- **A2**: No `droid search … sessions[0]` extraction path remains in `providers/*.delta.md` / `providers/*.md`.
- **A3**: Response text is read from the same JSON's `result` field (drops the `RESPONSE=` stdout text-capture + the `droid search` id lookup).
- **A4**: After parallel `trinity-glm` + `trinity-minimax` dispatch with similar prompts, the two `trinity.json` entries hold **different** session ids.
- **A5**: `make build && make verify-built` exits 0; `make test` green, `make lint` clean.
- **A6**: `CHANGELOG.md` records the fix.
- **A7**: `tests/test_build_providers.sh` asserts the generated `glm.md` + `minimax.md` contain `droid exec` + `-o json` + `session_id` and do NOT contain `droid search` (static regression guard — `make verify-built` must fail if the templates revert to the racy content-search path).

## Implementation Order

1. `providers/glm.delta.md`: replace the New-session extract block with `droid exec -o json` + JSON parse for `session_id` and `result`.
2. `providers/minimax.delta.md`: same change (`--model custom:MiniMax-M3`).
3. `make build`; commit the 2 `.delta.md` AND regenerated `*.md` in the SAME commit; confirm `make verify-built` clean.
4. Add `tests/test_build_providers.sh` grep assertions (generated `glm.md`/`minimax.md` contain `droid exec` + `-o json` + `session_id`, lack `droid search`); `make test && make lint`.
5. `CHANGELOG.md` entry.
6. Commit (identity per §2 / CLAUDE.md — `ryo.saeba@frankxu.me`).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-06-28 | Initial Proposed CHG per issue #263 (surfaced by glm/minimax/deepseek smoke test) | Claude Code (ryosaeba1985) |
| 2026-06-28 | R2: address §4 R1 minimax blocker (no regression test for A4 collision) — add A7 static grep assertions in `tests/test_build_providers.sh`; reword A3 + Why (droid family is `RESPONSE=` stdout-capture + `droid search`, NOT JSONL grep — that pattern is the claude/deepseek/openrouter family, out of scope). R1: glm 9.50 PASS, deepseek 9.60 PASS, minimax 8.30 FIX. | Claude Code (ryosaeba1985) |

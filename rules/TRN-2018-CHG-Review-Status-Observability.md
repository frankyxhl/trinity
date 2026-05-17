# CHG-2018: Review Status Observability

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-16
**Last reviewed:** 2026-05-16
**Status:** Approved
**Date:** 2026-05-05
**Requested by:** Frank
**Implementer:** Codex
**Priority:** High
**Change Type:** Normal
**Related:** TRN-2011, TRN-2013, TRN-2014, TRN-2015

---

## What

Improve Codex-native `trinity review` observability so long-running provider
reviews are inspectable while they run instead of appearing as one opaque
blocking process.

Target user-facing capabilities:

```bash
trinity status --latest
trinity status --latest --watch
trinity review --detach --preset fast-review --scope .
trinity wait <review-id> --timeout 60
```

The minimal useful version is intentionally smaller:

1. Live `metadata.json` updates while `trinity review` is running.
2. `trinity status --latest` for the newest review directory.
3. Provider stdout/stderr files written incrementally as soon as a provider
   starts.

---

## Why

Today `trinity review` blocks until every provider finishes. When a provider is
slow or silent, Codex has to infer health by inspecting processes, review
directories, raw files, and timeout values manually. This makes progress updates
less reliable and makes it harder to distinguish:

- a slow but healthy model,
- a provider waiting on auth or permission handling,
- a hung CLI,
- a provider that has already timed out,
- and a review that finished but has not yet been summarized.

First-class status data lets Codex and humans answer "what is still running?"
without guessing.

---

## Requirements

### Live Review Metadata

Write `metadata.json` when the review directory is created and update it as
providers move through lifecycle states.

Required top-level fields:

- `review_id`
- `review_dir`
- `status`: `queued`, `running`, `finished`, `failed`, `timed_out`, `stalled`
- `scope`
- `root`
- `started_at`
- `finished_at`
- `providers`: existing backward-compatible list of provider names, unchanged
  from current metadata shape
- `provider_states`: object keyed by provider name, containing live state
- `input`
- `preset`
- `results`

Backward compatibility requirement: this CHG must not remove or reshape current
top-level metadata keys. Existing `providers` remains a list. Rich provider
state goes under the new `provider_states` key.

Top-level timestamp and status semantics:

- `started_at` is set when `metadata.json` is first written, before any provider
  starts.
- `finished_at` is `null` until all selected providers reach a terminal state
  and `synthesis.md` has been written.
- `results` is initialized as `[]` and appended to after each provider reaches a
  terminal state.
- top-level `status` is `running` while any provider is queued/running/stalled,
  and becomes `finished` when every provider is `finished`; it becomes `failed`
  or `timed_out` if any provider reaches that terminal state.

Provider state should include:

- provider name
- status: `queued`, `running`, `finished`, `failed`, `timed_out`, `stalled`
- pid when known
- started / finished timestamps
- elapsed seconds
- timeout seconds
- timeout deadline
- heartbeat timestamp
- stdout/stderr paths
- raw output path
- return code when finished

### Incremental Provider Logs

Create provider-specific files under `logs/` as soon as each provider starts:

```text
logs/glm.stdout.log
logs/glm.stderr.log
logs/deepseek.stdout.log
logs/deepseek.stderr.log
```

The existing `raw/<provider>.txt` compatibility artifact should still be written
after the provider finishes. Its format must remain compatible with the current
implementation: stdout first, followed by `\n[stderr]\n` and stderr only when
stderr is non-empty.

### Status Command

Add:

```bash
trinity status --latest
```

It should find the newest review under the configured review output directory
and print a concise status summary:

```text
review 20260505-181600-. running
deepseek running 02:31/10:00 pid=40179 last_output=18:15:20
glm queued
```

`--watch` is a later-phase enhancement unless it falls out naturally from the
same implementation with low complexity.

The `review_id` is the review directory basename created by `make_review_dir()`,
including any collision suffix, for example `20260505-181600-.` or
`20260505-181600-.-2`. `review_dir` is the absolute review directory path.
Provider `stdout_path`, `stderr_path`, and `raw` paths are relative to
`review_dir`, matching the current `results[].raw` convention. `trinity status
--latest` finds the newest review directory under the configured
`review.output_dir` by directory modified time, then reads its `metadata.json`.
If no review directories exist, it exits 0 and prints `no reviews found`.

`last_output` in status output is derived from the newest stdout/stderr log file
modified time for that provider. Timestamps should use Trinity's existing local
ISO seconds format unless a later CHG standardizes timezone-aware timestamps.

### Events

Append machine-readable lifecycle events to `events.jsonl`:

```json
{"event":"provider_started","provider":"deepseek","pid":40179}
{"event":"provider_heartbeat","provider":"deepseek","elapsed_seconds":120}
{"event":"provider_finished","provider":"deepseek","status":"finished"}
```

Events are useful for polling scripts and debugging but should not become the
only source of truth; `metadata.json` remains the current-state snapshot. A
crash between appending an event and updating metadata may create divergence;
status commands should trust `metadata.json` for current state and treat
`events.jsonl` as audit history.

### Stalled Detection

If a provider produces no output and no heartbeat for a configured duration,
mark it `stalled`.

Milestone 2 introduces `review.stall_threshold_seconds`, defaulting to `60`.
Milestone 4 may add CLI/operator tuning, but Milestone 2 must have a documented
default and config key before stalled detection ships.

Do not kill stalled providers by default. Killing requires an explicit future
flag such as:

```bash
trinity review --fail-on-stall
```

In the current sequential execution model, only one provider is `running` at a
time; later providers remain `queued`. This still improves observability for the
active provider and makes timeout/stall diagnosis explicit. Provider parallelism
is not part of this CHG.

`stalled` is a transient provider state. If new stdout/stderr output appears
before timeout, the provider transitions back to `running`; otherwise it
eventually transitions to `timed_out`.

---

## Milestones

### Milestone 1: Minimal Observability

Goal: eliminate most manual process/file guessing while keeping review execution
blocking and sequential as it is today.

Scope:

1. Create `metadata.json` before provider execution.
2. Update provider states before start and after completion.
3. Stream stdout/stderr to provider log files during execution.
4. Preserve `raw/<provider>.txt` and `synthesis.md` compatibility.
5. Add `trinity status --latest`.
6. Add tests for live metadata shape, provider log files, status output, and
   backward-compatible raw/synthesis artifacts.
7. Add a backward-compatibility test asserting current consumers still see:
   - `providers` as a list,
   - `preset`,
   - `input`,
   - `results`,
   - result entries with `provider`, `returncode`, `raw`, `started_at`, and
     `finished_at`.

Non-goals:

- No detach mode.
- No background process management.
- No provider parallelism change.
- No automatic kill-on-stall.

Implementation note: create `logs/` in `make_review_dir()` alongside the
existing `raw/` directory, so status readers can rely on stable artifact
locations from the start of the review.

### Milestone 2: Events and Stalled Signals

Goal: make polling and stuck-provider diagnosis robust.

Scope:

1. Add `events.jsonl`.
2. Add heartbeat updates while provider processes run.
3. Detect stale output/heartbeat age and mark providers `stalled`.
4. Add status output for `stalled`, `timed_out`, and `failed` providers.
5. Add tests using fake provider scripts that sleep, emit partial output, hang,
   and exceed timeout.
6. Add `review.stall_threshold_seconds` config with default `60`.

Non-goals:

- Still no detached process orchestration.
- Stalled state is informational only.

Heartbeat mechanism: use a main-thread polling loop around `Popen.poll()` that
periodically updates metadata and checks stdout/stderr log file modified times.
Default polling interval is 2 seconds. Heartbeat updates and stall checks share
that polling cycle. No watcher threads or daemon process in this milestone.

### Milestone 3: Detached Execution and Wait

Goal: let Codex launch a review, regain control, then poll or wait explicitly.

Scope:

1. Add `trinity review --detach`.
2. Add `trinity wait <review-id> --timeout <seconds>`.
3. Add `trinity status --latest --watch`.
4. Record parent/child process metadata needed for detached review tracking.
5. Add tests for detached review lifecycle with fake provider scripts.

Non-goals:

- No daemon.
- No cross-machine status storage.
- No provider cancellation UI unless explicitly added later.

### Milestone 4: Cleanup and Operator Controls

Goal: complete operational ergonomics after the main observability path is
stable.

Scope:

1. Add optional `--fail-on-stall`.
2. Add CLI/operator override for stall threshold if config-only tuning is not
   enough.
3. Add cleanup guidance for old review directories.
4. Consider `trinity status <review-id>` if `--latest` is insufficient.

---

## Phased Implementation Plan

### Phase 0: CHG Review and Scope Lock

1. Review this CHG with `trinity review --preset fast-review`.
2. Decide whether Milestone 1 should include `events.jsonl`; default answer is
   no unless reviewers find it cheap and low risk.
   Events are deferred by default because Milestone 1 should validate the
   metadata state model independently before introducing a second append-only
   write path.
3. Confirm no schema compatibility promises beyond local Trinity artifacts.

### Phase 1: Metadata State Model

1. RED: add tests for initial `metadata.json` written before provider execution.
2. RED: add tests for provider state transitions: queued -> running ->
   finished/failed/timed_out.
3. GREEN: add helper functions for review id, metadata loading/writing, and
   atomic metadata updates.
4. REFACTOR: keep metadata helpers independent from provider CLI execution.

Atomic metadata update mechanism: write JSON to a temporary file in the same
review directory, flush it, then replace `metadata.json` with `os.replace()`.
Milestone 1 does not need file locking because provider execution remains
sequential in one process. Later status readers in Milestone 3 will see either
the old complete metadata file or the new complete metadata file, never a
partial write.

### Phase 2: Incremental Logs

1. RED: add fake provider tests proving stdout/stderr files exist while or
   immediately after provider execution starts.
2. GREEN: change provider execution from `subprocess.run(..., stdout=PIPE,
   stderr=PIPE)` to `subprocess.Popen` with live log sinks. Route stdout
   through a PTY-backed reader into `logs/<provider>.stdout.log` so child
   processes that line-buffer on `isatty()` flush progress before exit; route
   stderr to `logs/<provider>.stderr.log` with line-buffered file handles.
3. GREEN: compose legacy `raw/<provider>.txt` from the stdout/stderr logs after
   completion.
4. Implement timeout manually with `Popen.wait(timeout=...)`; on timeout, kill
   the child, mark provider `timed_out`, write return code `124`, and preserve
   any partial stdout/stderr logs.
   - Send `terminate()` first.
   - If the process does not exit within 5 seconds, send `kill()`.
   - After the process exits or is killed, close stdout/stderr sinks before
     composing `raw/<provider>.txt`.
5. Preserve current failure semantics for missing commands (`127`) and normal
   non-zero return codes. If `Popen()` raises `FileNotFoundError`, create empty
   stdout/stderr log files, write the existing command-not-found message to
   `raw/<provider>.txt`, and record return code `127`.
6. Verify timeout behavior still writes the expected raw output and metadata.

### Phase 3: `trinity status --latest`

1. RED: add tests for finding the newest review directory under the configured
   output path.
2. RED: add tests for rendering running, queued, finished, failed, and timed-out
   provider states from `metadata.json`.
3. GREEN: add `status` subcommand with `--latest` in `build_parser()`.
4. GREEN: keep output human-readable and intentionally compact.

### Phase 4: Documentation and Install Smoke

1. Update README and Codex skill docs with the new status workflow.
2. Add changelog entry.
3. Run `make install-codex`.
4. Verify `trinity status --latest` against a fake or low-risk review.

---

## Impact Analysis

- **Systems affected:** `scripts/codex.py`, `bin/trinity` behavior through the
  installed script, Codex adapter docs, README, tests, and review artifact
  layout under `.trinity/reviews/`.
- **Systems intentionally preserved:** existing `trinity review --providers`,
  `--preset`, `--base/--head`, `--pr`, provider preflight, prompt rendering,
  raw provider output under `raw/`, and deterministic `synthesis.md`.
- **Downtime required:** No.
- **Backward compatibility:** Existing consumers of `raw/<provider>.txt`,
  `prompt.md`, `metadata.json`, and `synthesis.md` should continue to work.
  `metadata.json` may gain fields but should not remove current top-level keys
  without a separate breaking-change CHG.
- **Main risks:** corrupt live metadata if a process exits mid-write, misleading
  status if timestamps are stale, leaking provider stderr details into
  user-facing output, and increasing complexity around timeouts.
- **Rollback plan:** revert status subcommand, live metadata helpers,
  incremental log writing, docs, and tests. Blocking `trinity review` can return
  to writing metadata only after all providers complete.

---

## Testing / Verification

Expected Milestone 1 evidence:

- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- targeted fake-provider tests for:
  - live metadata initialization,
  - pre-execution metadata is valid JSON and has all providers queued,
  - running/finished/failed/timed_out states,
  - stdout/stderr log creation,
  - `providers` remains a list and `provider_states` contains rich state,
  - existing `scope`, `root`, `preset`, `input`, and `results` keys remain
    present,
  - legacy `raw/<provider>.txt` preservation,
  - `trinity status --latest` rendering.
- `make test`
- `make lint`
- `af validate --root .`
- `make install-codex`
- `trinity review --preset fast-review --scope <small-safe-scope>`
- `trinity status --latest`

---

## Approval

- [x] Approved for implementation (Milestone 1 scope; M2-M4 deferred)
- [ ] Implemented
- [ ] Verified locally
- [ ] PR opened

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|
| 2026-05-05 | Created CHG from business requirement in `tmp/trinity-review-status-improvements.md` | Proposed |
| 2026-05-05 | Reviewed with Trinity fast-review | GLM/DeepSeek requested schema precision, backward compatibility tests, log path, raw format, atomic writes, Popen timeout detail, and sequential-execution caveat |
| 2026-05-05 | Re-reviewed with Trinity fast-review | GLM/DeepSeek requested final clarifications for stall threshold, timestamp semantics, transient stalled state, log buffering, results lifecycle, and no-review status behavior |
| 2026-05-16 | Approved for M1 implementation; M2-M4 deferred. Phase C execution plan v2 cleared trinity fast-review (glm 9.58 / deepseek 9.50, both PASS, ≥9.5 strict gate) | Frank + Claude |

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-05 | Initial CHG with milestone and phase split | Codex |
| 2026-05-05 | Revised after Trinity fast-review findings | Codex |
| 2026-05-05 | Revised after second Trinity fast-review findings | Codex |
| 2026-05-16 | Status: Proposed → Approved (M1 scope); recorded fast-review v2 plan PASS in Execution Log | Claude Opus 4.7 |

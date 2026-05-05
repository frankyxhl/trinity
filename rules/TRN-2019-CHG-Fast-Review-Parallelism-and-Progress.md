# CHG-2019: Fast Review Parallelism and Progress

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-05
**Last reviewed:** 2026-05-05
**Status:** Proposed
**Date:** 2026-05-05
**Requested by:** Frank
**Implementer:** Codex
**Priority:** High
**Change Type:** Normal
**Related:** GitHub issue #27, TRN-2011, TRN-2013, TRN-2015, TRN-2017, COR-1202, COR-1615

---

## What

Improve Codex-native `trinity review` so independent review providers can run
concurrently and operators can see progress while reviews are running.

Target user-facing behavior:

```bash
trinity review --preset fast-review --scope TRN-2019
```

For a preset such as `fast-review` that expands to `glm` and `deepseek`, Trinity
should start both providers in the same review run, wait for both results, and
write the same final artifacts it writes today:

- `prompt.md`
- `raw/<provider>.txt`
- `metadata.json`
- `synthesis.md`

The change also adds explicit progress logging and safer process cleanup for
provider CLIs that spawn child processes.

---

## Why

Issue #27 reports that `fast-review` is slow because provider execution is
sequential. Recent review metadata confirms the behavior: GLM finished at
`2026-05-05T21:29:45`, and DeepSeek started at exactly
`2026-05-05T21:29:45`. That makes wall-clock time roughly
`glm_time + deepseek_time` instead of `max(glm_time, deepseek_time)`.

The same issue makes operator feedback worse. A review can sit silently for
several minutes, and a timeout or interrupt may only affect the direct wrapper
process while provider child processes keep running.

---

## Current Evidence

Implementation evidence from `scripts/codex.py`:

- `cmd_review()` iterates providers with `for provider in providers`.
- Each iteration calls `run_provider()` and waits for completion before the next
  provider starts.
- `run_provider()` uses `subprocess.run(..., timeout=timeout)`, which does not
  create a dedicated process group/session for provider wrappers.
- `metadata.json` and `synthesis.md` are written only after every selected
  provider has returned.

Observed metadata from final TRN-2017 review:

```text
glm      started 2026-05-05T21:26:47  finished 2026-05-05T21:29:45
deepseek started 2026-05-05T21:29:45  finished 2026-05-05T21:32:19
```

Numbering note: TRN-2018 is intentionally not reused here because a separate
review observability draft exists outside `main`. This issue #27 plan uses
TRN-2019 to avoid overwriting that earlier work.

---

## Scope

### In Scope

1. Run selected review providers concurrently when `trinity review` dispatches
   independent provider CLIs.
2. Preserve deterministic result ordering in `metadata.json` and `synthesis.md`
   according to the resolved provider order, even if providers finish in a
   different order.
3. Add progress logging to stderr, at minimum:
   - preparing prompt
   - writing prompt
   - starting each provider with timeout
   - provider finished / failed / timed out
   - writing metadata and synthesis
4. Write an incomplete marker when a review exits before final metadata or
   synthesis is written.
5. Run provider subprocesses in their own process group/session and kill the
   whole process group on timeout or interruption.
6. Add a review-only prompt instruction that tells providers not to run tests or
   shell commands unless explicitly requested by the review prompt.

### Out of Scope

- Detached/background review mode.
- `trinity status --latest`.
- Watch mode.
- Provider result streaming into live UI.
- Changing provider presets or provider model configuration.
- Parsing reviewer PASS/FIX semantics from raw output.

These are valuable, but they should remain separate from the latency and
cleanup fix so this change stays reviewable.

---

## Design Notes

### Concurrency Model

Use a small standard-library concurrency layer around provider execution. The
preferred implementation is `concurrent.futures.ThreadPoolExecutor` because
provider work is subprocess-bound, not CPU-bound.

Concurrency limit:

- default: number of selected providers
- optional config key: `config["review"]["max_parallel_providers"]`
- minimum accepted value: `1`
- when omitted or `null`, use the number of selected providers
- reject `0`, negative numbers, non-integers, booleans, and values larger than
  the number of selected providers

Provider results should be collected by future completion, then sorted back into
the resolved provider order before writing metadata and synthesis.

Dispatch should be bounded to the current concurrency limit. Submit only the
currently running provider window, then submit the next provider after one
result completes. Do not queue every selected provider up front; on an interrupt
or orchestration error, queued providers must not start after cleanup has
already been snapshotted.

Use `ThreadPoolExecutor` without relying on its default context-manager shutdown
behavior for interrupt cleanup. The implementation must keep explicit handles to
active provider processes and must run cleanup from a `finally` block:

1. On normal completion, wait for all futures.
2. On `KeyboardInterrupt` or fatal orchestration error, cancel not-yet-started
   futures, terminate/kill all active provider process groups, then shut down
   the executor without waiting for natural provider completion.
3. Return only after active provider process groups have been cleaned up or the
   kill grace period has expired.

Thread-to-process ownership must be explicit. Provider workers create `Popen`
objects, but cleanup is orchestrated from the main thread. Track active
processes in a small shared registry guarded by `threading.Lock`:

- worker adds `(provider, popen, started_at)` immediately after successful
  `Popen()` creation;
- registry also records a provider in a monotonic started-provider set that is
  not removed when the provider finishes;
- worker removes that entry in its own `finally` block after `communicate()` or
  cleanup finishes;
- main-thread cleanup copies the active entries while holding the lock, releases
  the lock, then signals process groups from that snapshot.

Do not hold the lock while waiting for process termination. That avoids blocking
workers that are trying to remove completed process handles.

Running futures cannot be cancelled by `Future.cancel()` once their provider
process has started, and workers may be blocked in `Popen.communicate()`. On
interrupt, cleanup must therefore kill active process groups first, which
unblocks `communicate()`, and only then shut down the executor.

Provider failures are independent. If one provider times out or returns a
non-zero exit code while another provider is still running, Trinity should let
the other running provider finish or hit its own timeout. Final artifacts should
include every provider result that reached a terminal state. The command returns
`0` only when all selected providers return `0`; otherwise it returns non-zero.
This is a completed review with failed provider results, not an incomplete
review. `incomplete.json` is reserved for orchestration failures or interrupts
that prevent final `metadata.json` or `synthesis.md` from being written.

### Process Group Cleanup

Replace direct `subprocess.run()` provider execution with explicit `Popen`
management:

- POSIX/macOS: start provider with `start_new_session=True`.
- On timeout: terminate the provider process group first, wait up to 5 seconds,
  then kill the process group if it does not exit.
- On `KeyboardInterrupt` or wrapper interruption: terminate/kill every still
  running provider process group before returning.
- Treat an already-exited process group as successful cleanup, and record
  cleanup errors such as `permission_denied` instead of masking them.
- Preserve return code `124` for timeouts.
- Preserve return code `127` for command-not-found.
- Windows process-group behavior is out of scope for this CHG. Trinity's current
  supported operator environment is macOS/POSIX; a future CHG can add Windows
  process group support if needed.
- Process-group cleanup relies on provider wrappers and their children staying
  in the session started by Trinity. A wrapper that deliberately starts its own
  detached session may need its own cleanup logic or a future doctor smoke test.

Raw provider file writes may remain inside the provider worker because each
provider writes to a unique `raw/<provider>.txt` path. Main-process writes are
required for shared artifacts only: `metadata.json`, `synthesis.md`, and
`incomplete.json`.

### Progress Logging

Progress messages go to stderr so stdout can remain the review directory path
on success. If an interrupt or orchestration failure happens after the review
directory exists, stdout still prints that review directory so operators and
scripts can inspect `incomplete.json`. Preflight/config failures before
directory creation keep stdout empty.

Provider stdout/stderr should not be forwarded live to the operator terminal in
this CHG. Concurrent provider logs can interleave and become noisy; raw provider
output remains available in `raw/<provider>.txt`.

Example:

```text
trinity: preparing review prompt
trinity: starting provider glm timeout=360s
trinity: starting provider deepseek timeout=600s
trinity: provider glm finished returncode=0 elapsed=126s
trinity: provider deepseek finished returncode=0 elapsed=185s
trinity: writing metadata
trinity: writing synthesis
```

### Incomplete Marker

Create `incomplete.json` only when the review is interrupted or an orchestration
failure prevents final artifacts from being written. Avoid creating it on the
success path; do not write and then delete a transient incomplete marker during
normal execution.

Minimum contents:

- status: `interrupted`, `failed`, or `timed_out`
- timestamp
- review directory path
- selected providers
- providers already started
- providers still running when cleanup began
- cleanup result

Example:

```json
{
  "status": "interrupted",
  "timestamp": "2026-05-05T22:30:00",
  "review_dir": ".trinity/reviews/20260505-223000-TRN-2019",
  "providers_selected": ["glm", "deepseek"],
  "providers_started": ["glm", "deepseek"],
  "providers_running_at_cleanup": ["deepseek"],
  "cleanup": {
    "deepseek": {
      "pid": 12345,
      "result": "terminated"
    }
  }
}
```

Successful reviews must not leave the incomplete marker behind.

### Review-Only Prompt Mode

Add a concise instruction to the review prompt:

```text
Review-only mode: do not run tests, shell commands, network calls, or mutate
files unless the instructions in this review prompt explicitly ask you to. Base
findings only on the provided diff, file snapshots, and review context.
```

This should be default behavior for `trinity review`. A future CHG can add an
explicit opt-in for tool-running reviewers if needed.

This changes prompt content but does not change prompt input modes. Existing
working-tree, `--base/--head`, and `--pr` review inputs remain supported.

---

## Milestones

### Milestone 1: Parallel Provider Dispatch

Goal: reduce `fast-review` wall-clock time from additive provider latency to
approximately the slowest provider latency.

Tasks:

1. RED: add a fake-provider test where `glm` and `deepseek` each sleep, proving
   wall-clock duration is less than their summed sleeps.
2. RED: assert both providers are started before either slow provider completes.
3. GREEN: add concurrent provider dispatch with deterministic result ordering.
4. GREEN: add `config["review"]["max_parallel_providers"]` parsing and tests,
   defaulting to the number of selected providers when unset.
5. RED: add a mixed-success test where one provider succeeds and one provider
   fails or times out; assert deterministic result ordering and non-zero command
   return.
6. RED/GREEN: reject duplicate explicit or legacy default provider selections
   before creating a review directory so one provider result cannot overwrite
   another result keyed by the same provider name.
7. GREEN: preserve existing raw output, metadata, synthesis, and return-code
   behavior.
8. REFACTOR: keep prompt/rendering code separate from dispatch code.

### Milestone 2: Progress Logging

Goal: make long-running reviews visibly alive.

Tasks:

1. RED: add tests for stderr progress messages.
2. GREEN: log prompt preparation, provider start, provider finish/fail/timeout,
   and final artifact writes.
3. GREEN: ensure stdout remains stable enough for scripts that expect the final
   review directory path.
4. Docs: document progress logs in README and the Codex Trinity skill.

### Milestone 3: Process Group Timeout and Interrupt Cleanup

Goal: prevent provider wrapper children from surviving timeouts or interrupts.

Tasks:

1. RED: add fake wrapper tests that spawn a child process and then sleep.
2. RED: prove timeout cleanup terminates the child process group.
3. RED: prove interrupt cleanup does not wait for providers to finish
   naturally. Preferred test approach: launch the Trinity review command in a
   subprocess with fake providers, send SIGINT to the Trinity process, and
   assert provider child processes are terminated and `providers_started`
   remains distinct from `providers_running_at_cleanup`.
4. GREEN: start providers in new sessions/process groups.
5. GREEN: terminate then kill remaining provider groups on timeout.
6. GREEN: cleanup all active providers on `KeyboardInterrupt`.
7. GREEN: preserve `124` for provider timeouts and `127` for command-not-found
   while using `Popen`.

### Milestone 4: Incomplete Review Artifacts

Goal: make partial review directories self-describing.

Tasks:

1. RED: add tests for interrupted and pre-synthesis failure cases, including an
   interruption after review directory creation but before provider dispatch.
2. GREEN: write `incomplete.json` before cleanup returns failure.
3. GREEN: remove or avoid writing `incomplete.json` on successful reviews.
4. GREEN: catch `KeyboardInterrupt` after review directory creation but before
   provider dispatch, write `incomplete.json`, and print the review directory.
5. GREEN: catch `KeyboardInterrupt` or final artifact write failures during
   `metadata.json` / `synthesis.md` creation, mark the review incomplete, and
   print the review directory.
6. Docs: explain how to inspect incomplete review directories.

### Milestone 5: Review-Only Prompt Instruction

Goal: make review provider behavior explicit and low-risk.

Tasks:

1. RED: add prompt tests proving review-only instruction is present.
2. GREEN: add instruction to review prompt construction.
3. Docs: document when reviewers should not run commands and how future opt-in
   could work.

---

## Implementation Plan

1. Branch from current `main` after TRN-2017 is merged.
2. Add tests first for concurrency, progress logging, process group cleanup,
   incomplete markers, and prompt text.
3. Put the concurrency/process-management tests in a new module,
   `tests/test_codex_review_dispatch.py`, while keeping prompt/input-mode tests
   in `tests/test_codex_adapter.py` when they reuse existing helpers.
   Put `incomplete.json` orchestration tests in
   `tests/test_codex_review_dispatch.py`.
4. Implement provider dispatch as a small orchestration layer around existing
   `run_provider()` behavior.
5. Preserve provider health checks and review input collection before dispatch.
6. Preserve current artifact compatibility:
   - `metadata.providers` remains a list.
   - `metadata.results[]` entries keep `provider`, `returncode`, `raw`,
     `started_at`, and `finished_at`.
   - `raw/<provider>.txt` still contains stdout followed by optional
     `\n[stderr]\n`.
   - `synthesis.md` remains deterministic.
7. Add docs for progress logs, `incomplete.json`, and expected fast-review
   latency behavior.
8. Review the CHG and implementation with Trinity fast-review before PR.
9. After PR creation, follow COR-1615 for GitHub connector review and route
   actionable findings through COR-1612.

---

## Testing / Verification

Expected evidence before marking implementation complete:

- Focused pytest tests for concurrent dispatch with fake providers.
- Focused pytest tests for deterministic result ordering.
- Focused pytest tests for mixed provider success/failure behavior.
- Focused pytest tests for progress messages on stderr.
- Focused pytest tests for timeout cleanup of provider child processes.
- Focused pytest tests for incomplete marker creation and successful cleanup.
- Focused pytest tests for pre-dispatch interrupts after review directory
  creation.
- Focused pytest tests for late interrupts during final artifact writes.
- Focused pytest tests proving queued providers do not start after orchestration
  failure when `max_parallel_providers` is smaller than selected providers.
- Prompt test for review-only instruction.
- Config test for `config["review"]["max_parallel_providers"]`.
- Config validation tests for invalid parallelism values.
- Duplicate selected-provider validation tests for explicit `--providers` and
  legacy `review.default_providers`.
- `incomplete.json` schema assertions for status, review directory, selected
  providers, running providers, and cleanup map.
- `.venv/bin/pytest tests/test_codex_adapter.py -q`
- `.venv/bin/pytest tests/test_codex_compat.py -q`
- `.venv/bin/pytest tests/test_codex_review_dispatch.py -q`
- `make test`
- `make lint`
- `af validate --root .`
- `trinity doctor --preset fast-review`
- A low-risk `trinity review --preset fast-review --base main --head HEAD`
  smoke run showing providers start together.

---

## Impact Analysis

- **Systems affected:** `scripts/codex.py`, review artifact creation,
  `trinity review` runtime behavior, README/Codex skill docs, and tests.
- **Systems intentionally preserved:** preset resolution, provider health
  checks, prompt input modes, raw output paths, metadata compatibility, and
  synthesis format.
- **Downtime required:** No.
- **Backward compatibility:** Existing successful review artifacts remain
  readable. New artifacts may include additional progress/incomplete metadata,
  but existing top-level metadata keys must remain compatible.
- **Prompt behavior:** Review prompt content changes by adding review-only
  no-command guidance. This is intentional and applies to all `trinity review`
  input modes unless a future CHG adds an opt-out.
- **Main risks:** concurrency introduces race conditions, timeout cleanup can be
  platform-sensitive, progress logging may break scripts if written to stdout,
  prompt behavior may change reviewer habits, and process-group cleanup could
  terminate too broadly if scoped incorrectly.
- **Risk controls:** use stderr for progress, isolate provider process groups,
  keep shared artifact writes in the main process, add fake-provider tests for
  edge cases, and preserve deterministic output ordering.
- **Rollback plan:** revert dispatch/progress/cleanup changes and restore
  sequential `run_provider()` loop. Existing provider configs and artifacts do
  not require migration.

---

## Acceptance Criteria

- [ ] `fast-review` starts required providers concurrently.
- [ ] Wall-clock time for fake slow providers is closer to max latency than sum
      latency.
- [ ] Progress messages identify provider start and completion/failure/timeout.
- [ ] Timeout cleanup terminates provider child processes.
- [ ] Interrupted or failed partial reviews are marked incomplete.
- [ ] Successful reviews keep existing `metadata.json`, `raw/`, and
      `synthesis.md` compatibility.
- [ ] Review prompt includes review-only no-command guidance.
- [ ] Tests, lint, `af validate`, and Trinity fast-review pass.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-05 | Revised after second Trinity fast-review to define active `Popen` registry locking, independent provider failure semantics, cleanup ordering rationale, stderr handling, config validation, and incomplete-marker test scope | Codex |
| 2026-05-05 | Revised after Trinity fast-review to specify `incomplete.json`, interrupt-safe executor shutdown, 5-second process-group kill grace, POSIX scope, config/test locations, and prompt impact | Codex |
| 2026-05-05 | Initial CHG for issue #27 fast-review parallelism, progress, incomplete markers, process-group cleanup, and review-only prompt mode | Codex |

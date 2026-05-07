# CHG-2022: Wire Install-Sh Test Into Make Test

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Date:** 2026-05-07
**Requested by:** Frank (via GitHub issue #41 plan A)
**Implementer:** Claude Opus 4.7
**Priority:** Low
**Change Type:** Normal
**Related:** TRN-2020 (parent PRP), TRN-2021 (execution contract), TRN-1800, COR-1614, COR-1616, COR-1500

---

## What

Wire `tests/test_install_sh.sh` into the `make test` target so the install-path smoke test runs every cycle, and update `TRN-1800-REF-Evolution-Philosophy.md` §Behavior Baseline to reflect current truth.

This is slice A of the TRN-2020 / TRN-2021 multi-phase test-improvement contract.

---

## Why

`tests/test_install_sh.sh` already exists with ~10 hermetic cases (local `python3 -m http.server` against `mktemp -d` HOME, no network, no real `~/.claude/` impact). It catches the v2.0.0-class macOS-passes-Linux-fails parity bugs that the TRN-1801 evolve cycle exists to prevent. The file was last touched in commit `d1e4464` (claude-code provider, May 2026) and is **not** referenced by `Makefile`'s `test` target. No commit-history rationale explains the exclusion — it appears to be an oversight when the claude-code provider landed.

Two consequences worth fixing in one slice:

1. The install path is not regression-tested every cycle. Anyone touching `install.sh`, `providers/bin/*`, or the wrapper shell scripts has to remember to run `bash tests/test_install_sh.sh` manually. They usually don't.
2. `TRN-1800-REF-Evolution-Philosophy.md` §Behavior Baseline lists `pytest 63+ cases, shell tests/test_install_sh.sh 10+ cases, ...` as part of "what `make test` means" — but pytest is now 141, and `test_install_sh.sh` is not actually invoked by `make test`. The baseline doc is aspirational, not factual. Trinity panel review on the parent PLN (deepseek 2026-05-07, F2 + F3) flagged this; folding the correction into slice A closes the loop in one merge.

---

## Impact and Risk

**Impact:** Adds ~5 s wall-clock to `make test` (HTTP server bring-up + 10 cases). Existing `make test` baseline ~30 s → ~35 s. No new test code, no new dependencies, no new files in `tests/`.

**Risk:** Low (after PR review-driven scope expansion).

- ~~Port collision: `tests/test_install_sh.sh` hardcodes port 18742. Mitigation deferred to a follow-on.~~ Promoted to in-scope after PR #44 round 2 P2 from Codex bot. The test now allocates an OS-assigned port via `python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'` and probes the server root (not `/VERSION`, since T6 serves a directory that intentionally lacks VERSION). Fail-fast error message if the server never binds.
- Test brittleness: the test currently passes locally on macOS Darwin 25.4.0. CI is tag-only today, so this slice does not exercise Linux. The Linux parity check is implicit (test_install_sh.sh's own logic is the same regardless of OS), but slice B's optional CI workflow would close that gap explicitly.
- Reverse-side risk: if `test_install_sh.sh` itself has a flake or platform-specific bug that's been silent because nobody runs it, wiring it in surfaces the bug. That's a feature, not a regression — but it could turn slice A red on the first PR run. Mitigation: run the test locally before opening the PR; if it fails, fix the underlying issue or revert this slice and open a separate fix-first PR.

---

## Implementation Plan

Two file edits, one commit:

1. **`Makefile`** — append `bash tests/test_install_sh.sh` to the `test:` target after `test_release_workflow.sh`. Keep `test_make_bump.sh` last (matches existing ordering convention).

2. **`rules/TRN-1800-REF-Evolution-Philosophy.md`** §Behavior Baseline (line ~22) — update test case counts and remove the aspirational claim:
   - `pytest 63+ cases` → `pytest 141+ cases` (current actual)
   - `tests/test_release_workflow.sh 53+ cases` → `tests/test_release_workflow.sh 105+ cases` (current actual)
   - `shell tests/test_install_sh.sh 10+ cases` stays as-is (becomes accurate post-merge)

No regeneration required. `make verify-built` only triggers when `providers/_base/` changes, which this slice does not touch.

---

## Test / BDD / Coverage Expectations

- New behavior under test: `tests/test_install_sh.sh` runs as part of `make test`. The 10 PASS markers (T1 happy path, T2-T10 various edge cases — see file head for specifics) all execute and print PASS.
- No new assertions in this slice. The slice is "wire existing tests, don't add new ones."
- No coverage delta expected. `test_install_sh.sh` is shell, not Python; coverage tooling (slice B) doesn't apply.

---

## Acceptance

- `make test` on `main` post-merge invokes `tests/test_install_sh.sh` and prints its 10 PASS markers.
- `make test` exits 0.
- `make test` wall-clock between 30 s and 50 s (allows for HTTP server bring-up jitter).
- TRN-1800:22 baseline numbers match the actual test gate set on `main`.
- `af validate --root .` reports 0 issues.

---

## Validation Commands

```bash
make verify-built          # passes (no providers/_base/ changes)
make test                  # passes; output includes "PASS: T1: ...", "PASS: T2: ...", etc.
make lint                  # ruff clean
af validate --root .       # 102+ documents, 0 issues
```

Locally executed before commit on `codex/trn-2022-wire-install-sh`:

```
$ make verify-built
build_providers --check: OK (committed matches generated)

$ make test
... (existing 141 pytest + 113 build_providers + 105 release_workflow PASS) ...
bash tests/test_install_sh.sh
PASS: T1: happy path — all provider files installed
PASS: T2: idempotent — second run succeeds
PASS: T3: TRINITY_VERSION=1.0.0 with TRINITY_BASE_URL override — exit 0
PASS: T3b: URL construction uses v-prefixed tag (v1.0.0)
PASS: T4: leading v in TRINITY_VERSION stripped, URL correct
PASS: T5: destination dirs created
PASS: T6: 404 exits non-zero with 'failed downloading' in stderr
PASS: T7: success output contains version 3.2.0
PASS: T9: bin scripts installed + executable; wrapper provider cli use absolute paths
PASS: T11: legacy wrapper cli overwritten; glm migrated to current default
Results: 10 passed, 0 failed

$ make lint
All checks passed!
17 files already formatted

$ af validate --root .
103 documents checked, 0 issues found.
```

---

## Out of Scope

- ~~Reassigning the local-server port from 18742 to OS-allocated.~~ Promoted to in-scope mid-flight (see Risk).
- Adding Linux-side CI for the install path (slice B's optional workflow handles that).
- Updating any other section of TRN-1800 beyond the §Behavior Baseline counts.
- Coverage measurement (slice B).
- BDD scenarios for the install flow (out of slice C v1 scope per parent PRP).

---

## Authority

This CHG is subordinate to TRN-2021-PLN §4 (slice A definition). Operator defaults from TRN-2021-PLN §2 apply: branch `codex/trn-2022-wire-install-sh`, identity `ryosaeba1985`, plan-review skipped (parent PRP review covered strategy), code-review delegated to PR review loop.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft of slice A delivery contract | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 2 P2 from Codex bot escalated the deferred port-collision risk to a now-blocker because making the test part of `make test` exposed it. Scope expanded: switched `tests/test_install_sh.sh` to OS-allocated port + universal-readiness probe + fail-fast. Verified by reproducing the bot's pre-bind-18742 scenario; both runs (clean + squatted) produce 10 PASS markers. | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 3 P2 from Codex bot — `set -e` + a failing install regression aborts the test before `_stop_server`, leaking the background `python3 -m http.server`. Fix: install `trap '_stop_server' EXIT INT TERM` inside `_start_server`; make `_stop_server` idempotent (`unset SERVER_PID` after kill). Verified by injecting `false` between `_start_server` and the install invocation; captured the running http.server PID via stderr probe; confirmed `kill -0 $PID` after script exit returns non-zero (PID was reaped by the trap). | Claude Opus 4.7 |
| 2026-05-07 | PR #44 round 5 P2 from Codex bot — `python3 -m http.server` defaults to binding 0.0.0.0 (all interfaces), exposing the repo to any host on the local network during the test. Fix: add `--bind 127.0.0.1` to the http.server invocation. Verified via `lsof -i -P -n` while the test was running — server now listed as `127.0.0.1:<port> (LISTEN)`, no longer `*:<port>`. | Claude Opus 4.7 |
| 2026-05-08 | Status reconciled to Completed; merged in PR #44 at `07e1c14` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

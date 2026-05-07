# CHG-2025: Switch Install-Sh Test To File URL

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Completed
**Date:** 2026-05-07
**Requested by:** Frank (via GitHub issue #53)
**Implementer:** Claude Opus 4.7
**Priority:** Low
**Change Type:** Normal
**Related:** TRN-2020 (parent PRP, deferred-follow-on entry), TRN-2021 (execution contract §10), TRN-2022 (slice A — the http.server hardening this slice un-does), COR-1616, COR-1500, COR-1602

---

## What

Replace the local-HTTP-server fixture in `tests/test_install_sh.sh` with `file://` URLs. Removes `_start_server` / `_stop_server` / port allocation / readiness loop / `EXIT/INT/TERM` trap / `--bind 127.0.0.1` from the test (~30 lines), and replaces **eight** `_start_server` call sites with inline `TRINITY_BASE_URL=file://${REPO_DIR}` env-var setting.

This is a standalone single-slice CHG, not part of any execution contract. The TRN-2020 contract closed cleanly; TRN-2025 is one of the deferred-follow-on items recorded in TRN-2021-PLN §10.

---

## Why

`tests/test_install_sh.sh` validates that `install.sh` correctly downloads ~12 files into a fake `~/.claude/`. The current fixture starts a local `python3 -m http.server` on `127.0.0.1:<random-port>`, points `TRINITY_BASE_URL` at it, runs `install.sh` against a `mktemp -d` fake `HOME`, then kills the server.

This single fixture caused **three P2 review findings during PR #44** (slice A of TRN-2020):

| Round | Finding | Fix shipped in slice A |
|-------|---------|------------------------|
| R2 | Hardcoded port 18742 collides with anything else listening | Switched to OS-allocated port via `socket.bind(("127.0.0.1",0))` |
| R3 | `set -e` + failing install → script aborts before `_stop_server` → http.server leaked as zombie process | Added `trap '_stop_server' EXIT INT TERM`, made `_stop_server` idempotent |
| R5a | `python3 -m http.server` defaults to binding `0.0.0.0` → exposes repo on shared networks | Added `--bind 127.0.0.1` |

Each fix was correct, but they all defended against complexity that wouldn't exist if the test didn't run an HTTP server at all. `curl` natively supports `file://` URLs on every platform we care about; `install.sh` already uses only `curl -fsSL <url> -o <dest>` with exit-code checking. The switch is correctness-preserving and removes the entire fragility surface.

A Trinity multi-model panel decision matrix on 2026-05-07 (glm + gemini + deepseek) returned unanimous Option A (file:// URLs) at 8.8 weighted vs B (PATH curl wrapper) at 5.8 vs C (test seam in install.sh) at 6.6.

Pre-condition `grep` on `install.sh` (the panel's flip trigger) verified clean — no scheme assertions, no `http_code` parsing, no `--write-out`. The default `BASE_URL` uses `https://` but `TRINITY_BASE_URL` overrides it cleanly at line 18-19; no other code path requires the URL be HTTP.

---

## Impact and Risk

**Impact:**

- One file changed: `tests/test_install_sh.sh` (~−30 lines net).
- One file added: this CHG (~150 lines).
- No changes to `install.sh`, `scripts/`, `Makefile`, `providers/`, `.github/workflows/`.
- Test wall-clock: per-case overhead drops from "spawn http.server + readiness poll + cleanup" to "set env var". Informal estimate: ~5–10s saved on macOS CI across the 10 cases. Not a hard SLA.
- The slice A fixture-hardening commits (`03af408`, `5bc71c5`, `a1d3f0c`) become partially deletable code; their commit messages remain as the historical record of why the http.server pattern was problematic.

**Risk:** Low.

- **`curl` `file://` support**: standard on every platform we ship to (macOS, ubuntu-latest CI, every dev machine that has curl built with the `file` protocol — i.e. nearly all). No `--protocols file` flag needed; `file` is in the default protocol set.
- **`install.sh` URL-scheme assumption**: pre-condition `grep` verified clean (no scheme regex, no `http_code` checks, no redirect-following logic that file:// can't simulate). Re-grep before commit to defend against drift.
- **T6 (404 / "missing file" path)**: the test serves from a `MISSING_DIR` that intentionally lacks `providers/codex.md`. With http.server, curl gets HTTP 404; with file://, curl gets exit-code 37 ("Couldn't open file"). `install.sh` only checks `curl`'s non-zero exit, not the specific error code, so the test assertion (`stderr` contains "failed downloading") still holds — `install.sh`'s wrapper message is the same. Verify by running T6 specifically before commit.
- **Concurrent test runs**: with http.server, two parallel test runs would have raced on port 18742 (slice A R2 fixed by OS-allocation). With file://, concurrency is trivially safe — each test has its own `${REPO_DIR}` and `${FAKE_HOME}`.
- **Race that motivated slice C R1's settle delay**: `test_review_sigint_writes_incomplete_json_and_cleans_up` won't be affected — that race involved coverage shim activation in subprocess Python children, not http.server lifetime.
- **Space-in-path edge case** (panel advisory, glm + gemini + deepseek converged): `file://${REPO_DIR}` substitutes the absolute path verbatim into the URL. CI runners (`ubuntu-latest`, `macos-latest`) and `mktemp -d` paths don't contain spaces or special characters, but a developer's clone under a path like `/Users/frank/My Projects/trinity` would break. The implementation adds a one-line sanity check at the top of the test script that fails fast with a clear error if `${REPO_DIR}` contains characters the URL spec rejects (`[[:space:]]` or `?`/`#`). Existing http-URL fixture had the identical exposure, so this is a new defense, not a new regression.

---

## Implementation Plan

One file change, one commit:

1. **`tests/test_install_sh.sh`**

   Delete:
   - `_start_server()` function (allocates port, starts http.server, waits for readiness, installs EXIT/INT/TERM trap, fail-fast on bind failure) — ~25 lines.
   - `_stop_server()` function (kill + wait + unset SERVER_PID; idempotent) — ~7 lines.

   Replace each `_start_server` call site with inline env-var setting on the `bash "${INSTALL_SCRIPT}"` invocation:
   ```sh
   TRINITY_BASE_URL="file://<dir>" bash "${INSTALL_SCRIPT}" ...
   ```

   Delete each `_stop_server` call site (no longer needed).

   Eight `_start_server` call sites total. Per-case `TRINITY_BASE_URL` becomes:
   - **`file://${REPO_DIR}`**: T1 (line 66), T2 (line 111), T3 (line 126), T5 (line 169), T7 (line 217), T9 (line 234), T11 (line 293) — 7 sites
   - **`file://${MISSING_DIR}`**: T6 (line 194) — 1 site, intentionally pointing at a directory missing `providers/codex.md` to exercise the failure path

   **T3b and T4 do NOT call `_start_server`** and do not set `TRINITY_BASE_URL` — they're URL-construction tests that exercise install.sh's BASE_URL composition logic with `TRINITY_VERSION` set, no server needed. Both stay unchanged.

   Update header comment on line 5 of the test file: `# Requires: python3 (for local HTTP server), bash, curl` → `# Requires: bash, curl` (python3 no longer needed once the http.server fixture is gone).

2. **No changes** to:
   - `install.sh` — its `${BASE_URL}` already accepts any URL scheme via `TRINITY_BASE_URL`
   - `Makefile` `test` target — still calls `bash tests/test_install_sh.sh`
   - `make test` PASS count — same 10 markers, no new tests, no removed tests
   - Coverage gate — slice B's coverage shim activates on Python child processes; this slice doesn't change Python subprocess behavior

---

## Test / BDD / Coverage Expectations

- **Existing**: `bash tests/test_install_sh.sh` produces 10 PASS markers (T1, T2, T3, T3b, T4, T5, T6, T7, T9, T11).
- **After this slice**: same 10 PASS markers, no regressions, no new tests added. Output should be identical except for any timing differences (markedly faster on macOS CI).
- **Coverage**: no change. This slice doesn't touch Python code; coverage of `scripts/` + `dev/` stays at the slice-C baseline (TOTAL 83%).

---

## Acceptance

- `tests/test_install_sh.sh` no longer references `python3 -m http.server` (`grep -c "python3 -m http.server" tests/test_install_sh.sh` returns 0).
- `tests/test_install_sh.sh` no longer defines `_start_server` or `_stop_server` (`grep -cE "_start_server|_stop_server" tests/test_install_sh.sh` returns 0).
- T3b and T4 are unchanged (panel review confirmed they don't call `_start_server`); their PASS markers still produce.
- All 10 PASS markers still produce: `bash tests/test_install_sh.sh | tail -2` ends with `Results: 10 passed, 0 failed`.
- T6 stderr still contains `failed downloading` (panel verified `install.sh`'s `set -eE` + `trap '...' ERR` produces identical stderr for curl exit 22 and curl exit 37; T6 assertion is exit-code-agnostic).
- `make verify-built && make test && make lint && af validate --root .` all green.
- `make coverage` exits 0 with TOTAL ≥ 80% (no regression vs slice C baseline 83%).
- Cross-platform CI (`.github/workflows/test.yml`, slice B): both ubuntu-latest and macos-latest legs green on the PR.

---

## Validation Commands

```bash
make verify-built         # passes
make test                 # 141 + 113 + 105 + 10 + 2 + 13 BDD PASS, no regressions
make lint                 # ruff clean
af validate --root .      # 0 issues
make coverage             # TOTAL ≥ 80%
```

Pre-commit specific check:

```bash
grep -c "python3 -m http.server" tests/test_install_sh.sh    # expected: 0
grep -cE "_start_server|_stop_server" tests/test_install_sh.sh # expected: 0
bash tests/test_install_sh.sh | tail -2                       # expected: "Results: 10 passed, 0 failed"
```

Locally executed on `codex/trn-2025-file-url`:

```
$ grep -c "python3 -m http.server" tests/test_install_sh.sh
0

$ grep -cE "_start_server|_stop_server" tests/test_install_sh.sh
0

$ grep -c "TRINITY_BASE_URL=\"file://" tests/test_install_sh.sh
9   # 8 _start_server replacements + 1 second-run inside T2's idempotency

$ bash tests/test_install_sh.sh | tail -2
Results: 10 passed, 0 failed

$ make verify-built
build_providers --check: OK (committed matches generated)

$ make test    # 141 + 113 + 105 + 10 + 2 + 13 BDD all PASS, no regressions

$ make lint
All checks passed!  21 files already formatted

$ af validate --root .
106 documents checked, 0 issues found.

$ make coverage
TOTAL  1521  262  83%   # unchanged from slice C baseline; gate 80% passes
```

T6 verified empirically: under file://, curl returns exit 37 ("Couldn't open file") instead of HTTP 404 (curl exit 22). install.sh's `set -eE` + `trap '...failed downloading ${CURRENT_FILE}' ERR` produces identical "trinity-install: failed downloading providers/codex.md" stderr in both cases. T6's substring assertion (`grep -q "failed downloading"`) is exit-code-agnostic and holds.

---

## Out of Scope

- Other test files. This slice touches only `tests/test_install_sh.sh`.
- `install.sh` itself. No production-code changes.
- Coverage shim, BDD scenarios, slice B/C infrastructure. All untouched.
- Migrating to a different test-fixture pattern (mocking, dependency injection, etc.) — option B and C from the panel were rejected for fragility / production-coupling reasons.
- Concurrent-test orchestration. Each test case still runs serially within `bash tests/test_install_sh.sh`.

---

## Authority

This CHG is a standalone single-slice delivery, not part of any execution contract. It implements one of the deferred-follow-on items recorded in TRN-2021-PLN §10. Operator defaults from earlier sessions still apply: identity `ryosaeba1985` for GitHub-visible writes, branch `codex/trn-2025-file-url`, code-review delegated to PR-review loop (Codex GitHub App bot is the gate).

Plan-review: per operator instruction (2026-05-07), this CHG goes through Trinity multi-model panel review (`review` preset: glm + gemini + deepseek) before implementation begins.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-07 | Initial draft per COR-1616 step 3; references panel decision matrix from earlier session and pre-condition `grep` on `install.sh` | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel plan-review (3 Agent dispatches: glm PASS-with-advisories, gemini PASS-with-advisories, deepseek FAIL → trivially fixable). Adopted: Blocking finding (call-site count `six` → `eight`, T3b/T4 removed from per-case list because they don't call `_start_server`), advisory #1 (space-in-path sanity check added to §Risk + implementation), advisory #2 (Acceptance lifted explicit `Results: 10 passed, 0 failed` assertion + T6 stderr assertion), advisory #3 (header-comment update on line 5 added to §Implementation Plan). T6 file:// 404 semantics independently verified by all 3 agents via local curl test + `install.sh` ERR-trap inspection — confirmed safe. | Claude Opus 4.7 |
| 2026-05-08 | Status reconciled to Completed; merged in PR #56 at `b1ab34a` (TRN-3019 backlog reconciliation). | Claude Opus 4.7 |

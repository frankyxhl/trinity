# CHG-2028: Add Trinity Status Latest Command

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank (via GitHub issue #35; thematic placeholder TRN-3018)
**Implementer:** Claude Opus 4.7
**Priority:** Low
**Change Type:** Normal
**Related:** TRN-2010 (PRP that introduced `trinity review`), TRN-2014 (added `trinity doctor`), TRN-2019 (added `incomplete.json`), COR-1616, COR-1500

---

## What

Add a new CLI subcommand `trinity status --latest` to `scripts/codex.py`. Reads the most recent review directory under `.trinity/reviews/` (sorted by timestamp directory name), parses `metadata.json` and presence of `synthesis.md` / `incomplete.json`, and prints a one-screen summary.

Issue #35 carries the thematic identifier "TRN-3018" in its title. The implementing CHG uses the next available sequential TRN-2xxx CHG ACID (TRN-2028) per project convention; the two identifiers refer to the same work item.

---

## Why

`trinity review` writes a structured set of artifacts under `.trinity/reviews/<timestamp>-<scope>/`:

- `metadata.json` — providers, preset, input mode, per-provider start/finish times + return codes
- `prompt.md` — the rendered prompt that was sent to providers
- `raw/<provider>.txt` — each provider's verbatim response
- `synthesis.md` — deterministic top-level synthesis with per-provider PASS/FAIL summary
- `incomplete.json` — only present if the review was interrupted (SIGINT, timeout cap, etc.)

After running a review, users currently have to:

1. `ls -t .trinity/reviews/ | head -1` to find the latest dir
2. `cat .trinity/reviews/<dir>/metadata.json | jq '.results[] | {provider, returncode}'` to see provider status
3. `ls .trinity/reviews/<dir>/synthesis.md .trinity/reviews/<dir>/incomplete.json 2>/dev/null` to see completion state
4. `tail` raw outputs to read findings

Steps 1–3 are repetitive; a single `trinity status --latest` command with a one-screen summary captures everything except step 4 (raw findings, which are inherently free-form). This is a developer-experience win, not a runtime change.

---

## Impact and Risk

**Impact:**

- One new CLI subcommand: `trinity status [--latest]`. `--latest` is the only flag in v1; future flags (e.g. `--review-dir <path>` to inspect a specific dir, `--json` for machine-readable output) are out of scope here.
- Adds ~50–80 lines to `scripts/codex.py` (one new `cmd_status` function + parser + helpers for elapsed-time formatting and "ago" rendering).
- Adds a unit test file or section (~80–120 lines): fake review directories with various states (clean run, partial, interrupted, no synthesis, no metadata).
- No changes to `trinity review`, `trinity doctor`, `trinity init-config` — purely additive.

**Risk:** Low.

- **Read-only operation.** `cmd_status` reads existing files; never writes, deletes, or invokes providers. Cannot break a running review or corrupt any state.
- **Empty `.trinity/reviews/` directory.** The command exits with rc=1 and prints a clear "no reviews found" message to stderr — matching `trinity doctor`'s convention of non-zero on missing-state-the-user-asked-about.
- **Malformed `metadata.json`.** A user could have manually edited a metadata file or had an aborted write. The command should report the problem without crashing — exits rc=1 with a clear error naming the bad file.
- **In-progress review.** A review currently writing `metadata.json` could be observed mid-write (truncated JSON), or the review directory could exist before any metadata is written. The command must handle both: missing metadata.json and partial-data per-provider entries (missing `started_at` / `finished_at` / `returncode` fields). Both cases exit rc=1 with a clear "review in progress or no metadata" message.
- **Timestamp directory format.** `make_review_dir` (in `scripts/codex.py`) produces `<YYYYMMDD-HHMMSS>-<scope-slug>` (compact ISO, no internal dashes between date and time fields). Lexicographic sort on directory names yields chronological order because the timestamp prefix is fixed-width digits.
- **Cross-platform `os.path` vs `pathlib`.** Match the existing `scripts/codex.py` style (uses `pathlib.Path` throughout). No new portability concerns.

---

## Implementation Plan

Three files touched, one commit:

1. **`scripts/codex.py`**

   Add a new `cmd_status(args)` function near the existing `cmd_review` / `cmd_doctor` / `cmd_init_config`. The function:

   ```python
   def cmd_status(args):
       reviews_dir = Path(args.root) / ".trinity" / "reviews"
       if not reviews_dir.is_dir():
           print(f"trinity: no reviews dir at {reviews_dir}", file=sys.stderr)
           return 1
       # latest dir by lexicographic sort — timestamp prefix is fixed-width
       # %Y%m%d-%H%M%S so lex order == chronological order.
       candidates = sorted(
           [d for d in reviews_dir.iterdir() if d.is_dir()],
           reverse=True,
       )
       if not candidates:
           print(f"trinity: no reviews under {reviews_dir}", file=sys.stderr)
           return 1
       latest = candidates[0]
       return _print_review_summary(latest)
   ```

   Plus a `_print_review_summary(review_dir: Path) -> int` helper that:
   - Loads `metadata.json` via `json.loads(path.read_text())` (matches the existing `scripts/codex.py:114` pattern; avoids `json.load(open(...))` fd-leak on parse error). If missing → prints "review in progress or no metadata" to stderr and returns rc=1. If malformed → prints "malformed metadata: <error>" to stderr and returns rc=1.
   - Reads top-level metadata fields **defensively**: `metadata.get("scope", "?")`, `metadata.get("input", {}).get("mode", "?")`, `metadata.get("preset", {}).get("resolved", "?")`, `metadata.get("preset", {}).get("skipped_optional_providers", [])`, `metadata.get("results", [])`. Any absent key renders as `?`/empty rather than crashing — covers pre-TRN-2019 metadata files that may lack newer fields.
   - For each `results[]` entry, defensively extracts `returncode` / `started_at` / `finished_at` — a missing key renders as `?` and skips elapsed computation for that provider rather than crashing.
   - Computes elapsed via `(datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()`, **clamped to `max(0, elapsed)`**. Defends against fall-back DST transitions producing a negative delta when both timestamps are naive local time (per `dt.datetime.now().isoformat(...)` at `scripts/codex.py:949`).
   - Marks elapsed as `(timeout)` iff `returncode == 124` (deterministic, not a heuristic threshold).
   - Renders the format shown in #35's user scenario.
   - Detects `synthesis.md` / `incomplete.json` presence and surfaces it. When `incomplete.json` is present, surfaces its `status` field — the allowed values are written by `scripts/codex.py`'s own incomplete-marker writer (currently `interrupted` and `failed`; surfaced verbatim with no whitelist).
   - Reports skipped optional providers from `metadata.preset.skipped_optional_providers` (each entry has `provider` + `reason` per the actual metadata schema; both fields are rendered).
   - Closes with a `Status: completed | interrupted | partial` line. `interrupted` if `incomplete.json` exists; `partial` if any provider has `returncode != 0` but no `incomplete.json`; `completed` otherwise.
   - Returns rc=0 on a clean read; rc=1 on missing/malformed metadata.

   Plus parser registration in `build_parser()` and **manual dispatch** in `main()` (matches the existing `if args.command == "review": return cmd_review(args)` pattern — `set_defaults(func=)` would silently fail because `main()` doesn't read it):

   ```python
   # in build_parser(), after the review subparser:
   status = subparsers.add_parser("status")
   status.add_argument("--root", default=".")
   status.add_argument("--latest", action="store_true",
                       help="Explicitly request the latest review (default behavior; "
                            "reserved for forward-compatibility with future --all / "
                            "--review-dir flags).")

   # in main(), add a new dispatch line:
   if args.command == "status":
       return cmd_status(args)
   ```

   `--latest` defaults to implicit. Bare `trinity status` summarizes the latest review (panel-unanimous CLI design call). `--latest` is accepted as an explicit alias for self-documentation and scriptability; it is **not required**. When future modes arrive (`--all`, `--review-dir <path>`), they live in a mutually-exclusive argparse group with `--latest`; "no flag" continues to mean "latest."

2. **`tests/test_status_latest.py`** (new file)

   Pytest cases covering:

   - **T1**: clean review dir → exits 0, output contains "Status: completed", lists all providers with `rc=0`.
   - **T2**: review with one timed-out provider (`returncode=124`) → output renders the non-zero rc and appends `(timeout)` to elapsed iff `returncode == 124` (deterministic rule, not a threshold).
   - **T3**: review with `incomplete.json` present → "Status: interrupted" line; the `incomplete.json`'s own `status` field is surfaced (e.g. `interrupted`, `failed`, etc. per scripts/codex.py's own taxonomy).
   - **T4**: review with no `synthesis.md` → "Synthesis: missing".
   - **T5**: malformed `metadata.json` (truncated JSON) → exits rc=1 with a clear error mentioning the bad file.
   - **T6**: empty `.trinity/reviews/` → exits rc=1 with "no reviews found".
   - **T7**: missing `.trinity/reviews/` entirely → exits rc=1 with "no reviews dir".
   - **T8**: skipped optional providers in metadata → output lists each entry with its `{provider, reason}` (both fields, since the actual metadata schema has both).
   - **T9** (panel-added — race / partial-data): review dir exists but `metadata.json` missing entirely (review still in progress) → exits rc=1 with "review in progress or no metadata"; alternative variant — metadata exists but a `results[]` entry has no `started_at` / `finished_at` / `returncode` keys → renders `?` for those fields and does not crash.

3. **`rules/TRN-0000-REF-Document-Index.md`** — regenerated by `af index`.

No changes to `Makefile`, `.github/workflows/`, `install.sh`, `providers/`, `SKILL.md`, or any other CHG.

---

## Test / BDD / Coverage Expectations

- 9 new pytest cases (T1–T9, with T9 added per panel review for the in-progress / partial-data race) added to `tests/test_status_latest.py`. Total `make test` pytest count grows from 154 to 163.
- Coverage of `scripts/codex.py` should rise modestly (1–3 pt) as the new `cmd_status` + helper functions are exercised.
- No BDD scenario added in this slice — `trinity status --latest` is small CLI surface; the unit tests cover its observable behavior fully. A BDD scenario could be added as a follow-on if the command grows.

---

## Acceptance

- `trinity status --latest` exits 0 and prints a one-screen summary when at least one review exists in `.trinity/reviews/`.
- Output includes: latest review dir path, `metadata.scope`, `metadata.input.mode`, `metadata.preset.resolved` (preset name), per-provider rc + elapsed, synthesis presence, incomplete-marker presence (with its own `status` field surfaced), skipped optional providers list with reasons.
- All 9 pytest cases (T1–T9) pass.
- `trinity status` (no flag) and `trinity status --latest` produce identical output.
- `make verify-built && make test && make lint && af validate --root .` all green.
- `make coverage` exits 0 with TOTAL ≥ 80% (no regression vs current baseline).
- Manual smoke: running `.venv/bin/python3 scripts/codex.py status --latest` against the actual `.trinity/reviews/` on `main` produces a coherent output.

---

## Validation Commands

```bash
make verify-built
make test
make lint
af validate --root .
make coverage

# Manual smoke (run after implementing):
.venv/bin/python3 scripts/codex.py status --latest
```

Locally executed on `codex/trn-3018-status-latest`:

```
$ .venv/bin/pytest tests/test_status_latest.py -v
12 passed in 0.69s   # T1-T9 from CHG + T9b split + T10 (alignment) + T11 (empty-results)

$ make verify-built
build_providers --check: OK (committed matches generated)

$ make test
... 166 pytest passed (was 154 before) + 113 + 105 + 10 + 2 shell PASS ...

$ make coverage
TOTAL  1623  273  83%   # codex.py 82% → 83% (covers cmd_status + helpers)

$ make lint
All checks passed!  22 files already formatted

$ af validate --root .
107 documents checked, 0 issues found.

$ .venv/bin/python3 scripts/codex.py status     # smoke against real .trinity/reviews/
Latest review: .trinity/reviews/20260508-...  (started 1h ago)
  Scope: rules/   Mode: working-tree   Preset: review
  Providers:
    glm        ✓ rc=0     elapsed 3m 08s
    gemini     ✗ rc=124   elapsed 6m 00s (timeout)
    deepseek   ✓ rc=0     elapsed 3m 58s
  Skipped optional: codex (missing config), claude-code (missing config)
  Synthesis: ✓ synthesis.md
  Status: partial
```

---

## Out of Scope

- **Live streaming / detached background review mode** (per #35).
- **PASS/FIX semantic parsing** of raw provider outputs (per #35) — that's #55 (Trinity rich summary) territory; this slice only reports structural state (rc, presence of files, timing).
- **Provider execution** (per #35) — `cmd_status` is read-only.
- **`--review-dir <path>` flag** for inspecting a non-latest review — future enhancement, defer.
- **`--json` output mode** for machine consumers — future enhancement, defer.
- **Color / TTY output** — text only in v1.
- **Status across multiple historical reviews** (`--all`, `--last N`) — future.

---

## Authority

Standalone single-slice CHG, not part of any execution contract. Operator defaults from prior sessions: identity `ryosaeba1985` for GitHub-visible writes, branch `codex/trn-3018-status-latest`, plan-review via Trinity panel (review preset: glm + gemini + deepseek), code-review via single-provider GLM (slice is small, no architectural ambiguity remains after plan-review).

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3 | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel plan-review round 1 (3 Agent dispatches: glm PASS-with-advisories + 2 Blocking, gemini PASS-with-advisories, deepseek PASS-with-advisories). Adopted: glm B1 (manual `if args.command == "status":` dispatch in `main()`, not `set_defaults(func=)` — verified `main()` doesn't call `args.func`); glm B2 + unanimous CLI design call (make `--latest` implicit default; bare `trinity status` shows latest); timestamp format wording corrected (`%Y%m%d-%H%M%S-<scope>`, no internal dashes); `metadata.input.mode` location clarified in §Acceptance; T9 added for in-progress race + partial-data per-provider entries; exit-code policy locked at rc=1 for missing reviews dir / no reviews / malformed metadata. Skipped: glm A4 (--providers ad-hoc test — orchestration-side, not status-command-side); glm A5 (empty results list test — overlaps T5); deepseek A3 (T8 reasons claim — actually correct; metadata schema includes `reason` field); deepseek A5 (T2 rc=124 brittleness — fixture controls value, cosmetic). | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel plan-review round 2 (4 Agent dispatches incl. codex). Scores: glm 9.2, gemini 10.0, deepseek 9.3, codex 9.1 (mean 9.4); all PASS at the 9.0 threshold. Adopted advisory tightenings (none blocking, all minor): T2 timeout marker pinned to deterministic `returncode == 124` (glm + deepseek); incomplete.json `status` field surfaced verbatim with reference to `scripts/codex.py`'s incomplete-marker writer taxonomy (deepseek); elapsed-time computation clamped to `max(0, ...)` to defend against DST fall-back negative-delta on naive-local-ISO timestamps (codex); `_print_review_summary` reads top-level metadata fields via defensive `.get()` to handle pre-TRN-2019 metadata that may lack newer keys (codex); `json.loads(path.read_text())` instead of `json.load(open(...))` to match existing `scripts/codex.py:114` pattern + avoid fd-leak on parse error (codex); §Acceptance now references `metadata.scope` explicitly with field path (glm). | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel **code-review** round 1 (4 Agent dispatches): glm 9.0, gemini 8.7 (BLOCKING — `{name:10s}` truncates `claude-code`/11 chars), deepseek 9.0, codex 9.1. Adopted: dynamic `name_width = max([10] + [len(r.get("provider", "?")) for r in results])` (gemini's BLOCKING + glm/deepseek alignment advisory); empty `results: []` renders `Status: unknown (no results)` (glm + deepseek A1); missing `returncode` (None) counts as `partial` not `completed` to match the visual ✗ marker (codex A1); T9b assertion regex-tightened to bare `?` rendering for both rc and elapsed columns (codex A2); T10 added — regression test asserting ✓-marker columns align across glm/claude-code/openrouter/deepseek; T11 added — regression test asserting empty-results path renders `Status: unknown`. Test count grows from 10 to 12. | Claude Opus 4.7 |
| 2026-05-08 | Trinity panel **code-review** round 2 (4 Agent dispatches, post-fix). Scores: glm 9.3, gemini 9.3 (was 8.7; BLOCKING resolved + T10 empirically verified to catch the regression), deepseek 9.3, codex 9.3 (mean 9.3); **all 4 PASS individually at the 9.0 gate**. Adopted: gemini A1 (`name_width` default `""` → `"?"` to match print-loop default; 1-char column drift fix); codex round-2 defensive advisory (`_format_elapsed` subtraction `(f - s)` moved inside the same `try` to honor the "returns None if unparseable" contract on mixed naive/offset-aware ISO timestamps — defensive, no current-writer risk since `timestamp()` emits naive only). Status: Proposed → Approved. | Claude Opus 4.7 |
| 2026-05-08 | PR #60 round 1 from Codex GitHub App bot — caught a **functional bug** the 4-provider Trinity panel reviews missed: when `cmd_review` is interrupted (`KeyboardInterrupt` / `ReviewInterrupted` / `ReviewOrchestrationError`), it writes `incomplete.json` from its handlers BEFORE the `metadata.json` write at line 1365 ever happens. So an interrupted review directory has `incomplete.json` AND NO `metadata.json` — and my code bailed with "no metadata" exactly when the user most needs to summarize the artifact. Fix: split `_print_review_summary` to detect the "incomplete-only" case and render a dedicated summary from `incomplete.json` alone (status, timestamp, providers_selected/started/running_at_cleanup, cleanup, optional message). Added T12 (interrupted) + T12b (failed with message) regression tests. The Trinity panel chain missed this because the panels reviewed the diff in isolation; the bot caught it by tracing the actual `cmd_review` interrupt-handler flow. Lesson: future code-review prompts should explicitly ask agents to trace caller flows, not just diff semantics. | Claude Opus 4.7 |
| 2026-05-08 | PR #60 round 2 from Codex GitHub App bot — caught a **second schema-mismatch bug** in the round-1 fix's helper itself: `cleanup_active_processes` (scripts/codex.py:1050) writes per-provider cleanup payloads as `{"pid": ..., "result": "terminated"\|"killed"\|"kill_timeout"}`, but my `_print_incomplete_only_summary` was reading `info.get("status", "?")` — wrong field name, always renders `?` instead of the actual cleanup outcome. Fix: read `result` not `status`. Added T12c regression test asserting all three outcome values (terminated/killed/kill_timeout) render verbatim, plus negative assertions that none of them render as `?`. Updated T12's fixture to use the correct schema. Same lesson as round 1: the panel chain didn't read the writer's actual schema; the bot did. Test count grows from 14 to 15. | Claude Opus 4.7 |
| 2026-05-08 | PR #60 round 3 from Codex GitHub App bot — caught a **third caller-flow bug**: `cmd_status` used `args.root` directly without resolving via `resolve_root` / `resolve_health_root` like the other subcommands do. Running `trinity status` from a subdirectory (e.g. `scripts/`) builds `<subdir>/.trinity/reviews` instead of the repo-root `.trinity/reviews/` where `cmd_review` actually writes artifacts. Fix: call `resolve_health_root(args.root)` to get the git top-level (with non-git fallback), matching `cmd_doctor`'s pattern. Added T13 regression test that creates a real git repo, places a review at the top, runs `trinity status --root .` from a subdirectory, and asserts it finds the top-level review. Test count grows from 15 to 16. **Three consecutive bot findings on caller-flow / sibling-code mismatches confirms a structural gap in my code-review prompts** — they ask agents to review the diff but don't ask them to read writer functions or sibling subcommands. Concrete improvement queued for next CHG: add "trace caller flows + read writer schemas + compare to sibling subcommand patterns" to the code-review prompt template. | Claude Opus 4.7 |

# CHG-3048: Replace install.py Three Hand-Rolled Arg Loops with argparse

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #239 (source: ponytail over-engineering audit 2026-06-23)
**Priority:** Low
**Change Type:** Refactor
**Targets:** `main`
**Closes:** #239
**Builds on:** TRN-3047 / PR #276 (discover.py argparse; §Migration cross-script consistency constraint), issue #278 (lazy-CLI-defaults principle, applied here proactively)

---

## What

Replace the three near-identical manual `while i < len(args)` loops in
`scripts/install.py main()` (lines 262–350: `register`,
`register-from-registry`, `unregister`) with one `argparse.ArgumentParser`
plus three subparsers, following the choices locked in by TRN-3047
(`allow_abbrev=False` everywhere, parser inside `main()`, lazy defaults; the
version mechanism differs — see §Invariants pre-parse guard, which supersedes
TRN-3047's post-parse pattern here).

## Why

Three copies of the same flag-pairing/unknown-arg/default logic (~75 lines)
that must be maintained in lockstep; argparse subparsers express it in ~30.
Flagged by the ponytail audit; filed as #239. TRN-3047 §Migration explicitly
committed #239 to the same parser conventions.

## Out of Scope

- Any change to `cmd_register` / `cmd_register_from_registry` /
  `cmd_unregister` / `atomic_update` logic or locking.
- `install.sh` (shell installer) and `install_from_manifest.py`.
- New flags or commands.

## Behavioral Contract

**Preserved (documented CLI surface — existing tests must pass unmodified):**

| Invocation | Behavior (unchanged) |
|---|---|
| `install.py` (no args) | module docstring to stderr, exit 1 |
| `install.py --version` | semver only to stdout, exit 0 |
| `install.py --version <anything>` | version to stdout, exit 0 — honored ONLY as `argv[0]`, via a manual **pre-parse guard** (see Invariants). Current code has identical semantics (`args[0] == "--version"`); argparse never sees the invocation, so required subcommand arguments cannot interfere (R1 deepseek blocker / glm B5) |
| `install.py register p --global-config ""` | empty string passed through to `atomic_update` verbatim — lazy resolver uses `is None`, not falsy-`or` (R1 minimax) |
| `install.py register <provider> --cli <cmd> [--global-config P]` | registers provider; `--cli` required; values with spaces preserved verbatim |
| `install.py register-from-registry <path> [--global-config P]` | bulk-registers from registry file |
| `install.py unregister <provider> [--global-config P]` | removes provider; no-op if absent |
| `--global-config` default | `~/.claude/trinity.json` (expanduser), resolved lazily at dispatch |

Caveat (R2 minimax): top-level `-h` output lists only argparse-built
subcommands and flags — `--version` is handled by the pre-parse guard and
documented in the module docstring, not in argparse help.

**Changed (undocumented error/help surface — every row pinned by a NEW test):**

| Invocation | Before | After |
|---|---|---|
| `install.py --bogus` (top-level unknown flag) | `unknown command '--bogus'`, exit 1 | argparse error to stderr, exit 2 |
| `install.py bogus-cmd` | `unknown command`, exit 1 | argparse invalid-choice, exit 2 |
| `<subcmd> --bogus` (each of the 3) | `unknown argument`, exit 1 | argparse error, exit 2 |
| `register <p>` without `--cli` | custom `--cli is required` message, exit 1 | argparse `the following arguments are required: --cli`, exit 2 |
| `register` / `unregister` / `register-from-registry` with no positional | custom usage line, exit 1 | argparse required-positional error, exit 2 |
| `<subcmd> --global-config` (missing value) | treated as unknown argument, exit 1 | argparse "expected one argument", exit 2 |
| abbreviated flags (e.g. `register p --cl x`, `--global`) | unknown argument, exit 1 | rejected, exit 2 (`allow_abbrev=False` on ALL parsers) |
| `-h` / `--help` (top level and each subcommand) | unknown command/argument, exit 1 | argparse help to stdout, exit 0 (deliberate addition, matches TRN-3047) |
| `register -x --cli y` (dash-prefixed positional) | **succeeds** — registers provider literally named `-x`, exit 0 | argparse error, exit 2 (R1 glm B1; success→error change, deliberate: dash-named providers were never intended) |
| `register --cli foo` (positional missing, flag present) | **succeeds** — registers provider literally named `--cli`, exit 0 | argparse required-positional error, exit 2 (R1 glm B2 + minimax convergent) |
| `register p --cli -x` / `--cli --global-config` (dash-token flag value, space-separated) | value stored verbatim, exit 0 | argparse "expected one argument", exit 2 — workaround `--cli=-x` documented in §Migration (R1 glm B3/C3) |
| `unregister p extra` (trailing extra positional) | unknown argument, exit 1 | argparse "unrecognized arguments", exit 2 (R1 glm B4) |
| `register --cli x p` (flag BEFORE positional) | unknown argument, exit 1 | **accepted** — argparse intermixes flags and positionals; provider=`p`, cli=`x`, exit 0 (behavior ADDITION, declared per R1 deepseek advisory) |

No test or caller pins the old error text or exit-1 codes (verified:
`tests/test_install.py` pins only happy paths + `--version`;
`tests/test_install_sh.sh` references install.py only as a manifest entry).

**Invariants (carried verbatim from TRN-3047 per its §Migration constraint):**

- `allow_abbrev=False` passed explicitly to the top-level parser AND each of
  the three `add_parser` calls — do not rely on parent inheritance (version-
  dependent in CPython; the explicit pass is unambiguous and matches
  codex.py/discover.py practice; wording per R1 minimax).
- **Pre-parse version guard** — `if argv[0] == "--version": print(__version__); return`
  runs BEFORE argparse, exactly mirroring current semantics (`--version`
  honored only as first token). `--version` is NOT an argparse argument:
  post-parse `store_true` checking is unimplementable here because the
  subparsers carry required arguments that error before any version branch
  (R1 deepseek blocker). Supersedes TRN-3047's post-parse pattern for
  scripts whose subcommands have required args.
- Parser constructed inside `main()`, never module level.
- Empty-argv docstring dump stays a manual pre-parse check (exit 1).
- **Lazy defaults (issue #278 principle)** — `--global-config` uses
  `default=None`, resolved at dispatch via
  `if args.global_config is None: args.global_config = os.path.expanduser(...)`
  (`is None`, NOT falsy-`or`, so an explicit empty string passes through
  verbatim per the Preserved table; R1 minimax). Parser build touches
  neither filesystem nor environment (`expanduser` reads `$HOME` and can
  fall back to a passwd lookup — keep it out of `add_argument`). Necessity
  note (R1 deepseek): 2-line cost; principle operator-ratified via issue
  #278 out of the PR #276 retrospective.

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/install.py` | `import argparse`; `main()` rewritten: empty-argv guard, **pre-parse version guard** (`argv[0] == "--version"`), top-level parser (`prog="install.py"`, `allow_abbrev=False`, no `--version` argument), three subparsers each with their positional + flags per the Preserved table, lazy `--global-config` default resolved via `is None` at dispatch, dispatch via `args.command`. Three manual loops deleted. Est. −75/+35 lines. | trinity-glm |
| 2 | `tests/test_install.py` | New contract tests. ONE `pytest.mark.parametrize` exit-2 test enumerating **15 rows** (implementation split the dash-token row into both variants, `--cli -x` AND `--cli --global-config`; missing-flag-value is covered via one representative subcommand — `register` — by deliberate choice): top-level `--bogus`; `bogus-cmd`; unknown flag on each of the 3 subcommands; missing positional on each of the 3 subcommands; `register p` missing `--cli`; `register p --global-config` missing value; `register p --cl x` abbreviation; `register -x --cli y` dash positional; `register p --cli -x` dash-token value; `unregister p extra` trailing positional — each asserting exit 2 + stderr + offending token. Individual tests: `-h` and `register -h` → help stdout exit 0; `--version` exact-match (dynamic version load); `--version register` → version exit 0 AND no config file created under patched HOME (behavioral short-circuit proof, R1 minimax/deepseek — replaces the non-probative HOME-unset mechanism, since `expanduser` falls back to passwd and never crashes); `register --cli x p` flag-before-positional → exit 0, provider `p` registered (behavior-addition pin); `--global-config ""` empty-string passthrough; no-args docstring exit 1. CAUTION (R1 glm C1/C2): `test_install.py` has NO autouse `patch_home` fixture — every test touching the default path must patch `HOME` explicitly (direct `subprocess.run(..., env=...)`; the line-13 run helper inherits `os.environ`). Est. ~65 LoC via parametrization. | trinity-deepseek |
| 3 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry referencing #239. | trinity-glm |
| 4 | `rules/TRN-0000-REF-Document-Index.md` | Regenerated via `af index --root .`. | orchestrator |

Write sets are disjoint per TRN-1008 §5 (glm: scripts/ + CHANGELOG; deepseek: tests/).

## Acceptance Criteria

- [ ] `scripts/install.py` contains no manual `while i < len(args)` loop; one
  parser + three subparsers, `allow_abbrev=False` on all four.
- [ ] `--version` handled by the pre-parse guard (`argv[0]` check) before
  argparse; `--version <anything>` prints version, exit 0.
- [ ] `--global-config` default is `None` at parse time, resolved lazily at
  dispatch via `is None` (issue #278 principle; empty string passes through);
  parser build reads neither filesystem nor environment.
- [ ] Documented CLI surface preserved; existing tests pass **unmodified**.
- [ ] New tests pin every Changed-table row (15-row parametrized exit-2 set,
  help exit-0, flag-before-positional addition), both version paths incl.
  the no-config-write short-circuit proof, empty-string passthrough, and
  no-args exit 1.
- [ ] `pytest tests/test_install.py -q` and full `pytest -q` pass.
- [ ] `.venv/bin/ruff check` and `ruff format --check` on both changed files pass.
- [ ] `af validate --root .` passes.
- [ ] PR body includes `Closes #239` and the Plan Review table.

## Implementation Order

1. trinity-deepseek: contract tests (RED against current code on changed
   rows, GREEN on preserved rows) — TDD per COR-1500.
2. trinity-glm: rewrite `main()` per Surface 1.
3. Orchestrator: AC verification; index regen; CHANGELOG check.

Commit order: RED commit lands before GREEN; do not squash.

## Migration / Backward-compat

Documented CLI surface unchanged. Out-of-repo callers of error paths see
exit 2 + argparse messages (was 1 + custom messages); `-h`/`--help` now
supported. Two success-path changes are deliberate: providers literally named
`-x`/`--cli` can no longer be registered (argparse rejects dash-prefixed
positionals — these were accidents of the blind `args[1]` read, never
intended), and dash-token flag values need the `--cli=-x` form. One addition:
flags may now precede positionals. `--version` semantics are byte-identical
(pre-parse guard). Same conventions as `discover.py` post-TRN-3047 except the
version mechanism, which this CHG supersedes for required-arg subcommands —
noted for any future third argparse migration.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04) | 8.95 FAIL | 7.40 FAIL | 9.50 PASS | ❌ |
| R2 (2026-07-04) | 9.61 PASS | 9.60 PASS | 9.50 PASS | ✅ |

R2 notes: deepseek's provider initially emitted a hallucinated blocker
(claimed argparse silently accepts `--cli -x`); refuted empirically by the
wrapper per COR-1621 — the B3 row and `--cli=-x` workaround are correct.
Cosmetic R2 advisories folded post-gate: §What version-mechanism wording,
14-row count fix + one-representative note, `-h`-omits-`--version` caveat.
minimax surfaced a LATENT codex.py bug (`--version <subcommand>` with
required args exits 2) — filed as #279, out of scope here.

Code-review tier (PR #280, head 67d7703): glm 9.66 PASS / deepseek 9.60
PASS, 0 blocking. Codex bot: +1 on PR body, ZERO inline findings (the
lazy-defaults invariant pre-empted the PR #276 getcwd bug class). Post-gate
cosmetic fixes: parametrize count reconciled to 15 across Surface 2 + AC;
row-10 abbreviation token hardened from passenger `"--cl"` to stable
`"required"` (deepseek discrimination analysis).

R1 folds: pre-parse version guard replaces store_true mechanism (deepseek
blocker + glm B5, convergent root cause); Changed table +5 rows (glm B1-B4 +
flag-before-positional addition per deepseek advisory); `is None` lazy
resolver + empty-string Preserved row (minimax); 13-row parametrize
enumeration; behavioral no-config-write version test replaces non-probative
HOME-unset mechanism (deepseek/minimax convergent); env/patch_home cautions
(glm C1/C2); allow_abbrev wording neutralized (minimax). Deferred: minimax's
cross-script-consistency tracking issue (constraint already recorded in both
CHGs; file only if a third argparse migration appears).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft (Status: Proposed). Closes #239. Applies TRN-3047 conventions + issue #278 lazy-defaults principle from the PR #276 retrospective. | Claude Code (orchestrator) |
| 2026-07-04 | R1 panel fixes: pre-parse version guard (deepseek blocker — store_true unimplementable with required subparser args; glm B5 same root); +5 Changed rows incl. two success→error declarations (glm B1-B4, deepseek flag-before-positional); `is None` lazy resolver (minimax); Surface 2 rewritten (13-row parametrize, behavioral version short-circuit proof, env cautions). | Claude Code (orchestrator) |

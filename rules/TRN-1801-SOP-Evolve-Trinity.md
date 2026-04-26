# SOP-1801: Evolve Trinity

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-04-26
**Last reviewed:** 2026-04-26
**Status:** Active
**Depends on:** TRN-1800 (weights, thresholds, signals), COR-1800 (philosophy + cycle)

---

## What Is It?

The concrete evolve loop for the `trinity` repo. Implements the COR-1800 cycle (Signal → Candidate → Evaluation → Implementation → Review → PR) using TRN-1800's overridden weights, thresholds, and signal sources.

---

## Why

Trinity has a high-leverage failure mode: any drift between the source (`<name>.delta.md`, `_base/*.md`, `Makefile install`, `install.sh` register block) and what gets shipped (`providers/<name>.md`, `~/.claude/skills/trinity/bin/*`, `~/.claude/trinity.json` `cli` values) silently breaks fresh-user installs. The v2.0.0 stat-order bug (caught only by Linux CI; macOS local test was happy) is the canonical example of why an explicit evolve loop matters here. Without one, drift accumulates between releases — `[Unreleased]` rot, README drifting from reality, SOPs citing dead commands, model IDs falling behind vendor docs, provider registrations diverging between `Makefile` and `install.sh`.

This SOP makes pruning and consolidation a deliberate, scored process rather than ad-hoc cleanup.

---

## When to Use

- User explicitly invokes the evolve loop ("run evolve", "audit trinity", "tighten the repo")
- Before cutting a release that is **not** a small bugfix (i.e., minor or major bumps)
- Periodic maintenance — suggested cadence: when 5+ commits have landed since the last release with no `[Unreleased]` entry, OR when the last evolve cycle was > 2 months ago
- After any incident (broken release, failed `make install`, contributor confusion)

## When NOT to Use

- For a single targeted edit with clear scope (just edit the file; CHANGELOG `[Unreleased]` covers the trail)
- For changes inside COR PKG documents (read-only — propose upstream instead)
- For changes to TRN-1800 or this SOP itself (use PRP/CHG per COR-1800 guard rails)
- For patch-level bugfixes that have a clear single-surface fix and a regression test (just ship it, don't ceremonialise)

---

## Steps

### 1. Signal Collection

Run each signal source from TRN-1800 §Signal Sources and record findings in a working list. Concrete commands:

```bash
# Build drift — must be empty / OK
make verify-built

# Provider parity — diff Makefile vs install.sh register blocks.
# Normalize before sort: leading tabs/spaces (Makefile uses TAB, install.sh
# uses 4 spaces) AND Makefile's $(HOME) vs install.sh's ${HOME} (semantically
# identical). Without normalization the diff produces false positives where
# parity is actually fine.
_norm() { sed -E 's/^[[:space:]]+//; s/\$\(HOME\)/${HOME}/g'; }
diff \
  <(grep -E '^[[:space:]]+--cli ' Makefile   | _norm | sort) \
  <(grep -E '^[[:space:]]+--cli ' install.sh | _norm | sort)

# Cross-platform shell traps — every hit needs a "did we test the other OS?" review
grep -rnE "stat -[fc] |sed -i ''|readlink -f|date -d " \
  providers/bin/ scripts/ install.sh Makefile 2>/dev/null

# Model-ID drift — compare against TRN-1006 example log + current vendor docs
grep -nE "ANTHROPIC_MODEL|--model |gpt-5|gemini-3|deepseek-v|qwen" \
  providers/bin/* providers/*.delta.md install.sh Makefile 2>/dev/null

# install.sh share-readiness smoke (no network beyond GitHub raw)
F=$(mktemp -d); HOME=$F bash -c \
  'curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash' \
  >/dev/null 2>&1
# Then assert the install:
test -x $F/.claude/skills/trinity/bin/deepseek && echo "deepseek bin OK"
test -x $F/.claude/skills/trinity/bin/openrouter && echo "openrouter bin OK"
python3 -c "import json; d=json.load(open('$F/.claude/trinity.json'))['providers']; \
  print('providers:', sorted(d.keys())); \
  print('cli has _cy:', any('_cy' in v['cli'] for v in d.values()))"
rm -rf $F

# CHANGELOG [Unreleased] lag — every behaviour-changing commit since last tag
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
git log ${LAST_TAG}..HEAD --oneline | grep -vE "^[a-f0-9]+ (chore|docs|test):"

# Or, more strictly, every commit since last tag (including chore/docs/test):
git log ${LAST_TAG}..HEAD --oneline

# Inspect [Unreleased] section content
awk '/^## /{c++} c==2{exit} c>=1' CHANGELOG.md

# af validate — PRJ doc structure
af validate --root .

# SOP↔code drift — manual scan; for each TRN-100x SOP, grep for the commands it cites
for sop in rules/TRN-1*-SOP-*.md; do
  echo "=== $sop ==="
  grep -oE 'make [a-z-]+|\.venv/bin/[a-z]+ [a-z]+' "$sop" | sort -u
done
# Then verify those targets/binaries still exist with the documented behaviour
```

For each finding, capture:
- **Surface** (which file / SOP / section)
- **Evidence** (file path + line, command output, log excerpt)
- **Proposed action** (delete / merge / rewrite / extract / regenerate)

### 2. Candidate Generation

Convert each finding into a candidate with this shape:

```
Candidate ID: C<n>
Surface: <providers/bin/deepseek | rules/TRN-1004-SOP-Release.md §Steps | install.sh:42-67 | ...>
Action: <edit | delete | rewrite | regenerate | extract | hotfix>
Evidence: <pointer to signal output>
Estimated compression: +<chars added> / -<chars removed>
```

**What counts as one surface:**

- **Single-purpose file** (one `.delta.md`, one `tests/test_<name>.py`, one `scripts/<name>.py`, one `providers/bin/<name>`, one `rules/TRN-XXXX-*.md`, one section of `_base/`): the file is the surface.
- **Multi-section document** (`Makefile`, `README.md`, `CHANGELOG.md`, any SOP in `rules/`): each `##`-level heading is a surface. **A single candidate touches ≤ 1 such section.** Multi-section rewrites split into one candidate per section.
- **Symmetric multi-file refactor** — the *class* is the surface. Two recognised classes in trinity:
  - All five generated providers via a `_base/*.md` partial change (cascades to `codex.md`, `gemini.md`, `glm.md`, `openrouter.md`, `deepseek.md`)
  - Both Anthropic-compat wrappers (`providers/bin/{deepseek,openrouter}` — symmetric env-injection scripts)

  Conditions: (a) the change must be symmetric across all members; if only some members change, that's N separate candidates. (b) The candidate must list every member explicitly and state the shared before/after invariant.
- **Cross-class candidates** (a single conceptual change touching, e.g., `providers/bin/deepseek` AND `Makefile install` AND `tests/test_anthropic_compat_wrappers.py`): always N separate candidates, one per surface. Common case: a model-ID bump touches the bin script + the test assertion + maybe a SOP example log — file as 3 candidates and let the review weigh each.

Discard immediately if the action is "add new feature" without a deletion offset OR a real necessity signal — this loop is for compression and parity, not growth. New features go through ordinary creation flow.

### 3. Evaluation

Score each candidate against TRN-1800 weights. Code candidates use the code weight table; doc candidates use the doc weight table. Mixed candidates score against both and use the lower of the two composites.

For each dimension, score 0–10 with a one-line justification. Composite = Σ(weight × score). Discard candidates with composite < 7.0 (inherited COR-1800 threshold).

Record scores in the candidate working list. Surface the top candidates to the user before implementation.

### 4. Implementation

For each surviving candidate:

- Make the change on a feature branch (worktree per `superpowers:using-git-worktrees`, especially if multiple candidates run in parallel)
- Touch only the surface listed in the candidate. **"No cascade"** means: no edits outside the candidate's declared surface. Within the surface (every member of a symmetric class, or one section of a multi-section doc), the change may span every member; outside it, nothing changes. Scope restraint is 15% of the code score.
- Run the relevant subset of `make test` after every step:
  - Bin script change → `pytest tests/test_anthropic_compat_wrappers.py -q`
  - `.delta.md` change → `make build && make verify-built`
  - `Makefile` / `install.sh` change → `bash tests/test_install_sh.sh`
  - Anything else → full `make test`
- If a regression sample (`samples/regression-dispatch.md`) exists, run any affected case before/after
- If no regression sample exists and the candidate's "behavior observability" scored ≥ 8 (under TRN-1800's "test coverage of changed surface" 30% weight), write the regression case now and add it to `samples/regression-dispatch.md`
- Run the Linux CI safety net: cross-platform parity is 20% of the code score. If the candidate touches shell code, you cannot trust macOS-only test passes. Push to a draft PR or feature branch to trigger CI's Linux runner before merging to main.

### 5. Review

Two-reviewer gate per inherited COR-1800. Both must score ≥ 9.0:

- **Reviewer A**: re-score against TRN-1800 weights with the implemented diff in hand
- **Reviewer B**: independent reviewer (different agent/model, or human) confirms behaviour is preserved on:
  - the regression sample (if applicable)
  - `make verify-built` + `make test` + `make lint` all green
  - cross-platform proof (Linux CI run output, not just local macOS pass)

Reviewers may also use COR-1610 (Code Review Scoring) as procedural reference, but the final score uses TRN-1800 weights.

### 6. PR

Bundle survivors into a single PR (or skip the PR step for hotfixes that ship straight to `main` per the project's "trivial single-surface fix" exception). PR title: `evolve(trn): <one-line summary>`. PR body includes:

- Candidate IDs and final composite scores
- Compression delta (lines/chars added vs removed across all surfaces)
- Test results: `make test` output, regression sample diff if applicable, Linux CI run URL
- Any candidates rejected at review and why

---

## Guard Rails

- This SOP must not modify TRN-1800, COR-1800, or itself. Changes to these go through PRP/CHG.
- Never delete files based on signal alone — every deletion needs evidence in the candidate record.
- Never claim "behaviour preserved" without `make verify-built` + `make test` green AND, for shell changes, a Linux CI pass. The v2.0.0 stat-order bug class is the canonical reason this rule exists.
- `make install` against your local `~/.claude/` is destructive (overwrites `~/.claude/skills/trinity/*`, mutates `~/.claude/trinity.json`). Always snapshot to `~/.claude/trinity-backup-$(date +%Y%m%d-%H%M%S)/` first; treat it as the smoke test of last resort, not a routine evolve step.
- Never bypass the verify/publish split (TRN-2007). `git push origin main vX.Y.Z` is the act-of-no-return; a CI verify failure means *no GitHub Release was published* (TRN-2007 working as designed) — fix forward with a patch bump, do not force-push the tag.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-04-26 | Initial version. Mirrors CLD-1801 shape; signal commands and surface taxonomy customised for trinity (build composition via `_base/`, `bin/` Anthropic-compat wrappers, `Makefile`/`install.sh` parity, Linux CI as cross-platform safety net). | Claude Opus 4.7 |

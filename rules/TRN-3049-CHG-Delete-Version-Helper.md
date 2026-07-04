# CHG-3049: Shrink _version.py to a Textual Parse (No __init__.py Execution)

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-07-04
**Last reviewed:** 2026-07-04
**Status:** Approved
**Date:** 2026-07-04
**Requested by:** @ryosaeba1985 via issue #237 (ponytail audit 2026-06-23); batch mandate from @frankyxhl (2026-07-04)
**Priority:** Low
**Change Type:** Refactor (single-file shrink, behavior-preserving)
**Targets:** `main`
**Closes:** #237

---

## What

Rewrite `scripts/_version.py` from an 18-line importlib spec/exec dance to a
~13-line textual parse (7 functional lines + docstring — roughly halves the
module) that reads the `__version__ = "x.y.z"` constant from `__init__.py`
**without ever executing it**. The public API
(`load_version()`) is unchanged, so **nothing else in the repo moves**: the
5 script callers, both test EXPECTED_VERSION loaders, `install-manifest.json`,
and `tests/test_install_sh.sh` are all untouched.

```python
"""Shared version loader for trinity scripts.

Textual parse — never executes __init__.py, so this stays safe even if
__init__.py grows imports. Depends on the double-quoted single-line format
written by `make bump` (Makefile perl substitution); ruff format does not
normalize string quotes, so the bump script is the sole format authority.
"""

import re
from pathlib import Path


def load_version():
    init_text = (Path(__file__).parent / "__init__.py").read_text()
    return re.search(r'^__version__ = "([^"]+)"$', init_text, re.M).group(1)
```

## Why (and why not the issue's original ask)

Issue #237 asked to DELETE `_version.py` and repoint 5 callers to a
dual-mode `from . import __version__` / `from __init__ import __version__`.
Panel R1 (minimax blocking, 8.60) rejected that implementation: the
`from __init__` fallback registers `scripts/__init__.py` in
`sys.modules["__init__"]`, executes it under two module names, and plants an
opaque idiom in 5 files — distributing the risk the dance currently
contains in one. The pivot above satisfies the issue's actual premise
(18 lines of importlib machinery to read one constant is over-engineering)
with strictly better numbers: 18→7 lines, **zero caller churn**, and the
`__init__.py` side-effect-execution risk is *eliminated* (textual read)
rather than deferred behind guard comments.

R1 side-benefits of keeping the `load_version()` API:
- glm's blocker (unsatisfiable `git grep load_version` AC vs the CHANGELOG
  historical entry) is moot — `load_version` legitimately remains.
- The two test EXPECTED_VERSION loaders (test_discover.py / test_install.py)
  keep working verbatim — they importlib-load `_version.py` by path and call
  `load_version()`, both unchanged.
- Manifest and installed-tree surfaces unchanged; no upgrade/stale-file
  considerations (deepseek R1 probe: stale old copy is overwritten in place
  since the path still ships).

## Behavioral Contract

Behavior-preserving; pinned by existing tests, all unmodified:

| Pin | Where |
|---|---|
| `<script> --version` → `3.3.0`, exit 0 (direct invocation, all 5 scripts) | 5 CLI suites + TRN-3047/3048 exact-match tests |
| Package-context `from ._version import load_version` | codex.py import path exercised by pytest package imports (per R1 deepseek: codex.py exercises both branches; the other 4 exercise the fallback via subprocess — unchanged from status quo) |
| Test-loader path (`spec_from_file_location` on `_version.py` + `load_version()`) | test_discover.py:301 / test_install.py:158 EXPECTED_VERSION blocks, untouched |
| Installed tree resolves version | tests/test_install_sh.sh t7 |

Format dependency (R1 deepseek advisory, declared): the regex requires the
exact double-quoted single-line form `__version__ = "x.y.z"`. That form is
maintained mechanically by the Makefile version-bump perl substitution
(Makefile:113) and ruff format. If it ever drifts, `load_version()` raises
`AttributeError` at first call — loud, not silent; the module docstring
records the dependency.

## Out of Scope

- Caller import blocks (5 scripts) — untouched by design.
- Test loaders, manifest, install.sh, shell tests — untouched.
- CHANGELOG:265-269 historical entry — history stays.
- `#238` (_compat.py) — next in batch, will be evaluated against this
  precedent (a 2-line module KEPT may similarly beat deletion).

## Surfaces

| # | Surface | Change | Worker |
|---|---------|--------|--------|
| 1 | `scripts/_version.py` | Rewrite per §What: importlib dance → textual parse. −18/+~13 (net negative, single file). Failure mode kept as the bare `.group(1)` AttributeError — loud at import time; an explicit RuntimeError was considered (R2 glm advisory) and skipped as net-line-negative-hostile for a failure that names its own line. | trinity-glm |
| 2 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry referencing #237, noting the panel pivot (issue's deletion ask superseded by API-preserving shrink). | trinity-glm |
| 3 | `rules/TRN-0000-REF-Document-Index.md` | `af index` regen. | orchestrator |

## Acceptance Criteria

- [ ] `scripts/_version.py` contains no `importlib` reference; `load_version()`
  API unchanged. (Line-count clause dropped per R2 glm — the importlib-absence
  + API + behavior clauses cover the intent.)
- [ ] `git grep -l importlib scripts/` no longer lists `_version.py`.
- [ ] Zero changes outside Surfaces 1-3: `git diff --stat` shows exactly
  `scripts/_version.py`, `CHANGELOG.md`, and the regenerated index.
- [ ] Full `pytest -q` passes with all test files byte-identical.
- [ ] `bash tests/test_install_sh.sh` passes (installed-tree version).
- [ ] `ruff check` / `format --check` on `scripts/_version.py` pass.
- [ ] `af validate --root .` passes; PR body includes `Closes #237` + the
  pivot rationale.

## Implementation Order

1. trinity-glm: Surfaces 1-2.
2. Orchestrator: full verification incl. shell test; index regen.

(No RED step: behavior-preserving under existing coverage per COR-1500.)

## Migration / Backward-compat

None. `load_version()` signature and semantics identical; the module still
ships at the same path.

## Plan Review

TRN-1008 §4 rounds:

| Round | trinity-glm | trinity-deepseek | trinity-minimax | Gate (all ≥9.5) |
|-------|------------|------------------|-----------------|------|
| R1 (2026-07-04, pre-pivot plan) | 9.20 FAIL | 9.63 PASS | 8.60 FAIL | ❌ |
| R2 (2026-07-04, pivoted plan) | 9.65 FAIL (AC line-count contradiction only) | 9.93 PASS | 9.70 PASS | ❌ |
| R3 (2026-07-04) | 9.74 PASS | — (R2 carry) | — (R2 carry) | ✅ |

R2 fold: AC ≤10-line clause DROPPED (glm blocker, deepseek advisory —
convergent); size framing corrected to −18/+~13; docstring quote-stability
attribution corrected to `make bump` alone (ruff format does not touch
quotes); explicit-RuntimeError advisory considered and skipped with
rationale in Surface 1.

R1 triage: minimax's blocking pivot ADOPTED and extended (keep
`load_version()` API → zero churn beyond `_version.py` itself); glm's
AC-contradiction blocker and all 4 advisories mooted by the pivot;
deepseek's regex-fragility advisory folded into §Behavioral Contract +
module docstring; deepseek's package-coverage overstatement folded into the
pin table wording. deepseek session note (concurrent same-provider dispatch
interleaving) carried to §11 retrospective.

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-07-04 | Initial draft: delete _version.py + dual-mode `__init__` import in 5 callers. | Claude Code (orchestrator) |
| 2026-07-04 | Unparked after PR #280 merged (dependency: test_install.py loader + shared install.py edits). | Claude Code (orchestrator) |
| 2026-07-04 | R1 PIVOT (minimax 8.60 blocking): deletion replaced by API-preserving textual-parse shrink — 18→7 lines, zero caller churn, `__init__.py` execution risk eliminated. Title updated; Surfaces collapsed 7→3; glm/deepseek R1 findings folded or mooted as recorded in §Plan Review. | Claude Code (orchestrator) |

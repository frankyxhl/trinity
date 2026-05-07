"""Test-runner setup: enable coverage tracking inside subprocesses.

The Trinity test suite invokes its target modules as CLI subprocesses
(e.g. `subprocess.run([..., scripts/session.py, "read", ...])`) rather
than importing them. Without subprocess tracking, `pytest --cov` only
sees the test runner's own execution and reports ~27% across modules
that actually have ~83% line coverage. This conftest closes that gap
by:

1. Setting `COVERAGE_PROCESS_START` to the project's `.coveragerc` so
   any Python child process that imports `coverage.process_startup()`
   activates coverage with the project's parallel-mode config.

2. Prepending `tests/` to `PYTHONPATH` so child processes auto-import
   `tests/sitecustomize.py`, which calls `coverage.process_startup()`
   exactly once at child-process startup.

The pair (env var + sitecustomize) is the canonical pattern documented
in coverage.py's "subprocess" recipe. It's preferred over writing a
sitecustomize.py into the venv's site-packages (an invasive global
side-effect that would activate coverage for unrelated tools too).
"""

import os
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _TESTS_DIR.parent
_COVERAGERC = _PROJECT_ROOT / ".coveragerc"

if _COVERAGERC.exists():
    os.environ.setdefault("COVERAGE_PROCESS_START", str(_COVERAGERC))

    _existing_pp = os.environ.get("PYTHONPATH", "")
    _parts = _existing_pp.split(os.pathsep) if _existing_pp else []
    if str(_TESTS_DIR) not in _parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(_TESTS_DIR), *_parts])

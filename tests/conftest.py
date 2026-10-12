"""Test-runner setup: optionally enable coverage tracking inside subprocesses.

Subprocess-coverage tracking is OPT-IN, controlled by `COVERAGE_PROCESS_START`:

- When `COVERAGE_PROCESS_START` is set in the env (set by `Makefile`'s
  `coverage:` target via inline `VAR=val cmd`, or by a developer
  invoking pytest directly with the env var prefix), this conftest
  prepends `tests/` to `PYTHONPATH` so child Python processes
  auto-import `tests/sitecustomize.py`, which calls
  `coverage.process_startup()`. It also prepends the test interpreter's
  directory to `PATH`, because the CLI shim runs bare `python3` from `PATH`
  and sitecustomize needs `coverage` importable in that interpreter.

- When `COVERAGE_PROCESS_START` is unset (the default during plain
  `make test` and direct `pytest tests/` invocation), this conftest
  is a no-op. No PYTHONPATH mutation, no `.coverage.*` files written
  by subprocesses.

Note on ambient env: a developer who has `COVERAGE_PROCESS_START`
exported globally in their shell will trigger the gate even on plain
`make test`. This is by design (the env var IS the opt-in switch),
but worth noting if `.coverage.*` files appear unexpectedly.

`coverage.process_startup()` is a no-op unless `COVERAGE_PROCESS_START`
or `COVERAGE_PROCESS_CONFIG` is set (verified against coverage.py
`control.py` `process_startup()` — early-return gate at the function
top). So accidental imports of sitecustomize stay harmless.
"""

import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()

if os.environ.get("COVERAGE_PROCESS_START"):
    _existing_pp = os.environ.get("PYTHONPATH", "")
    _parts = _existing_pp.split(os.pathsep) if _existing_pp else []
    if str(_TESTS_DIR) not in _parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(_TESTS_DIR), *_parts])

    _interpreter_dir = os.path.dirname(sys.executable)
    _existing_path = os.environ.get("PATH", "")
    _path_parts = _existing_path.split(os.pathsep) if _existing_path else []
    if _interpreter_dir not in _path_parts:
        os.environ["PATH"] = os.pathsep.join([_interpreter_dir, *_path_parts])

"""Auto-start coverage in any Python child process that has tests/ on PYTHONPATH.

When PYTHONPATH includes tests/, Python imports `sitecustomize` at startup;
this module then activates coverage based on the COVERAGE_PROCESS_START
env var. The combination lets pytest-cov see lines executed inside
subprocesses spawned via subprocess.run (the dominant test pattern).

Producer of COVERAGE_PROCESS_START: `Makefile`'s `coverage:` target sets
it via inline `VAR=val cmd` form (see Makefile `coverage:` target for
the canonical incantation including `--include` and `--fail-under`
flags). A developer can also set it directly to opt in via the same
pattern: `COVERAGE_PROCESS_START=$(pwd)/.coveragerc .venv/bin/coverage
run -m pytest tests/ -q && .venv/bin/coverage combine && .venv/bin/coverage report`.

Reader of COVERAGE_PROCESS_START: `tests/conftest.py` reads it as the
gate; child processes pass it via env inheritance to
`coverage.process_startup()` here.

`coverage.process_startup()` is a no-op when neither
`COVERAGE_PROCESS_START` nor `COVERAGE_PROCESS_CONFIG` is set, so this
module stays harmless on accidental imports.
"""

import coverage

coverage.process_startup()

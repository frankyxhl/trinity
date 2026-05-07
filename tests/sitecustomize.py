"""Auto-start coverage in any Python child process that has tests/ on PYTHONPATH.

When PYTHONPATH includes tests/, Python imports `sitecustomize` at startup; this
module then activates coverage based on the COVERAGE_PROCESS_START env var. The
combination lets pytest-cov see lines executed inside subprocesses spawned via
subprocess.run, which the test suite uses heavily (e.g. tests invoke
scripts/session.py as a CLI rather than importing it).

The conftest.py at the same directory sets COVERAGE_PROCESS_START and prepends
tests/ to PYTHONPATH; together they form a self-contained subprocess-tracking
shim that doesn't write to the venv's site-packages.
"""

import coverage

coverage.process_startup()

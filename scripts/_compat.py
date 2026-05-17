"""Shared POSIX compatibility helpers for trinity scripts.

Exposes ``fcntl`` after a guarded import. On platforms where ``fcntl`` is
unavailable the module prints the unsupported-platform message to stderr
and exits 1, so callers never see an uncaught ``ImportError``.
"""

import sys

try:
    import fcntl  # noqa: F401 - re-exported for callers
except ImportError:
    print(
        "trinity-scripts: unsupported platform (fcntl not available). Windows is not supported.",
        file=sys.stderr,
    )
    sys.exit(1)

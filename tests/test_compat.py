"""Tests for scripts/_compat.py guarded fcntl import.

Two scenarios:
  1. Normal import exposes ``fcntl`` with ``flock``.
  2. Simulated missing ``fcntl`` exits 1 with the exact stderr message.

The missing-fcntl simulation uses a subprocess with ``-c`` so that an
``import fcntl`` hook can be installed before ``_compat`` is imported,
without affecting the host Python process.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

COMPAT_MODULE = Path(__file__).parent.parent / "scripts" / "_compat.py"

EXPECTED_STDERR = (
    "trinity-scripts: unsupported platform (fcntl not available)."
    " Windows is not supported."
)


# ---- helpers ----


def _run_subprocess(code: str) -> subprocess.CompletedProcess:
    """Run *code* in a subprocess with scripts/ on sys.path."""
    scripts_dir = str(COMPAT_MODULE.parent)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": scripts_dir},
    )


# ---- tests ----


def test_normal_import_exposes_fcntl_with_flock():
    """Importing _compat on a POSIX host exposes a ``fcntl`` module with ``flock``."""
    proc = _run_subprocess(
        textwrap.dedent("""\
            from _compat import fcntl
            assert hasattr(fcntl, "flock"), "fcntl.flock must be available"
            print("ok")
        """)
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr!r}"
    assert proc.stdout.strip() == "ok"


def test_missing_fcntl_exits_1_with_exact_stderr():
    """When ``fcntl`` cannot be imported, _compat exits 1 with the expected message."""

    # Override ``builtins.__import__`` only in the child process, and only
    # for the top-level ``fcntl`` import that _compat performs.
    proc = _run_subprocess(
        textwrap.dedent("""\
            import builtins
            _real_import = builtins.__import__

            def _fake_import(name, *args, **kwargs):
                if name == "fcntl":
                    raise ImportError("mocked: fcntl not available")
                return _real_import(name, *args, **kwargs)

            builtins.__import__ = _fake_import

            # Now import _compat. It should catch the ImportError,
            # print the message to stderr, and sys.exit(1).
            try:
                from _compat import fcntl  # noqa: F401
            except SystemExit:
                import sys
                sys.stderr.flush()
                raise
        """)
    )
    assert proc.returncode == 1, (
        f"Expected exit 1, got {proc.returncode}. stderr: {proc.stderr!r}"
    )
    assert proc.stderr.strip() == EXPECTED_STDERR, (
        f"stderr mismatch.\\n  expected: {EXPECTED_STDERR!r}\\n  got:      {proc.stderr.strip()!r}"
    )
    assert proc.stdout.strip() == ""


def test_normal_import_fcntl_lock_constants():
    """On a POSIX host, ``fcntl`` from _compat exposes LOCK_SH, LOCK_EX, LOCK_UN."""
    proc = _run_subprocess(
        textwrap.dedent("""\
            from _compat import fcntl
            for attr in ("LOCK_SH", "LOCK_EX", "LOCK_UN"):
                assert hasattr(fcntl, attr), f"fcntl.{attr} missing"
            print("ok")
        """)
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr!r}"
    assert proc.stdout.strip() == "ok"

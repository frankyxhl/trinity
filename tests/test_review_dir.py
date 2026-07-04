"""Contract tests for make_review_dir (TRN-3051: mkdtemp-based).

Pins the four behavior deltas of the tempfile.mkdtemp rewrite:
  - Dir name always ends in an 8-char random suffix (mkdtemp contract).
  - Parent dir mode 0700 (mkdtemp); subdirs raw/ / logs/ keep umask defaults.
  - Two same-second calls yield distinct dirs (atomic, no collision loop).
  - Parent path resolves via expanduser (preserved).
"""

from __future__ import annotations

import re
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _review  # noqa: E402


def test_review_dir_name_has_random_suffix(tmp_path):
    d = _review.make_review_dir(str(tmp_path), "src")
    assert re.fullmatch(r"\d{8}-\d{6}-src-[a-z0-9_]{8}", d.name), d.name


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms")
def test_review_dir_permission_asymmetry(tmp_path):
    d = _review.make_review_dir(str(tmp_path), "src")
    # mkdtemp contract: parent directory is 0700 regardless of umask
    assert stat.S_IMODE(d.stat().st_mode) == 0o700, oct(stat.S_IMODE(d.stat().st_mode))
    # Subdirs keep umask defaults — assumes umask 022 (trinity CI default);
    # under umask 077 this assertion would false-fail.
    assert stat.S_IMODE((d / "raw").stat().st_mode) != 0o700
    assert stat.S_IMODE((d / "logs").stat().st_mode) != 0o700


def test_review_dir_unique_subdirs_and_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    a = _review.make_review_dir("~/reviews", "src")
    b = _review.make_review_dir("~/reviews", "src")
    assert a != b
    assert (a / "raw").is_dir() and (a / "logs").is_dir()
    assert a.parent == Path("~/reviews").expanduser() == tmp_path / "reviews"

"""Tests for scripts/install_from_manifest.py (TRN: trinity-zc install wiring).

The installer copies manifest `files` unconditionally and `conditional_files`
only when their `condition_dir` already exists under ~ (auto-detection). The
ZCode peer skill trinity-zc uses this so `make install` places it into
~/.agents/ when that runtime is present, without creating ~/.agents otherwise.

Each test runs the installer in a subprocess with HOME pointed at a tmp dir, so
the real home directory is never touched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install_from_manifest.py"
MANIFEST = ROOT / "install-manifest.json"
ZC_SRC = ROOT / "skills" / "trinity-zc" / "SKILL.md"


def _run(home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_manifest_declares_trinity_zc_conditional():
    manifest = json.loads(MANIFEST.read_text())
    entry = next(
        (
            e
            for e in manifest.get("conditional_files", [])
            if e["src"] == "skills/trinity-zc/SKILL.md"
        ),
        None,
    )
    assert entry, "trinity-zc not declared in conditional_files"
    assert entry["dest"] == ".agents/skills/trinity-zc/SKILL.md"
    assert entry["condition_dir"] == ".agents"


def test_installs_trinity_zc_when_agents_dir_exists(tmp_path):
    home = tmp_path / "home"
    (home / ".agents").mkdir(parents=True)  # simulate ZCode runtime present
    result = _run(home)
    assert result.returncode == 0, result.stderr

    dest = home / ".agents" / "skills" / "trinity-zc" / "SKILL.md"
    assert dest.exists(), "trinity-zc not installed despite ~/.agents present"
    assert dest.read_text() == ZC_SRC.read_text(), "installed copy != repo source"
    # Unconditional files still install.
    assert (home / ".claude" / "skills" / "trinity" / "SKILL.md").exists()


def test_skips_trinity_zc_when_no_agents_dir(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _run(home)
    assert result.returncode == 0, result.stderr

    assert not (home / ".agents").exists(), (
        "installer must not create ~/.agents when the runtime is absent"
    )
    # Unconditional install still happened.
    assert (home / ".claude" / "skills" / "trinity" / "SKILL.md").exists()

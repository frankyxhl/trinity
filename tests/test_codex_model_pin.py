"""Pin the shipped Codex default and reject the retired model in shipped files.

History in CHANGELOG.md, rules/, and tests/fixtures/ is outside this contract.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_codex_registry_cli_pins_gpt_6_1_sol():
    registry = json.loads((ROOT / "providers" / "registry.json").read_text())

    assert registry["providers"]["codex"]["cli"] == (
        "codex exec --skip-git-repo-check -m gpt-6.1-sol"
    )


def test_shipped_files_do_not_contain_gpt_5_6_sol():
    shipped_files = [
        ROOT / "providers" / "registry.json",
        ROOT / "SKILL.md",
        ROOT / "README.md",
    ]
    shipped_files.extend((ROOT / "providers").glob("*.md"))
    shipped_files.extend((ROOT / "providers" / "bin").glob("*"))
    for directory in (ROOT / ".agents" / "skills", ROOT / "plugins"):
        shipped_files.extend(directory.rglob("*"))

    offenders = [
        str(path.relative_to(ROOT))
        for path in sorted(shipped_files)
        if path.is_file() and b"gpt-5.6-sol" in path.read_bytes()
    ]

    assert not offenders, "retired Codex model in shipped files: " + ", ".join(offenders)

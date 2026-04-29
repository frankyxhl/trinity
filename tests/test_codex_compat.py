"""Tests for Codex skill/plugin compatibility packaging."""

import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
VERSION = (ROOT / "VERSION").read_text().strip()

REPO_SKILL = ROOT / ".agents" / "skills" / "trinity" / "SKILL.md"
PLUGIN_ROOT = ROOT / "plugins" / "trinity"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_SKILL = PLUGIN_ROOT / "skills" / "trinity" / "SKILL.md"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
README = ROOT / "README.md"


def _frontmatter_value(text, key):
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    end = text.index("\n---", 4)
    for line in text[4:end].splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"missing frontmatter key: {key}")


def test_repo_local_codex_skill_is_importable_and_codex_specific():
    text = REPO_SKILL.read_text()

    assert _frontmatter_value(text, "name") == "trinity"
    description = _frontmatter_value(text, "description").lower()
    assert "codex" in description
    assert "/trinity" in description or "$trinity" in description

    assert ".agents/skills/trinity" in text
    assert "Claude's Agent tool" not in text
    assert "Agent(" not in text
    assert "Claude Code" in text
    assert "Codex" in text


def test_plugin_manifest_points_to_bundled_skill():
    data = json.loads(PLUGIN_MANIFEST.read_text())

    assert data["name"] == "trinity"
    assert data["version"] == VERSION
    assert data["skills"] == "./skills/"
    assert data["interface"]["displayName"] == "Trinity"
    assert data["interface"]["category"] == "Engineering"
    assert "codex" in data["description"].lower()

    assert PLUGIN_SKILL.exists()
    assert PLUGIN_SKILL.read_text() == REPO_SKILL.read_text()


def test_repo_marketplace_installs_local_trinity_plugin():
    data = json.loads(MARKETPLACE.read_text())

    assert data["name"] == "trinity-local"
    assert data["interface"]["displayName"] == "Trinity Local"

    entries = {entry["name"]: entry for entry in data["plugins"]}
    trinity = entries["trinity"]
    assert trinity["source"] == {"source": "local", "path": "./plugins/trinity"}
    assert trinity["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert trinity["category"] == "Engineering"


def test_readme_documents_claude_and_codex_load_smoke_checks():
    text = README.read_text()

    assert "Codex repo-local skill" in text
    assert "Codex plugin" in text
    assert "/skills" in text
    assert "/plugins" in text
    assert "/trinity status" in text
    assert "Claude Code" in text

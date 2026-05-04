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
    assert "trinity review" in text
    assert ".agents/trinity.codex.json" in text
    assert "Claude-specific background worker" in text


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
    assert "make install-codex" in text
    assert "trinity review --providers glm,gemini,deepseek" in text
    assert ".agents/trinity.codex.json" in text
    assert "| `fast-review` | `glm`, `deepseek` | none |" in text
    assert "Until preset resolution is implemented" in text


def test_codex_skill_documents_preset_config_as_seed_only():
    text = REPO_SKILL.read_text()

    assert "`fast-review` expands to `glm` and `deepseek`" in text
    assert "configuration seeds only" in text
    assert "--providers` or `review.default_providers`" in text

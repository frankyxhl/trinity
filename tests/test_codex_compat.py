"""Tests for Codex skill/plugin compatibility packaging."""

import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent
VERSION = (ROOT / "VERSION").read_text().strip()

REPO_SKILL = ROOT / ".agents" / "skills" / "trinity" / "SKILL.md"
PLUGIN_ROOT = ROOT / "plugins" / "trinity"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_SKILL = PLUGIN_ROOT / "skills" / "trinity" / "SKILL.md"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
README = ROOT / "README.md"
ROOT_SKILL = ROOT / "SKILL.md"


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
    assert "trinity doctor --preset fast-review" in text
    assert "trinity review --preset fast-review" in text
    assert "trinity review --pr 21 --preset deep-review" in text
    assert "trinity review --sop COR-1602 --rubric COR-1609" in text
    assert "Strict COR review mode" in text
    assert "review.max_parallel_providers" in text
    assert "Progress is logged to stderr" in text
    assert "incomplete.json" in text
    assert ".agents/trinity.codex.json" in text
    assert "| `fast-review` | `glm`, `deepseek` | none |" in text
    assert "explicit `--providers`, explicit `--preset`" in text


def test_readme_version_examples_match_version():
    text = README.read_text()

    install_output_versions = re.findall(
        r"Trinity ([0-9]+\.[0-9]+\.[0-9]+) installed to ~/.claude/",
        text,
    )
    pinned_install_versions = re.findall(
        r"TRINITY_VERSION=([0-9]+\.[0-9]+\.[0-9]+)",
        text,
    )

    assert install_output_versions == [VERSION]
    assert pinned_install_versions == [VERSION]


def test_codex_skill_documents_preset_resolution():
    text = REPO_SKILL.read_text()

    assert "trinity doctor --preset fast-review" in text
    assert "trinity review --preset fast-review" in text
    assert "trinity review --sop COR-1602 --rubric COR-1609" in text
    assert "strict template is `COR-1602` with `COR-1609`" in text
    assert "`fast-review` expands to `glm` and `deepseek`" in text
    assert "review.max_parallel_providers" in text
    assert "Progress is written to stderr" in text
    assert "incomplete.json" in text
    assert "review.default_preset" in text
    assert "skipped providers are recorded" in text


def test_claude_skill_documents_review_presets():
    text = ROOT_SKILL.read_text()

    assert '/trinity fast-review "task"' in text
    assert "| `fast-review` | `glm`, `deepseek` | none |" in text
    assert "Configured presets" in text
    assert "Preset/provider collisions are invalid" in text


def test_claude_skill_documents_nested_dispatch_guard():
    text = ROOT_SKILL.read_text()

    assert "TRINITY_DISABLE_DISPATCH" in text
    assert "Nested Trinity dispatch is disabled" in text
    assert "claude-code provider wrapper" in text
    assert "exit 1" in text


# ---------------------------------------------------------------------------
# TRN-3043 / issue #76 — build_codex_skill.sh is the single source-of-truth
# enforcement for the .agents/ ↔ plugins/ SKILL.md pair.
# ---------------------------------------------------------------------------

BUILD_CODEX_SKILL = ROOT / "scripts" / "build_codex_skill.sh"
MAKEFILE = ROOT / "Makefile"
PRE_COMMIT_HOOK = ROOT / "scripts" / "pre-commit-hook.sh"


def test_build_codex_skill_script_exists_and_is_executable():
    assert BUILD_CODEX_SKILL.exists(), f"missing: {BUILD_CODEX_SKILL}"
    assert os.access(BUILD_CODEX_SKILL, os.X_OK), f"not executable: {BUILD_CODEX_SKILL}"


def test_build_codex_skill_check_passes_on_committed_tree():
    result = subprocess.run(
        ["bash", str(BUILD_CODEX_SKILL), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"build_codex_skill --check failed on committed tree:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _copy_build_codex_skill_fixture(tmp_path):
    script = tmp_path / "scripts" / "build_codex_skill.sh"
    source = tmp_path / ".agents" / "skills" / "trinity" / "SKILL.md"
    target = tmp_path / "plugins" / "trinity" / "skills" / "trinity" / "SKILL.md"

    script.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    script.write_text(BUILD_CODEX_SKILL.read_text())
    script.chmod(0o755)
    return script, source, target


def test_build_codex_skill_build_mode_copies_source_and_keeps_regular_file(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    source.write_text("canonical skill\n")
    target.write_text("stale plugin skill\n")

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"build_codex_skill failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert target.read_text() == source.read_text()
    assert target.is_file()
    assert not target.is_symlink()


def test_build_codex_skill_build_mode_replaces_symlink_target(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    symlink_target = tmp_path / "outside-symlink-target.md"
    source.write_text("canonical skill\n")
    symlink_target.write_text("old target contents\n")
    target.symlink_to(symlink_target)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"build_codex_skill failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert target.read_text() == source.read_text()
    assert target.is_file()
    assert not target.is_symlink()
    assert symlink_target.read_text() == "old target contents\n"


def test_build_codex_skill_check_rejects_intentional_drift(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    source.write_text("canonical skill\n")
    target.write_text("drifted plugin skill\n")

    result = subprocess.run(
        ["bash", str(script), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "drift detected" in result.stderr
    assert "DRIFT" in result.stderr


def test_build_codex_skill_check_rejects_symlink_target(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    symlink_target = tmp_path / "outside-symlink-target.md"
    source.write_text("canonical skill\n")
    symlink_target.write_text("canonical skill\n")
    target.symlink_to(symlink_target)

    result = subprocess.run(
        ["bash", str(script), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "NOT A REGULAR FILE" in result.stderr


def test_build_codex_skill_rejects_missing_source_with_exit_2(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    target.write_text("canonical skill\n")

    result = subprocess.run(
        ["bash", str(script), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "source missing or not regular" in result.stderr
    assert str(source.relative_to(tmp_path)) in result.stderr


def test_build_codex_skill_rejects_unknown_argument_with_exit_2(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    source.write_text("canonical skill\n")
    target.write_text("canonical skill\n")

    result = subprocess.run(
        ["bash", str(script), "--unknown"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unknown argument: --unknown" in result.stderr
    assert "usage: scripts/build_codex_skill.sh [--check]" in result.stderr


def test_build_codex_skill_check_rejects_staged_drift_after_partial_add(tmp_path):
    script, source, target = _copy_build_codex_skill_fixture(tmp_path)
    source.write_text("canonical v1\n")
    target.write_text("canonical v1\n")

    subprocess.run(
        ["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "add",
            str(source.relative_to(tmp_path)),
            str(target.relative_to(tmp_path)),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    source.write_text("canonical v2\n")
    target.write_text("canonical v2\n")
    subprocess.run(
        ["git", "add", str(source.relative_to(tmp_path))],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        ["bash", str(script), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "staged drift detected" in result.stderr
    assert "index:plugins/trinity/skills/trinity/SKILL.md" in result.stderr


def test_makefile_wires_build_codex_skill_into_build_and_verify_built():
    text = MAKEFILE.read_text()
    assert "scripts/build_codex_skill.sh" in text
    assert "scripts/build_codex_skill.sh --check" in text


def test_makefile_release_prep_guards_codex_skill_dirty_tree():
    text = MAKEFILE.read_text()
    assert "git diff --quiet .agents/skills/trinity/SKILL.md" in text
    assert "git diff --cached --quiet .agents/skills/trinity/SKILL.md" in text
    assert "plugins/trinity/skills/trinity/SKILL.md" in text
    assert "release-prep: Codex skill copy has uncommitted changes" in text


def test_pre_commit_hook_runs_build_codex_skill_check():
    text = PRE_COMMIT_HOOK.read_text()
    assert "scripts/build_codex_skill.sh --check" in text

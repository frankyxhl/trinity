"""Tests for the Codex-native Trinity adapter."""

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
CODEX_CONFIG = ROOT / ".agents" / "trinity.codex.json"
CODEX_SCRIPT = ROOT / "scripts" / "codex.py"
CODEX_BIN = ROOT / "bin" / "trinity"
CODEX_SKILL = ROOT / ".agents" / "skills" / "trinity" / "SKILL.md"
CLAUDE_SKILL = ROOT / "SKILL.md"
MAKEFILE = ROOT / "Makefile"
INSTALL_SH = ROOT / "install.sh"


def run_codex(args, cwd=None, env=None):
    result = subprocess.run(
        [sys.executable, str(CODEX_SCRIPT)] + args,
        cwd=cwd or ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_codex_default_config_has_direct_review_providers():
    data = json.loads(CODEX_CONFIG.read_text())

    assert data["providers"]["glm"] == {
        "cli": "droid exec --model glm-5",
        "supports_resume": True,
        "resume_arg": "-s",
        "timeout": 360,
    }
    assert data["providers"]["gemini"] == {
        "cli": "gemini --model gemini-3.1-pro-preview -p",
        "supports_resume": True,
        "resume_arg": "-r",
        "timeout": 360,
    }
    assert data["providers"]["deepseek"] == {
        "cli": "droid exec --model deepseek-v4-pro[1m]",
        "supports_resume": True,
        "resume_arg": "-s",
        "timeout": 600,
    }
    assert data["review"]["default_providers"] == ["glm", "gemini", "deepseek"]
    assert "{diff}" in data["review"]["prompt_template"]
    assert "{files}" in data["review"]["prompt_template"]


def test_claude_code_install_path_remains_unchanged():
    makefile = MAKEFILE.read_text()
    install_sh = INSTALL_SH.read_text()
    root_skill = CLAUDE_SKILL.read_text()

    assert "install:        ## Install Trinity to ~/.claude/" in makefile
    assert "cp SKILL.md ~/.claude/skills/trinity/SKILL.md" in makefile
    assert "--global-config ~/.claude/trinity.json" in makefile
    assert "${HOME}/.claude/skills/trinity/SKILL.md" in install_sh
    assert "${HOME}/.claude/trinity.json" in install_sh

    assert "background sub-agents" in root_skill
    assert ".claude/trinity.json" in root_skill
    assert "Agent(" in root_skill
    assert CODEX_SKILL.read_text() != root_skill


def test_codex_review_collects_tracked_and_untracked_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("before\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    tracked.write_text("before\nafter tracked change\n")
    (repo / "untracked.txt").write_text("new untracked evidence\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for provider in ["glm", "gemini", "deepseek"]:
        script = fake_bin / provider
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, re, sys\n"
            "prompt_arg = sys.argv[-1]\n"
            "print(f'provider={pathlib.Path(sys.argv[0]).name}')\n"
            "print(f'argv_len={len(prompt_arg)}')\n"
            "assert 'after tracked change' not in prompt_arg\n"
            "match = re.search(r'Prompt file: (.+)', prompt_arg)\n"
            "assert match, prompt_arg\n"
            "prompt = pathlib.Path(match.group(1).strip()).read_text()\n"
            "if 'after tracked change' in prompt:\n"
            "    print('tracked-ok')\n"
            "if 'new untracked evidence' in prompt:\n"
            "    print('untracked-ok')\n"
        )
        script.chmod(0o755)

    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": str(fake_bin / "glm"), "timeout": 10},
                    "gemini": {"cli": str(fake_bin / "gemini"), "timeout": 10},
                    "deepseek": {"cli": str(fake_bin / "deepseek"), "timeout": 10},
                },
                "review": {
                    "prompt_template": "Scope: {scope}\n\n{diff}\n\n{files}\n",
                    "default_providers": ["glm", "gemini", "deepseek"],
                },
            }
        )
    )
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm,gemini,deepseek",
            "--scope",
            ".",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    assert review_dir.is_dir()
    assert (review_dir / "prompt.md").read_text().count("after tracked change") >= 1
    assert "new untracked evidence" in (review_dir / "prompt.md").read_text()
    for provider in ["glm", "gemini", "deepseek"]:
        raw = (review_dir / "raw" / f"{provider}.txt").read_text()
        assert "tracked-ok" in raw
        assert "untracked-ok" in raw
    synthesis = (review_dir / "synthesis.md").read_text()
    assert "Trinity Review Synthesis" in synthesis
    assert "raw/glm.txt" in synthesis


def test_codex_review_uses_short_prompt_file_handoff_for_large_diffs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    tracked = repo / "large.txt"
    tracked.write_text("before\n")
    subprocess.run(["git", "add", "large.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    tracked.write_text("large-change\n" + ("x" * 70000) + "\n")

    fake = tmp_path / "provider"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, re, sys\n"
        "prompt_arg = sys.argv[-1]\n"
        "print(f'argv_len={len(prompt_arg)}')\n"
        "assert len(prompt_arg) < 500\n"
        "assert 'large-change' not in prompt_arg\n"
        "match = re.search(r'Prompt file: (.+)', prompt_arg)\n"
        "assert match, prompt_arg\n"
        "prompt = pathlib.Path(match.group(1).strip()).read_text()\n"
        "assert 'large-change' in prompt\n"
        "print('large-prompt-file-ok')\n"
    )
    fake.chmod(0o755)
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake), "timeout": 10}},
                "review": {
                    "prompt_template": "{diff}\n\n{files}\n",
                    "default_providers": ["glm"],
                },
            }
        )
    )

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm",
            "--scope",
            ".",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    raw = (Path(out) / "raw" / "glm.txt").read_text()
    assert "large-prompt-file-ok" in raw


def test_install_codex_installs_skill_config_and_wrapper_without_claude(tmp_path):
    home = tmp_path / "home"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = os.environ["PATH"]

    result = subprocess.run(
        ["make", "install-codex"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (home / ".codex" / "skills" / "trinity" / "SKILL.md").read_text() == (
        CODEX_SKILL.read_text()
    )
    installed_config = json.loads((home / ".codex" / "trinity.json").read_text())
    assert installed_config["providers"]["glm"]["cli"] == "droid exec --model glm-5"
    assert installed_config["providers"]["deepseek"]["cli"] == (
        "droid exec --model deepseek-v4-pro[1m]"
    )
    assert (home / ".codex" / "skills" / "trinity" / "scripts" / "codex.py").exists()
    assert (home / ".local" / "bin" / "trinity").read_text() == CODEX_BIN.read_text()
    assert os.access(home / ".local" / "bin" / "trinity", os.X_OK)
    assert not (home / ".claude").exists()

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


def init_repo(repo):
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def commit_all(repo, message):
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True)


def write_fake_provider(path, marker="provider-ok"):
    path.write_text(f"#!/bin/sh\necho {marker}\n")
    path.chmod(0o755)


def simple_review_config(config, provider):
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(provider), "timeout": 10}},
                "review": {
                    "prompt_template": "Scope: {scope}\n\n{diff}\n\n{files}\n",
                    "default_providers": ["glm"],
                },
            }
        )
    )


def simple_repo(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("before\n")
    commit_all(repo, "init")
    tracked.write_text("before\nafter\n")
    return repo


def write_named_fake_providers(fake_bin, providers):
    fake_bin.mkdir()
    for provider in providers:
        script = fake_bin / provider
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, re, sys\n"
            "provider = pathlib.Path(sys.argv[0]).name\n"
            "print(f'provider={provider}')\n"
            "match = re.search(r'Prompt file: (.+)', sys.argv[-1])\n"
            "assert match, sys.argv[-1]\n"
            "prompt = pathlib.Path(match.group(1).strip()).read_text()\n"
            "if 'after' in prompt:\n"
            "    print('prompt-ok')\n"
        )
        script.chmod(0o755)


def preset_review_config(config, fake_bin):
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": str(fake_bin / "glm"), "timeout": 10},
                    "deepseek": {"cli": str(fake_bin / "deepseek"), "timeout": 10},
                    "codex": {"cli": str(fake_bin / "codex"), "timeout": 10},
                },
                "review": {
                    "prompt_template": "Scope: {scope}\n\n{diff}\n\n{files}\n",
                    "default_providers": ["glm"],
                    "default_preset": "fast-review",
                },
                "presets": {
                    "fast-review": {
                        "providers": ["glm", "deepseek"],
                        "task_type": "review",
                    },
                    "deep-review": {
                        "providers": ["deepseek"],
                        "optional_providers": ["codex", "missing"],
                        "task_type": "review",
                    },
                },
                "preset_aliases": {
                    "fr": "fast-review",
                    "dr": "deep-review",
                },
            }
        )
    )


def test_codex_default_config_has_direct_review_providers():
    data = json.loads(CODEX_CONFIG.read_text())

    assert data["providers"]["glm"] == {
        "cli": "droid exec --auto medium --model custom:GLM-5.2",
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
        "cli": "~/.codex/skills/trinity/bin/deepseek -p",
        "supports_resume": True,
        "resume_arg": "-r",
        "timeout": 600,
    }
    assert data["review"]["default_providers"] == ["glm", "gemini", "deepseek"]
    assert data["review"]["default_preset"] == "review"
    assert "{diff}" in data["review"]["prompt_template"]
    assert "{files}" in data["review"]["prompt_template"]
    assert data["presets"]["review"] == {
        "providers": ["glm", "gemini", "deepseek"],
        "optional_providers": ["codex", "claude-code"],
        "task_type": "review",
    }
    assert data["presets"]["fast-review"] == {
        "providers": ["glm", "deepseek"],
        "task_type": "review",
    }
    assert data["presets"]["deep-review"] == {
        "providers": ["glm", "gemini", "deepseek"],
        "optional_providers": ["codex", "claude-code"],
        "task_type": "review",
    }
    assert data["preset_aliases"] == {
        "r": "review",
        "fr": "fast-review",
        "dr": "deep-review",
    }


def test_claude_code_install_path_remains_unchanged():
    makefile = MAKEFILE.read_text()
    install_sh = INSTALL_SH.read_text()
    root_skill = CLAUDE_SKILL.read_text()

    assert "install:        ## Install Trinity to ~/.claude/" in makefile
    assert "cp SKILL.md ~/.claude/skills/trinity/SKILL.md" in makefile
    assert "--global-config ~/.claude/trinity.json" in makefile
    assert "${HOME}/.claude/trinity.json" in install_sh
    assert (
        ".claude/skills/trinity/SKILL.md"
        in (ROOT / "install-manifest.json").read_text()
    )

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


def test_codex_review_explicit_preset_expands_required_and_optional_providers(
    tmp_path,
):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek", "codex"])
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--preset",
            "deep-review",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    assert "optional provider 'missing' skipped: missing config" in err
    review_dir = Path(out)
    assert not (review_dir / "raw" / "glm.txt").exists()
    for provider in ["deepseek", "codex"]:
        raw = (review_dir / "raw" / f"{provider}.txt").read_text()
        assert f"provider={provider}" in raw
        assert "prompt-ok" in raw
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["providers"] == ["deepseek", "codex"]
    assert metadata["preset"] == {
        "requested": "deep-review",
        "resolved": "deep-review",
        "source": "explicit",
        "task_type": "review",
        "skipped_optional_providers": [
            {"provider": "missing", "reason": "missing config"}
        ],
        # TRN-3021: REQUIRED/OPTIONAL provider lists for doctor metadata-aware rendering.
        "providers": ["deepseek"],
        "optional_providers": ["codex", "missing"],
    }


def test_codex_review_preset_alias_resolves(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek", "codex"])
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--preset",
            "fr",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    assert (review_dir / "raw" / "glm.txt").exists()
    assert (review_dir / "raw" / "deepseek.txt").exists()
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["providers"] == ["glm", "deepseek"]
    assert metadata["preset"]["requested"] == "fr"
    assert metadata["preset"]["resolved"] == "fast-review"
    assert metadata["preset"]["source"] == "explicit"


def test_codex_review_default_preset_wins_over_default_providers(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek", "codex"])
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    assert (review_dir / "raw" / "glm.txt").exists()
    assert (review_dir / "raw" / "deepseek.txt").exists()
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["providers"] == ["glm", "deepseek"]
    assert metadata["preset"]["resolved"] == "fast-review"
    assert metadata["preset"]["source"] == "default"


def test_codex_review_providers_override_preset_with_warning(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek", "codex"])
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm",
            "--preset",
            "deep-review",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    assert "--providers supplied; ignoring --preset 'deep-review'" in err
    review_dir = Path(out)
    assert (review_dir / "raw" / "glm.txt").exists()
    assert not (review_dir / "raw" / "deepseek.txt").exists()
    assert not (review_dir / "raw" / "codex.txt").exists()
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["providers"] == ["glm"]
    assert metadata["preset"]["source"] == "providers"


def test_codex_review_legacy_default_providers_still_work_without_presets(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
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
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    metadata = json.loads((Path(out) / "metadata.json").read_text())
    assert metadata["providers"] == ["glm"]
    assert metadata["preset"]["source"] == "default_providers"
    assert metadata["preset"]["resolved"] is None


def test_codex_review_unknown_preset_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek", "codex"])
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--preset",
            "missing",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: unknown preset 'missing'" in err
    assert not out_dir.exists()


def test_codex_review_invalid_preset_alias_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "review"},
                "presets": {"review": {"providers": ["glm"]}},
                "preset_aliases": {"r": "fr", "fr": "review"},
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
            "--preset",
            "r",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: preset alias 'r' points to another alias" in err
    assert not out_dir.exists()


def test_codex_review_invalid_task_type_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "review"},
                "presets": {"review": {"providers": ["glm"], "task_type": "security"}},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: preset 'review' has invalid task_type 'security'" in err
    assert not out_dir.exists()


def test_codex_review_missing_default_preset_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "missing"},
                "presets": {"review": {"providers": ["glm"]}},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: review.default_preset 'missing' not found" in err
    assert not out_dir.exists()


def test_codex_review_empty_preset_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "review"},
                "presets": {"review": {"providers": []}},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: preset 'review' has no providers" in err
    assert not out_dir.exists()


def test_codex_review_alias_collision_fails_before_review_dir(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "review"},
                "presets": {"review": {"providers": ["glm"]}},
                "preset_aliases": {"glm": "review"},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: preset alias 'glm' collides with provider" in err
    assert not out_dir.exists()


def test_codex_review_alias_collision_status_subcommand(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": str(fake_bin / "glm"), "timeout": 10}},
                "review": {"default_preset": "review"},
                "presets": {"review": {"providers": ["glm"]}},
                "preset_aliases": {"status": "review"},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: preset alias 'status' collides with subcommand" in err
    assert not out_dir.exists()


def test_codex_review_optional_provider_with_empty_cli_is_skipped(tmp_path):
    repo = simple_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": str(fake_bin / "glm"), "timeout": 10},
                    "codex": {"cli": " ", "timeout": 10},
                },
                "review": {"default_preset": "review"},
                "presets": {
                    "review": {
                        "providers": ["glm"],
                        "optional_providers": ["codex"],
                    }
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
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    assert "optional provider 'codex' skipped: missing cli" in err
    metadata = json.loads((Path(out) / "metadata.json").read_text())
    assert metadata["providers"] == ["glm"]
    assert metadata["preset"]["skipped_optional_providers"] == [
        {"provider": "codex", "reason": "missing cli"}
    ]


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


def test_codex_review_strict_cor1602_cor1609_prompt_and_metadata(tmp_path):
    repo = simple_repo(tmp_path)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm",
            "--sop",
            "COR-1602",
            "--rubric",
            "COR-1609",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "## Strict COR Review Mode" in prompt
    assert "SOP: COR-1602" in prompt
    assert "Rubric: COR-1609" in prompt
    assert "PASS threshold: 9.0/10" in prompt
    assert "Correctness | 25%" in prompt
    assert "Completeness | 25%" in prompt
    assert "TDD Plan Quality | 20%" in prompt
    assert "Rollback Safety | 15%" in prompt
    assert "### Decision Matrix" in prompt
    assert "**Weighted Average: X.X/10 - PASS/FIX**" in prompt
    assert "COR-1611" in prompt
    assert "## Review-Only Mode" in prompt
    assert prompt.index("## Strict COR Review Mode") < prompt.index(
        "## Review-Only Mode"
    )
    assert prompt.index("## Review-Only Mode") < prompt.index("## Review Artifact")
    assert "after" in prompt

    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["strict_review"] == {
        "enabled": True,
        "sop": "COR-1602",
        "rubric": "COR-1609",
        "pass_threshold": 9.0,
        "calibration": "COR-1611",
        "decision_rule": (
            "PASS when weighted_average >= 9.0 and no blocking findings remain; "
            "otherwise FIX."
        ),
        "output_schema": [
            "### Findings",
            "### Decision Matrix",
            "**Weighted Average: X.X/10 - PASS/FIX**",
        ],
    }


def test_codex_review_strict_mode_requires_sop_and_rubric_pair(tmp_path):
    repo = simple_repo(tmp_path)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)

    cases = [
        ("sop-only", ["--sop", "COR-1602"]),
        ("rubric-only", ["--rubric", "COR-1609"]),
    ]
    for label, flags in cases:
        out_dir = tmp_path / f"reviews-{label}"
        rc, out, err = run_codex(
            [
                "review",
                "--root",
                str(repo),
                "--config",
                str(config),
                "--providers",
                "glm",
                *flags,
                "--out-dir",
                str(out_dir),
            ]
        )

        assert rc == 1
        assert out == ""
        assert "trinity: --sop and --rubric must be used together" in err
        assert not out_dir.exists()


def test_codex_review_strict_mode_rejects_invalid_doc_id_format(tmp_path):
    repo = simple_repo(tmp_path)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm",
            "--sop",
            "COR1602",
            "--rubric",
            "COR-1609",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity: --sop must look like COR-1602" in err
    assert not out_dir.exists()


def test_codex_review_strict_mode_rejects_unsupported_template(tmp_path):
    repo = simple_repo(tmp_path)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--providers",
            "glm",
            "--sop",
            "COR-1602",
            "--rubric",
            "COR-1610",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert (
        "trinity: unsupported strict review template: SOP COR-1602 with rubric COR-1610"
        in err
    )
    assert not out_dir.exists()


def test_codex_review_strict_mode_combines_with_pr_and_preset(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("base version\n")
    commit_all(repo, "base")
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    tracked.write_text("strict pr head snapshot\n")
    commit_all(repo, "feature change")
    head_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek"])
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['pr', 'diff', '456']:\n"
        "    print('diff --git a/review.txt b/review.txt')\n"
        "    print('+from mocked strict gh pr diff')\n"
        "elif args[:3] == ['pr', 'view', '456']:\n"
        "    print(json.dumps({\n"
        "        'number': 456,\n"
        "        'url': 'https://github.example/pr/456',\n"
        "        'baseRefName': 'main',\n"
        "        'headRefName': 'feature',\n"
        f"        'headRefOid': '{head_oid}',\n"
        "        'files': [{'path': 'review.txt', 'changeType': 'MODIFIED'}],\n"
        "    }))\n"
        "else:\n"
        "    raise SystemExit(f'unexpected gh args: {args}')\n"
    )
    gh.chmod(0o755)
    config = tmp_path / "codex.json"
    preset_review_config(config, fake_bin)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--preset",
            "fr",
            "--pr",
            "456",
            "--sop",
            "COR-1602",
            "--rubric",
            "COR-1609",
            "--out-dir",
            str(tmp_path / "reviews"),
        ],
        env=env,
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "from mocked strict gh pr diff" in prompt
    assert "strict pr head snapshot" in prompt
    assert "## Strict COR Review Mode" in prompt
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["providers"] == ["glm", "deepseek"]
    assert metadata["preset"]["resolved"] == "fast-review"
    assert metadata["input"]["pr"] == 456
    assert metadata["input"]["head_oid"] == head_oid
    assert metadata["strict_review"]["sop"] == "COR-1602"
    assert metadata["strict_review"]["rubric"] == "COR-1609"


def test_codex_review_strict_mode_combines_with_base_head(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("base version\n")
    commit_all(repo, "base")
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    tracked.write_text("strict base-head snapshot\n")
    commit_all(repo, "feature change")

    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--base",
            "main",
            "--head",
            "feature",
            "--sop",
            "COR-1602",
            "--rubric",
            "COR-1609",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "strict base-head snapshot" in prompt
    assert "## Strict COR Review Mode" in prompt
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["input"]["mode"] == "base-head"
    assert metadata["input"]["base"] == "main"
    assert metadata["input"]["head"] == "feature"
    assert metadata["strict_review"]["sop"] == "COR-1602"
    assert metadata["strict_review"]["rubric"] == "COR-1609"


def test_codex_review_base_head_collects_committed_diff_and_head_snapshots(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("base version\n")
    commit_all(repo, "base")
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    tracked.write_text("feature committed version\n")
    commit_all(repo, "feature change")
    tracked.write_text("dirty local version must not leak\n")
    (repo / "untracked.txt").write_text("untracked local must not leak\n")

    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--base",
            "main",
            "--head",
            "feature",
            "--out-dir",
            str(tmp_path / "reviews"),
        ]
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "feature committed version" in prompt
    assert "base version" in prompt
    assert "dirty local version must not leak" not in prompt
    assert "untracked local must not leak" not in prompt
    metadata = json.loads((review_dir / "metadata.json").read_text())
    review_input_sha256 = metadata["input"].pop("review_input_sha256")
    assert len(review_input_sha256) == 64
    assert metadata["input"] == {
        "mode": "base-head",
        "base": "main",
        "head": "feature",
        "pr": None,
        "scope": ".",
        "changed_paths": ["review.txt"],
        "snapshot_source": "git:feature",
    }


def test_codex_review_base_head_fails_before_review_dir_for_bad_ref(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "review.txt").write_text("base version\n")
    commit_all(repo, "base")
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--base",
            "main",
            "--head",
            "missing-head",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "unable to collect git diff for main...missing-head" in err
    assert not out_dir.exists()


def test_codex_review_base_head_requires_base_and_head_together(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "review.txt").write_text("base version\n")
    commit_all(repo, "base")
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    out_dir = tmp_path / "reviews"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--base",
            "main",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "trinity-codex: --base and --head must be used together" in err
    assert not out_dir.exists()


def test_codex_review_pr_uses_gh_diff_view_and_head_snapshots(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("base version\n")
    commit_all(repo, "base")
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    tracked.write_text("pr head snapshot\n")
    commit_all(repo, "feature change")
    head_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['pr', 'diff', '123']:\n"
        "    print('diff --git a/review.txt b/review.txt')\n"
        "    print('+from mocked gh pr diff')\n"
        "elif args[:3] == ['pr', 'view', '123']:\n"
        "    print(json.dumps({\n"
        "        'number': 123,\n"
        "        'url': 'https://github.example/pr/123',\n"
        "        'baseRefName': 'main',\n"
        "        'headRefName': 'feature',\n"
        f"        'headRefOid': '{head_oid}',\n"
        "        'files': [{'path': 'review.txt', 'changeType': 'MODIFIED'}],\n"
        "    }))\n"
        "else:\n"
        "    raise SystemExit(f'unexpected gh args: {args}')\n"
    )
    gh.chmod(0o755)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--pr",
            "123",
            "--out-dir",
            str(tmp_path / "reviews"),
        ],
        env=env,
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "from mocked gh pr diff" in prompt
    assert "pr head snapshot" in prompt
    metadata = json.loads((review_dir / "metadata.json").read_text())
    review_input_sha256 = metadata["input"].pop("review_input_sha256")
    assert len(review_input_sha256) == 64
    assert metadata["input"] == {
        "mode": "pr",
        "base": "main",
        "head": "feature",
        "head_oid": head_oid,
        "pr": 123,
        "pr_url": "https://github.example/pr/123",
        "scope": ".",
        "changed_paths": ["review.txt"],
        "snapshot_source": f"git:{head_oid}",
    }


def test_codex_review_pr_records_unavailable_head_snapshots(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "review.txt").write_text("base version\n")
    commit_all(repo, "base")
    missing_oid = "0" * 40

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['pr', 'diff', '123']:\n"
        "    print('diff --git a/review.txt b/review.txt')\n"
        "    print('+from mocked gh pr diff')\n"
        "elif args[:3] == ['pr', 'view', '123']:\n"
        "    print(json.dumps({\n"
        "        'number': 123,\n"
        "        'url': 'https://github.example/pr/123',\n"
        "        'baseRefName': 'main',\n"
        "        'headRefName': 'feature',\n"
        f"        'headRefOid': '{missing_oid}',\n"
        "        'files': [{'path': 'review.txt', 'changeType': 'MODIFIED'}],\n"
        "    }))\n"
        "else:\n"
        "    raise SystemExit(f'unexpected gh args: {args}')\n"
    )
    gh.chmod(0o755)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--pr",
            "123",
            "--out-dir",
            str(tmp_path / "reviews"),
        ],
        env=env,
    )

    assert rc == 0, err
    review_dir = Path(out)
    prompt = (review_dir / "prompt.md").read_text()
    assert "from mocked gh pr diff" in prompt
    assert "(PR head snapshots unavailable locally)" in prompt
    metadata = json.loads((review_dir / "metadata.json").read_text())
    assert metadata["input"]["snapshot_source"] == "unavailable"
    assert metadata["input"]["changed_paths"] == ["review.txt"]


def test_codex_review_pr_fails_before_review_dir_when_gh_fails(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "review.txt").write_text("base\n")
    commit_all(repo, "base")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("#!/bin/sh\necho gh auth failed >&2\nexit 4\n")
    gh.chmod(0o755)
    provider = tmp_path / "provider"
    write_fake_provider(provider)
    config = tmp_path / "codex.json"
    simple_review_config(config, provider)
    out_dir = tmp_path / "reviews"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    rc, out, err = run_codex(
        [
            "review",
            "--root",
            str(repo),
            "--config",
            str(config),
            "--pr",
            "123",
            "--out-dir",
            str(out_dir),
        ],
        env=env,
    )

    assert rc == 1
    assert out == ""
    assert "trinity-codex: gh pr view 123 failed: gh auth failed" in err
    assert not out_dir.exists()


def test_codex_doctor_reports_provider_health_failures(tmp_path):
    fake = tmp_path / "fake"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("#!/bin/sh\nexit 0\n")
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "empty": {"cli": "", "timeout": 10},
                    "missing": {"cli": "missing-trinity-provider-cmd", "timeout": 10},
                    "not_exec": {"cli": str(not_executable), "timeout": 10},
                    "bad_timeout": {"cli": str(fake), "timeout": 0},
                },
                "review": {"default_providers": []},
            }
        )
    )

    rc, out, err = run_codex(
        [
            "doctor",
            "--config",
            str(config),
            "--providers",
            "empty,missing,not_exec,bad_timeout,unknown",
        ]
    )

    assert rc == 1
    report = out + err
    assert "empty: FAIL - missing cli" in report
    assert "missing: FAIL - command not found: missing-trinity-provider-cmd" in report
    assert f"not_exec: FAIL - not executable: {not_executable}" in report
    assert "bad_timeout: FAIL - invalid timeout: 0" in report
    assert "unknown: FAIL - unknown provider" in report


def test_codex_doctor_passes_healthy_provider(tmp_path):
    fake = tmp_path / "fake-provider"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "healthy": {"cli": f"{fake} --unused-arg", "timeout": "10"}
                },
                "review": {"default_providers": ["healthy"]},
            }
        )
    )

    rc, out, err = run_codex(["doctor", "--config", str(config)])

    assert rc == 0, err
    assert f"healthy: OK - {fake} (timeout 10s)" in out


def test_codex_doctor_uses_default_preset_when_no_providers_supplied(tmp_path):
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": str(fake_bin / "glm"), "timeout": 10},
                    "deepseek": {"cli": str(fake_bin / "deepseek"), "timeout": 10},
                },
                "review": {
                    "default_preset": "fast-review",
                    "default_providers": [],
                },
                "presets": {
                    "fast-review": {
                        "providers": ["glm", "deepseek"],
                        "task_type": "review",
                    }
                },
            }
        )
    )

    rc, out, err = run_codex(["doctor", "--config", str(config)])

    assert rc == 0, err
    assert f"glm: OK - {fake_bin / 'glm'} (timeout 10s)" in out
    assert f"deepseek: OK - {fake_bin / 'deepseek'} (timeout 10s)" in out


def test_codex_doctor_accepts_preset_alias(tmp_path):
    fake_bin = tmp_path / "bin"
    write_named_fake_providers(fake_bin, ["glm", "deepseek"])
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": str(fake_bin / "glm"), "timeout": 10},
                    "deepseek": {"cli": str(fake_bin / "deepseek"), "timeout": 10},
                },
                "review": {"default_providers": []},
                "presets": {"fast-review": {"providers": ["glm", "deepseek"]}},
                "preset_aliases": {"fr": "fast-review"},
            }
        )
    )

    rc, out, err = run_codex(["doctor", "--config", str(config), "--preset", "fr"])

    assert rc == 0, err
    assert f"glm: OK - {fake_bin / 'glm'} (timeout 10s)" in out
    assert f"deepseek: OK - {fake_bin / 'deepseek'} (timeout 10s)" in out


def test_codex_doctor_resolves_relative_provider_cli_from_git_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    nested = repo / "nested"
    nested.mkdir()
    tools = repo / "tools"
    tools.mkdir()
    provider = tools / "provider"
    provider.write_text("#!/bin/sh\nexit 0\n")
    provider.chmod(0o755)
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"relative": {"cli": "./tools/provider", "timeout": 10}},
                "review": {"default_providers": ["relative"]},
            }
        )
    )

    rc, out, err = run_codex(["doctor", "--root", str(nested), "--config", str(config)])

    assert rc == 0, err
    assert f"relative: OK - {provider} (timeout 10s)" in out


def test_codex_review_preflights_provider_health_before_creating_review(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    config = tmp_path / "codex.json"
    config.write_text(
        json.dumps(
            {
                "providers": {
                    "missing": {"cli": "missing-trinity-provider-cmd", "timeout": 10}
                },
                "review": {"default_providers": ["missing"]},
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    assert out == ""
    assert "missing: FAIL - command not found: missing-trinity-provider-cmd" in err
    assert not out_dir.exists()


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
    deepseek_wrapper = home / ".codex" / "skills" / "trinity" / "bin" / "deepseek"
    installed_config = json.loads((home / ".codex" / "trinity.json").read_text())
    assert (
        installed_config["providers"]["glm"]["cli"]
        == "droid exec --auto medium --model custom:GLM-5.2"
    )
    assert installed_config["providers"]["deepseek"]["cli"] == (
        "~/.codex/skills/trinity/bin/deepseek -p"
    )
    assert installed_config["review"]["default_preset"] == "review"
    assert installed_config["presets"]["fast-review"]["providers"] == [
        "glm",
        "deepseek",
    ]
    assert installed_config["presets"]["deep-review"]["providers"] == [
        "glm",
        "gemini",
        "deepseek",
    ]
    assert installed_config["preset_aliases"]["dr"] == "deep-review"
    assert deepseek_wrapper.exists()
    assert os.access(deepseek_wrapper, os.X_OK)
    assert (home / ".codex" / "skills" / "trinity" / "scripts" / "codex.py").exists()
    assert (home / ".local" / "bin" / "trinity").read_text() == CODEX_BIN.read_text()
    assert os.access(home / ".local" / "bin" / "trinity", os.X_OK)
    assert not (home / ".claude").exists()

    # TRN-3021 doctor now checks deepseek wrapper auth via env-or-file
    # precedence (mirrors providers/bin/deepseek:10-31). Set the env var
    # to satisfy the auth check without writing a real key file in the
    # test environment.
    doctor_env = dict(env)
    doctor_env["DEEPSEEK_API_KEY"] = "test-key"
    rc, out, err = run_codex(
        [
            "doctor",
            "--config",
            str(home / ".codex" / "trinity.json"),
            "--providers",
            "deepseek",
        ],
        env=doctor_env,
    )

    assert rc == 0, err
    assert f"deepseek: OK - {deepseek_wrapper} (timeout 600s)" in out


def test_strict_cor_reviewer_at_9_2_passes():
    """Surface 9: under strict COR template (threshold 9.0), a 9.2/PASS verdict is NOT FIX-coerced."""
    import json as _json
    from pathlib import Path as _Path
    import sys as _sys

    _ROOT = _Path(__file__).resolve().parent.parent
    if str(_ROOT / "scripts") not in _sys.path:
        _sys.path.insert(0, str(_ROOT / "scripts"))
    import codex as _codex_mod

    payload = _json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.2,
            "blocking": [],
            "advisories": [],
        }
    )
    raw = f"```json\n{payload}\n```"
    result = _codex_mod.parse_structured_review(raw, pass_threshold=9.0)
    assert result is not None
    assert result["effective_decision"] == "PASS"


def test_fast_review_panel_at_9_4_coerces_to_FIX():
    """Surface 9b: with no strict template (default 9.5), 9.4/PASS is FIX-coerced."""
    import json as _json
    from pathlib import Path as _Path
    import sys as _sys

    _ROOT = _Path(__file__).resolve().parent.parent
    if str(_ROOT / "scripts") not in _sys.path:
        _sys.path.insert(0, str(_ROOT / "scripts"))
    import codex as _codex_mod

    payload = _json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.4,
            "blocking": [],
            "advisories": [],
        }
    )
    raw = f"```json\n{payload}\n```"
    result = _codex_mod.parse_structured_review(raw)
    assert result is not None
    assert result["effective_decision"] == "FIX"


def test_parse_structured_review_default_threshold():
    """Surface 9c: parse_structured_review with no kwarg uses _REVIEW_PASS_THRESHOLD (9.5)."""
    import json as _json
    from pathlib import Path as _Path
    import sys as _sys

    _ROOT = _Path(__file__).resolve().parent.parent
    if str(_ROOT / "scripts") not in _sys.path:
        _sys.path.insert(0, str(_ROOT / "scripts"))
    import codex as _codex_mod

    # Score 9.5 should PASS (>= 9.5)
    payload_pass = _json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.5,
            "blocking": [],
            "advisories": [],
        }
    )
    raw_pass = f"```json\n{payload_pass}\n```"
    result_pass = _codex_mod.parse_structured_review(raw_pass)
    assert result_pass["effective_decision"] == "PASS"
    # Score 9.4 should FIX (< 9.5)
    payload_fix = _json.dumps(
        {
            "decision": "PASS",
            "weighted_score": 9.4,
            "blocking": [],
            "advisories": [],
        }
    )
    raw_fix = f"```json\n{payload_fix}\n```"
    result_fix = _codex_mod.parse_structured_review(raw_fix)
    assert result_fix["effective_decision"] == "FIX"


def test_init_config_warns_on_undeclared_custom_model(tmp_path):
    """codex init-config must surface the BYOK custom-model prerequisite —
    custom:GLM-5.2 needs an explicit ~/.factory/settings.json customModels
    entry, mirroring the install.py register path so Codex installs get the
    same guidance instead of failing on first dispatch (PR #228 review)."""
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(home)
    cfg = home / ".codex" / "trinity.json"
    rc, out, err = run_codex(["init-config", "--global-config", str(cfg)], env=env)
    assert rc == 0
    assert cfg.exists()
    assert "custom:GLM-5.2" in err
    assert "glm" in err


def test_init_config_no_warn_when_custom_model_declared(tmp_path):
    """No warning once the explicit customModels id is declared in
    ~/.factory/settings.json."""
    home = tmp_path / "home"
    (home / ".factory").mkdir(parents=True)
    (home / ".factory" / "settings.json").write_text(
        json.dumps({"customModels": [{"id": "custom:GLM-5.2"}]})
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    cfg = home / ".codex" / "trinity.json"
    rc, out, err = run_codex(["init-config", "--global-config", str(cfg)], env=env)
    assert rc == 0
    assert "custom:GLM-5.2" not in err

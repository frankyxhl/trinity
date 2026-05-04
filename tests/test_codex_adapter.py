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
        "cli": "~/.codex/skills/trinity/bin/deepseek -p",
        "supports_resume": True,
        "resume_arg": "-r",
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
    assert installed_config["providers"]["glm"]["cli"] == "droid exec --model glm-5"
    assert installed_config["providers"]["deepseek"]["cli"] == (
        "~/.codex/skills/trinity/bin/deepseek -p"
    )
    assert deepseek_wrapper.exists()
    assert os.access(deepseek_wrapper, os.X_OK)
    assert (home / ".codex" / "skills" / "trinity" / "scripts" / "codex.py").exists()
    assert (home / ".local" / "bin" / "trinity").read_text() == CODEX_BIN.read_text()
    assert os.access(home / ".local" / "bin" / "trinity", os.X_OK)
    assert not (home / ".claude").exists()

    rc, out, err = run_codex(
        [
            "doctor",
            "--config",
            str(home / ".codex" / "trinity.json"),
            "--providers",
            "deepseek",
        ],
        env=env,
    )

    assert rc == 0, err
    assert f"deepseek: OK - {deepseek_wrapper} (timeout 600s)" in out

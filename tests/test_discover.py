"""Tests for trinity/scripts/discover.py"""

import json
import subprocess
import sys
import pytest
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "discover.py"


@pytest.fixture(autouse=True)
def patch_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


def run(args):
    """Run the discover script with given args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def write_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def write_agent(project_dir, name):
    """Write a trinity-<name>.md agent file in project .claude/agents/."""
    agent_dir = project_dir / ".claude" / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agent_dir / f"trinity-{name}.md"
    agent_file.write_text(f"# trinity-{name} agent")
    return str(agent_file)


def write_global_agent(global_agents_dir, name):
    """Write a trinity-<name>.md agent file in global agents dir."""
    global_agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = global_agents_dir / f"trinity-{name}.md"
    agent_file.write_text(f"# trinity-{name} global agent")
    return str(agent_file)


# --- list ---


def test_empty_config_no_agent_files_returns_empty(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result == []


def test_config_entry_with_agent_file_is_usable(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    write_config(
        project_dir / ".claude" / "trinity.json",
        {"providers": {"glm": {"cli": "droid exec --model glm-5"}}},
    )
    write_agent(project_dir, "glm")
    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == "glm"
    assert entry["status"] == "usable"
    assert entry["cli"] == "droid exec --model glm-5"
    assert entry["agent"] is not None


def test_config_entry_no_agent_file_is_missing_agent(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    write_config(
        project_dir / ".claude" / "trinity.json",
        {"providers": {"glm": {"cli": "droid exec --model glm-5"}}},
    )
    # no agent file written
    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == "glm"
    assert entry["status"] == "missing_agent"
    assert entry["cli"] == "droid exec --model glm-5"
    assert entry["agent"] is None


def test_agent_file_no_config_entry_is_missing_config(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    # no config entry, just agent file
    write_agent(project_dir, "glm")
    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == "glm"
    assert entry["status"] == "missing_config"
    assert entry["cli"] is None
    assert entry["agent"] is not None


def test_project_agent_takes_precedence_over_global(tmp_path, patch_home):
    global_agents_dir = patch_home / ".claude" / "agents"
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"

    write_config(
        project_dir / ".claude" / "trinity.json",
        {"providers": {"glm": {"cli": "droid exec --model glm-5"}}},
    )
    project_agent_path = write_agent(project_dir, "glm")
    write_global_agent(global_agents_dir, "glm")

    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert len(result) == 1
    entry = result[0]
    # Project agent path should be used
    assert entry["agent"] == project_agent_path


def test_output_sorted_usable_then_missing_agent_then_missing_config(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"

    write_config(
        project_dir / ".claude" / "trinity.json",
        {
            "providers": {
                "glm": {"cli": "droid exec"},
                "codex": {"cli": "codex exec"},  # missing_agent
            }
        },
    )
    # glm has agent file -> usable
    write_agent(project_dir, "glm")
    # gemini has agent file but no config -> missing_config
    write_agent(project_dir, "gemini")
    # codex has config but no agent -> missing_agent

    rc, out, err = run(
        [
            "list",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    statuses = [e["status"] for e in result]

    # usable first, then missing_agent, then missing_config
    usable_idxs = [i for i, s in enumerate(statuses) if s == "usable"]
    missing_agent_idxs = [i for i, s in enumerate(statuses) if s == "missing_agent"]
    missing_config_idxs = [i for i, s in enumerate(statuses) if s == "missing_config"]

    assert all(u < m for u in usable_idxs for m in missing_agent_idxs)
    assert all(u < m for u in usable_idxs for m in missing_config_idxs)
    assert all(a < c for a in missing_agent_idxs for c in missing_config_idxs)


# --- version ---


def test_version_returns_parseable_semver():
    rc, out, err = run(["--version"])
    assert rc == 0
    parts = out.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)

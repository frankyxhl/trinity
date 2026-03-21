"""Tests for trinity/scripts/config.py"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "config.py"


def run(args):
    """Run the config script with given args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def write_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# --- merge ---


def test_missing_both_files_returns_empty(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # stdout must be valid JSON when stripped
    assert json.loads(result.stdout.strip()) == {}
    # stdout should not have a double trailing newline
    assert not result.stdout.endswith("\n\n"), (
        "output should not have a double trailing newline"
    )


def test_global_only_returns_global_no_sessions(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(
        global_config,
        {
            "providers": {"glm": {"cli": "droid"}},
            "defaults": {"timeout": 60},
            "sessions": {"glm": {"session_id": "should-not-appear"}},
        },
    )
    project_dir = tmp_path / "project"
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["providers"]["glm"]["cli"] == "droid"
    assert result["defaults"]["timeout"] == 60
    assert "sessions" not in result


def test_project_only_returns_project(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(
        project_trinity,
        {"providers": {"codex": {"cli": "codex exec"}}, "defaults": {"model": "gpt-5"}},
    )
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["providers"]["codex"]["cli"] == "codex exec"
    assert result["defaults"]["model"] == "gpt-5"


def test_providers_project_key_wins_on_conflict(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(
        global_config,
        {
            "providers": {
                "glm": {"cli": "droid-global"},
                "codex": {"cli": "codex-global"},
            }
        },
    )
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(project_trinity, {"providers": {"glm": {"cli": "droid-project"}}})
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["providers"]["glm"]["cli"] == "droid-project"
    assert result["providers"]["codex"]["cli"] == "codex-global"


def test_defaults_project_wins_per_key(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(global_config, {"defaults": {"timeout": 60, "model": "global-model"}})
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(project_trinity, {"defaults": {"timeout": 120}})
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["defaults"]["timeout"] == 120


def test_defaults_missing_project_key_inherits_from_global(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(global_config, {"defaults": {"timeout": 60, "model": "global-model"}})
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(project_trinity, {"defaults": {"timeout": 120}})
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["defaults"]["model"] == "global-model"


def test_defaults_project_null_overrides_global(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(global_config, {"defaults": {"timeout": 60}})
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(project_trinity, {"defaults": {"timeout": None}})
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert "timeout" in result["defaults"]
    assert result["defaults"]["timeout"] is None


def test_defaults_project_array_replaces_global_array(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    write_config(global_config, {"defaults": {"tags": ["a", "b"]}})
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    write_config(project_trinity, {"defaults": {"tags": ["c"]}})
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 0
    result = json.loads(out)
    assert result["defaults"]["tags"] == ["c"]


def test_invalid_json_in_global_exits_1(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text("{ bad json }")
    project_dir = tmp_path / "project"
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 1
    assert (
        "trinity-scripts" in err or "invalid JSON" in err or str(global_config) in err
    )


def test_invalid_json_in_project_exits_1(tmp_path):
    global_config = tmp_path / "global" / "trinity.json"
    project_dir = tmp_path / "project"
    project_trinity = project_dir / ".claude" / "trinity.json"
    project_trinity.parent.mkdir(parents=True, exist_ok=True)
    project_trinity.write_text("not json at all")
    rc, out, err = run(
        [
            "merge",
            "--global-config",
            str(global_config),
            "--project-dir",
            str(project_dir),
        ]
    )
    assert rc == 1
    assert (
        "trinity-scripts" in err or "invalid JSON" in err or str(project_trinity) in err
    )


# --- version ---


def test_version_returns_parseable_semver():
    rc, out, err = run(["--version"])
    assert rc == 0
    parts = out.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)

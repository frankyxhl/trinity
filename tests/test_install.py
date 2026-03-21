"""Tests for trinity/scripts/install.py"""
import json
import subprocess
import sys
import concurrent.futures
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "install.py"


def run(args):
    """Run the install script with given args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def global_config_path(tmp_path):
    return tmp_path / "trinity.json"


# --- register ---

def test_register_creates_providers_entry_in_new_file(tmp_path):
    cfg = global_config_path(tmp_path)
    rc, out, err = run(["register", "glm", "--cli", "droid exec --model glm-5", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == "droid exec --model glm-5"
    assert data["providers"]["glm"]["installed"] is True


def test_register_idempotent_second_call_updates_cli(tmp_path):
    cfg = global_config_path(tmp_path)
    run(["register", "glm", "--cli", "droid-v1", "--global-config", str(cfg)])
    rc, out, err = run(["register", "glm", "--cli", "droid-v2", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == "droid-v2"


def test_register_preserves_existing_providers(tmp_path):
    cfg = global_config_path(tmp_path)
    cfg.write_text(json.dumps({"providers": {"codex": {"cli": "codex exec", "installed": True}}}))
    rc, out, err = run(["register", "glm", "--cli", "droid exec", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["codex"]["cli"] == "codex exec"
    assert data["providers"]["glm"]["cli"] == "droid exec"


def test_cli_with_spaces_preserved_verbatim(tmp_path):
    cfg = global_config_path(tmp_path)
    cli_str = "droid exec --model glm-5 --some-flag with spaces"
    rc, out, err = run(["register", "glm", "--cli", cli_str, "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == cli_str


# --- unregister ---

def test_unregister_removes_provider(tmp_path):
    cfg = global_config_path(tmp_path)
    cfg.write_text(json.dumps({
        "providers": {
            "glm": {"cli": "droid exec", "installed": True},
            "codex": {"cli": "codex exec", "installed": True}
        }
    }))
    rc, out, err = run(["unregister", "glm", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert "glm" not in data["providers"]
    assert data["providers"]["codex"]["cli"] == "codex exec"


def test_unregister_noop_on_absent_provider(tmp_path):
    cfg = global_config_path(tmp_path)
    cfg.write_text(json.dumps({"providers": {"codex": {"cli": "codex exec"}}}))
    rc, out, err = run(["unregister", "glm", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert "glm" not in data["providers"]
    assert data["providers"]["codex"]["cli"] == "codex exec"


def test_concurrent_register_no_corruption(tmp_path):
    """Two processes registering different providers concurrently — no corruption."""
    cfg = global_config_path(tmp_path)

    def do_register(provider, cli):
        return run(["register", provider, "--cli", cli, "--global-config", str(cfg)])

    for _ in range(20):
        # Remove file between iterations to also test from-scratch creation
        if cfg.exists():
            cfg.unlink()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_register, "glm", "droid exec")
            f2 = executor.submit(do_register, "codex", "codex exec")
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == 0
        assert r2[0] == 0
        data = json.loads(cfg.read_text())
        assert data["providers"]["glm"]["cli"] == "droid exec"
        assert data["providers"]["codex"]["cli"] == "codex exec"


# --- version ---

def test_version_returns_parseable_semver():
    rc, out, err = run(["--version"])
    assert rc == 0
    parts = out.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)

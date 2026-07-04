"""Tests for trinity/scripts/install.py"""

import importlib.util
import json
import os
import subprocess
import sys
import concurrent.futures
from pathlib import Path

import pytest

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
    rc, out, err = run(
        [
            "register",
            "glm",
            "--cli",
            "droid exec --model glm-5",
            "--global-config",
            str(cfg),
        ]
    )
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == "droid exec --model glm-5"
    assert data["providers"]["glm"]["installed"] is True


def test_register_idempotent_second_call_updates_cli(tmp_path):
    cfg = global_config_path(tmp_path)
    run(["register", "glm", "--cli", "droid-v1", "--global-config", str(cfg)])
    rc, out, err = run(
        ["register", "glm", "--cli", "droid-v2", "--global-config", str(cfg)]
    )
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == "droid-v2"


def test_register_preserves_existing_providers(tmp_path):
    cfg = global_config_path(tmp_path)
    cfg.write_text(
        json.dumps({"providers": {"codex": {"cli": "codex exec", "installed": True}}})
    )
    rc, out, err = run(
        ["register", "glm", "--cli", "droid exec", "--global-config", str(cfg)]
    )
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["codex"]["cli"] == "codex exec"
    assert data["providers"]["glm"]["cli"] == "droid exec"


def test_cli_with_spaces_preserved_verbatim(tmp_path):
    cfg = global_config_path(tmp_path)
    cli_str = "droid exec --model glm-5 --some-flag with spaces"
    rc, out, err = run(
        ["register", "glm", "--cli", cli_str, "--global-config", str(cfg)]
    )
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["glm"]["cli"] == cli_str


# --- unregister ---


def test_unregister_removes_provider(tmp_path):
    cfg = global_config_path(tmp_path)
    cfg.write_text(
        json.dumps(
            {
                "providers": {
                    "glm": {"cli": "droid exec", "installed": True},
                    "codex": {"cli": "codex exec", "installed": True},
                }
            }
        )
    )
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


# --- CHG-3048 argparse contract ---

_spec = importlib.util.spec_from_file_location(
    "_version", SCRIPT.parent / "_version.py"
)
_vmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vmod)
EXPECTED_VERSION = _vmod.load_version()


def run_home(args, tmp_path):
    """run() variant with HOME patched to a tmp dir (and cwd=tmp_path)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        cwd=str(tmp_path),
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip(), home


CHG_3048_ERROR_CASES = [
    (["--bogus"], "--bogus"),  # top-level unknown flag
    (["bogus-cmd"], "bogus-cmd"),  # invalid subcommand
    (["register", "p", "--cli", "y", "--bogus"], "--bogus"),  # unknown flag: register
    (
        ["register-from-registry", "r.json", "--bogus"],
        "--bogus",
    ),  # unknown flag: register-from-registry
    (["unregister", "p", "--bogus"], "--bogus"),  # unknown flag: unregister
    (["register"], "required"),  # missing positional
    (["register-from-registry"], "required"),  # missing positional
    (["unregister"], "required"),  # missing positional
    (["register", "p"], "--cli"),  # missing required --cli
    (["register", "p", "--global-config"], "--global-config"),  # flag missing its value
    # abbreviation rejected; token is "required" (stable argparse phrasing) —
    # "--cl" only matched as a substring of "--cli" in the error, adding no
    # independent discrimination (PR #280 code-review, deepseek)
    (["register", "p", "--cl", "x"], "required"),
    (["register", "-x", "--cli", "y"], "required"),  # dash-prefixed positional
    (["register", "p", "--cli", "-x"], "--cli"),  # dash-token flag value
    (["register", "p", "--cli", "--global-config"], "--cli"),  # flag-as-value
    (["unregister", "p", "extra"], "extra"),  # trailing extra positional
]


@pytest.mark.parametrize("argv,offending_token", CHG_3048_ERROR_CASES)
def test_chg3048_argparse_error_exit2(argv, offending_token, tmp_path):
    """Argparse exits 2 with error on stderr mentioning the bad token."""
    rc, out, err, _ = run_home(argv, tmp_path)
    assert rc == 2, f"expected exit 2, got {rc}"
    assert err != "", "expected stderr output"
    assert offending_token in err, f"expected '{offending_token}' in stderr: {err}"


def test_chg3048_top_level_help():
    """-h prints help to stdout, exit 0."""
    rc, out, err = run(["-h"])
    assert rc == 0
    assert "usage" in out.lower()


def test_chg3048_register_help():
    """register -h prints subcommand help to stdout, exit 0."""
    rc, out, err = run(["register", "-h"])
    assert rc == 0
    assert "usage" in out.lower()


def test_chg3048_version_exact():
    """--version prints semver exactly, no stray usage line."""
    rc, out, err = run(["--version"])
    assert rc == 0
    assert out == EXPECTED_VERSION


def test_chg3048_version_short_circuit(tmp_path):
    """--version register prints version, exit 0, no config file created."""
    rc, out, err, home = run_home(["--version", "register"], tmp_path)
    assert rc == 0
    assert out == EXPECTED_VERSION
    assert not (home / ".claude" / "trinity.json").exists()


def test_chg3048_flag_before_positional(tmp_path):
    """register --cli x p — flag before positional, behavior ADDITION."""
    cfg = tmp_path / "trinity.json"
    rc, out, err = run(["register", "--cli", "x", "p", "--global-config", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text())
    assert data["providers"]["p"]["cli"] == "x"


def test_chg3048_empty_global_config_passthrough(tmp_path):
    """Empty --global-config string passed through verbatim via is None check."""
    rc, out, err, home = run_home(
        ["register", "p", "--cli", "x", "--global-config", ""], tmp_path
    )
    assert rc == 1
    assert "IO error" in err


def test_chg3048_no_args_docstring():
    """No args prints docstring to stderr, exit 1."""
    rc, out, err = run([])
    assert rc == 1
    assert "Usage:" in err
    assert "install.py" in err

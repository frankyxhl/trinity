"""
Tests for providers/bin/deepseek and providers/bin/openrouter (TRN-2008/TRN-2009).

The wrapper scripts run `exec claude --dangerously-skip-permissions "$@"` after
loading an API key (env DEEPSEEK_API_KEY / OPENROUTER_API_KEY wins; falls back
to ~/.secrets/<provider>_api_key with mode 600 or 400) and injecting
ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL etc.

Strategy: prepend a Python `claude` stub onto PATH that records argv + selected
env vars to a JSON file before exit(0). Because the wrapper does `exec`, the
stub IS the leaf process — the JSON file is the source of truth for assertions.

Test grid covers PRP TRN-2008 §Test Cases (T1-T8, T13) for both wrappers.
T9-T12 (install.sh integration) live in tests/test_install_sh.sh.
T14 (make verify-built after .delta.md edit) is enforced by `make test` itself.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DEEPSEEK_BIN = REPO_ROOT / "providers" / "bin" / "deepseek"
OPENROUTER_BIN = REPO_ROOT / "providers" / "bin" / "openrouter"

CAPTURED_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CONFIG_DIR",
)


# --- fixtures ---


@pytest.fixture
def stub_env(tmp_path):
    """
    Return a callable: stub_env(env_extra=None) -> (env, record_path).

    Sets up tmp_path/bin/claude as a Python script that records argv+env to JSON
    and exits 0. PATH is rebuilt to put the stub first; HOME is set to tmp_path.
    Wrapper scripts inherit this env when invoked via subprocess.
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record_path = tmp_path / "claude.invoked.json"
    stub = bin_dir / "claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "captured_env = {k: os.environ.get(k) for k in (\n"
        + ",\n".join(f"    {k!r}" for k in CAPTURED_ENV_KEYS)
        + ",\n)}\n"
        f"open({str(record_path)!r}, 'w').write(json.dumps({{\n"
        "    'argv': sys.argv[1:],\n"
        "    'env': captured_env,\n"
        "}))\n"
        "sys.exit(0)\n"
    )
    stub.chmod(0o755)

    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()

    def make_env(env_extra=None):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
        }
        if env_extra:
            env.update(env_extra)
        return env, record_path

    return make_env


def _run(wrapper, args, env):
    return subprocess.run(
        [str(wrapper), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def _write_key_file(home, provider, content, mode=0o600):
    p = Path(home) / ".secrets" / f"{provider}_api_key"
    p.write_text(content)
    p.chmod(mode)
    return p


# --- DeepSeek wrapper tests (T1-T6, T6b, T8) ---


def test_t1_deepseek_env_key_sets_anthropic_env_and_passes_argv(stub_env):
    env, rec = stub_env({"DEEPSEEK_API_KEY": "from-env-xxx"})
    res = _run(DEEPSEEK_BIN, ["arg1", "arg2"], env)
    assert res.returncode == 0, res.stderr
    rec_data = json.loads(rec.read_text())
    assert rec_data["argv"] == ["--dangerously-skip-permissions", "arg1", "arg2"]
    e = rec_data["env"]
    assert e["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert e["ANTHROPIC_AUTH_TOKEN"] == "from-env-xxx"
    assert e["ANTHROPIC_API_KEY"] == "from-env-xxx"
    assert e["ANTHROPIC_MODEL"] == "deepseek-v4-pro"
    assert e["ANTHROPIC_SMALL_FAST_MODEL"] == "deepseek-v4-flash"
    assert e["API_TIMEOUT_MS"] == "600000"
    assert e["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert e["CLAUDE_CONFIG_DIR"].endswith(".claude-deepseek")


def test_t2_deepseek_no_env_reads_key_file_mode_600(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "deepseek", "from-file-yyy", mode=0o600)
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == "from-file-yyy"


def test_t3_deepseek_env_wins_over_file(stub_env):
    env, rec = stub_env({"DEEPSEEK_API_KEY": "from-env"})
    _write_key_file(env["HOME"], "deepseek", "from-file", mode=0o600)
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 0
    assert json.loads(rec.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == "from-env"


def test_t4_deepseek_no_key_anywhere_exits_1(stub_env):
    env, rec = stub_env()
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 1
    assert "no API key" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"


def test_t5_deepseek_refuses_world_readable_key_file(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "deepseek", "secret", mode=0o644)
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 1
    assert "refuse to read" in res.stderr
    assert "perm 644" in res.stderr
    assert "expected 600 or 400" in res.stderr
    assert not rec.exists()


def test_t6_deepseek_empty_key_file_treated_as_missing(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "deepseek", "", mode=0o600)
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 1
    assert "no API key" in res.stderr


def test_t6b_deepseek_accepts_key_file_mode_400(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "deepseek", "ro-key", mode=0o400)
    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == "ro-key"


def test_t8_deepseek_resume_argv_ordering(stub_env):
    """Worker invokes resume as: <wrapper> --resume <id> -p "<prompt>".
    Wrapper must produce: claude --dangerously-skip-permissions --resume <id> -p "<prompt>"
    (no double -p, --resume placed correctly)."""
    env, rec = stub_env({"DEEPSEEK_API_KEY": "k"})
    res = _run(DEEPSEEK_BIN, ["--resume", "sess123", "-p", "hello world"], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["argv"] == [
        "--dangerously-skip-permissions",
        "--resume",
        "sess123",
        "-p",
        "hello world",
    ]


# --- OpenRouter wrapper tests (T7 = T1-T6/T8 mirrored) ---


def test_t7_openrouter_env_key_sets_anthropic_env(stub_env):
    env, rec = stub_env({"OPENROUTER_API_KEY": "or-env"})
    res = _run(OPENROUTER_BIN, ["arg"], env)
    assert res.returncode == 0, res.stderr
    rec_data = json.loads(rec.read_text())
    assert rec_data["argv"] == ["--dangerously-skip-permissions", "arg"]
    e = rec_data["env"]
    assert e["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
    assert e["ANTHROPIC_AUTH_TOKEN"] == "or-env"
    assert e["ANTHROPIC_MODEL"] == "qwen/qwen3.6-plus:free"
    assert e["CLAUDE_CONFIG_DIR"].endswith(".claude-openrouter")


def test_t7_openrouter_reads_key_file(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "openrouter", "from-file", mode=0o600)
    res = _run(OPENROUTER_BIN, [], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == "from-file"


def test_t7_openrouter_env_wins_over_file(stub_env):
    env, rec = stub_env({"OPENROUTER_API_KEY": "from-env"})
    _write_key_file(env["HOME"], "openrouter", "from-file", mode=0o600)
    res = _run(OPENROUTER_BIN, [], env)
    assert res.returncode == 0
    assert json.loads(rec.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == "from-env"


def test_t7_openrouter_no_key_anywhere_exits_1(stub_env):
    env, rec = stub_env()
    res = _run(OPENROUTER_BIN, [], env)
    assert res.returncode == 1
    assert "no API key" in res.stderr


def test_t7_openrouter_refuses_world_readable(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], "openrouter", "secret", mode=0o644)
    res = _run(OPENROUTER_BIN, [], env)
    assert res.returncode == 1
    assert "refuse to read" in res.stderr


def test_t7_openrouter_resume_argv(stub_env):
    env, rec = stub_env({"OPENROUTER_API_KEY": "k"})
    res = _run(OPENROUTER_BIN, ["--resume", "or-sess", "-p", "x"], env)
    assert res.returncode == 0
    assert json.loads(rec.read_text())["argv"] == [
        "--dangerously-skip-permissions",
        "--resume",
        "or-sess",
        "-p",
        "x",
    ]


# --- Stat-failure portability test (T13) ---


def test_t13_deepseek_unknown_perm_when_stat_fails(stub_env, tmp_path):
    """If both `stat -f` and `stat -c` fail (exotic FS / sshfs / etc.), the
    wrapper must refuse via the explicit `unknown` branch — never silently
    abort under `set -e`."""
    bin_dir = tmp_path / "bin"
    # Replace `stat` on PATH with a stub that always exits 1 — simulates both
    # BSD and GNU stat failing on the key file.
    stat_stub = bin_dir / "stat"
    stat_stub.write_text("#!/bin/sh\nexit 1\n")
    stat_stub.chmod(0o755)

    env, rec = stub_env()
    _write_key_file(env["HOME"], "deepseek", "secret", mode=0o600)

    res = _run(DEEPSEEK_BIN, [], env)
    assert res.returncode == 1
    assert "cannot stat" in res.stderr
    assert "refusing to read for safety" in res.stderr
    assert not rec.exists()


# --- Sanity check on installed bits (these are the obvious RED indicators) ---


def test_wrapper_scripts_exist_and_executable():
    assert DEEPSEEK_BIN.is_file(), f"{DEEPSEEK_BIN} missing"
    assert OPENROUTER_BIN.is_file(), f"{OPENROUTER_BIN} missing"
    assert os.access(DEEPSEEK_BIN, os.X_OK), f"{DEEPSEEK_BIN} not executable"
    assert os.access(OPENROUTER_BIN, os.X_OK), f"{OPENROUTER_BIN} not executable"


def test_wrappers_use_posix_sh_shebang():
    for p in (DEEPSEEK_BIN, OPENROUTER_BIN):
        first_line = p.read_text().splitlines()[0]
        assert first_line == "#!/bin/sh", (
            f"{p}: expected POSIX sh shebang, got {first_line!r}"
        )

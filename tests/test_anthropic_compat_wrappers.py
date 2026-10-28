"""
Tests for providers/bin/deepseek, providers/bin/openrouter, and
providers/bin/claude-code (TRN-2008/TRN-2009/TRN-2012).

The Anthropic-compatible wrappers run
`exec claude --dangerously-skip-permissions "$@"` after loading an API key (env
DEEPSEEK_API_KEY / OPENROUTER_API_KEY wins; falls back to
~/.secrets/<provider>_api_key with mode 600 or 400) and injecting
ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL etc. The
claude-code wrapper instead runs native Claude Code with
`--permission-mode bypassPermissions`.

Strategy: prepend a Python `claude` stub onto PATH that records argv + selected
env vars to a JSON file before exit(0). Because the wrapper does `exec`, the
stub IS the leaf process — the JSON file is the source of truth for assertions.

Test grid covers PRP TRN-2008 §Test Cases (T1-T8, T13) for both wrappers.
T9-T12 (install.sh integration) live in tests/test_install_sh.sh.
T14 (make verify-built after .delta.md edit) is enforced by `make test` itself.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DEEPSEEK_BIN = REPO_ROOT / "providers" / "bin" / "deepseek"
GLM_BIN = REPO_ROOT / "providers" / "bin" / "glm"
OPENROUTER_BIN = REPO_ROOT / "providers" / "bin" / "openrouter"
CLAUDE_CODE_BIN = REPO_ROOT / "providers" / "bin" / "claude-code"
CLAUDE_CODE_DELTA = REPO_ROOT / "providers" / "claude-code.delta.md"

CAPTURED_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "API_TIMEOUT_MS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
    "TRINITY_DISABLE_DISPATCH",
    "TOKEN",
)

# Fake fleet tokens used by the claude-code account tests (D2596-FIX3). Never
# real credentials — written only into the pytest tmp HOME.
FLEET_TOKEN_B = "fake-token-acct-b-123"
FLEET_TOKEN_A = "fake-token-acct-a-456"
FLEET_TOKEN_C = "fake-token-acct-c-789"


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
        "    'env_names': sorted(os.environ),\n"
        "}))\n"
        "sys.exit(0)\n"
    )
    stub.chmod(0o755)

    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()

    # D2596-FIX3: the claude-code wrapper fails closed without a token file, so
    # seed a valid default account-b token so the pre-existing T14 tests keep
    # exercising model/effort behaviour (R6) once the fix lands.
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "fleet-token.b").write_text(FLEET_TOKEN_B)
    (claude_dir / "fleet-token.b").chmod(0o600)

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


def _write_token_file(home, account, content, mode=0o600):
    p = Path(home) / ".claude" / f"fleet-token.{account}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    p.chmod(mode)
    return p


def _assert_token_absent(res, token):
    """R4: the token must never appear on stdout OR stderr on any path."""
    assert token not in res.stdout, "token leaked to stdout"
    assert token not in res.stderr, "token leaked to stderr"


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
    # V4-Flash runs 1M context by default on the official endpoint — no [1m]
    # suffix needed (the API normalizes it away; verified 2026-07-31).
    assert e["ANTHROPIC_MODEL"] == "deepseek-flash"
    assert e["ANTHROPIC_SMALL_FAST_MODEL"] == "deepseek-flash"
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


@pytest.fixture
def glm_env(stub_env, tmp_path):
    sandbox = tmp_path / "sandbox-exec"
    sandbox_record = tmp_path / "sandbox.invoked.json"
    sandbox.write_text(
        "\x23!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(sandbox_record)!r}, 'w').write(json.dumps(sys.argv))\n"
        "os.execvp(sys.argv[3], sys.argv[3:])\n"
    )
    sandbox.chmod(0o755)
    deny_list = tmp_path / "client-data-dirs.txt"
    deny_list.write_text(
        f"{tmp_path / 'client-one'}\n\n"
        "\x23 ignored-client-path\n"
        f"{tmp_path / 'client two'}\n"
    )

    def make_env(env_extra=None):
        extra = {
            "GLM_SANDBOX_EXEC": str(sandbox),
            "GLM_DENY_LIST": str(deny_list),
            "LANG": "en_US.UTF-8",
        }
        if env_extra:
            extra.update(env_extra)
        return stub_env(extra)

    return make_env


def test_g1_glm_env_key_sets_anthropic_env_and_passes_argv(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    res = _run(GLM_BIN, ["-p", "hi"], env)
    assert res.returncode == 0, res.stderr
    data = json.loads(rec.read_text())
    assert data["argv"][0] == "--dangerously-skip-permissions"
    assert data["argv"][-2:] == ["-p", "hi"]
    captured = data["env"]
    assert captured["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "zai-test-key-123"
    assert captured["ANTHROPIC_API_KEY"] == "zai-test-key-123"
    assert captured["ANTHROPIC_MODEL"] == "glm-5.3-flash"
    assert captured["ANTHROPIC_SMALL_FAST_MODEL"] == "glm-5.3-flash"
    assert captured["CLAUDE_CONFIG_DIR"] == str(Path(env["HOME"]) / ".claude-glm")
    assert captured["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_g2_glm_key_file_mode_600(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env()
    _write_key_file(env["HOME"], "zai", "zai-test-key-123\n", mode=0o600)
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    captured = json.loads(rec.read_text())["env"]
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "zai-test-key-123"
    assert captured["ANTHROPIC_API_KEY"] == "zai-test-key-123"


def test_g3_glm_key_file_mode_400(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env()
    _write_key_file(env["HOME"], "zai", "zai-test-key-123\n", mode=0o400)
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    captured = json.loads(rec.read_text())["env"]
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "zai-test-key-123"
    assert captured["ANTHROPIC_API_KEY"] == "zai-test-key-123"


def test_g4_glm_refuses_world_readable_key_file(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env()
    _write_key_file(env["HOME"], "zai", "zai-test-key-123\n", mode=0o644)
    res = _run(GLM_BIN, [], env)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (Path(env["HOME"]) / "sandbox.invoked.json").exists()
    assert "zai_api_key" in res.stderr
    assert "zai-test-key-123" not in res.stderr
    assert "zai-test-key-123" not in res.stdout


def test_g5_glm_no_key_anywhere_exits_1(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env()
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 1
    assert not rec.exists(), "claude stub should not have been invoked"
    assert "ZAI_API_KEY" in res.stderr


def test_g6_glm_empty_key_file_treated_as_missing(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env()
    _write_key_file(env["HOME"], "zai", "", mode=0o600)
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 1
    assert not rec.exists(), "claude stub should not have been invoked"
    assert "ZAI_API_KEY" in res.stderr


def test_g7_glm_env_wins_over_file(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    _write_key_file(env["HOME"], "zai", "zai-file-key-456\n", mode=0o600)
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    captured = json.loads(rec.read_text())["env"]
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "zai-test-key-123"
    assert captured["ANTHROPIC_API_KEY"] == "zai-test-key-123"
    env["ZAI_API_KEY"] = ""
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    captured = json.loads(rec.read_text())["env"]
    assert captured["ANTHROPIC_AUTH_TOKEN"] == "zai-file-key-456"
    assert captured["ANTHROPIC_API_KEY"] == "zai-file-key-456"


def test_g8_glm_resume_argv_ordering(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    args = ["-r", "sid-1", "-p", "next"]
    res = _run(GLM_BIN, args, env)
    assert res.returncode == 0, res.stderr
    argv = json.loads(rec.read_text())["argv"]
    assert argv[-4:] == args
    assert "--append-system-prompt" in argv
    assert "--disallowedTools" in argv
    assert argv.index("--append-system-prompt") + 1 < argv.index("-r")
    assert argv.index("--disallowedTools") + 1 < argv.index("-r")


def test_g9_glm_appends_fleet_secrets_line(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    argv = json.loads(rec.read_text())["argv"]
    assert "--append-system-prompt" in argv
    pos = argv.index("--append-system-prompt")
    assert pos + 1 < len(argv)
    assert argv[pos + 1] == (
        "Secrets never enter output: no env, printenv, set, ps e / ps eww / "
        "ps -E, set -x, no cat of any file under ~/.secrets, no traceback "
        "that carries a key. If one slips out, stop and tell the steward."
    )


def test_g10_glm_denies_env_and_secrets_tools(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    args = ["-p", "hi"]
    res = _run(GLM_BIN, args, env)
    assert res.returncode == 0, res.stderr
    argv = json.loads(rec.read_text())["argv"]
    assert "--disallowedTools" in argv
    pos = argv.index("--disallowedTools")
    assert pos + 1 < len(argv)
    assert set(argv[pos + 1].split(",")) >= {
        "Bash(env:*)",
        "Bash(printenv:*)",
        "Bash(set:*)",
        "Bash(ps:*)",
        "Read(~/.secrets/**)",
        "Grep(~/.secrets/**)",
        "Glob(~/.secrets/**)",
    }
    assert argv[pos + 2 :] == args


def test_g11_glm_key_never_in_argv_or_output(glm_env, tmp_path):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    key = "zai-test-key-123"
    env, rec = glm_env({"ZAI_API_KEY": key})
    res = _run(GLM_BIN, ["-p", "two words", "", "*"], env)
    assert res.returncode == 0, res.stderr
    argv = json.loads(rec.read_text())["argv"]
    assert argv[-4:] == ["-p", "two words", "", "*"]
    assert all(key not in arg for arg in argv)
    assert key not in res.stdout
    assert key not in res.stderr
    records = {rec, tmp_path / "sandbox.invoked.json"}
    leaked = [
        str(p)
        for p in tmp_path.rglob("*")
        if p.is_file() and p not in records and key.encode() in p.read_bytes()
    ]
    assert leaked == [], f"key written to {leaked}"


def test_g12_glm_wrapper_is_executable_sh(glm_env):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    assert os.access(GLM_BIN, os.X_OK), f"{GLM_BIN} not executable"
    assert GLM_BIN.read_text().splitlines()[0] == "#!/bin/sh"


def test_g13_glm_env_is_allowlist_only(glm_env, tmp_path):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env(
        {
            "ZAI_API_KEY": "zai-test-key-123",
            "OTHER_SECRET": "planted-1",
            "TMPDIR": str(tmp_path),
            "ANTHROPIC_BASE_URL": "https://caller.invalid",
            "CLAUDE_CODE_OAUTH_TOKEN": "planted-oauth",
        }
    )
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    data = json.loads(rec.read_text())
    assert data["env"]["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    names = set(data["env_names"])
    assert "OTHER_SECRET" not in names
    assert "ZAI_API_KEY" not in names
    assert names - {
        "__CF_USER_TEXT_ENCODING",
        "LC_CTYPE",
        "CPATH",
        "LIBRARY_PATH",
        "MANPATH",
        "SDKROOT",
    } == {
        "HOME",
        "PATH",
        "TMPDIR",
        "LANG",
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    }


def test_g14_glm_runs_under_sandbox_with_deny_profile(glm_env, tmp_path):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    env, rec = glm_env({"ZAI_API_KEY": "zai-test-key-123"})
    res = _run(GLM_BIN, [], env)
    assert res.returncode == 0, res.stderr
    assert rec.exists(), "claude stub was not invoked"
    sandbox_record = tmp_path / "sandbox.invoked.json"
    assert sandbox_record.is_file(), "sandbox stub was not invoked"
    argv = json.loads(sandbox_record.read_text())
    assert argv[1] == "-p"
    profile = argv[2]
    assert "(version 1)" in profile
    assert "(allow default)" in profile
    assert "(deny file-read*" in profile
    for directory in (
        tmp_path / ".secrets",
        tmp_path / ".ssh",
        tmp_path / ".claude" / "fleet-tokens",
        tmp_path / ".config" / "gh",
        tmp_path / "client-one",
        tmp_path / "client two",
    ):
        assert f'(subpath "{directory}")' in profile
    assert "ignored-client-path" not in profile
    assert argv[3:5] == ["env", "-i"]


def test_g15_glm_refuses_missing_sandbox_binary(glm_env, tmp_path):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    missing = tmp_path / "missing-sandbox"
    env, rec = glm_env(
        {"ZAI_API_KEY": "zai-test-key-123", "GLM_SANDBOX_EXEC": str(missing)}
    )
    res = _run(GLM_BIN, [], env)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (tmp_path / "sandbox.invoked.json").exists()
    assert "sandbox" in res.stderr.lower()
    sandbox = tmp_path / "sandbox-exec"
    sandbox.chmod(0o644)
    env["GLM_SANDBOX_EXEC"] = str(sandbox)
    res = _run(GLM_BIN, [], env)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (tmp_path / "sandbox.invoked.json").exists()
    assert "sandbox" in res.stderr.lower()


def test_g16_glm_refuses_missing_or_empty_deny_list(glm_env, tmp_path):
    assert GLM_BIN.is_file(), f"{GLM_BIN} missing"
    deny_list = tmp_path / "missing-deny-list.txt"
    env, rec = glm_env(
        {"ZAI_API_KEY": "zai-test-key-123", "GLM_DENY_LIST": str(deny_list)}
    )
    res = _run(GLM_BIN, [], env)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (tmp_path / "sandbox.invoked.json").exists()
    assert "deny" in res.stderr.lower()
    deny_list.write_text("\n\x23 ignored-client-path\n")
    res = _run(GLM_BIN, [], env)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (tmp_path / "sandbox.invoked.json").exists()
    assert "deny" in res.stderr.lower()
    deny_list.write_text(f"{tmp_path / 'client-one'}\n")
    deny_list.chmod(0o000)
    try:
        res = _run(GLM_BIN, [], env)
    finally:
        deny_list.chmod(0o600)
    assert res.returncode != 0
    assert not rec.exists(), "claude stub should not have been invoked"
    assert not (tmp_path / "sandbox.invoked.json").exists()
    assert "deny" in res.stderr.lower()


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


def test_t14_claude_code_default_model_effort_and_recursion_guard(stub_env):
    env, rec = stub_env()
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    rec_data = json.loads(rec.read_text())
    assert rec_data["argv"] == [
        "--permission-mode",
        "bypassPermissions",
        "--disable-slash-commands",
        "--model",
        "sonnet",
        "--effort",
        "high",
        "-p",
        "hello",
    ]
    e = rec_data["env"]
    assert e["TRINITY_DISABLE_DISPATCH"] == "1"
    assert e["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert e["CLAUDE_CONFIG_DIR"].endswith(".claude-trinity-claude-code")


def test_t14_claude_code_accepts_model_and_max_effort_overrides(stub_env):
    env, rec = stub_env(
        {
            "TRINITY_CLAUDE_CODE_MODEL": "claude-sonnet-4-6",
            "TRINITY_CLAUDE_CODE_EFFORT": "max",
        }
    )
    res = _run(CLAUDE_CODE_BIN, ["--resume", "cc-sess", "-p", "continue"], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["argv"] == [
        "--permission-mode",
        "bypassPermissions",
        "--disable-slash-commands",
        "--model",
        "claude-sonnet-4-6",
        "--effort",
        "max",
        "--resume",
        "cc-sess",
        "-p",
        "continue",
    ]


def test_t14_claude_code_rejects_invalid_effort_before_invoking_claude(stub_env):
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_EFFORT": "ultra"})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "invalid effort" in res.stderr
    assert "low|medium|high|xhigh|max" in res.stderr
    assert not rec.exists()


# --- claude-code account/token tests (D2596-FIX3 R9) ---
#
# The wrapper reads "$HOME/.claude/fleet-token.<account>" and passes the
# stripped contents to the exec'd claude as CLAUDE_CODE_OAUTH_TOKEN. Account
# comes from TRINITY_CLAUDE_CODE_ACCOUNT (unset/empty => b). All tokens here are
# FAKE and live only in the pytest tmp HOME.


def test_t15_claude_code_defaults_to_account_b_token_via_env(stub_env):
    """R9: unset account => b; its token reaches claude only via the env var."""
    env, rec = stub_env()
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    e = json.loads(rec.read_text())["env"]
    assert e["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_B
    _assert_token_absent(res, FLEET_TOKEN_B)


def test_t15_claude_code_account_a_selects_its_token_file(stub_env):
    """R9: TRINITY_CLAUDE_CODE_ACCOUNT=a reads fleet-token.a (not b)."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "b", "fake-token-acct-b-decoy")
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert (
        json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    )
    _assert_token_absent(res, FLEET_TOKEN_A)
    _assert_token_absent(res, "fake-token-acct-b-decoy")


def test_t15_claude_code_account_c_selects_its_token_file(stub_env):
    """R9: TRINITY_CLAUDE_CODE_ACCOUNT=c reads fleet-token.c."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "c"})
    _write_token_file(env["HOME"], "c", FLEET_TOKEN_C)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert (
        json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_C
    )
    _assert_token_absent(res, FLEET_TOKEN_C)


def test_t15_claude_code_empty_account_env_defaults_to_b(stub_env):
    """R1/R9: empty TRINITY_CLAUDE_CODE_ACCOUNT behaves like unset => b."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": ""})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert (
        json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_B
    )
    _assert_token_absent(res, FLEET_TOKEN_B)


def test_t15_claude_code_invalid_account_rejected_before_invoking_claude(stub_env):
    """R1/R9: any account other than a/b/c exits 1 without running claude and
    names the allowed values."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "z"})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "a|b|c" in res.stderr
    assert "z" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_missing_token_file_rejected_before_invoking_claude(stub_env):
    """R3/R9: missing file exits 1 naming account letter + path; no claude run."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "missing" in res.stderr.lower()
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_empty_token_file_rejected_before_invoking_claude(stub_env):
    """R3/R9: empty-after-strip file exits 1; the (empty) value never leaks."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", "   \n\t\n", mode=0o600)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "empty" in res.stderr.lower()
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_group_or_other_readable_token_rejected(stub_env):
    """R3/R9: mode 0644 (group/other readable) exits 1 and never echoes the token."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", "fake-token-acct-a-secret", mode=0o644)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "group or other" in res.stderr.lower()
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, "fake-token-acct-a-secret")


def test_t15_claude_code_group_writable_token_rejected(stub_env):
    """R3/R7: mode 0620 (group-writable only, not readable) is still a 077 bit."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", "fake-token-acct-a-secret", mode=0o620)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "group or other" in res.stderr.lower()
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, "fake-token-acct-a-secret")


def test_t15_claude_code_symlink_token_file_rejected(stub_env):
    """P1: a symlink is rejected before permissions (cat would follow it)."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    real = Path(env["HOME"]) / ".claude" / "real-token"
    real.write_text(FLEET_TOKEN_A)
    real.chmod(0o600)
    os.symlink(real, Path(env["HOME"]) / ".claude" / "fleet-token.a")
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "not a regular file" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_directory_token_path_rejected(stub_env):
    """P1: any non-regular file (here a directory) is rejected."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    (Path(env["HOME"]) / ".claude" / "fleet-token.a").mkdir()
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "not a regular file" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_token_file_with_acl_marker_rejected(stub_env):
    """P1: char 11 '+' (ACL present) is rejected even when mode bits are 0600.

    A fake `ls` on PATH deterministically emits the ACL marker, so this branch
    is covered on every OS (macOS 27 surfaces ACLs as '@', not '+')."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    ls_stub = Path(env["HOME"]) / "bin" / "ls"
    ls_stub.write_text("#!/bin/sh\nprintf '%s\\n' '-rw-------+ 1 u g 0 tok'\n")
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "has an ACL" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


@pytest.mark.skipif(sys.platform != "darwin", reason="chmod +a ACLs are macOS-only")
def test_t15_claude_code_token_file_with_real_acl_rejected(stub_env):
    """P1: a real 0600 file whose ACL grants group read is rejected.

    macOS 27 hides the ACL behind the xattr marker `@` in `ls -ld`, so this
    exercises the `ls -lde` extra-line detection, not the `+` marker."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    p = _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    add = subprocess.run(
        ["chmod", "+a", "group:staff allow read", str(p)],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        pytest.skip(f"chmod +a unavailable: {add.stderr.strip()}")
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "has an ACL" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_acl_listing_extra_line_rejected(stub_env):
    """P1: `ls -lde` printing an ACL entry (extra line) is rejected."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    ls_stub = Path(env["HOME"]) / "bin" / "ls"
    ls_stub.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  -lde) printf '%s\\n' '-rw------- 1 u g 0 tok' ' 0: group:staff allow read';;\n"
        "  *) printf '%s\\n' '-rw------- 1 u g 0 tok';;\n"
        "esac\n"
    )
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "has an ACL" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_ls_without_dash_e_still_accepts(stub_env):
    """P1/R7: on non-Darwin, `ls -lde` unsupported (GNU ls exits non-zero) falls
    back to the `+` check, so a clean 0600 file is accepted. Pinned to Linux so
    it keeps meaning "GNU ls" after the Darwin fail-closed fix."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    bin_dir = Path(env["HOME"]) / "bin"
    uname_stub = bin_dir / "uname"
    uname_stub.write_text("#!/bin/sh\nprintf '%s\\n' Linux\n")
    uname_stub.chmod(0o755)
    ls_stub = bin_dir / "ls"
    ls_stub.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  -lde) exit 2;;\n"
        "  *) printf '%s\\n' '-rw------- 1 u g 0 tok';;\n"
        "esac\n"
    )
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert (
        json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    )
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_darwin_acl_listing_failure_refuses(stub_env):
    """P1 fail-closed: on Darwin `ls -lde` is the only way to see an ACL, so a
    failure to inspect must REFUSE rather than fall through to the `+` check."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    bin_dir = Path(env["HOME"]) / "bin"
    uname_stub = bin_dir / "uname"
    uname_stub.write_text("#!/bin/sh\nprintf '%s\\n' Darwin\n")
    uname_stub.chmod(0o755)
    ls_stub = bin_dir / "ls"
    ls_stub.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  -lde) exit 1;;\n"
        "  *) printf '%s\\n' '-rw------- 1 u g 0 tok';;\n"
        "esac\n"
    )
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1, (res.stdout, res.stderr)
    assert "fleet-token.a" in res.stderr
    assert "cannot inspect ACL" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_acl_listing_failure_with_unknown_uname_refuses(stub_env):
    """Gap fail-closed: if `ls -lde` fails AND `uname -s` fails/prints nothing,
    the OS is unknown, so the ACL check could not be done — REFUSE rather than
    treat it as non-Darwin and accept the token."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    bin_dir = Path(env["HOME"]) / "bin"
    uname_stub = bin_dir / "uname"
    uname_stub.write_text("#!/bin/sh\nexit 1\n")
    uname_stub.chmod(0o755)
    ls_stub = bin_dir / "ls"
    ls_stub.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  -lde) exit 1;;\n"
        "  *) printf '%s\\n' '-rw------- 1 u g 0 tok';;\n"
        "esac\n"
    )
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1, (res.stdout, res.stderr)
    assert "fleet-token.a" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_unreadable_ls_rejected(stub_env):
    """P2: an ls that fails (even with permission-shaped output) must not pass."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    ls_stub = Path(env["HOME"]) / "bin" / "ls"
    ls_stub.write_text("#!/bin/sh\nprintf '%s\\n' '-rw------- 1 u g 0 tok'\nexit 1\n")
    ls_stub.chmod(0o755)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 1
    assert "fleet-token.a" in res.stderr
    assert "cannot determine permissions" in res.stderr
    assert not rec.exists(), "claude stub should not have been invoked"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_inherited_tokens_do_not_reach_claude(stub_env):
    """R5/R9: the selected token wins; inherited OAuth/API/auth tokens are
    overridden or unset for the exec'd claude."""
    env, rec = stub_env(
        {
            "TRINITY_CLAUDE_CODE_ACCOUNT": "a",
            "CLAUDE_CODE_OAUTH_TOKEN": "inherited-wrong-token",
            "ANTHROPIC_API_KEY": "inherited-api-key",
            "ANTHROPIC_AUTH_TOKEN": "inherited-auth-token",
        }
    )
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    e = json.loads(rec.read_text())["env"]
    assert e["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    assert e["ANTHROPIC_API_KEY"] is None
    assert e["ANTHROPIC_AUTH_TOKEN"] is None
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_inherited_exported_token_not_reused(stub_env):
    """P2: an inherited exported TOKEN must not be re-exported carrying the
    secret; the value reaches claude only as CLAUDE_CODE_OAUTH_TOKEN."""
    env, rec = stub_env(
        {"TRINITY_CLAUDE_CODE_ACCOUNT": "a", "TOKEN": "inherited-token-xyz"}
    )
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    e = json.loads(rec.read_text())["env"]
    assert e["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    assert e["TOKEN"] is None
    leaked = [
        k for k, v in e.items() if v == FLEET_TOKEN_A and k != "CLAUDE_CODE_OAUTH_TOKEN"
    ]
    assert leaked == [], f"token re-exported under {leaked}"
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_token_never_in_argv(stub_env):
    """R4/R9: the token is delivered via env, never on claude's argv."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    rec_data = json.loads(rec.read_text())
    assert rec_data["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    assert FLEET_TOKEN_A not in " ".join(rec_data["argv"])
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_strips_surrounding_whitespace_from_token(stub_env):
    """R2/R9: trailing newline/whitespace is stripped before handing to claude."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", f"  {FLEET_TOKEN_A}\n", mode=0o600)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert (
        json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == FLEET_TOKEN_A
    )
    _assert_token_absent(res, FLEET_TOKEN_A)


def test_t15_claude_code_preserves_internal_whitespace(stub_env):
    """P2: only surrounding whitespace is trimmed; internal characters stay."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", "  fake a b  \n", mode=0o600)
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)
    assert res.returncode == 0, res.stderr
    assert json.loads(rec.read_text())["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "fake a b"
    _assert_token_absent(res, "fake a b")


# --- claude-code ACCOUNT parse in providers/claude-code.delta.md (P2) ---
#
# The orchestrator snippet documented in the delta file parses the task
# prompt's `ACCOUNT=<a|b|c>` token. These tests extract that snippet verbatim
# from the doc and run it, so they fail if the doc's parse diverges from the
# contract: exactly a/b/c is accepted; any `ACCOUNT=` token with any other value
# (empty, `a=bad`, `=a`, `B`, `ab`) must error and never silently default to b;
# no `ACCOUNT=` token at all leaves the account to the wrapper default b.
#
# Extraction: the ACCOUNT assignment line plus the contiguous non-blank lines
# after it (a validation `if`/`case` must be adjacent to the assignment).


def _code_blocks(text):
    blocks, cur, in_block = [], [], False
    for line in text.splitlines():
        if line.startswith("```"):
            if in_block:
                blocks.append(cur)
                cur = []
            in_block = not in_block
            continue
        if in_block:
            cur.append(line)
    return blocks


def _extract_account_snippet():
    for block in _code_blocks(CLAUDE_CODE_DELTA.read_text()):
        for i, line in enumerate(block):
            if re.match(r"\s*ACCOUNT=", line):
                snippet = [line]
                for nxt in block[i + 1 :]:
                    if nxt.strip() == "":
                        break
                    snippet.append(nxt)
                return "\n".join(snippet)
    raise AssertionError(
        "no `ACCOUNT=` snippet found in providers/claude-code.delta.md"
    )


def _run_account_snippet(prompt):
    snippet = _extract_account_snippet()
    script = (
        f"PROMPT={shlex.quote(prompt)}\n"
        + snippet
        + "\n"
        + "printf 'ACCOUNT=[%s]\\n' \"${ACCOUNT-<unset>}\"\n"
    )
    return subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True)


@pytest.mark.parametrize("account", ["a", "b", "c"])
def test_t15_delta_account_snippet_accepts_valid(account):
    res = _run_account_snippet(f"ACCOUNT={account}")
    assert res.returncode == 0, res.stderr
    assert f"ACCOUNT=[{account}]" in res.stdout


def test_t15_delta_account_snippet_no_token_leaves_account_unset():
    """No `ACCOUNT=` token at all: no account is chosen here (wrapper default b)."""
    res = _run_account_snippet("please review the code")
    assert res.returncode == 0, res.stderr
    assert ("ACCOUNT=[<unset>]" in res.stdout) or ("ACCOUNT=[]" in res.stdout)


@pytest.mark.parametrize(
    "prompt",
    ["ACCOUNT=a=bad", "ACCOUNT==a", "ACCOUNT=", "ACCOUNT=B", "ACCOUNT=ab"],
)
def test_t15_delta_account_snippet_rejects_invalid(prompt):
    """An `ACCOUNT=` token with an invalid value must error, not fall to b."""
    res = _run_account_snippet(prompt)
    assert res.returncode != 0, (res.stdout, res.stderr)
    assert "ACCOUNT=[b]" not in res.stdout


# --- Sanity check on installed bits (these are the obvious RED indicators) ---


def test_wrapper_scripts_exist_and_executable():
    assert DEEPSEEK_BIN.is_file(), f"{DEEPSEEK_BIN} missing"
    assert OPENROUTER_BIN.is_file(), f"{OPENROUTER_BIN} missing"
    assert CLAUDE_CODE_BIN.is_file(), f"{CLAUDE_CODE_BIN} missing"
    assert os.access(DEEPSEEK_BIN, os.X_OK), f"{DEEPSEEK_BIN} not executable"
    assert os.access(OPENROUTER_BIN, os.X_OK), f"{OPENROUTER_BIN} not executable"
    assert os.access(CLAUDE_CODE_BIN, os.X_OK), f"{CLAUDE_CODE_BIN} not executable"


def test_wrappers_use_posix_sh_shebang():
    for p in (DEEPSEEK_BIN, OPENROUTER_BIN, CLAUDE_CODE_BIN):
        first_line = p.read_text().splitlines()[0]
        assert first_line == "#!/bin/sh", (
            f"{p}: expected POSIX sh shebang, got {first_line!r}"
        )


# --- WO005R item 1 small: wrapper auth refusal and controls (S1-S3) ----------

AUTH_MARKER = "trinity-claude-code: auth_error:"
CLAUDE_LOGIN_RESULT = "Not logged in \u00b7 Please run /login"


def _isolated_login_command(config_dir: Path) -> str:
    return f"CLAUDE_CONFIG_DIR={shlex.quote(str(config_dir))} claude"


def _assert_single_line_start_auth_marker(stderr: str) -> None:
    lines = stderr.splitlines()
    matching = [line for line in lines if line.startswith(AUTH_MARKER)]
    assert lines, "expected an auth refusal diagnostic on stderr"
    assert len(matching) == 1, (stderr,)
    assert lines[0].startswith(AUTH_MARKER), stderr


def test_wo005r_i1s_s1_missing_token_refusal_uses_marker_before_claude(stub_env):
    """The wrapper's own login refusal emits the exact marker and runs no Claude."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)

    assert res.returncode == 1, (res.stdout, res.stderr)
    _assert_single_line_start_auth_marker(res.stderr)
    assert "account a" in res.stderr, res.stderr
    token_path = Path(env["HOME"]) / ".claude" / "fleet-token.a"
    assert shlex.quote(str(token_path)) in res.stderr, res.stderr
    assert "600" in res.stderr, res.stderr
    config_dir = Path(env["HOME"]) / ".claude-trinity-claude-code"
    assert _isolated_login_command(config_dir) in res.stderr, res.stderr
    assert "/login" in res.stderr, res.stderr
    assert not rec.exists(), "an auth refusal still executed Claude"


def test_wo005r_i1s_s2_auth_hint_quotes_hard_token_path_and_mode(stub_env):
    """Token refusal hints safely render hard paths and the exact mode fix."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    hard_home = Path(env["HOME"]) / "ho me's\\path"
    hard_home.mkdir()
    env["HOME"] = str(hard_home)
    token_path = _write_token_file(hard_home, "a", FLEET_TOKEN_A, mode=0o644)

    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)

    assert res.returncode == 1, (res.stdout, res.stderr)
    _assert_single_line_start_auth_marker(res.stderr)
    assert "account a" in res.stderr, res.stderr
    assert "0644" in res.stderr, res.stderr
    assert "chmod 600" in res.stderr, res.stderr
    assert shlex.quote(str(token_path)) in res.stderr, res.stderr
    config_dir = hard_home / ".claude-trinity-claude-code"
    assert _isolated_login_command(config_dir) in res.stderr, res.stderr
    assert "/login" in res.stderr, res.stderr
    _assert_token_absent(res, FLEET_TOKEN_A)
    assert not rec.exists(), "an auth refusal still executed Claude"


def test_wo005r_i1s_s2_missing_token_hint_names_isolated_login(stub_env):
    """A missing-token hint safely names a hard isolated config and login."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    hard_home = Path(env["HOME"]) / "ho me's\\path"
    hard_home.mkdir()
    env["HOME"] = str(hard_home)
    token_path = hard_home / ".claude" / "fleet-token.a"
    config_dir = hard_home / ".claude-trinity-claude-code"

    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)

    assert res.returncode == 1, (res.stdout, res.stderr)
    assert AUTH_MARKER in res.stderr, res.stderr
    assert "account a" in res.stderr, res.stderr
    assert shlex.quote(str(token_path)) in res.stderr, res.stderr
    assert _isolated_login_command(config_dir) in res.stderr, res.stderr
    assert res.stderr.rstrip().endswith("/login"), res.stderr
    assert not rec.exists()


def test_wo005r_i1s_s3_invalid_effort_refusal_has_no_auth_marker(stub_env):
    """Invalid effort is a non-auth wrapper validation, not an auth refusal."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_EFFORT": "ultra"})
    res = _run(CLAUDE_CODE_BIN, ["-p", "hello"], env)

    assert res.returncode == 1, (res.stdout, res.stderr)
    assert "invalid effort" in res.stderr, res.stderr
    assert AUTH_MARKER not in res.stderr, res.stderr
    assert not rec.exists(), "invalid effort still executed Claude"

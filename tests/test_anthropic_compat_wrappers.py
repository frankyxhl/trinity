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
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DEEPSEEK_BIN = REPO_ROOT / "providers" / "bin" / "deepseek"
OPENROUTER_BIN = REPO_ROOT / "providers" / "bin" / "openrouter"
CLAUDE_CODE_BIN = REPO_ROOT / "providers" / "bin" / "claude-code"

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
    assert e["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
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
    """P1/R7: `ls -lde` unsupported (GNU ls exits non-zero) falls back to the
    `+` check, so a clean 0600 file is accepted."""
    env, rec = stub_env({"TRINITY_CLAUDE_CODE_ACCOUNT": "a"})
    _write_token_file(env["HOME"], "a", FLEET_TOKEN_A, mode=0o600)
    ls_stub = Path(env["HOME"]) / "bin" / "ls"
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

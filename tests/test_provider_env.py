"""Unit tests for build_provider_env (TRN-3023).

Verifies spawn-time env sanitization in scripts/codex.py:
- Strips known-problematic patterns (*_BASE_URL, *_API_BASE, *_API_HOST,
  OTEL_*, TRINITY_DISABLE_DISPATCH) from the env passed to provider
  subprocesses.
- Preserves universal essentials (PATH, HOME, ..., LC_*, GIT_*) even if
  a clear pattern would otherwise match them.
- Returns a fresh dict (no mutable-default antipattern; safe to pass to
  subprocess.Popen's env= parameter).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Importable scripts/codex.py
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import codex as codex_mod  # noqa: E402

build_provider_env = codex_mod.build_provider_env


# ---------------------------------------------------------------------------
# A1-A4: clearlist strips
# ---------------------------------------------------------------------------


def test_a1_openai_base_url_stripped():
    env = build_provider_env({"OPENAI_BASE_URL": "https://corp.invalid/v1"})
    assert "OPENAI_BASE_URL" not in env


def test_anthropic_base_url_stripped():
    env = build_provider_env({"ANTHROPIC_BASE_URL": "https://x.invalid"})
    assert "ANTHROPIC_BASE_URL" not in env


def test_api_base_stripped():
    env = build_provider_env({"OPENAI_API_BASE": "https://x.invalid"})
    assert "OPENAI_API_BASE" not in env


def test_api_host_stripped():
    env = build_provider_env({"OPENAI_API_HOST": "x.invalid"})
    assert "OPENAI_API_HOST" not in env


def test_a3_otel_wildcard_stripped():
    env = build_provider_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://x"})
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env


def test_otel_other_var_stripped():
    env = build_provider_env({"OTEL_SERVICE_NAME": "trinity"})
    assert "OTEL_SERVICE_NAME" not in env


def test_a4_trinity_disable_dispatch_stripped():
    env = build_provider_env({"TRINITY_DISABLE_DISPATCH": "1"})
    assert "TRINITY_DISABLE_DISPATCH" not in env


def test_a4b_legacy_trinity_mcp_token_stripped():
    env = build_provider_env({"TRINITY_MCP_TOKEN": "token-for-current-review"})
    assert "TRINITY_MCP_TOKEN" not in env


# ---------------------------------------------------------------------------
# A2: auth survives
# ---------------------------------------------------------------------------


def test_a2_openai_api_key_preserved():
    env = build_provider_env({"OPENAI_API_KEY": "sk-test"})
    assert env.get("OPENAI_API_KEY") == "sk-test"


def test_anthropic_api_key_preserved():
    env = build_provider_env({"ANTHROPIC_API_KEY": "sk-ant-test"})
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-test"


def test_google_api_key_preserved():
    env = build_provider_env({"GOOGLE_API_KEY": "g-test"})
    assert env.get("GOOGLE_API_KEY") == "g-test"


# ---------------------------------------------------------------------------
# A5: all 18 literal essentials preserved
# ---------------------------------------------------------------------------


LITERAL_ESSENTIALS = [
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "TERM",
    "SHELL",
    "TZ",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "SSH_AUTH_SOCK",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "PWD",
]


def test_a5_all_literal_essentials_preserved():
    fixture = {key: f"value_for_{key}" for key in LITERAL_ESSENTIALS}
    env = build_provider_env(fixture)
    for key in LITERAL_ESSENTIALS:
        assert env.get(key) == f"value_for_{key}", f"essential {key} was not preserved"


# ---------------------------------------------------------------------------
# A5: glob essentials preserved
# ---------------------------------------------------------------------------


def test_a5_lc_all_preserved():
    env = build_provider_env({"LC_ALL": "C.UTF-8"})
    assert env.get("LC_ALL") == "C.UTF-8"


def test_a5_lc_time_preserved():
    env = build_provider_env({"LC_TIME": "en_US"})
    assert env.get("LC_TIME") == "en_US"


def test_a5_git_ssh_command_preserved():
    env = build_provider_env({"GIT_SSH_COMMAND": "ssh -i ~/.ssh/key"})
    assert env.get("GIT_SSH_COMMAND") == "ssh -i ~/.ssh/key"


def test_a5_git_author_email_preserved():
    env = build_provider_env({"GIT_AUTHOR_EMAIL": "test@example.com"})
    assert env.get("GIT_AUTHOR_EMAIL") == "test@example.com"


# ---------------------------------------------------------------------------
# A5: bare-prefix glob edge case (per glm round-2 A3)
# ---------------------------------------------------------------------------


def test_lc_bare_prefix_preserved():
    """fnmatch.fnmatchcase('LC_', 'LC_*') matches because * is zero-or-more."""
    env = build_provider_env({"LC_": "edge_case"})
    assert env.get("LC_") == "edge_case"


# ---------------------------------------------------------------------------
# A6: empty-string-valued var matching clear pattern is stripped
# ---------------------------------------------------------------------------


def test_a6_empty_string_clearlist_stripped():
    env = build_provider_env({"OPENAI_BASE_URL": ""})
    assert "OPENAI_BASE_URL" not in env


def test_a6_empty_string_essential_preserved():
    env = build_provider_env({"PATH": ""})
    assert env.get("PATH") == ""


# ---------------------------------------------------------------------------
# A7: base_env=None default resolves at call time (no mutable-default
# antipattern). Two calls with different os.environ snapshots return
# different results.
# ---------------------------------------------------------------------------


def test_a7_base_env_none_resolves_at_call_time():
    with patch.object(codex_mod, "os") as mock_os:
        mock_os.environ = {"OPENAI_API_KEY": "first"}
        first = build_provider_env()
        mock_os.environ = {"OPENAI_API_KEY": "second"}
        second = build_provider_env()
    assert first.get("OPENAI_API_KEY") == "first"
    assert second.get("OPENAI_API_KEY") == "second"


# ---------------------------------------------------------------------------
# A8: build_provider_env returns dict[str, str]
# ---------------------------------------------------------------------------


def test_a8_return_type_is_dict():
    env = build_provider_env({"FOO": "bar"})
    assert isinstance(env, dict)
    for key, value in env.items():
        assert isinstance(key, str)
        assert isinstance(value, str)


def test_a8_returned_dict_is_fresh_not_alias():
    """Result is a fresh dict, not an alias of base_env. Mutating the
    returned dict must not mutate the input."""
    base = {"PATH": "/usr/bin"}
    env = build_provider_env(base)
    env["NEW_VAR"] = "added"
    assert "NEW_VAR" not in base


# ---------------------------------------------------------------------------
# A9: run_provider passes env=build_provider_env() to Popen
# ---------------------------------------------------------------------------


def test_a9_run_provider_passes_env_to_popen():
    """Round-2 codex advisory A1: replace grep-only check with monkeypatched
    Popen test. Asserts that run_provider calls Popen with env= matching
    build_provider_env's output (sanitized — no OPENAI_BASE_URL even if
    parent has it)."""
    import os
    import tempfile

    captured = {}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            captured["env"] = kwargs.get("env")
            self.returncode = 0
            self.pid = 12345

        def communicate(self, timeout=None):
            return ("ok\n", "")

        def wait(self, timeout=None):
            # TRN-2018 M1: run_provider uses Popen.wait() now (file-handle
            # stdout/stderr); mock returns immediately with rc=0.
            return 0

    class FakeRegistry:
        def add(self, *args, **kwargs):
            pass

        def remove(self, *args, **kwargs):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        review_dir = tmp / "review"
        (review_dir / "raw").mkdir(parents=True)
        prompt_path = tmp / "prompt.md"
        prompt_path.write_text("test prompt")

        provider_config = {"cli": "echo ok", "timeout": 10}

        with patch("subprocess.Popen", FakePopen):
            with patch.dict(
                os.environ, {"OPENAI_BASE_URL": "https://leak.invalid"}, clear=False
            ):
                codex_mod.run_provider(
                    "test-provider",
                    provider_config,
                    prompt_path,
                    review_dir,
                    tmp,
                    FakeRegistry(),
                )

    env = captured["env"]
    assert env is not None, "Popen was not called with env="
    assert "OPENAI_BASE_URL" not in env, (
        "leaked OPENAI_BASE_URL into spawned provider env"
    )
    # Non-cleared vars should still be present (PATH always essential).
    assert "PATH" in env

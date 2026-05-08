"""Unit tests for TRN-3021 doctor preflight expansions.

Covers:
- A1: provider_health result dict includes new keys (cli, auth, warnings, timeout_warning)
- A2-A3: detect_env_pollution flags clearlist matches, NOT API keys / essentials
- A4-A4c: wrapper_auth_check env-precedence + mode boundary (REQUIRED fatal / OPTIONAL warn)
- A5: wrapper_auth_check returns None for non-wrapper providers
- A6/A6b: timeout sanity warning (boundary at == 60)
- A7: warnings non-empty alone → exit 0; issues non-empty → exit 1
- A8b: format_health_results(verbose=False) preserves cmd_review co-consumer format
- A8c: synthetic-error branches in provider_health_results carry new keys
- A13: resolve_preset_providers metadata gains providers + optional_providers
- A14: health_results_ok metadata-aware (REQUIRED issues fatal; OPTIONAL demoted)
- A15: format_health_results verbose mode renders REQUIRED/OPTIONAL split
- A16: env pollution sorted alphabetically
- A17: tests use clean base_env (no host os.environ leakage)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import codex as codex_mod  # noqa: E402

provider_health = codex_mod.provider_health
provider_health_results = codex_mod.provider_health_results
format_health_results = codex_mod.format_health_results
health_results_ok = codex_mod.health_results_ok
detect_env_pollution = codex_mod.detect_env_pollution
wrapper_auth_check = codex_mod.wrapper_auth_check
_make_health_result = codex_mod._make_health_result
_MIN_TIMEOUT_WARNING_SECONDS = codex_mod._MIN_TIMEOUT_WARNING_SECONDS


# ---------------------------------------------------------------------------
# A1: provider_health result dict shape
# ---------------------------------------------------------------------------


def test_a1_result_dict_has_all_new_keys():
    result = _make_health_result("glm", ok=True)
    for key in (
        "provider",
        "ok",
        "executable",
        "timeout",
        "issues",
        "warnings",
        "cli",
        "auth",
        "timeout_warning",
    ):
        assert key in result, f"missing key {key}"


# ---------------------------------------------------------------------------
# A2 / A3 / A16 / A17: detect_env_pollution
# ---------------------------------------------------------------------------


def test_a2_openai_base_url_flagged():
    pollution = detect_env_pollution({"OPENAI_BASE_URL": "https://corp.invalid/v1"})
    keys = [k for k, _ in pollution]
    assert "OPENAI_BASE_URL" in keys


def test_a3_openai_api_key_NOT_flagged():
    pollution = detect_env_pollution({"OPENAI_API_KEY": "sk-test"})
    keys = [k for k, _ in pollution]
    assert "OPENAI_API_KEY" not in keys


def test_a16_pollution_sorted_alphabetically():
    pollution = detect_env_pollution(
        {
            "OTEL_SERVICE_NAME": "x",
            "OPENAI_BASE_URL": "y",
            "ANTHROPIC_BASE_URL": "z",
        }
    )
    keys = [k for k, _ in pollution]
    assert keys == sorted(keys)


def test_a17_clean_base_env_no_host_leakage():
    """A17: tests pass a clean dict; no host os.environ contamination."""
    pollution = detect_env_pollution({})
    assert pollution == []


def test_pollution_value_redacted():
    """Long values truncated to 12 chars + …"""
    pollution = detect_env_pollution(
        {"OPENAI_BASE_URL": "https://corp-internal.example.com/v1/chat"}
    )
    assert pollution[0][1].endswith("…")
    assert len(pollution[0][1]) == 13  # 12 chars + …


def test_pollution_essential_not_flagged():
    """PATH/HOME/etc. must never appear as pollution even if a clear pattern matched."""
    pollution = detect_env_pollution(
        {
            "PATH": "/usr/bin",
            "HOME": "/Users/x",
            "LC_ALL": "C.UTF-8",
            "GIT_SSH_COMMAND": "ssh",
        }
    )
    assert pollution == []


# ---------------------------------------------------------------------------
# A4 / A4b / A4c: wrapper_auth_check
# ---------------------------------------------------------------------------


def test_a4_missing_returns_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = wrapper_auth_check("deepseek")
    assert result["source"] == "missing"


def test_a4b_env_var_takes_precedence(tmp_path, monkeypatch):
    """A4b: $DEEPSEEK_API_KEY set → source: env, regardless of file."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = wrapper_auth_check("deepseek")
    assert result["source"] == "env"
    assert result["env_var"] == "DEEPSEEK_API_KEY"


def test_a4c_mode_600_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    key_file = secrets / "deepseek_api_key"
    key_file.write_text("sk-test\n")
    key_file.chmod(0o600)
    result = wrapper_auth_check("deepseek")
    assert result["source"] == "file"
    assert result["mode_ok"] is True


def test_a4c_mode_400_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    key_file = secrets / "deepseek_api_key"
    key_file.write_text("sk-test\n")
    key_file.chmod(0o400)
    result = wrapper_auth_check("deepseek")
    assert result["mode_ok"] is True


def test_a4c_mode_644_NOT_ok(tmp_path, monkeypatch):
    """A4c: wrong-mode file → mode_ok: False (matches wrapper exit-1)."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    key_file = secrets / "deepseek_api_key"
    key_file.write_text("sk-test\n")
    key_file.chmod(0o644)
    result = wrapper_auth_check("deepseek")
    assert result["source"] == "file"
    assert result["mode_ok"] is False


def test_a4c_symlink_uses_lstat(tmp_path, monkeypatch):
    """Codex bot PR #68 finding: wrapper_auth_check must use lstat() so
    symlinks report their OWN mode (typically 777), not the target's.
    Otherwise doctor reports mode_ok=True for a symlink → 0600 target,
    while the wrapper's `stat -c '%a'` on Linux would report 777 and
    refuse to read."""
    import os as _os

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    target = tmp_path / "real_secret"
    target.write_text("sk-target\n")
    target.chmod(0o600)  # target is 0600
    link = secrets / "deepseek_api_key"
    _os.symlink(target, link)
    result = wrapper_auth_check("deepseek")
    # On Linux, lstat reports symlink mode as 0o777 — mode_ok should be False.
    # On macOS, lstat reports 0o755 — also False.
    # Either way the symlink's own mode is NOT 600 or 400.
    assert result["source"] == "file"
    assert result["mode_ok"] is False


# ---------------------------------------------------------------------------
# A5: non-wrapper providers
# ---------------------------------------------------------------------------


def test_a5_glm_returns_none():
    """glm uses vendor login flow, not auth file."""
    assert wrapper_auth_check("glm") is None


def test_a5_codex_returns_none():
    assert wrapper_auth_check("codex") is None


def test_a5_gemini_returns_none():
    assert wrapper_auth_check("gemini") is None


def test_a5_claude_code_returns_none():
    """claude-code wrapper exists in providers/bin/ but uses vendor login
    (CLAUDE_CONFIG_DIR), not a KEY_FILE pattern. Asserts the
    "exactly two wrapper providers" registry invariant (per glm code-review A1)."""
    assert wrapper_auth_check("claude-code") is None


# Auth check moved to cmd_doctor for canonical-wrapper paths only — see
# test_codex_doctor_* in test_codex_adapter.py for end-to-end coverage.
# The wrapper_auth_check unit tests A4/A4b/A4c-mode-600/400/644 above already
# cover the helper's behavior across all source/mode_ok permutations.


# ---------------------------------------------------------------------------
# A6 / A6b: timeout sanity
# ---------------------------------------------------------------------------


def test_a6_timeout_30_flags_warning(tmp_path):
    config = {"providers": {"glm": {"cli": "echo", "timeout": 30}}}
    results = provider_health_results(config, ["glm"], tmp_path)
    assert results[0]["timeout_warning"] is True
    assert any("30s" in w and "60s" in w for w in results[0]["warnings"])


def test_a6b_timeout_60_NOT_flagged(tmp_path):
    """Boundary: timeout == 60 (the threshold) → NOT flagged."""
    config = {"providers": {"glm": {"cli": "echo", "timeout": 60}}}
    results = provider_health_results(config, ["glm"], tmp_path)
    assert results[0]["timeout_warning"] is False


def test_timeout_61_NOT_flagged(tmp_path):
    config = {"providers": {"glm": {"cli": "echo", "timeout": 61}}}
    results = provider_health_results(config, ["glm"], tmp_path)
    assert results[0]["timeout_warning"] is False


# ---------------------------------------------------------------------------
# A7 / A14: health_results_ok metadata-aware
# ---------------------------------------------------------------------------


def test_a7_warnings_only_passes():
    """Warnings non-empty alone → True (exit 0)."""
    results = [_make_health_result("glm", ok=True, warnings=["timeout 30s low"])]
    assert health_results_ok(results) is True


def test_a7_required_issues_fail():
    """REQUIRED provider with issues → False (exit 1)."""
    results = [_make_health_result("glm", ok=False, issues=["auth missing"])]
    assert health_results_ok(results) is False


def test_a14_optional_issues_demoted():
    """OPTIONAL provider with issues → demoted (True / exit 0)."""
    results = [_make_health_result("codex", ok=False, issues=["auth missing"])]
    metadata = {"providers": ["glm"], "optional_providers": ["codex"]}
    assert health_results_ok(results, preset_metadata=metadata) is True


def test_a14_required_issues_still_fatal_with_metadata():
    results = [_make_health_result("glm", ok=False, issues=["x"])]
    metadata = {"providers": ["glm"], "optional_providers": ["codex"]}
    assert health_results_ok(results, preset_metadata=metadata) is False


def test_a14_metadata_none_treats_all_as_required():
    """preset_metadata=None (cmd_review --check-providers existing call site) treats all as REQUIRED."""
    results = [_make_health_result("codex", ok=False, issues=["x"])]
    assert health_results_ok(results) is False
    assert health_results_ok(results, preset_metadata=None) is False


def test_a14_overlap_required_wins(tmp_path):
    """Codex bot PR #68 finding: a provider listed in BOTH `providers` and
    `optional_providers` must be treated as REQUIRED for exit-code purposes.
    Without subtraction, the optional set membership would silently demote
    the issue and exit 0."""
    results = [_make_health_result("glm", ok=False, issues=["auth missing"])]
    metadata = {"providers": ["glm"], "optional_providers": ["glm", "codex"]}
    # glm appears in BOTH lists; required wins → exit 1.
    assert health_results_ok(results, preset_metadata=metadata) is False


# ---------------------------------------------------------------------------
# A8b: format_health_results(verbose=False) backwards-compat
# ---------------------------------------------------------------------------


def test_a8b_compact_mode_preserves_existing_format():
    results = [
        _make_health_result("glm", ok=True, executable="/usr/bin/droid", timeout=360),
    ]
    out = format_health_results(results)  # verbose=False default
    assert out == "glm: OK - /usr/bin/droid (timeout 360s)"


def test_a8b_compact_mode_fail_format():
    results = [_make_health_result("glm", ok=False, issues=["command not found"])]
    out = format_health_results(results)
    assert out == "glm: FAIL - command not found"


# ---------------------------------------------------------------------------
# A15: format_health_results verbose mode REQUIRED/OPTIONAL split
# ---------------------------------------------------------------------------


def test_a15_verbose_renders_required_optional_split():
    results = [
        _make_health_result("glm", ok=True, executable="/bin/droid", timeout=360),
        _make_health_result("codex", ok=True, executable="/bin/codex", timeout=600),
    ]
    metadata = {"providers": ["glm"], "optional_providers": ["codex"]}
    out = format_health_results(results, preset_metadata=metadata, verbose=True)
    assert "REQUIRED:" in out
    assert "OPTIONAL:" in out
    # First line per provider grep-compatible.
    assert "glm: OK - /bin/droid (timeout 360s)" in out
    assert "codex: OK - /bin/codex (timeout 600s)" in out


def test_a15_verbose_no_preset_single_section():
    """When preset_metadata is None, no REQUIRED/OPTIONAL split."""
    results = [
        _make_health_result("glm", ok=True, executable="/bin/droid", timeout=360),
    ]
    out = format_health_results(results, verbose=True)
    assert "REQUIRED:" not in out
    assert "OPTIONAL:" not in out
    assert "glm: OK - /bin/droid" in out


def test_verbose_includes_env_pollution():
    results = [
        _make_health_result("glm", ok=True, executable="/bin/droid", timeout=360)
    ]
    out = format_health_results(
        results,
        env_pollution=[("OPENAI_BASE_URL", "https://x.inv…")],
        verbose=True,
    )
    assert "ENV POLLUTION" in out
    assert "OPENAI_BASE_URL" in out


# ---------------------------------------------------------------------------
# A8c: synthetic-error branches carry new keys
# ---------------------------------------------------------------------------


def test_a8c_unknown_provider_branch_has_new_keys(tmp_path):
    config = {"providers": {"glm": {"cli": "echo"}}}
    results = provider_health_results(config, ["nonexistent"], tmp_path)
    for key in ("cli", "auth", "warnings", "timeout_warning"):
        assert key in results[0]


def test_a8c_malformed_providers_branch_has_new_keys(tmp_path):
    config = {"providers": "not-a-dict"}
    results = provider_health_results(config, ["glm"], tmp_path)
    for key in ("cli", "auth", "warnings", "timeout_warning"):
        assert key in results[0]


# ---------------------------------------------------------------------------
# A13: resolve_preset_providers extended metadata
# ---------------------------------------------------------------------------


def test_a13_preset_metadata_has_providers_and_optional_providers():
    """A13: resolve_preset_providers returns metadata with the 2 new keys
    populated for a preset with required + optional."""
    # Use the resolve_preset_providers function directly with a synthetic config.
    config = {
        "providers": {
            "glm": {"cli": "echo"},
            "deepseek": {"cli": "echo"},
            "codex": {"cli": "echo"},
        },
        "presets": {
            "review": {
                "providers": ["glm", "deepseek"],
                "optional_providers": ["codex", "missing"],
                "task_type": "review",
            }
        },
    }
    providers, metadata, _ = codex_mod.resolve_preset_providers(
        config, "review", "explicit"
    )
    assert "providers" in metadata
    assert "optional_providers" in metadata
    assert metadata["providers"] == ["glm", "deepseek"]
    assert metadata["optional_providers"] == ["codex", "missing"]
    # Existing 5 keys preserved:
    for key in (
        "requested",
        "resolved",
        "source",
        "task_type",
        "skipped_optional_providers",
    ):
        assert key in metadata


# ---------------------------------------------------------------------------
# CLI shlex.join
# ---------------------------------------------------------------------------


def test_cli_field_uses_shlex_join(tmp_path):
    """provider_health.cli is shlex.join'd for safe quoting."""
    config = {"providers": {"glm": {"cli": "echo --foo bar"}}}
    results = provider_health_results(config, ["glm"], tmp_path)
    cli = results[0]["cli"]
    assert cli is not None
    # The resolved executable + args, shlex-joined
    assert "echo" in cli
    assert "--foo" in cli
    assert "bar" in cli

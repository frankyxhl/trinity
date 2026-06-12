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
        "live_probe",
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


def test_optional_provider_issues_render_as_warn_not_fail():
    """Codex bot PR #68 round-3 P2 finding: OPTIONAL provider with issues
    must render as WARN headline (not FAIL), since health_results_ok
    demotes the issue to non-fatal. Without this, doctor exits 0 but
    display says FAIL — user-visible inconsistency."""
    results = [
        _make_health_result("codex", ok=False, issues=["command not found: codex"]),
    ]
    metadata = {"providers": ["glm"], "optional_providers": ["codex"]}
    out = format_health_results(results, preset_metadata=metadata, verbose=True)
    # Headline for optional provider must say WARN, not FAIL.
    assert "codex: WARN -" in out
    assert "codex: FAIL -" not in out


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


# ---------------------------------------------------------------------------
# Canonical wrapper exact path match (PR #68 round-4)
# ---------------------------------------------------------------------------


def test_canonical_wrapper_rejects_substring_match(tmp_path, monkeypatch):
    """Codex bot PR #68 round-4 P2 finding: _is_canonical_wrapper must use
    exact path match, not substring. A custom executable named
    `deepseek-test` or under a non-canonical `/tmp/skills/trinity/bin/`
    path must NOT trigger wrapper auth probing."""
    from codex import _is_canonical_wrapper

    monkeypatch.setenv("HOME", str(tmp_path))

    fake_dir = tmp_path / ".codex" / "skills" / "trinity" / "bin"
    fake_dir.mkdir(parents=True)
    fake = fake_dir / "deepseek-test"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert _is_canonical_wrapper(str(fake), "deepseek") is False, (
        "deepseek-test must not match canonical deepseek wrapper"
    )

    other_dir = tmp_path / "tmp" / "skills" / "trinity" / "bin"
    other_dir.mkdir(parents=True)
    other = other_dir / "deepseek"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    assert _is_canonical_wrapper(str(other), "deepseek") is False, (
        "non-canonical /tmp/skills/.../deepseek must not match"
    )

    real = fake_dir / "deepseek"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    assert _is_canonical_wrapper(str(real), "deepseek") is True, (
        "canonical ~/.codex/skills/trinity/bin/deepseek must match"
    )


def test_canonical_wrapper_resolves_symlinks(tmp_path, monkeypatch):
    """Symlinked install: if user has the real wrapper at a non-canonical
    location and symlinks the canonical path to it, _is_canonical_wrapper
    should still match (Path.resolve() follows the link)."""
    import os as _os

    from codex import _is_canonical_wrapper

    monkeypatch.setenv("HOME", str(tmp_path))

    real = tmp_path / "actual_wrapper"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)

    canonical_dir = tmp_path / ".claude" / "skills" / "trinity" / "bin"
    canonical_dir.mkdir(parents=True)
    canonical = canonical_dir / "deepseek"
    _os.symlink(real, canonical)

    assert _is_canonical_wrapper(str(canonical), "deepseek") is True


# ---------------------------------------------------------------------------
# Live probe tests (TRN-3042_209)
# ---------------------------------------------------------------------------


def test_live_probe_success(tmp_path):
    """Probe passes when the provider exits 0."""
    from codex import _probe_provider

    fake = tmp_path / "ok_provider"
    fake.write_text("#!/bin/sh\necho OK\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None
    assert result["status"] == "pass"


def test_live_probe_auth_failure(tmp_path):
    """Probe classifies 401/unauthorized output as auth failure."""
    from codex import _probe_provider

    fake = tmp_path / "auth_fail"
    fake.write_text("#!/bin/sh\necho '401 Unauthorized: invalid API key'\nexit 1\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None
    assert result["status"] == "fail"
    assert result["cause"] == "auth"


def test_live_probe_quota_failure(tmp_path):
    """Probe classifies 429/quota output as quota failure."""
    from codex import _probe_provider

    fake = tmp_path / "quota_fail"
    fake.write_text("#!/bin/sh\necho '429 Too Many Requests: quota exceeded'\nexit 1\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None
    assert result["status"] == "fail"
    assert result["cause"] == "quota"


def test_live_probe_timeout(tmp_path):
    """Probe reports timeout when the provider does not respond in time."""
    from codex import _probe_provider, _LIVE_PROBE_TIMEOUT

    fake = tmp_path / "slow_provider"
    # Sleep a long time
    fake.write_text(f"#!/bin/sh\nsleep {_LIVE_PROBE_TIMEOUT + 5}\necho 'too late'\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 120}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None
    assert result["status"] == "fail"
    assert result["cause"] == "timeout"


def test_live_probe_skips_bad_config(tmp_path):
    """Probe returns None when the provider config is unparseable."""
    from codex import _probe_provider

    config = {"cli": ""}  # missing cli — parse error
    result = _probe_provider("test", config, tmp_path)
    assert result is None


def test_live_probe_renders_in_verbose_output(tmp_path):
    """A passed live probe adds 'live: pass' in verbose format."""
    from codex import _format_provider_block

    fake = tmp_path / "ok_provider"
    fake.write_text("#!/bin/sh\necho OK\n")
    fake.chmod(0o755)

    result = _make_health_result("test", ok=True, executable=str(fake), timeout=30)
    result["live_probe"] = {"status": "pass"}
    lines = _format_provider_block(result)
    assert any("live: pass" in line for line in lines)


def test_live_probe_fail_renders_in_verbose_output(tmp_path):
    """A failed live probe adds 'live: FAIL - cause: detail' in verbose."""
    from codex import _format_provider_block

    result = _make_health_result("test", ok=False, executable="/bin/fake", timeout=30)
    result["live_probe"] = {
        "status": "fail",
        "cause": "auth",
        "detail": "exit 1: 401 Unauthorized",
    }
    lines = _format_provider_block(result)
    assert any("live: FAIL - auth" in line for line in lines)


def test_live_probe_via_script_execution(tmp_path):
    """Regression for PR #215 codex P1: `doctor --live` must work when
    codex.py executes as a script (`__main__`), not only when imported.

    The probe helpers were originally appended AFTER the `__main__`
    block, so `main()` ran before they were defined and `--live`
    crashed with NameError. Import-based tests cannot catch that
    execution-order bug; this test runs the real CLI as a subprocess.
    """
    import json
    import subprocess

    fake = tmp_path / "ok_provider"
    fake.write_text("#!/bin/sh\necho OK\n")
    fake.chmod(0o755)

    config_path = tmp_path / "trinity.codex.json"
    config_path.write_text(
        json.dumps({"providers": {"test": {"cli": str(fake), "timeout": 30}}})
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "codex.py"),
            "doctor",
            "--root",
            str(tmp_path),
            "--config",
            str(config_path),
            "--providers",
            "test",
            "--live",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "NameError" not in result.stderr
    assert result.returncode == 0, result.stderr
    assert "live: pass" in result.stdout


def test_live_probe_passes_prompt_as_cli_argument(tmp_path):
    """Regression (PR #215 codex P2): the probe prompt must be appended as
    the final CLI argument, mirroring run_provider, because the bundled
    CLIs (gemini -p / droid exec / codex exec) take the prompt via argv —
    a stdin-only probe would report live failures for working providers."""
    from codex import _probe_provider

    fake = tmp_path / "argv_provider"
    fake.write_text('#!/bin/sh\n[ -n "$1" ] || exit 1\necho OK\n')
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None
    assert result["status"] == "pass"


def test_live_probe_runs_from_resolved_root(tmp_path, monkeypatch):
    """Regression (PR #215 codex P2): a provider configured with a relative
    executable path passes executable_health (resolved against root) but
    the probe subprocess ran from the process cwd, hit FileNotFoundError,
    and was silently skipped. The probe must run with cwd=root."""
    from codex import _probe_provider

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rel_provider"
    fake.write_text("#!/bin/sh\necho OK\n")
    fake.chmod(0o755)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    config = {"cli": "bin/rel_provider", "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None, "probe must not be silently skipped"
    assert result["status"] == "pass"


def test_live_probe_reports_launch_failure(tmp_path):
    """Regression (PR #215 codex P2 #3): a file that passes the static
    executable check but cannot launch (missing shebang interpreter)
    must surface as a live 'error' failure, not be silently skipped —
    otherwise doctor --live exits 0 for a provider reviews cannot run."""
    from codex import _probe_provider

    fake = tmp_path / "broken_shebang"
    fake.write_text("#!/no/such/interpreter\necho OK\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 30}
    result = _probe_provider("test", config, tmp_path)
    assert result is not None, "launch failure must not be silently skipped"
    assert result["status"] == "fail"
    assert result["cause"] == "error"
    assert "failed to launch" in result["detail"]


def test_live_probe_timeout_kills_process_group(tmp_path, monkeypatch):
    """Regression (PR #215 codex P2 #4): when a provider spawns a child
    that inherits the captured pipes, a probe timeout must kill the whole
    process group — otherwise communicate() keeps waiting on the pipes
    held by the orphaned child, far past the advertised timeout."""
    import time as _time

    monkeypatch.setattr(codex_mod, "_LIVE_PROBE_TIMEOUT", 1)

    fake = tmp_path / "forking_provider"
    fake.write_text("#!/bin/sh\nsleep 30 &\nsleep 30\n")
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 120}

    start = _time.monotonic()
    result = codex_mod._probe_provider("test", config, tmp_path)
    elapsed = _time.monotonic() - start

    assert result is not None
    assert result["status"] == "fail"
    assert result["cause"] == "timeout"
    assert elapsed < 10, f"probe blocked {elapsed:.1f}s past its 1s timeout"


def test_live_probe_timeout_kills_orphaned_children(tmp_path, monkeypatch):
    """Regression (PR #215 codex P2 #5): when the provider leader exits
    before the deadline but leaves a pipe-holding child behind,
    terminate_process_group() short-circuits on poll() and the child
    survived. The probe must signal the process group id directly
    (== proc.pid under start_new_session) so the orphan dies too."""
    import os as _os
    import time as _time

    monkeypatch.setattr(codex_mod, "_LIVE_PROBE_TIMEOUT", 1)

    pid_file = tmp_path / "child.pid"
    fake = tmp_path / "exiting_leader"
    fake.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{pid_file}"\nexit 0\n')
    fake.chmod(0o755)
    config = {"cli": str(fake), "timeout": 120}

    result = codex_mod._probe_provider("test", config, tmp_path)

    assert result is not None
    assert result["status"] == "fail"
    assert result["cause"] == "timeout"

    child_pid = int(pid_file.read_text().strip())
    deadline = _time.monotonic() + 5
    while _time.monotonic() < deadline:
        try:
            _os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        _time.sleep(0.1)
    else:
        _os.kill(child_pid, 9)  # cleanup before failing
        raise AssertionError("orphaned child survived the probe timeout")

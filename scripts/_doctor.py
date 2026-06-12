"""Doctor / preflight health-check subcommand for Trinity.

Extracted from scripts/codex.py as part of issue #206 (module split).
codex.py imports this module and re-exports all public names so
``import codex; codex.provider_health`` keeps working.

IMPORTANT: _probe_provider reads _LIVE_PROBE_TIMEOUT via a lazy ``import
codex`` so that monkeypatch.setattr(codex_mod, "_LIVE_PROBE_TIMEOUT", ...)
in tests still takes effect.
"""

import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

try:
    from . import provider_runtime as _provider_runtime
except ImportError:
    import provider_runtime as _provider_runtime

parse_provider_command = _provider_runtime.parse_provider_command
provider_timeout = _provider_runtime.provider_timeout
command_has_path = _provider_runtime.command_has_path
_DEFAULT_ENV_CLEAR_PATTERNS = _provider_runtime._DEFAULT_ENV_CLEAR_PATTERNS
_matches_any = _provider_runtime._matches_any
_is_essential = _provider_runtime._is_essential

_MIN_TIMEOUT_WARNING_SECONDS = 60

# TRN-3021: per-provider auth-file paths for wrapper providers. Hardcoded
# v1 because exactly 2 providers in providers/registry.json use this
# pattern (verified: `grep KEY_FILE providers/bin/*` returns deepseek + openrouter).
# Tagged tech-debt — declarative `auth_env` + `auth_file` registry fields
# belong in TRN-3030 follow-up CHG.
_WRAPPER_AUTH_CONFIG = {
    "deepseek": {
        "env_var": "DEEPSEEK_API_KEY",
        "file": "~/.secrets/deepseek_api_key",
    },
    "openrouter": {
        "env_var": "OPENROUTER_API_KEY",
        "file": "~/.secrets/openrouter_api_key",
    },
}


def _make_health_result(
    provider,
    *,
    ok,
    issues=(),
    warnings=(),
    executable=None,
    timeout=None,
    cli=None,
    auth=None,
    timeout_warning=False,
):
    """Construct a provider_health result dict with all TRN-3021 keys.

    Used by all 3 sites that build result dicts: canonical at
    provider_health (line ~413), synthetic-error branches at
    provider_health_results (lines ~425, ~440). Defensive defaults
    keep the dict additive — older consumers reading via .get() see
    sensible values for new keys.
    """
    return {
        "provider": provider,
        "ok": ok,
        "executable": executable,
        "timeout": timeout,
        "issues": list(issues),
        # TRN-3021 additions:
        "warnings": list(warnings),
        "cli": cli,
        "auth": auth,
        "timeout_warning": timeout_warning,
        "live_probe": None,
    }


def wrapper_auth_check(provider):
    """TRN-3021: check wrapper-provider auth via env-or-file precedence.

    Mirrors providers/bin/<provider>:10-31 contract:
      1. env var (DEEPSEEK_API_KEY / OPENROUTER_API_KEY) → source: "env"
      2. file at ~/.secrets/<provider>_api_key with mode 600 or 400
         → source: "file", mode_ok: True
      3. file with wrong mode → source: "file", mode_ok: False
         (wrapper exits 1 at runtime; severity is fatal for REQUIRED)
      4. neither → source: "missing"

    Returns None for non-wrapper providers (vendor login flow, no file).
    """
    if provider not in _WRAPPER_AUTH_CONFIG:
        return None
    config = _WRAPPER_AUTH_CONFIG[provider]
    env_name = config["env_var"]
    if os.environ.get(env_name):
        return {
            "source": "env",
            "env_var": env_name,
            "file": None,
            "mode_ok": None,
        }
    file_path = Path(config["file"]).expanduser()
    if not file_path.exists():
        return {
            "source": "missing",
            "env_var": env_name,
            "file": str(file_path),
            "mode_ok": None,
        }
    try:
        # Use lstat to match wrapper's `stat -c '%a' "$KEY_FILE"` behavior:
        # on GNU/Linux that reports the symlink's own mode (typically 777),
        # not the target's. Following the symlink (file_path.stat()) would
        # report a 0600 target as ok while the wrapper still refuses to
        # read the symlink at runtime — inconsistency caught by codex bot
        # on PR #68.
        mode = file_path.lstat().st_mode & 0o777
    except OSError:
        return {
            "source": "file",
            "env_var": env_name,
            "file": str(file_path),
            "mode_ok": False,
        }
    return {
        "source": "file",
        "env_var": env_name,
        "file": str(file_path),
        "mode_ok": mode in (0o600, 0o400),
    }


def _is_canonical_wrapper(executable, provider):
    """True iff `executable` is the actual canonical wrapper script for `provider`.

    The canonical wrapper lives at one of these EXACT paths (exact basename
    match, no substring fuzzing):
      - <HOME>/.claude/skills/trinity/bin/<provider>
      - <HOME>/.codex/skills/trinity/bin/<provider>
      - <repo>/providers/bin/<provider>  (when running tests from repo root)

    Custom configs that reuse the provider name with a different executable
    (e.g. `deepseek-test`) or a different path (e.g. `/tmp/skills/trinity/
    bin/deepseek`) won't match, so cmd_doctor's wrapper-auth check stays
    out of their way.

    Compares against `Path(executable).resolve()` so a symlinked install
    still matches the canonical target.
    """
    if executable is None or provider not in _WRAPPER_AUTH_CONFIG:
        return False
    try:
        actual = Path(executable).resolve()
    except (OSError, RuntimeError):
        return False

    home = Path(os.path.expanduser("~"))
    candidates = [
        home / ".claude" / "skills" / "trinity" / "bin" / provider,
        home / ".codex" / "skills" / "trinity" / "bin" / provider,
        Path(__file__).resolve().parent.parent / "providers" / "bin" / provider,
    ]

    for c in candidates:
        try:
            if c.resolve() == actual:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def detect_env_pollution(base_env=None):
    """TRN-3021: scan parent env for vars that match the TRN-3023 clearlist.

    Flag iff `_matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS) AND NOT
    _is_essential(key)`. Essentials check first (defensive ordering, matches
    `build_provider_env` at codex.py:_is_essential). Values truncated to
    first 12 chars + "…" to avoid leaking corp hostnames / token-adjacent
    strings. Returns list of (key, redacted_value) sorted alphabetically
    by key for deterministic display.
    """
    if base_env is None:
        base_env = os.environ
    found = []
    for key, value in base_env.items():
        if _is_essential(key):
            continue
        if _matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS):
            redacted = value if len(value) <= 12 else value[:12] + "…"
            found.append((key, redacted))
    found.sort(key=lambda kv: kv[0])
    return found


def executable_health(command, root):
    executable = command[0]
    if command_has_path(executable):
        executable_path = Path(executable)
        if not executable_path.is_absolute():
            executable_path = root / executable_path
        if not executable_path.exists():
            return None, f"command not found: {executable_path}"
        if executable_path.is_dir() or not os.access(executable_path, os.X_OK):
            return str(executable_path), f"not executable: {executable_path}"
        return str(executable_path), None

    resolved = shutil.which(executable)
    if resolved is None:
        return None, f"command not found: {executable}"
    return resolved, None


def provider_health(provider, provider_config, root):
    """TRN-3021: extended preflight health check.

    Returns a result dict with keys: provider, ok, executable, timeout,
    issues, warnings, cli, auth, timeout_warning. See _make_health_result.

    Severity routing:
      - timeout-sanity (timeout < 60): always `warnings`
      - wrapper-auth-MISSING / WRONG-MODE: REQUIRED → `issues` (fatal,
        matches wrapper exit 1); OPTIONAL → demoted via metadata-aware
        `health_results_ok` at exit-code time. This function reports
        the auth fault into `issues` unconditionally; demotion happens
        in health_results_ok based on preset_metadata.
    """
    issues = []
    warnings = []
    command = None
    executable = None
    timeout = None
    cli = None
    timeout_warning = False

    try:
        command = parse_provider_command(provider, provider_config)
    except ValueError as exc:
        issues.append(str(exc))

    if command:
        executable, issue = executable_health(command, root)
        if issue:
            issues.append(issue)
        if executable is not None:
            cli = shlex.join([executable, *command[1:]])

    if isinstance(provider_config, dict):
        try:
            timeout = provider_timeout(provider, provider_config)
        except ValueError as exc:
            issues.append(str(exc))

    if timeout is not None and timeout < _MIN_TIMEOUT_WARNING_SECONDS:
        warnings.append(
            f"timeout {timeout}s is below {_MIN_TIMEOUT_WARNING_SECONDS}s "
            f"minimum recommended"
        )
        timeout_warning = True

    return _make_health_result(
        provider,
        ok=not issues,
        issues=issues,
        warnings=warnings,
        executable=executable,
        timeout=timeout,
        cli=cli,
        auth=None,
        timeout_warning=timeout_warning,
    )


def provider_health_results(config, providers, root):
    provider_configs = config.get("providers", {})
    if not isinstance(provider_configs, dict):
        return [
            _make_health_result(
                provider,
                ok=False,
                issues=["providers config must be an object"],
            )
            for provider in providers
        ]

    results = []
    for provider in providers:
        if provider not in provider_configs:
            results.append(
                _make_health_result(
                    provider,
                    ok=False,
                    issues=["unknown provider"],
                )
            )
            continue
        results.append(provider_health(provider, provider_configs[provider], root))
    return results


def _format_provider_block(result, *, optional=False):
    """Render one provider's verbose block. Helper for format_health_results.

    When optional=True, NOT-OK providers render as `WARN` instead of
    `FAIL` because health_results_ok demotes their issues to warnings
    (codex bot finding on PR #68 round 3).
    """
    provider = result["provider"]
    fail_label = "WARN" if optional else "FAIL"
    lines = []
    if result.get("ok"):
        first = (
            f"{provider}: OK - {result.get('executable')} "
            f"(timeout {result.get('timeout')}s)"
        )
    else:
        # First non-fatal warning OR first issue feeds the headline.
        if result.get("issues"):
            first = f"{provider}: {fail_label} - {result['issues'][0]}"
        else:
            first = (
                f"{provider}: OK - {result.get('executable')} "
                f"(timeout {result.get('timeout')}s)"
            )
    lines.append(first)
    if result.get("cli"):
        lines.append(f"    cli: {result['cli']}")
    auth = result.get("auth")
    if auth is not None:
        if auth["source"] == "env":
            lines.append(f"    auth: env ${auth['env_var']} set")
        elif auth["source"] == "file" and auth["mode_ok"]:
            lines.append(f"    auth: file {auth['file']} (mode ok)")
        elif auth["source"] == "file":
            lines.append(
                f"    auth: file {auth['file']} (mode WRONG, expected 600/400)"
            )
        else:
            lines.append(
                f"    auth: missing — ${auth['env_var']} unset, {auth['file']} absent"
            )
    probe = result.get("live_probe")
    if probe is not None:
        if probe["status"] == "pass":
            lines.append("    live: pass")
        else:
            lines.append(f"    live: FAIL - {probe['cause']}: {probe['detail']}")
    for w in result.get("warnings", []):
        lines.append(f"    warning: {w}")
    for issue in result.get("issues", []):
        if first.startswith(f"{provider}: {fail_label} - {issue}"):
            continue  # already in headline
        lines.append(f"    issue: {issue}")
    return lines


def format_health_results(
    results, *, env_pollution=None, preset_metadata=None, verbose=False
):
    """Render provider health results.

    Default (verbose=False) preserves the existing single-line shape
    `{provider}: OK - {executable} (timeout Ns)` per provider — used by
    `cmd_review --check-providers` (codex.py:1397-1403). Verbose mode
    (cmd_doctor) adds REQUIRED/OPTIONAL split, indented detail rows, and
    an ENV POLLUTION section. First line per provider stays grep-compatible.
    """
    if not verbose:
        lines = []
        for result in results:
            provider = result["provider"]
            if result["ok"]:
                lines.append(
                    f"{provider}: OK - {result['executable']} "
                    f"(timeout {result['timeout']}s)"
                )
                continue
            for issue in result["issues"]:
                lines.append(f"{provider}: FAIL - {issue}")
        return "\n".join(lines)

    # Verbose mode.
    optional_set = set()
    if preset_metadata is not None:
        # Subtract REQUIRED to match health_results_ok demotion logic
        # (codex bot finding on PR #68): a provider in BOTH lists is
        # treated as required.
        required_set = set(preset_metadata.get("providers", []))
        optional_set = set(preset_metadata.get("optional_providers", [])) - required_set

    required_results = [r for r in results if r["provider"] not in optional_set]
    optional_results = [r for r in results if r["provider"] in optional_set]

    lines = []
    if preset_metadata is not None and (required_results or optional_results):
        if required_results:
            lines.append("REQUIRED:")
            for r in required_results:
                lines.extend(_format_provider_block(r))
                lines.append("")
        if optional_results:
            lines.append("OPTIONAL:")
            for r in optional_results:
                lines.extend(_format_provider_block(r, optional=True))
                lines.append("")
    else:
        # No preset → single PROVIDERS section.
        for r in results:
            lines.extend(_format_provider_block(r))
            lines.append("")

    if env_pollution:
        lines.append(
            "ENV POLLUTION (would leak into provider spawn pre-TRN-3023; now stripped at spawn):"
        )
        for key, redacted in env_pollution:
            if redacted:
                lines.append(
                    f"    ⚠️  {key} set in shell ({redacted}) — stripped at spawn"
                )
            else:
                lines.append(f"    ⚠️  {key} set in shell — stripped at spawn")
        lines.append("")

    return "\n".join(lines).rstrip("\n")


def health_results_ok(results, *, preset_metadata=None):
    """TRN-3021: metadata-aware exit-code decision.

    REQUIRED providers with `issues` non-empty → False (exit 1).
    OPTIONAL providers with `issues` non-empty → demoted (don't fail).
    `preset_metadata=None` (existing call sites in cmd_review --check-providers)
    treats all providers as REQUIRED, preserving current semantics.
    """
    optional_set = set()
    if preset_metadata is not None:
        # Subtract REQUIRED first: if a provider appears in BOTH
        # `providers` (required) and `optional_providers`, the required
        # designation wins (resolve_preset_providers selects it as
        # required first). Codex bot finding on PR #68: without this
        # subtraction, an overlap silently demotes a fatal issue to
        # warning-only and exits 0.
        required_set = set(preset_metadata.get("providers", []))
        optional_set = set(preset_metadata.get("optional_providers", [])) - required_set
    for result in results:
        if result.get("issues") and result["provider"] not in optional_set:
            return False
    return True


def _probe_provider(provider, provider_config, root):
    """Run a minimal live probe against a provider CLI.

    Returns a dict with 'status' ('pass'|'fail') and if fail, 'cause'
    ('auth'|'quota'|'timeout'|'error') and 'detail'. Returns None when
    the provider cannot be probed (static check would already have
    caught it).

    NOTE: reads _LIVE_PROBE_TIMEOUT from the codex module at call time so
    monkeypatch.setattr(codex_mod, "_LIVE_PROBE_TIMEOUT", ...) works in tests.
    """
    # Lazy import so codex.py's _LIVE_PROBE_TIMEOUT is always the live value.
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    live_probe_timeout = _codex._LIVE_PROBE_TIMEOUT

    try:
        command = parse_provider_command(provider, provider_config)
    except ValueError:
        return None
    executable, issue = executable_health(command, root)
    if issue or executable is None:
        return None
    env = _codex.build_provider_env()
    try:
        # Mirror run_provider semantics: the prompt is appended as the final
        # CLI argument (gemini -p / droid exec / codex exec all take it that
        # way), the probe runs from the resolved root so relative
        # executable paths match the static executable_health check, and the
        # probe gets its own session so a timeout can kill the whole process
        # group — descendants holding the captured pipes would otherwise
        # stall communicate() well past the advertised timeout.
        proc = subprocess.Popen(
            command + ["Reply with exactly one word: OK"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=env,
        )
        try:
            probe_stdout, probe_stderr = proc.communicate(timeout=live_probe_timeout)
        except subprocess.TimeoutExpired:
            # terminate_process_group no-ops once the leader has exited,
            # but children that inherited the pipes can keep the group
            # alive (and communicate() blocked). start_new_session=True
            # makes the group id equal to proc.pid, so signal the group
            # directly — covering both the live-leader and exited-leader
            # cases. The probe is a throwaway call; no graceful TERM
            # needed.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.communicate(timeout=1)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
            return {
                "status": "fail",
                "cause": "timeout",
                "detail": f"no response within {live_probe_timeout}s",
            }
        if proc.returncode == 0:
            return {"status": "pass"}

        combined = ((probe_stdout or "") + "\n" + (probe_stderr or "")).lower()
        if any(
            p in combined
            for p in (
                "401",
                "403",
                "unauthorized",
                "auth",
                "api key",
                "invalid key",
                "forbidden",
                "permission",
            )
        ):
            cause = "auth"
        elif any(
            p in combined
            for p in (
                "429",
                "quota",
                "rate limit",
                "rate_limit",
                "too many",
                "insufficient",
            )
        ):
            cause = "quota"
        else:
            cause = "error"

        detail = (probe_stdout or "").strip()[:200] or (probe_stderr or "").strip()[
            :200
        ]
        if detail:
            detail = f"exit code {proc.returncode}: {detail}"
        else:
            detail = f"exit code {proc.returncode}"
        return {"status": "fail", "cause": cause, "detail": detail}

    except OSError as exc:
        # executable_health already vouched for the file, so a launch-time
        # OSError (FileNotFoundError from a missing shebang interpreter,
        # ENOEXEC, etc.) means reviews cannot launch this provider —
        # surface it as a live failure rather than silently omitting the
        # probe result for a statically healthy provider.
        return {
            "status": "fail",
            "cause": "error",
            "detail": f"failed to launch: {exc}",
        }


def cmd_doctor(args):
    # Import shared helpers from codex to avoid circular-import at module level.
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex

    root = _codex.resolve_health_root(args.root)
    config = _codex.load_config(args.config)
    providers, preset_metadata, resolver_warnings = _codex.resolve_review_providers(
        args, config
    )
    for warning in resolver_warnings:
        print(warning, file=sys.stderr)
    health = provider_health_results(config, providers, root)
    # TRN-3021: attach wrapper-auth check to results, but only for providers
    # whose resolved executable matches the canonical wrapper path. Test
    # fixtures with fake bin scripts won't trigger this, so cmd_review's
    # preflight (which uses provider_health directly) is unaffected.
    for h in health:
        if not _is_canonical_wrapper(h.get("executable"), h["provider"]):
            continue
        auth = wrapper_auth_check(h["provider"])
        if auth is None:
            continue
        h["auth"] = auth
        if auth["source"] == "missing":
            h["issues"].append(
                f"auth missing: ${auth['env_var']} unset and {auth['file']} absent"
            )
            h["ok"] = False
        elif auth["source"] == "file" and auth["mode_ok"] is False:
            h["issues"].append(
                f"auth file {auth['file']} has wrong mode (expected 600 or 400)"
            )
            h["ok"] = False
    if args.live:
        provider_configs = config.get("providers", {})
        if not isinstance(provider_configs, dict):
            provider_configs = {}
        for h in health:
            if not h["ok"]:
                continue
            probe = _probe_provider(
                h["provider"], provider_configs.get(h["provider"], {}), root
            )
            h["live_probe"] = probe
            if probe and probe["status"] == "fail":
                h["issues"].append(f"live probe: {probe['cause']} — {probe['detail']}")
                h["ok"] = False
    env_pollution = detect_env_pollution()
    print(
        format_health_results(
            health,
            env_pollution=env_pollution,
            preset_metadata=preset_metadata,
            verbose=True,
        )
    )
    return 0 if health_results_ok(health, preset_metadata=preset_metadata) else 1

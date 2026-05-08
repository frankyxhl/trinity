#!/usr/bin/env python3
"""Codex-native Trinity command wrapper."""

import argparse
import concurrent.futures
import datetime as dt
import difflib
import fnmatch
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time


DEFAULT_CONFIG = Path("~/.codex/trinity.json").expanduser()
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_CANDIDATES = [
    SCRIPT_ROOT / "trinity.codex.json",
    SCRIPT_ROOT / ".agents" / "trinity.codex.json",
]
DEFAULT_CONFIG_SECTIONS = ("providers", "review", "presets", "preset_aliases")
PRESET_TASK_TYPES = {"tdd", "review", "prp", "general"}
PRESET_ALIAS_RESERVED_WORDS = {"init-config", "doctor", "review", "status", "help"}
STRICT_REVIEW_OUTPUT_SCHEMA = [
    "### Findings",
    "### Decision Matrix",
    "**Weighted Average: X.X/10 - PASS/FIX**",
]
STRICT_REVIEW_DECISION_RULE = (
    "PASS when weighted_average >= 9.0 and no blocking findings remain; otherwise FIX."
)
REVIEW_ONLY_INSTRUCTION = (
    "## Review-Only Mode\n\n"
    "Do not run tests, shell commands, network calls, or mutate files unless the "
    "instructions in this review prompt explicitly ask you to. Base findings only "
    "on the provided diff, file snapshots, and review context.\n"
)
PROCESS_GROUP_KILL_GRACE_SECONDS = 5
_REVIEW_PASS_THRESHOLD = 9.0
_STDERR_SENTINEL = "\n%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%\n"
STRICT_REVIEW_TEMPLATES = {
    ("COR-1602", "COR-1609"): {
        "pass_threshold": 9.0,
        "calibration": "COR-1611",
        "rubric_title": "CHG Review Scoring",
        "criteria": [
            ("Correctness", "25%", "Change is technically sound and feasible."),
            ("Completeness", "25%", "CHG covers scope, risks, verification, and docs."),
            (
                "TDD Plan Quality",
                "20%",
                "Plan uses RED/GREEN/REFACTOR where code changes are involved.",
            ),
            ("Consistency", "15%", "Fits local conventions and related COR/TRN docs."),
            ("Rollback Safety", "15%", "Rollback path and blast radius are clear."),
        ],
        "non_code_note": (
            "For non-code CHGs where TDD is not applicable, redistribute the TDD "
            "weight to Completeness (35%) and Consistency (25%)."
        ),
    }
}


def _load_version():
    init_file = Path(__file__).resolve().parent / "__init__.py"
    spec = importlib.util.spec_from_file_location("_scripts_init", str(init_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.__version__


__version__ = _load_version()


def run_git(root, args, allow_error=False):
    result = subprocess.run(
        ["git"] + args,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0 and not allow_error:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def resolve_root(root_arg):
    root = Path(root_arg).expanduser().resolve()
    try:
        top = run_git(root, ["rev-parse", "--show-toplevel"]).strip()
    except RuntimeError:
        raise SystemExit(f"trinity-codex: not a git repository: {root}")
    return Path(top).resolve()


def resolve_health_root(root_arg):
    root = Path(root_arg).expanduser().resolve()
    try:
        top = run_git(root, ["rev-parse", "--show-toplevel"]).strip()
    except (OSError, RuntimeError):
        return root
    return Path(top).resolve()


def load_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"trinity-codex: config not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"trinity-codex: invalid JSON in {path}: {exc}")


def load_config(path):
    return load_json(Path(path).expanduser())


def write_default_config(path):
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate.exists():
            source = load_json(candidate)
            break
    else:
        raise SystemExit("trinity-codex: bundled trinity.codex.json not found")
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        current = load_json(target)
    else:
        current = {}

    for section in DEFAULT_CONFIG_SECTIONS:
        if section in source:
            current[section] = source[section]
    target.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    return target


def split_provider_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def config_section(config, key):
    value = config.get(key, {}) or {}
    if not isinstance(value, dict):
        raise SystemExit(f"trinity: {key} must be an object")
    return value


def review_section(config):
    return config_section(config, "review")


def provider_configs_section(config):
    return config_section(config, "providers")


def provider_config_missing_cli_reason(provider_configs, provider):
    provider_config = provider_configs.get(provider)
    if provider_config is None:
        return "missing config"
    if not isinstance(provider_config, dict):
        return "missing cli"
    cli = provider_config.get("cli")
    if not isinstance(cli, str) or not cli.strip():
        return "missing cli"
    return None


def validate_preset_aliases(config, presets, aliases):
    provider_configs = provider_configs_section(config)
    for alias, target in aliases.items():
        if alias in PRESET_ALIAS_RESERVED_WORDS:
            raise SystemExit(
                f"trinity: preset alias '{alias}' collides with subcommand"
            )
        if alias in provider_configs:
            raise SystemExit(f"trinity: preset alias '{alias}' collides with provider")
        if alias in presets:
            raise SystemExit(f"trinity: preset alias '{alias}' collides with preset")
        if target in aliases:
            raise SystemExit(f"trinity: preset alias '{alias}' points to another alias")
        if target not in presets:
            raise SystemExit(
                f"trinity: preset alias '{alias}' targets unknown preset '{target}'"
            )


def resolve_preset_name(config, requested, source):
    presets = config_section(config, "presets")
    aliases = config_section(config, "preset_aliases")
    validate_preset_aliases(config, presets, aliases)

    resolved = aliases.get(requested, requested)
    if resolved not in presets:
        if source == "default":
            raise SystemExit(f"trinity: review.default_preset '{requested}' not found")
        raise SystemExit(f"trinity: unknown preset '{requested}'")
    if resolved in provider_configs_section(config):
        raise SystemExit(f"trinity: '{resolved}' is both provider and preset")
    return resolved, presets[resolved]


def append_unique(items, value):
    if value not in items:
        items.append(value)


def reject_duplicate_providers(providers):
    seen = set()
    duplicates = []
    for provider in providers:
        if provider in seen and provider not in duplicates:
            duplicates.append(provider)
        seen.add(provider)
    if duplicates:
        raise SystemExit(
            "trinity: duplicate provider selected: " + ", ".join(duplicates)
        )
    return providers


def resolve_preset_providers(config, requested, source):
    resolved, preset = resolve_preset_name(config, requested, source)
    if not isinstance(preset, dict):
        raise SystemExit(f"trinity: preset '{resolved}' must be an object")

    task_type = preset.get("task_type")
    if task_type is not None and task_type not in PRESET_TASK_TYPES:
        raise SystemExit(
            f"trinity: preset '{resolved}' has invalid task_type '{task_type}'"
        )

    required = preset.get("providers", [])
    optional = preset.get("optional_providers", [])
    if not isinstance(required, list):
        raise SystemExit(f"trinity: preset '{resolved}' providers must be a list")
    if not isinstance(optional, list):
        raise SystemExit(
            f"trinity: preset '{resolved}' optional_providers must be a list"
        )
    required = [
        item.strip() for item in required if isinstance(item, str) and item.strip()
    ]
    optional = [
        item.strip() for item in optional if isinstance(item, str) and item.strip()
    ]
    if not required:
        raise SystemExit(f"trinity: preset '{resolved}' has no providers")

    provider_configs = provider_configs_section(config)
    providers = []
    for provider in required:
        append_unique(providers, provider)

    skipped = []
    warnings = []
    for provider in optional:
        reason = provider_config_missing_cli_reason(provider_configs, provider)
        if reason:
            skipped.append({"provider": provider, "reason": reason})
            warnings.append(
                f"trinity: optional provider '{provider}' skipped: {reason}"
            )
            continue
        append_unique(providers, provider)

    return (
        providers,
        {
            # Existing 5 keys — semantics UNCHANGED:
            "requested": requested,
            "resolved": resolved,
            "source": source,
            "task_type": task_type,
            "skipped_optional_providers": skipped,
            # TRN-3021: REQUIRED/OPTIONAL provider lists for doctor's
            # metadata-aware rendering and exit-code decision. `providers`
            # is the preset's required list; `optional_providers` is the
            # full optional list (NOT just `skipped` — those that were
            # config-eligible too).
            "providers": list(required),
            "optional_providers": list(optional),
        },
        warnings,
    )


def resolve_review_providers(args, config):
    if args.providers:
        providers = split_provider_csv(args.providers)
        if not providers:
            raise SystemExit("trinity-codex: no providers selected")
        reject_duplicate_providers(providers)
        warnings = []
        if args.preset:
            warnings.append(
                f"trinity: --providers supplied; ignoring --preset '{args.preset}'"
            )
        return (
            providers,
            {
                "requested": args.preset,
                "resolved": None,
                "source": "providers",
                "task_type": None,
                "skipped_optional_providers": [],
            },
            warnings,
        )

    review_config = review_section(config)
    if args.preset:
        return resolve_preset_providers(config, args.preset, "explicit")

    default_preset = review_config.get("default_preset")
    if default_preset:
        return resolve_preset_providers(config, default_preset, "default")

    providers = review_config.get("default_providers", [])
    if not providers:
        raise SystemExit("trinity-codex: no providers selected")
    reject_duplicate_providers(providers)
    return (
        providers,
        {
            "requested": None,
            "resolved": None,
            "source": "default_providers",
            "task_type": None,
            "skipped_optional_providers": [],
        },
        [],
    )


def parse_provider_command(provider, provider_config):
    if not isinstance(provider_config, dict):
        raise ValueError("provider config must be an object")
    cli = provider_config.get("cli")
    if not isinstance(cli, str) or not cli.strip():
        raise ValueError("missing cli")
    expanded = os.path.expandvars(os.path.expanduser(cli))
    try:
        command = shlex.split(expanded)
    except ValueError as exc:
        raise ValueError(f"invalid cli: {exc}") from exc
    if not command:
        raise ValueError("missing cli")
    return command


def provider_timeout(provider, provider_config):
    raw_timeout = provider_config.get("timeout", 360)
    if isinstance(raw_timeout, bool):
        raise ValueError(f"invalid timeout: {raw_timeout}")
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid timeout: {raw_timeout}") from exc
    if timeout <= 0:
        raise ValueError(f"invalid timeout: {raw_timeout}")
    return timeout


def command_has_path(command):
    return os.path.sep in command or (
        os.path.altsep is not None and os.path.altsep in command
    )


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


def scope_pathspec(root, scope):
    if not scope or scope == ".":
        return []
    candidate = (root / scope).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return []
    if candidate.exists():
        return [scope]
    return []


def git_diff(root, pathspec):
    args = ["diff", "--no-ext-diff", "--binary", "HEAD", "--"]
    return run_git(root, args + pathspec, allow_error=True)


def git_diff_range(root, base, head, pathspec):
    args = ["diff", "--no-ext-diff", "--binary", f"{base}...{head}", "--"]
    return run_git(root, args + pathspec)


def changed_paths(root, pathspec):
    args = ["diff", "--name-only", "--diff-filter=ACMRT", "HEAD", "--"]
    output = run_git(root, args + pathspec, allow_error=True)
    return [line for line in output.splitlines() if line.strip()]


def changed_paths_range(root, base, head, pathspec):
    args = ["diff", "--name-only", "--diff-filter=ACMRT", f"{base}...{head}", "--"]
    output = run_git(root, args + pathspec)
    return [line for line in output.splitlines() if line.strip()]


def untracked_paths(root, pathspec):
    args = ["ls-files", "--others", "--exclude-standard", "--"]
    output = run_git(root, args + pathspec, allow_error=True)
    return [line for line in output.splitlines() if line.strip()]


def is_text_file(path):
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" not in sample


def read_text_file(path, max_bytes=200000):
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if b"\0" in data:
        return "[binary file omitted]"
    if len(data) > max_bytes:
        head = data[:max_bytes].decode("utf-8", errors="replace")
        return head + "\n[truncated: file exceeds max snapshot bytes]\n"
    return data.decode("utf-8", errors="replace")


def read_text_file_at_ref(root, ref, rel, max_bytes=200000):
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    data = result.stdout
    if b"\0" in data:
        return "[binary file omitted]"
    if len(data) > max_bytes:
        head = data[:max_bytes].decode("utf-8", errors="replace")
        return head + "\n[truncated: file exceeds max snapshot bytes]\n"
    return data.decode("utf-8", errors="replace")


def synthetic_untracked_diff(root, paths):
    chunks = []
    for rel in paths:
        path = root / rel
        if not path.is_file() or not is_text_file(path):
            chunks.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n")
            chunks.append(
                "--- /dev/null\n+++ b/{0}\n[binary or unreadable]\n".format(rel)
            )
            continue
        lines = read_text_file(path).splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                [],
                lines,
                fromfile="/dev/null",
                tofile=f"b/{rel}",
            )
        )
    return "".join(chunks)


def file_snapshots(root, paths):
    if not paths:
        return "(no changed or untracked file snapshots)\n"

    chunks = []
    seen = set()
    for rel in paths:
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        chunks.append(f"### {rel}\n\n")
        if not path.exists():
            chunks.append("[deleted]\n\n")
            continue
        if path.is_dir():
            chunks.append("[directory omitted]\n\n")
            continue
        content = read_text_file(path)
        chunks.append("```text\n")
        chunks.append(content)
        if content and not content.endswith("\n"):
            chunks.append("\n")
        chunks.append("```\n\n")
    return "".join(chunks)


def file_snapshots_at_ref(root, paths, ref):
    if not paths:
        return "(no changed file snapshots)\n"

    chunks = []
    seen = set()
    for rel in paths:
        if rel in seen:
            continue
        seen.add(rel)
        chunks.append(f"### {rel}\n\n")
        content = read_text_file_at_ref(root, ref, rel)
        if content is None:
            chunks.append("[deleted]\n\n")
            continue
        chunks.append("```text\n")
        chunks.append(content)
        if content and not content.endswith("\n"):
            chunks.append("\n")
        chunks.append("```\n\n")
    return "".join(chunks)


def working_tree_review_input(root, scope):
    pathspec = scope_pathspec(root, scope)
    tracked_diff = git_diff(root, pathspec)
    untracked = untracked_paths(root, pathspec)
    untracked_diff = synthetic_untracked_diff(root, untracked)
    diff = (
        tracked_diff
        + ("\n" if tracked_diff and untracked_diff else "")
        + (untracked_diff)
    )
    paths = changed_paths(root, pathspec) + untracked
    files = file_snapshots(root, paths)
    if not diff.strip():
        diff = "(no tracked or untracked git diff)"
    return {
        "diff": diff,
        "files": files,
        "metadata": {
            "mode": "working-tree",
            "base": "HEAD",
            "head": "working-tree",
            "pr": None,
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": "working-tree",
        },
    }


def base_head_review_input(root, base, head, scope):
    pathspec = scope_pathspec(root, scope)
    try:
        diff = git_diff_range(root, base, head, pathspec)
        paths = changed_paths_range(root, base, head, pathspec)
    except RuntimeError as exc:
        raise SystemExit(
            f"trinity-codex: unable to collect git diff for {base}...{head}: {exc}"
        ) from exc
    files = file_snapshots_at_ref(root, paths, head)
    if not diff.strip():
        diff = f"(no git diff for {base}...{head})"
    return {
        "diff": diff,
        "files": files,
        "metadata": {
            "mode": "base-head",
            "base": base,
            "head": head,
            "pr": None,
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": f"git:{head}",
        },
    }


def run_gh(root, args, label):
    try:
        result = subprocess.run(
            ["gh"] + args,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "trinity-codex: gh command not found; install/authenticate gh for --pr"
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "gh command failed"
        raise SystemExit(f"trinity-codex: {label} failed: {detail}")
    return result.stdout


def gh_pr_view(root, pr_number):
    output = run_gh(
        root,
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,url,baseRefName,headRefName,headRefOid,files",
        ],
        f"gh pr view {pr_number}",
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"trinity-codex: invalid gh pr view JSON: {exc}")


def gh_pr_diff(root, pr_number):
    return run_gh(
        root,
        ["pr", "diff", str(pr_number), "--patch", "--color", "never"],
        f"gh pr diff {pr_number}",
    )


def git_commit_exists(root, ref):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def ensure_pr_head_available(root, pr_number, head_oid):
    if not head_oid:
        return None
    if git_commit_exists(root, head_oid):
        return head_oid
    run_git(
        root,
        ["fetch", "--quiet", "origin", f"pull/{pr_number}/head"],
        allow_error=True,
    )
    if git_commit_exists(root, head_oid):
        return head_oid
    return None


def pr_changed_paths(view):
    paths = []
    for item in view.get("files", []) or []:
        path = item.get("path")
        if path:
            paths.append(path)
    return paths


def pr_review_input(root, pr_number, scope):
    view = gh_pr_view(root, pr_number)
    diff = gh_pr_diff(root, pr_number)
    paths = pr_changed_paths(view)
    head_oid = view.get("headRefOid")
    snapshot_ref = ensure_pr_head_available(root, pr_number, head_oid)
    if snapshot_ref:
        files = file_snapshots_at_ref(root, paths, snapshot_ref)
        snapshot_source = f"git:{snapshot_ref}"
    else:
        files = "(PR head snapshots unavailable locally)\n"
        snapshot_source = "unavailable"
    if not diff.strip():
        diff = f"(no GitHub PR diff for PR #{pr_number})"
    return {
        "diff": diff,
        "files": files,
        "metadata": {
            "mode": "pr",
            "base": view.get("baseRefName"),
            "head": view.get("headRefName"),
            "head_oid": head_oid,
            "pr": int(view.get("number") or pr_number),
            "pr_url": view.get("url"),
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": snapshot_source,
        },
    }


def resolve_review_input(args, root):
    if args.pr is not None:
        return pr_review_input(root, args.pr, args.scope)
    if args.base or args.head:
        if not args.base or not args.head:
            raise SystemExit("trinity-codex: --base and --head must be used together")
        return base_head_review_input(root, args.base, args.head, args.scope)
    return working_tree_review_input(root, args.scope)


def normalize_review_doc_id(value, flag):
    normalized = (value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}-\d{4}", normalized):
        raise SystemExit(f"trinity: {flag} must look like COR-1602")
    return normalized


def strict_review_metadata(sop, rubric, template):
    return {
        "enabled": True,
        "sop": sop,
        "rubric": rubric,
        "pass_threshold": template["pass_threshold"],
        "calibration": template["calibration"],
        "decision_rule": STRICT_REVIEW_DECISION_RULE,
        "output_schema": list(STRICT_REVIEW_OUTPUT_SCHEMA),
    }


def resolve_strict_review(args):
    if bool(args.sop) != bool(args.rubric):
        raise SystemExit("trinity: --sop and --rubric must be used together")
    if not args.sop and not args.rubric:
        return None

    sop = normalize_review_doc_id(args.sop, "--sop")
    rubric = normalize_review_doc_id(args.rubric, "--rubric")
    template = STRICT_REVIEW_TEMPLATES.get((sop, rubric))
    if template is None:
        raise SystemExit(
            f"trinity: unsupported strict review template: SOP {sop} with rubric {rubric}"
        )
    metadata = strict_review_metadata(sop, rubric, template)
    return {**metadata, "template": template}


def render_strict_review_instructions(strict_review):
    template = strict_review["template"]
    lines = [
        "## Strict COR Review Mode",
        "",
        f"SOP: {strict_review['sop']}",
        f"Rubric: {strict_review['rubric']} ({template['rubric_title']})",
        f"Calibration: {strict_review['calibration']}",
        f"PASS threshold: {strict_review['pass_threshold']:.1f}/10",
        "",
        "Follow the SOP workflow and score the artifact with this rubric:",
        "",
        "| Criterion | Weight | Scoring focus |",
        "|-----------|--------|---------------|",
    ]
    for criterion, weight, focus in template["criteria"]:
        lines.append(f"| {criterion} | {weight} | {focus} |")

    matrix_rows = [
        f"| {criterion} | {weight} | X.X | ... |"
        for criterion, weight, _focus in template["criteria"]
    ]
    lines.extend(
        [
            "",
            template["non_code_note"],
            "",
            "Use COR-1611 calibration: cite every deduction, distinguish blocking "
            "findings from advisory improvements, and reserve 10/10 for zero "
            "remaining improvements.",
            "",
            "Required output:",
            "",
            "### Findings",
            "",
            "- List each finding with severity, file/path reference when applicable, "
            "and whether it is blocking or advisory.",
            "",
            "### Decision Matrix",
            "",
            "| Criterion | Weight | Score | Rationale |",
            "|-----------|--------|-------|-----------|",
            *matrix_rows,
            "",
            "**Weighted Average: X.X/10 - PASS/FIX**",
            "",
            STRICT_REVIEW_DECISION_RULE,
        ]
    )
    return "\n".join(lines) + "\n"


def render_prompt(
    config, root, scope, review_input, strict_review=None, *, task_type=None
):
    diff = review_input["diff"]
    files = review_input["files"]
    template = config.get("review", {}).get("prompt_template", "{diff}\n\n{files}\n")
    prompt = (
        template.replace("{scope}", scope or ".")
        .replace("{root}", str(root))
        .replace("{diff}", diff)
        .replace("{files}", files)
    )
    if strict_review is None:
        base = REVIEW_ONLY_INSTRUCTION + "\n" + prompt
    else:
        base = (
            render_strict_review_instructions(strict_review)
            + "\n"
            + REVIEW_ONLY_INSTRUCTION
            + "\n## Review Artifact\n\n"
            + prompt
        )
    # TRN-3022: schema addendum appended AFTER all other sections so
    # the "LAST in your output" instruction is truly at the bottom.
    return base + _review_schema_addendum(task_type)


def slugify(value):
    value = value.strip() or "review"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-") or "review"


def make_review_dir(out_dir, scope):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(out_dir).expanduser()
    slug = slugify(scope)
    for index in range(100):
        suffix = f"{stamp}-{slug}" if index == 0 else f"{stamp}-{slug}-{index}"
        review_dir = base / suffix
        try:
            review_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (review_dir / "raw").mkdir()
        return review_dir
    raise SystemExit("trinity-codex: unable to create unique review directory")


def provider_command(provider, provider_config):
    try:
        return parse_provider_command(provider, provider_config)
    except ValueError as exc:
        raise SystemExit(f"trinity-codex: provider {provider} {exc}") from exc


def build_prompt_handoff(prompt_path):
    return (
        "Read the complete Trinity review prompt from the file below, then perform "
        "the requested code review.\n\n"
        f"Prompt file: {prompt_path}"
    )


def progress(message):
    print(f"trinity: {message}", file=sys.stderr, flush=True)


def timestamp():
    return dt.datetime.now().isoformat(timespec="seconds")


def elapsed_seconds(started):
    return max(0, int(time.monotonic() - started))


class ActiveProcessRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}
        self._started = set()

    def add(self, provider, popen, started_at):
        with self._lock:
            self._started.add(provider)
            self._items[provider] = {
                "provider": provider,
                "pid": popen.pid,
                "popen": popen,
                "started_at": started_at,
            }

    def remove(self, provider, popen):
        with self._lock:
            current = self._items.get(provider)
            if current is not None and current["popen"] is popen:
                self._items.pop(provider, None)

    def snapshot(self):
        with self._lock:
            return list(self._items.values())

    def started_providers(self):
        with self._lock:
            return set(self._started)


class ReviewInterrupted(Exception):
    def __init__(self, cleanup, started_providers):
        super().__init__("review interrupted")
        self.cleanup = cleanup
        self.started_providers = started_providers


class ReviewOrchestrationError(Exception):
    def __init__(self, message, cleanup, started_providers):
        super().__init__(message)
        self.cleanup = cleanup
        self.started_providers = started_providers


def process_group_id(popen):
    try:
        return os.getpgid(popen.pid)
    except ProcessLookupError:
        return None
    except PermissionError:
        return "permission_denied"


def signal_process_group(popen, sig):
    pgid = process_group_id(popen)
    if pgid is None:
        return "already_exited"
    if pgid == "permission_denied":
        return pgid
    try:
        os.killpg(pgid, sig)
        return "signaled"
    except ProcessLookupError:
        return "already_exited"
    except PermissionError:
        return "permission_denied"


def terminate_process_group(popen, grace_seconds=PROCESS_GROUP_KILL_GRACE_SECONDS):
    if popen.poll() is not None:
        return "already_exited"
    term_status = signal_process_group(popen, signal.SIGTERM)
    if term_status == "already_exited":
        return term_status
    if term_status != "signaled":
        return term_status
    try:
        popen.wait(timeout=grace_seconds)
        return "terminated"
    except subprocess.TimeoutExpired:
        kill_status = signal_process_group(popen, signal.SIGKILL)
        if kill_status == "already_exited":
            return kill_status
        if kill_status != "signaled":
            return kill_status
        try:
            popen.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            return "kill_timeout"
        return "killed"


def cleanup_active_processes(registry):
    cleanup = {}
    for item in registry.snapshot():
        cleanup[item["provider"]] = {
            "pid": item["pid"],
            "result": terminate_process_group(item["popen"]),
        }
    return cleanup


def raw_output(stdout, stderr):
    # TRN-3022 coupling: the _STDERR_SENTINEL written here is consumed by
    # _strip_stderr_region — do NOT change the sentinel format without
    # updating both. The sentinel is a unique marker (random hex tag) so
    # neither stdout nor stderr can plausibly contain a colliding string.
    # Always append the sentinel (even with empty stderr) so the boundary
    # exists unambiguously.
    return (stdout or "") + _STDERR_SENTINEL + (stderr or "")


def timeout_partial_output(exc, stdout=None, stderr=None):
    def normalize(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    return raw_output(
        normalize(stdout) or normalize(exc.stdout),
        normalize(stderr) or normalize(exc.stderr),
    )


_UNIVERSAL_ENV_KEEP_LITERAL = frozenset(
    {
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
    }
)
_UNIVERSAL_ENV_KEEP_GLOB = ("LC_*", "GIT_*")
_DEFAULT_ENV_CLEAR_PATTERNS = (
    "*_BASE_URL",
    "*_API_BASE",
    "*_API_HOST",
    "OTEL_*",
    "TRINITY_DISABLE_DISPATCH",
)


def _matches_any(key, patterns):
    return any(fnmatch.fnmatchcase(key, pat) for pat in patterns)


def _is_essential(key):
    if key in _UNIVERSAL_ENV_KEEP_LITERAL:
        return True
    return _matches_any(key, _UNIVERSAL_ENV_KEEP_GLOB)


def build_provider_env(base_env=None):
    """Build a sanitized env dict for spawning provider CLIs (TRN-3023).

    Strips known-problematic patterns (vendor *_BASE_URL overrides, OTEL_*
    telemetry leakage, TRINITY_DISABLE_DISPATCH from caller's shell).
    Preserves universal essentials regardless of clear patterns. Returns
    a fresh dict suitable for `subprocess.Popen(env=...)`.

    Universal essentials are checked BEFORE the clearlist, so a future
    clearlist pattern that happened to match an essential (e.g., a
    pattern accidentally globbing PATH) would still preserve the
    essential.

    `base_env=None` resolves to `os.environ` at call time (avoids the
    mutable-default antipattern if `os.environ` mutates between calls).

    Patterns use `fnmatch.fnmatchcase` (case-sensitive — POSIX env
    names ARE case-sensitive even on macOS/Windows).
    """
    if base_env is None:
        base_env = os.environ
    sanitized = {}
    for key, value in base_env.items():
        if _is_essential(key):
            sanitized[key] = value
            continue
        if _matches_any(key, _DEFAULT_ENV_CLEAR_PATTERNS):
            continue
        sanitized[key] = value
    return sanitized


# ---------------------------------------------------------------------------
# TRN-3022: structured review result schema — parser + helpers
# ---------------------------------------------------------------------------

_SCHEMA_BLOCK_RE = re.compile(
    r"(?ims)^```json\s*$\n(.*?)\n^```\s*$",
)


def _strip_stderr_region(text):
    """Strip the stderr tail appended by raw_output().

    TRN-3022 coupling: the sentinel _STDERR_SENTINEL is a unique marker
    written by raw_output() at this module. It contains a random hex tag,
    so a colliding string in either stdout or stderr is astronomically
    unlikely. The pre-sentinel region (stdout) is scanned for structured
    blocks. If absent (custom raw-output writers), the full text is returned.
    """
    idx = text.rfind(_STDERR_SENTINEL)
    if idx == -1:
        return text
    return text[:idx]


def _safe_read_raw(path):
    """Read a raw provider file, returning text or None on failure.

    Catches OSError (file deleted/moved between run and synthesis) and
    UnicodeDecodeError (corrupt bytes). Returns None on failure — caller
    falls through to legacy rendering.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _validate_review_schema(data):
    """Validate a parsed JSON dict against the TRN-3022 review schema.

    Returns True if valid, False otherwise. Never raises.
    Checks: top-level dict, required fields, types, ranges, finding shapes.
    Unknown top-level and finding-level keys are ignored (forward-compat).
    Rejects numeric bools (isinstance(True, int) is True in Python).
    """
    if not isinstance(data, dict):
        return False

    # decision
    decision = data.get("decision")
    if not isinstance(decision, str) or decision.upper() not in ("PASS", "FIX"):
        return False

    # weighted_score — reject bools (True/False are int subclasses) and NaN/Inf.
    # math.isfinite() on huge ints raises OverflowError, so guard with isinstance(float).
    # Ints are always finite by definition; oversized ints fall through to range check.
    ws = data.get("weighted_score")
    if isinstance(ws, bool) or not isinstance(ws, (int, float)):
        return False
    if isinstance(ws, float) and not math.isfinite(ws):
        return False
    if ws < 0.0 or ws > 10.0:
        return False

    # blocking and advisories
    for key in ("blocking", "advisories"):
        val = data.get(key)
        if not isinstance(val, list):
            return False
        for item in val:
            if not isinstance(item, dict):
                return False
            if not isinstance(item.get("title"), str):
                return False
            if not isinstance(item.get("evidence"), str):
                return False
            # fix is optional; if present must be str
            fix = item.get("fix")
            if fix is not None and not isinstance(fix, str):
                return False

    # confidence (optional) — reject bools and NaN/Inf (same overflow guard as weighted_score).
    conf = data.get("confidence")
    if conf is not None:
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            return False
        if isinstance(conf, float) and not math.isfinite(conf):
            return False
        if conf < 0.0 or conf > 1.0:
            return False

    return True


def parse_structured_review(raw_text):
    """Parse a structured review schema block from raw provider output.

    Returns a dict with schema fields + effective_decision, or None on any
    failure. Never raises — synthesis must work on malformed provider output.

    Steps:
      1. Strip stderr region via _strip_stderr_region.
      2. Find last fenced ```json block via regex (DOTALL).
      3. json.loads contents.
      4. Validate via _validate_review_schema.
      5. Coerce effective_decision if needed.
    """
    try:
        stdout_region = _strip_stderr_region(raw_text)

        matches = _SCHEMA_BLOCK_RE.findall(stdout_region)
        if not matches:
            return None

        last_block = matches[-1]
        data = json.loads(last_block)

        if not _validate_review_schema(data):
            return None

        # Normalize decision to uppercase.
        data["decision"] = data["decision"].upper()

        # Effective-decision coercion.
        if data["decision"] == "PASS" and (
            data["blocking"] or data["weighted_score"] < _REVIEW_PASS_THRESHOLD
        ):
            data["effective_decision"] = "FIX"
        else:
            data["effective_decision"] = data["decision"]

        return data
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _review_schema_addendum(task_type):
    """Return the structured-output prompt addendum for review task types.

    Returns empty string for non-review task types (tdd, prp, general, None).
    Addendum is appended at the end of the rendered prompt so providers emit
    the JSON block as the LAST thing in their output.
    """
    task_type = (task_type or "").lower()
    if task_type != "review":
        return ""

    threshold = _REVIEW_PASS_THRESHOLD
    return (
        "\n## Required: Structured Output\n"
        "\n"
        "After your free-form review, emit EXACTLY ONE fenced JSON block at the END\n"
        'of your output. Required fields: `decision` ("PASS" or "FIX"),\n'
        "`weighted_score` (number 0.0-10.0), `blocking` (list, may be `[]`),\n"
        "`advisories` (list, may be `[]`). Optional: `confidence` (number 0.0-1.0).\n"
        "Each finding in blocking/advisories is an object with `title` (str),\n"
        '`evidence` (str, file:line, may be `""`), and optional `fix` (str).\n'
        "\n"
        "Concrete example — REPLACE values with your actual verdict; do NOT copy\n"
        "this block verbatim:\n"
        "\n"
        "```json\n"
        "{\n"
        '  "decision": "FIX",\n'
        '  "weighted_score": 7.5,\n'
        '  "blocking": [\n'
        "    {\n"
        '      "title": "Race condition in worker shutdown",\n'
        '      "evidence": "scripts/foo.py:142",\n'
        '      "fix": "Acquire lock before signaling done"\n'
        "    }\n"
        "  ],\n"
        '  "advisories": [],\n'
        '  "confidence": 0.85\n'
        "}\n"
        "```\n"
        "\n"
        "Rules:\n"
        f'- "decision" MUST be "PASS" only when "blocking" is empty AND "weighted_score" >= {threshold}.\n'
        '  (If you write PASS while "blocking" is non-empty or score < '
        f"{threshold}, Trinity will\n"
        "  display your provider as FIX — the consistency is enforced.)\n"
        '- "blocking" and "advisories" are required lists (use [] if empty, not null).\n'
        '- "evidence" is required per finding; use "" for cross-cutting issues.\n'
        "- This block must be the LAST fenced ```json block in your output. Trinity scans\n"
        "  for the last match. Earlier illustrative JSON in your prose is fine.\n"
    )


def run_provider(provider, provider_config, prompt_path, review_dir, root, registry):
    raw_path = review_dir / "raw" / f"{provider}.txt"
    cmd = provider_command(provider, provider_config) + [
        build_prompt_handoff(prompt_path)
    ]
    try:
        timeout = provider_timeout(provider, provider_config)
    except ValueError as exc:
        raise SystemExit(f"trinity-codex: provider {provider} {exc}") from exc
    started = timestamp()
    started_monotonic = time.monotonic()
    progress(f"starting provider {provider} timeout={timeout}s")
    popen = None
    try:
        popen = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=build_provider_env(),
        )
        registry.add(provider, popen, started)
        stdout, stderr = popen.communicate(timeout=timeout)
        raw_path.write_text(raw_output(stdout, stderr))
        finished = timestamp()
        progress(
            f"provider {provider} finished returncode={popen.returncode} "
            f"elapsed={elapsed_seconds(started_monotonic)}s"
        )
        return {
            "provider": provider,
            "returncode": popen.returncode,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": finished,
        }
    except FileNotFoundError as exc:
        raw_path.write_text(f"ERROR: command not found: {exc}\n")
        progress(
            f"provider {provider} failed returncode=127 "
            f"elapsed={elapsed_seconds(started_monotonic)}s"
        )
        return {
            "provider": provider,
            "returncode": 127,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": timestamp(),
        }
    except subprocess.TimeoutExpired as exc:
        cleanup_result = terminate_process_group(popen)
        stdout = None
        stderr = None
        try:
            stdout, stderr = popen.communicate(timeout=1)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        partial = timeout_partial_output(exc, stdout, stderr)
        output = f"ERROR: timeout after {timeout}s\n{exc}\n"
        if partial:
            output += "\n[partial output]\n" + partial
        raw_path.write_text(output)
        progress(
            f"provider {provider} timed out returncode=124 "
            f"cleanup={cleanup_result} elapsed={elapsed_seconds(started_monotonic)}s"
        )
        return {
            "provider": provider,
            "returncode": 124,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": timestamp(),
        }
    except Exception:
        if popen is not None and popen.poll() is None:
            terminate_process_group(popen)
        raise
    finally:
        if popen is not None:
            registry.remove(provider, popen)


def review_parallelism(config, providers):
    review_config = review_section(config)
    raw_value = review_config.get("max_parallel_providers")
    if raw_value is None:
        return len(providers)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise SystemExit(
            "trinity: review.max_parallel_providers must be an integer "
            f"between 1 and {len(providers)}"
        )
    if raw_value < 1 or raw_value > len(providers):
        raise SystemExit(
            f"trinity: review.max_parallel_providers must be between 1 and {len(providers)}"
        )
    return raw_value


def run_providers(
    max_workers,
    providers,
    provider_configs,
    prompt_path,
    review_dir,
    root,
):
    registry = ActiveProcessRegistry()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    provider_iter = iter(providers)
    futures = {}
    results = {}

    def submit_provider(provider):
        future = executor.submit(
            run_provider,
            provider,
            provider_configs[provider],
            prompt_path,
            review_dir,
            root,
            registry,
        )
        futures[future] = provider

    try:
        for provider in provider_iter:
            submit_provider(provider)
            if len(futures) >= max_workers:
                break
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                provider = futures.pop(future)
                results[provider] = future.result()
                try:
                    submit_provider(next(provider_iter))
                except StopIteration:
                    pass
    except KeyboardInterrupt as exc:
        for future in futures:
            future.cancel()
        started_providers = registry.started_providers()
        cleanup = cleanup_active_processes(registry)
        executor.shutdown(wait=False)
        raise ReviewInterrupted(cleanup, started_providers) from exc
    except Exception as exc:
        for future in futures:
            future.cancel()
        started_providers = registry.started_providers()
        cleanup = cleanup_active_processes(registry)
        executor.shutdown(wait=False)
        raise ReviewOrchestrationError(str(exc), cleanup, started_providers) from exc
    else:
        executor.shutdown(wait=True)
    return [results[provider] for provider in providers]


def ordered_subset(providers, selected):
    selected = set(selected)
    ordered = [provider for provider in providers if provider in selected]
    ordered.extend(sorted(selected.difference(providers)))
    return ordered


def ordered_cleanup(providers, cleanup):
    payload = {
        provider: cleanup[provider] for provider in providers if provider in cleanup
    }
    for provider in sorted(set(cleanup).difference(payload)):
        payload[provider] = cleanup[provider]
    return payload


def write_incomplete(
    review_dir,
    status,
    providers,
    started_providers,
    cleanup,
    message=None,
):
    cleanup_payload = ordered_cleanup(providers, cleanup)
    payload = {
        "status": status,
        "timestamp": timestamp(),
        "review_dir": str(review_dir),
        "providers_selected": providers,
        "providers_started": ordered_subset(providers, started_providers),
        "providers_running_at_cleanup": ordered_subset(providers, cleanup),
        "cleanup": cleanup_payload,
    }
    if message:
        payload["message"] = message
    (review_dir / "incomplete.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )


def _sanitize_md(text):
    """Strip embedded newlines from Markdown-rendered finding fields."""
    return text.replace("\n", " ") if "\n" in text else text


def _render_finding_items(label, items):
    """Render a labeled list of finding items (blocking or advisories).

    Returns a list of lines including the **Label:** header, one bullet per
    item, and a trailing blank line. Returns an empty list if items is empty.
    """
    if not items:
        return []
    lines = [f"**{label}:**"]
    for item in items:
        title = _sanitize_md(item.get("title", ""))
        evidence = _sanitize_md(item.get("evidence", ""))
        fix = item.get("fix")
        if fix:
            fix = _sanitize_md(fix)
        if evidence:
            line = f"- **{title}** at `{evidence}`"
        else:
            line = f"- **{title}** (no evidence cited)"
        if fix:
            line += f" — {fix}"
        lines.append(line)
    lines.append("")
    return lines


def _render_findings_for(result, parsed):
    """Render a single provider's structured findings block.

    Returns a list of lines for the Findings section, or an empty list
    if the provider has no findings to render (structured-but-clean).
    """
    provider = result["provider"]
    eff = parsed["effective_decision"]
    score = parsed["weighted_score"]
    blocking = parsed.get("blocking", [])
    advisories = parsed.get("advisories", [])
    lines = []
    lines.append(
        f"### {provider} — {eff} "
        f"({score}, {len(blocking)} blocking, {len(advisories)} advisories)"
    )
    lines.append("")
    lines.extend(_render_finding_items("Blocking", blocking))
    lines.extend(_render_finding_items("Advisories", advisories))
    return lines


def write_synthesis(review_dir, scope, results):
    # TRN-3022: parse structured review schema per provider.
    # rc != 0 → FAIL <rc> regardless of structured content.
    # rc == 0 + parsed → enriched status.
    # rc == 0 + no parsed → legacy PASS.
    parsed_per_provider = []
    for result in results:
        rc = result.get("returncode", -1)
        if rc == 0:
            raw_path = review_dir / result["raw"]
            raw_text = _safe_read_raw(raw_path)
            if raw_text is not None:
                parsed_per_provider.append(parse_structured_review(raw_text))
            else:
                parsed_per_provider.append(None)
        else:
            parsed_per_provider.append(None)

    any_structured = any(p is not None for p in parsed_per_provider)

    # Legacy path: byte-identical to pre-TRN-3022 output.
    if not any_structured:
        lines = [
            "# Trinity Review Synthesis",
            "",
            f"Scope: {scope or '.'}",
            "",
            "## Provider Status",
            "",
            "| Provider | Status | Raw Output |",
            "|----------|--------|------------|",
        ]
        for result in results:
            status = (
                "PASS" if result["returncode"] == 0 else f"FAIL {result['returncode']}"
            )
            lines.append(f"| {result['provider']} | {status} | `{result['raw']}` |")
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
                "",
            ]
        )
        path = review_dir / "synthesis.md"
        path.write_text("\n".join(lines) + "\n")
        return

    # Enriched path: at least one provider has structured output.
    lines = [
        "# Trinity Review Synthesis",
        "",
        f"Scope: {scope or '.'}",
        "",
        "## Provider Status",
        "",
        "| Provider | Status | Raw Output |",
        "|----------|--------|------------|",
    ]
    for i, result in enumerate(results):
        rc = result.get("returncode", -1)
        if rc != 0:
            # Returncode precedence: rc wins regardless of structured content.
            status = f"FAIL {rc}"
        else:
            parsed = parsed_per_provider[i]
            if parsed is not None:
                eff = parsed["effective_decision"]
                score = parsed["weighted_score"]
                n_blocking = len(parsed.get("blocking", []))
                if eff == "FIX":
                    status = f"FIX ({score}, {n_blocking} blocking)"
                else:
                    status = f"PASS ({score})"
            else:
                status = "PASS"
        lines.append(f"| {result['provider']} | {status} | `{result['raw']}` |")

    # Findings section — only rc=0 providers with parsed results.
    has_findings = False
    for i, result in enumerate(results):
        parsed = parsed_per_provider[i]
        rc = result.get("returncode", -1)
        if rc == 0 and parsed is not None:
            if not has_findings:
                lines.append("")
                lines.append("## Findings")
                lines.append("")
                has_findings = True
            lines.extend(_render_findings_for(result, parsed))

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
            "",
        ]
    )
    path = review_dir / "synthesis.md"
    path.write_text("\n".join(lines) + "\n")


def cmd_review(args):
    progress("preparing review prompt")
    root = resolve_root(args.root)
    config = load_config(args.config)
    providers, preset_metadata, resolver_warnings = resolve_review_providers(
        args, config
    )
    strict_review = resolve_strict_review(args)
    for warning in resolver_warnings:
        print(warning, file=sys.stderr)
    provider_configs = config.get("providers", {})
    health = provider_health_results(config, providers, root)
    if args.check_providers:
        print(format_health_results(health))
        return 0 if health_results_ok(health) else 1
    if not health_results_ok(health):
        print(format_health_results(health), file=sys.stderr)
        return 1
    max_workers = review_parallelism(config, providers)
    review_input = resolve_review_input(args, root)

    out_base = args.out_dir or config.get("review", {}).get(
        "output_dir", ".trinity/reviews"
    )
    out_base = Path(out_base)
    if not out_base.is_absolute():
        out_base = root / out_base
    review_dir = make_review_dir(out_base, args.scope)

    try:
        prompt = render_prompt(
            config,
            root,
            args.scope,
            review_input,
            strict_review,
            task_type=preset_metadata.get("task_type") if preset_metadata else None,
        )
        prompt_path = review_dir / "prompt.md"
        progress("writing prompt")
        prompt_path.write_text(prompt)
        results = run_providers(
            max_workers,
            providers,
            provider_configs,
            prompt_path,
            review_dir,
            root,
        )
        metadata = {
            "scope": args.scope,
            "root": str(root),
            "providers": providers,
            "preset": preset_metadata,
            "input": review_input["metadata"],
            "results": results,
        }
        if strict_review is not None:
            metadata["strict_review"] = {
                key: value for key, value in strict_review.items() if key != "template"
            }
        progress("writing metadata")
        (review_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
        )
        progress("writing synthesis")
        write_synthesis(review_dir, args.scope, results)
    except KeyboardInterrupt:
        started_providers = providers if "results" in locals() else []
        write_incomplete(review_dir, "interrupted", providers, started_providers, {})
        print(review_dir)
        return 130
    except ReviewInterrupted as exc:
        write_incomplete(
            review_dir,
            "interrupted",
            providers,
            exc.started_providers,
            exc.cleanup,
        )
        print(review_dir)
        return 130
    except ReviewOrchestrationError as exc:
        write_incomplete(
            review_dir,
            "failed",
            providers,
            exc.started_providers,
            exc.cleanup,
            str(exc),
        )
        print(review_dir)
        return 1
    except Exception as exc:
        started_providers = providers if "results" in locals() else []
        write_incomplete(
            review_dir, "failed", providers, started_providers, {}, str(exc)
        )
        print(review_dir)
        return 1

    print(review_dir)
    return 0 if all(item["returncode"] == 0 for item in results) else 1


def cmd_doctor(args):
    root = resolve_health_root(args.root)
    config = load_config(args.config)
    providers, preset_metadata, resolver_warnings = resolve_review_providers(
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


# ---------------------------------------------------------------------------
# `trinity status` — read-only summary of the most recent review
# (TRN-2028 / GitHub issue #35).
# ---------------------------------------------------------------------------


def _format_elapsed(started_iso, finished_iso):
    """Compute elapsed seconds between two ISO timestamps, clamped to >= 0.

    `make_review_dir` writes timestamps via `dt.datetime.now().isoformat(...)`
    (naive local time). On fall-back DST a sub-hour run straddling the
    transition can produce finished < started → negative elapsed. Clamp to
    `max(0, ...)` to defend against that without introducing tz handling.
    Returns None if either timestamp is missing or unparseable.
    """
    if not started_iso or not finished_iso:
        return None
    try:
        s = dt.datetime.fromisoformat(started_iso)
        f = dt.datetime.fromisoformat(finished_iso)
        # Subtraction inside the try too — mixed naive/offset-aware datetimes
        # raise TypeError on `f - s`. Current writer (`timestamp()`) emits
        # naive only, so this is defensive against future schema drift.
        delta = (f - s).total_seconds()
    except (TypeError, ValueError):
        return None
    return max(0, int(delta))


def _format_duration(seconds):
    """Render seconds as 'Xm YYs' / 'Ys' / '?' for None."""
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _format_ago(now_iso, then_iso):
    """Render a coarse 'N ago' string. Returns '?' if either is missing."""
    secs = _format_elapsed(then_iso, now_iso)
    if secs is None:
        return "?"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _print_incomplete_only_summary(review_dir, incomplete_path):
    """Render a summary for an interrupted review (no metadata.json yet).

    cmd_review writes incomplete.json from its KeyboardInterrupt /
    ReviewInterrupted / ReviewOrchestrationError handlers BEFORE the
    metadata.json write would have happened, so an interrupted review has
    only incomplete.json. This path renders what's available.
    """
    try:
        incomplete = json.loads(incomplete_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"trinity: malformed incomplete.json at {incomplete_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    status = incomplete.get("status", "interrupted")
    when = incomplete.get("timestamp", "?")
    providers_sel = incomplete.get("providers_selected", []) or []
    providers_started = incomplete.get("providers_started", []) or []
    providers_running = incomplete.get("providers_running_at_cleanup", []) or []
    cleanup = incomplete.get("cleanup", {}) or {}
    message = incomplete.get("message")

    # cmd_review writes status="interrupted" (KeyboardInterrupt /
    # ReviewInterrupted) or status="failed" (ReviewOrchestrationError /
    # bare Exception). Use the stored status as the top-level label so
    # orchestration failures aren't misrendered as user interruptions.
    print(f"Latest review: {review_dir}  ({status} at {when})")
    print(f"  Status: {status}")
    print()
    print(f"  Providers selected: {', '.join(providers_sel) or '(none)'}")
    print(f"  Providers started:  {', '.join(providers_started) or '(none)'}")
    if providers_running:
        print(f"  Running at cleanup: {', '.join(providers_running)}")
    if cleanup:
        # cleanup_active_processes() (scripts/codex.py:1050) writes
        # {"pid": ..., "result": "terminated"|"killed"|"kill_timeout"}
        # per provider. Read 'result' not 'status'.
        cleanup_lines = ", ".join(
            f"{name}: {info if isinstance(info, str) else info.get('result', '?')}"
            for name, info in cleanup.items()
        )
        print(f"  Cleanup: {cleanup_lines}")
    if message:
        print(f"  Message: {message}")
    print()
    print("  (metadata.json not present — review never reached completion)")
    return 0


def _print_review_summary(review_dir):
    """Render a one-screen summary of one review directory. Returns rc."""
    metadata_path = review_dir / "metadata.json"
    incomplete_path = review_dir / "incomplete.json"

    # An interrupted review never reaches the metadata-write step in
    # cmd_review — incomplete.json exists by itself with the structural
    # state. If that's the case, render from incomplete.json alone rather
    # than bailing with "no metadata", since this is the exact artifact
    # the user most wants summarized.
    if not metadata_path.exists() and incomplete_path.exists():
        return _print_incomplete_only_summary(review_dir, incomplete_path)

    if not metadata_path.exists():
        print(
            f"trinity: review in progress or no metadata at {metadata_path}",
            file=sys.stderr,
        )
        return 1
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"trinity: malformed metadata at {metadata_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    # All field reads are defensive — pre-TRN-2019 metadata may lack newer
    # keys (preset, skipped_optional_providers, input.mode).
    scope = metadata.get("scope", "?")
    mode = metadata.get("input", {}).get("mode", "?")
    preset = metadata.get("preset", {}).get("resolved", "?")
    skipped = metadata.get("preset", {}).get("skipped_optional_providers", [])
    results = metadata.get("results", [])

    # "started Xm ago" — earliest started_at across results, vs now.
    started_isos = [r.get("started_at") for r in results if r.get("started_at")]
    earliest = min(started_isos) if started_isos else None
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    ago = _format_ago(now_iso, earliest) if earliest else "?"

    print(f"Latest review: {review_dir}  (started {ago})")
    print(f"  Scope: {scope}   Mode: {mode}   Preset: {preset}")
    print()
    print("  Providers:")
    if not results:
        print("    (no results in metadata)")
    # Column width = max provider name length (or 10, whichever is larger).
    # Defends against `claude-code` (11 chars) and any future longer name
    # shifting the rest of the columns out of alignment.
    name_width = max([10] + [len(r.get("provider", "?")) for r in results])
    for r in results:
        name = r.get("provider", "?")
        rc = r.get("returncode")
        rc_str = "?" if rc is None else f"rc={rc}"
        marker = "✓" if rc == 0 else "✗"
        elapsed = _format_elapsed(r.get("started_at"), r.get("finished_at"))
        elapsed_str = _format_duration(elapsed)
        suffix = " (timeout)" if rc == 124 else ""
        print(
            f"    {name:{name_width}s} {marker} {rc_str:8s} elapsed {elapsed_str}{suffix}"
        )
    print()
    if skipped:
        skipped_str = ", ".join(
            f"{s.get('provider', '?')} ({s.get('reason', '?')})" for s in skipped
        )
        print(f"  Skipped optional: {skipped_str}")
    synthesis_path = review_dir / "synthesis.md"
    incomplete_path = review_dir / "incomplete.json"
    if synthesis_path.exists():
        print("  Synthesis: ✓ synthesis.md")
    else:
        print("  Synthesis: missing")
    incomplete_status = None
    if incomplete_path.exists():
        try:
            incomplete = json.loads(incomplete_path.read_text())
            incomplete_status = incomplete.get("status", "interrupted")
        except (json.JSONDecodeError, OSError):
            incomplete_status = "interrupted"
        print(f"  Incomplete: ✓ incomplete.json (status={incomplete_status})")

    # Final status line.
    if incomplete_status is not None:
        # Use the stored status directly. cmd_review writes status=
        # "interrupted" (KeyboardInterrupt / ReviewInterrupted) or
        # "failed" (ReviewOrchestrationError / bare Exception) — see
        # scripts/codex.py:1370-1402. Hard-coding "interrupted" here
        # would mislabel an exception-after-metadata-write (e.g. inside
        # write_synthesis()) as a user interruption.
        overall = incomplete_status
    elif not results:
        # Empty results list isn't "completed" — no providers ran.
        overall = "unknown (no results)"
    elif any(r.get("returncode") != 0 for r in results):
        # Any non-success rc (non-zero OR missing — None != 0) → partial.
        # The visual marker for rc=None is ✗, so the overall status must
        # not contradict that by reporting "completed".
        overall = "partial"
    else:
        overall = "completed"
    print(f"  Status: {overall}")
    return 0


def cmd_status(args):
    # Resolve to git top-level (with non-git fallback) so `trinity status`
    # works from any subdirectory, matching cmd_doctor's behavior. Without
    # this, a user running from `scripts/` would look at
    # `scripts/.trinity/reviews/` instead of the repo-root one where
    # `cmd_review` actually writes artifacts.
    root = resolve_health_root(args.root)
    reviews_dir = root / ".trinity" / "reviews"
    if not reviews_dir.is_dir():
        print(
            f"trinity: no reviews dir at {reviews_dir}",
            file=sys.stderr,
        )
        return 1

    # Sort key: (timestamp_prefix, mtime). The fixed-width
    # %Y%m%d-%H%M%S prefix gives chronological order across distinct
    # seconds; mtime breaks ties for same-second creates where the
    # slug or numeric collision suffix (`-10` vs `-2`) doesn't preserve
    # creation order. `make_review_dir()` (scripts/codex.py:914) only
    # stamps to seconds and appends `<slug>[-<index>]`, so two reviews
    # made in the same second can have lex order != creation order.
    def _sort_key(d):
        try:
            mtime = d.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (d.name[:15], mtime)

    candidates = sorted(
        [d for d in reviews_dir.iterdir() if d.is_dir()],
        key=_sort_key,
        reverse=True,
    )
    if not candidates:
        print(
            f"trinity: no reviews under {reviews_dir}",
            file=sys.stderr,
        )
        return 1
    return _print_review_summary(candidates[0])


def build_parser():
    parser = argparse.ArgumentParser(prog="trinity", allow_abbrev=False)
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    init_config = subparsers.add_parser("init-config")
    init_config.add_argument("--global-config", default=str(DEFAULT_CONFIG))

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--root", default=".")
    doctor.add_argument("--config", default=str(DEFAULT_CONFIG))
    doctor.add_argument("--providers")
    doctor.add_argument("--preset")

    review = subparsers.add_parser("review")
    review.add_argument("--root", default=".")
    review.add_argument("--config", default=str(DEFAULT_CONFIG))
    review.add_argument("--providers")
    review.add_argument("--preset")
    review.add_argument("--scope", default=".")
    review.add_argument("--out-dir")
    review.add_argument("--check-providers", action="store_true")
    review.add_argument("--pr", type=int)
    review.add_argument("--base")
    review.add_argument("--head")
    review.add_argument("--sop")
    review.add_argument("--rubric")

    status = subparsers.add_parser("status")
    status.add_argument("--root", default=".")
    status.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Explicitly request the latest review (default behavior; reserved "
            "for forward-compatibility with future --all / --review-dir flags)."
        ),
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "init-config":
        path = write_default_config(args.global_config)
        print(path)
        return 0
    if args.command == "review":
        return cmd_review(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "status":
        return cmd_status(args)
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Codex-native Trinity command wrapper."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

try:
    from ._version import load_version
    from . import _review_metadata as _rm  # noqa: F401 — tests patch codex._rm
except ImportError:
    from _version import load_version
    import _review_metadata as _rm  # noqa: F401 — tests patch codex._rm

try:
    from . import provider_runtime as _provider_runtime
except ImportError:
    import provider_runtime as _provider_runtime

try:
    from . import review_schema as _review_schema
except ImportError:
    import review_schema as _review_schema

try:
    from . import _doctor as _doctor_mod
except ImportError:
    import _doctor as _doctor_mod

try:
    from . import _review as _review_mod
except ImportError:
    import _review as _review_mod

try:
    from . import _status as _status_mod
except ImportError:
    import _status as _status_mod

parse_provider_command = _provider_runtime.parse_provider_command
provider_timeout = _provider_runtime.provider_timeout
command_has_path = _provider_runtime.command_has_path
provider_command = _provider_runtime.provider_command
build_prompt_handoff = _provider_runtime.build_prompt_handoff
progress = _provider_runtime.progress
timestamp = _provider_runtime.timestamp
elapsed_seconds = _provider_runtime.elapsed_seconds
ActiveProcessRegistry = _provider_runtime.ActiveProcessRegistry
ReviewInterrupted = _provider_runtime.ReviewInterrupted
ReviewOrchestrationError = _provider_runtime.ReviewOrchestrationError
process_group_id = _provider_runtime.process_group_id
signal_process_group = _provider_runtime.signal_process_group
terminate_process_group = _provider_runtime.terminate_process_group
cleanup_active_processes = _provider_runtime.cleanup_active_processes
raw_output = _provider_runtime.raw_output
write_text_atomic = _provider_runtime.write_text_atomic
timeout_partial_output = _provider_runtime.timeout_partial_output
_STDERR_SENTINEL = _provider_runtime._STDERR_SENTINEL
_DEFAULT_ENV_CLEAR_PATTERNS = _provider_runtime._DEFAULT_ENV_CLEAR_PATTERNS
_matches_any = _provider_runtime._matches_any
_is_essential = _provider_runtime._is_essential
_strip_stderr_region = _review_schema._strip_stderr_region
_safe_read_raw = _review_schema._safe_read_raw
_validate_review_schema = _review_schema._validate_review_schema
_REVIEW_PASS_THRESHOLD = _review_schema._REVIEW_PASS_THRESHOLD


# Re-exports from _doctor module (doctor/preflight/health-check subcommand).
_MIN_TIMEOUT_WARNING_SECONDS = _doctor_mod._MIN_TIMEOUT_WARNING_SECONDS
_WRAPPER_AUTH_CONFIG = _doctor_mod._WRAPPER_AUTH_CONFIG
_make_health_result = _doctor_mod._make_health_result
wrapper_auth_check = _doctor_mod.wrapper_auth_check
_is_canonical_wrapper = _doctor_mod._is_canonical_wrapper
detect_env_pollution = _doctor_mod.detect_env_pollution
executable_health = _doctor_mod.executable_health
provider_health = _doctor_mod.provider_health
provider_health_results = _doctor_mod.provider_health_results
_format_provider_block = _doctor_mod._format_provider_block
format_health_results = _doctor_mod.format_health_results
health_results_ok = _doctor_mod.health_results_ok
# NOTE: _LIVE_PROBE_TIMEOUT stays as a real attribute on this module (NOT
# re-exported from _doctor) so monkeypatch.setattr(codex_mod,
# "_LIVE_PROBE_TIMEOUT", ...) in test_doctor_preflight.py takes effect.
# _doctor._probe_provider reads this value via lazy `import codex` at call time.
_LIVE_PROBE_TIMEOUT = 10  # hard 10s timeout for live probes.
_probe_provider = _doctor_mod._probe_provider
cmd_doctor = _doctor_mod.cmd_doctor

# Re-exports from _review module (review orchestration subcommand).
scope_pathspec = _review_mod.scope_pathspec
git_diff = _review_mod.git_diff
git_diff_range = _review_mod.git_diff_range
changed_paths = _review_mod.changed_paths
changed_paths_range = _review_mod.changed_paths_range
untracked_paths = _review_mod.untracked_paths
is_text_file = _review_mod.is_text_file
read_text_file = _review_mod.read_text_file
read_text_file_at_ref = _review_mod.read_text_file_at_ref
synthetic_untracked_diff = _review_mod.synthetic_untracked_diff
file_snapshots = _review_mod.file_snapshots
file_snapshots_at_ref = _review_mod.file_snapshots_at_ref
review_input_sha256 = _review_mod.review_input_sha256
make_review_input = _review_mod.make_review_input
working_tree_review_input = _review_mod.working_tree_review_input
base_head_review_input = _review_mod.base_head_review_input
run_gh = _review_mod.run_gh
gh_pr_view = _review_mod.gh_pr_view
gh_pr_diff = _review_mod.gh_pr_diff
git_commit_exists = _review_mod.git_commit_exists
ensure_pr_head_available = _review_mod.ensure_pr_head_available
pr_changed_paths = _review_mod.pr_changed_paths
pr_review_input = _review_mod.pr_review_input
resolve_review_input = _review_mod.resolve_review_input
normalize_review_doc_id = _review_mod.normalize_review_doc_id
strict_review_metadata = _review_mod.strict_review_metadata
resolve_strict_review = _review_mod.resolve_strict_review
render_strict_review_instructions = _review_mod.render_strict_review_instructions
render_prompt = _review_mod.render_prompt
slugify = _review_mod.slugify
make_review_dir = _review_mod.make_review_dir
review_parallelism = _review_mod.review_parallelism
ordered_subset = _review_mod.ordered_subset
ordered_cleanup = _review_mod.ordered_cleanup
write_incomplete = _review_mod.write_incomplete
_sanitize_md = _review_mod._sanitize_md
_render_finding_items = _review_mod._render_finding_items
_render_findings_for = _review_mod._render_findings_for
_compute_summary = _review_mod._compute_summary
_render_summary_block = _review_mod._render_summary_block
_format_cli_summary = _review_mod._format_cli_summary
write_synthesis = _review_mod.write_synthesis
STRICT_REVIEW_OUTPUT_SCHEMA = _review_mod.STRICT_REVIEW_OUTPUT_SCHEMA
REVIEW_ONLY_INSTRUCTION = _review_mod.REVIEW_ONLY_INSTRUCTION
STRICT_REVIEW_TEMPLATES = _review_mod.STRICT_REVIEW_TEMPLATES
cmd_review = _review_mod.cmd_review

# Re-exports from _status module (status subcommand).
_format_elapsed = _status_mod._format_elapsed
_format_duration = _status_mod._format_duration
_format_ago = _status_mod._format_ago
_print_incomplete_only_summary = _status_mod._print_incomplete_only_summary
_print_review_summary = _status_mod._print_review_summary
cmd_status = _status_mod.cmd_status


def parse_structured_review(raw_text, pass_threshold=None):
    if pass_threshold is None:
        pass_threshold = _REVIEW_PASS_THRESHOLD
    return _review_schema.parse_structured_review(
        raw_text, pass_threshold=pass_threshold
    )


def _review_schema_addendum(task_type, strict_review=None):
    return _review_schema._review_schema_addendum(
        task_type,
        strict_review=strict_review,
        pass_threshold=_REVIEW_PASS_THRESHOLD,
    )


def build_provider_env(base_env=None):
    if base_env is None:
        base_env = os.environ
    return _provider_runtime.build_provider_env(base_env)


def run_provider(provider, provider_config, prompt_path, review_dir, root, registry):
    return _provider_runtime.run_provider(
        provider, provider_config, prompt_path, review_dir, root, registry
    )


def run_providers(
    max_workers, providers, provider_configs, prompt_path, review_dir, root
):
    return _provider_runtime.run_providers(
        max_workers,
        providers,
        provider_configs,
        prompt_path,
        review_dir,
        root,
        run_provider_fn=run_provider,
    )


DEFAULT_CONFIG = Path("~/.codex/trinity.json").expanduser()
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_CANDIDATES = [
    SCRIPT_ROOT / "trinity.codex.json",
    SCRIPT_ROOT / ".agents" / "trinity.codex.json",
]
DEFAULT_CONFIG_SECTIONS = ("providers", "review", "presets", "preset_aliases")
PRESET_TASK_TYPES = {"tdd", "review", "prp", "general"}
PRESET_ALIAS_RESERVED_WORDS = {
    "init-config",
    "doctor",
    "review",
    "status",
    "help",
    "session-path",
}
__version__ = load_version()


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


def cmd_session_path(args):
    """Resolve a Trinity session pointer to its on-disk JSONL transcript path.

    Lookup-key normalization (per CHG-3040 Surface 4):
    `<project>/.claude/trinity.json` keys are unsuffixed (`glm`, `codex`,
    `gemini`). The CLI accepts `<provider>[:<instance>]`; we strip a
    `:default` suffix at lookup time so `trinity session-path glm:default`
    is equivalent to `trinity session-path glm`. Other suffixes
    (e.g. `glm:experimental`) pass through verbatim and look up the
    suffixed key.
    """
    # Local import: keep `scripts/session_path.py` off the import path of
    # codex.py at module load (consistent with how this file imports the
    # heavy dependencies lazily inside command handlers elsewhere).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import session_path
    finally:
        # Best-effort cleanup; harmless if path was already present.
        try:
            sys.path.remove(str(Path(__file__).resolve().parent))
        except ValueError:
            pass

    spec = args.provider_spec or ""
    if ":" in spec:
        provider, instance = spec.split(":", 1)
        if instance == "default":
            lookup_key = provider
        else:
            lookup_key = spec
    else:
        lookup_key = spec

    if not lookup_key:
        print(
            "trinity session-path: missing <provider>[:<instance>]",
            file=sys.stderr,
        )
        return 1

    # Use the LITERAL --project directory (absolute path, NO symlink
    # following), NOT the git toplevel. `session.py:cmd_write` stores
    # .claude/trinity.json under the exact <project_dir> the worker passed;
    # session-path must read from the same path to find the matching pointer.
    #
    # Two earlier defects narrowed down to here:
    # - R1 used `resolve_health_root` which rewrote subdirs of a git repo
    #   to the toplevel (bot R3 P2 finding 3214530179, fixed in R5).
    # - R5 used `Path(...).resolve()` which follows symlinks; `--project
    #   /tmp/link` would canonicalize to the symlink target, causing the
    #   claude-family slug encoding to differ from where the wrapper wrote
    #   the pointer (bot R4 P2 finding 3214543729, fixed in R6).
    #
    # `os.path.abspath(os.path.expanduser(...))` gives an absolute path
    # without following symlinks. Works for git, non-git, nested, and
    # symlinked dirs alike, matching the literal $PROJECT_DIR semantics
    # used everywhere in providers/<name>.md.
    project_dir = os.path.abspath(os.path.expanduser(args.project))
    return session_path.cmd_session_path(project_dir, lookup_key)


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
    doctor.add_argument(
        "--live",
        action="store_true",
        help="Probe providers with a minimal prompt to surface auth/quota/timeout failures.",
    )

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

    session_path = subparsers.add_parser(
        "session-path",
        help="Resolve a Trinity session pointer to its JSONL transcript path.",
    )
    session_path.add_argument(
        "provider_spec",
        help="Provider key, optionally with instance suffix (e.g. 'glm', 'glm:default', 'codex:experimental').",
    )
    session_path.add_argument(
        "--project",
        default=".",
        help="Project directory containing .claude/trinity.json (default: cwd).",
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
    if args.command == "session-path":
        return cmd_session_path(args)
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

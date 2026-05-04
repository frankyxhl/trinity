#!/usr/bin/env python3
"""Codex-native Trinity command wrapper."""

import argparse
import datetime as dt
import difflib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


DEFAULT_CONFIG = Path("~/.codex/trinity.json").expanduser()
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_CANDIDATES = [
    SCRIPT_ROOT / "trinity.codex.json",
    SCRIPT_ROOT / ".agents" / "trinity.codex.json",
]
DEFAULT_CONFIG_SECTIONS = ("providers", "review", "presets", "preset_aliases")


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


def split_providers(value, config):
    if value:
        providers = [item.strip() for item in value.split(",") if item.strip()]
    else:
        providers = config.get("review", {}).get("default_providers", [])
    if not providers:
        raise SystemExit("trinity-codex: no providers selected")
    return providers


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
    issues = []
    command = None
    executable = None
    timeout = None

    try:
        command = parse_provider_command(provider, provider_config)
    except ValueError as exc:
        issues.append(str(exc))

    if command:
        executable, issue = executable_health(command, root)
        if issue:
            issues.append(issue)

    if isinstance(provider_config, dict):
        try:
            timeout = provider_timeout(provider, provider_config)
        except ValueError as exc:
            issues.append(str(exc))

    return {
        "provider": provider,
        "ok": not issues,
        "executable": executable,
        "timeout": timeout,
        "issues": issues,
    }


def provider_health_results(config, providers, root):
    provider_configs = config.get("providers", {})
    if not isinstance(provider_configs, dict):
        return [
            {
                "provider": provider,
                "ok": False,
                "executable": None,
                "timeout": None,
                "issues": ["providers config must be an object"],
            }
            for provider in providers
        ]

    results = []
    for provider in providers:
        if provider not in provider_configs:
            results.append(
                {
                    "provider": provider,
                    "ok": False,
                    "executable": None,
                    "timeout": None,
                    "issues": ["unknown provider"],
                }
            )
            continue
        results.append(provider_health(provider, provider_configs[provider], root))
    return results


def format_health_results(results):
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


def health_results_ok(results):
    return all(result["ok"] for result in results)


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


def render_prompt(config, root, scope, review_input):
    diff = review_input["diff"]
    files = review_input["files"]
    template = config.get("review", {}).get("prompt_template", "{diff}\n\n{files}\n")
    return (
        template.replace("{scope}", scope or ".")
        .replace("{root}", str(root))
        .replace("{diff}", diff)
        .replace("{files}", files)
    )


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


def run_provider(provider, provider_config, prompt_path, review_dir, root):
    raw_path = review_dir / "raw" / f"{provider}.txt"
    cmd = provider_command(provider, provider_config) + [
        build_prompt_handoff(prompt_path)
    ]
    try:
        timeout = provider_timeout(provider, provider_config)
    except ValueError as exc:
        raise SystemExit(f"trinity-codex: provider {provider} {exc}") from exc
    started = dt.datetime.now().isoformat(timespec="seconds")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        raw_path.write_text(output)
        return {
            "provider": provider,
            "returncode": result.returncode,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    except FileNotFoundError as exc:
        raw_path.write_text(f"ERROR: command not found: {exc}\n")
        return {
            "provider": provider,
            "returncode": 127,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    except subprocess.TimeoutExpired as exc:
        raw_path.write_text(f"ERROR: timeout after {timeout}s\n{exc}\n")
        return {
            "provider": provider,
            "returncode": 124,
            "raw": str(raw_path.relative_to(review_dir)),
            "started_at": started,
            "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        }


def write_synthesis(review_dir, scope, results):
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
        status = "PASS" if result["returncode"] == 0 else f"FAIL {result['returncode']}"
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
    path.write_text("\n".join(lines))


def cmd_review(args):
    root = resolve_root(args.root)
    config = load_config(args.config)
    providers = split_providers(args.providers, config)
    provider_configs = config.get("providers", {})
    health = provider_health_results(config, providers, root)
    if args.check_providers:
        print(format_health_results(health))
        return 0 if health_results_ok(health) else 1
    if not health_results_ok(health):
        print(format_health_results(health), file=sys.stderr)
        return 1
    review_input = resolve_review_input(args, root)

    out_base = args.out_dir or config.get("review", {}).get(
        "output_dir", ".trinity/reviews"
    )
    out_base = Path(out_base)
    if not out_base.is_absolute():
        out_base = root / out_base
    review_dir = make_review_dir(out_base, args.scope)
    prompt = render_prompt(config, root, args.scope, review_input)
    prompt_path = review_dir / "prompt.md"
    prompt_path.write_text(prompt)

    results = []
    for provider in providers:
        results.append(
            run_provider(
                provider,
                provider_configs[provider],
                prompt_path,
                review_dir,
                root,
            )
        )
    metadata = {
        "scope": args.scope,
        "root": str(root),
        "providers": providers,
        "input": review_input["metadata"],
        "results": results,
    }
    (review_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    )
    write_synthesis(review_dir, args.scope, results)
    print(review_dir)
    return 0 if all(item["returncode"] == 0 for item in results) else 1


def cmd_doctor(args):
    root = resolve_health_root(args.root)
    config = load_config(args.config)
    providers = split_providers(args.providers, config)
    health = provider_health_results(config, providers, root)
    print(format_health_results(health))
    return 0 if health_results_ok(health) else 1


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

    review = subparsers.add_parser("review")
    review.add_argument("--root", default=".")
    review.add_argument("--config", default=str(DEFAULT_CONFIG))
    review.add_argument("--providers")
    review.add_argument("--scope", default=".")
    review.add_argument("--out-dir")
    review.add_argument("--check-providers", action="store_true")
    review.add_argument("--pr", type=int)
    review.add_argument("--base")
    review.add_argument("--head")
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
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

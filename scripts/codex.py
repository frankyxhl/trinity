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
import subprocess
import sys


DEFAULT_CONFIG = Path("~/.codex/trinity.json").expanduser()
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_CANDIDATES = [
    SCRIPT_ROOT / "trinity.codex.json",
    SCRIPT_ROOT / ".agents" / "trinity.codex.json",
]


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

    current["providers"] = source["providers"]
    current["review"] = source["review"]
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


def changed_paths(root, pathspec):
    args = ["diff", "--name-only", "--diff-filter=ACMRT", "HEAD", "--"]
    output = run_git(root, args + pathspec, allow_error=True)
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


def render_prompt(config, root, scope):
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
    template = config.get("review", {}).get("prompt_template", "{diff}\n\n{files}\n")
    if not diff.strip():
        diff = "(no tracked or untracked git diff)"
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
    cli = provider_config.get("cli")
    if not cli:
        raise SystemExit(f"trinity-codex: provider {provider} missing cli")
    expanded = os.path.expandvars(os.path.expanduser(cli))
    return shlex.split(expanded)


def run_provider(provider, provider_config, prompt, review_dir, root):
    raw_path = review_dir / "raw" / f"{provider}.txt"
    cmd = provider_command(provider, provider_config) + [prompt]
    timeout = int(provider_config.get("timeout", 360))
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
    out_base = args.out_dir or config.get("review", {}).get(
        "output_dir", ".trinity/reviews"
    )
    out_base = Path(out_base)
    if not out_base.is_absolute():
        out_base = root / out_base
    review_dir = make_review_dir(out_base, args.scope)
    prompt = render_prompt(config, root, args.scope)
    (review_dir / "prompt.md").write_text(prompt)

    results = []
    provider_configs = config.get("providers", {})
    for provider in providers:
        if provider not in provider_configs:
            raise SystemExit(f"trinity-codex: unknown provider: {provider}")
        results.append(
            run_provider(provider, provider_configs[provider], prompt, review_dir, root)
        )
    metadata = {
        "scope": args.scope,
        "root": str(root),
        "providers": providers,
        "results": results,
    }
    (review_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    )
    write_synthesis(review_dir, args.scope, results)
    print(review_dir)
    return 0 if all(item["returncode"] == 0 for item in results) else 1


def build_parser():
    parser = argparse.ArgumentParser(prog="trinity")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    init_config = subparsers.add_parser("init-config")
    init_config.add_argument("--global-config", default=str(DEFAULT_CONFIG))

    review = subparsers.add_parser("review")
    review.add_argument("--root", default=".")
    review.add_argument("--config", default=str(DEFAULT_CONFIG))
    review.add_argument("--providers")
    review.add_argument("--scope", default=".")
    review.add_argument("--out-dir")
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
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
discover.py -- Provider discovery (usable / unregistered)

Usage:
    discover.py --version
    discover.py list [--global-config <path>] [--project-dir <dir>]
"""

import argparse
import json
import os
import subprocess
import sys

try:
    from ._version import load_version
except ImportError:
    from _version import load_version

__version__ = load_version()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_SCRIPT = os.path.join(SCRIPT_DIR, "config.py")


def get_merged_config(global_config, project_dir):
    """Call config.py merge to get the merged provider map."""
    result = subprocess.run(
        [
            sys.executable,
            CONFIG_SCRIPT,
            "merge",
            "--global-config",
            global_config,
            "--project-dir",
            project_dir,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def scan_agent_dirs(project_dir):
    """
    Scan .claude/agents/ and ~/.claude/agents/ for trinity-*.md files.
    Returns dict: name -> resolved path (project takes precedence).
    """
    found = {}

    # Global agents first (lower precedence)
    global_agents_dir = os.path.expanduser(os.path.join("~", ".claude", "agents"))
    if os.path.isdir(global_agents_dir):
        for fname in os.listdir(global_agents_dir):
            if fname.startswith("trinity-") and fname.endswith(".md"):
                agent_path = os.path.join(global_agents_dir, fname)
                if not os.path.exists(agent_path):
                    continue
                name = fname[len("trinity-") : -len(".md")]
                if name and name not in found:
                    found[name] = agent_path

    # Project agents (higher precedence — overwrite global)
    project_agents_dir = os.path.join(project_dir, ".claude", "agents")
    if os.path.isdir(project_agents_dir):
        for fname in os.listdir(project_agents_dir):
            if fname.startswith("trinity-") and fname.endswith(".md"):
                agent_path = os.path.join(project_agents_dir, fname)
                if not os.path.exists(agent_path):
                    continue
                name = fname[len("trinity-") : -len(".md")]
                if name:
                    found[name] = agent_path

    return found


def cmd_list(global_config, project_dir):
    merged = get_merged_config(global_config, project_dir)
    providers = merged.get("providers", {}) or {}

    # Scan all agent files (name -> path)
    all_agent_files = scan_agent_dirs(project_dir)

    rows = {}

    # (a) For each config entry, check agent file
    for name, entry in providers.items():
        cli = entry.get("cli") if entry else None
        agent_path = all_agent_files.get(name)
        if agent_path:
            rows[name] = {
                "name": name,
                "status": "usable",
                "cli": cli,
                "agent": agent_path,
            }
        else:
            rows[name] = {
                "name": name,
                "status": "missing_agent",
                "cli": cli,
                "agent": None,
            }

    # (b) Agent files not in config -> missing_config
    for name, agent_path in all_agent_files.items():
        if name not in rows:
            rows[name] = {
                "name": name,
                "status": "missing_config",
                "cli": None,
                "agent": agent_path,
            }

    # Sort: usable first, then missing_agent, then missing_config; alphabetical within
    status_order = {"usable": 0, "missing_agent": 1, "missing_config": 2}
    result = sorted(rows.values(), key=lambda r: (status_order[r["status"]], r["name"]))

    print(json.dumps(result, indent=2, ensure_ascii=False), end="")


def main():
    argv = sys.argv[1:]

    if not argv:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    # Parser built inside main() so expanduser()/getcwd() defaults bind
    # per-invocation (honors patched HOME in subprocess tests). Mirrors
    # scripts/codex.py:build_parser + main() ordering.
    parser = argparse.ArgumentParser(prog="discover.py", allow_abbrev=False)
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", allow_abbrev=False)
    list_parser.add_argument(
        "--global-config",
        default=os.path.expanduser("~/.claude/trinity.json"),
    )
    list_parser.add_argument(
        "--project-dir",
        default=os.getcwd(),
    )

    args = parser.parse_args(argv)

    # Version-check-before-dispatch invariant (CHG-3047): `--version list`
    # must print version and exit 0 without dispatching the list subcommand.
    if args.version:
        print(__version__)
        return

    if args.command == "list":
        cmd_list(args.global_config, args.project_dir)


if __name__ == "__main__":
    main()

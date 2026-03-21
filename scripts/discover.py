#!/usr/bin/env python3
"""
discover.py -- Provider discovery (usable / unregistered)

Usage:
    discover.py --version
    discover.py list [--global-config <path>] [--project-dir <dir>]
"""
import sys
import json
import os
import subprocess
from pathlib import Path

VERSION = "1.0.0"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_SCRIPT = os.path.join(SCRIPT_DIR, "config.py")


def get_merged_config(global_config, project_dir):
    """Call config.py merge to get the merged provider map."""
    result = subprocess.run(
        [sys.executable, CONFIG_SCRIPT, "merge",
         "--global-config", global_config,
         "--project-dir", project_dir],
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


def find_agent_file(name, project_dir):
    """
    Find agent file for given provider name.
    Check project .claude/agents/trinity-<name>.md first,
    then ~/.claude/agents/trinity-<name>.md.
    Returns resolved path string if found, else None.
    """
    filename = f"trinity-{name}.md"
    project_agent = os.path.join(project_dir, ".claude", "agents", filename)
    if os.path.exists(project_agent):
        return str(project_agent)
    global_agent = os.path.expanduser(os.path.join("~", ".claude", "agents", filename))
    if os.path.exists(global_agent):
        return str(global_agent)
    return None


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
                name = fname[len("trinity-"):-len(".md")]
                if name and name not in found:
                    found[name] = os.path.join(global_agents_dir, fname)

    # Project agents (higher precedence — overwrite global)
    project_agents_dir = os.path.join(project_dir, ".claude", "agents")
    if os.path.isdir(project_agents_dir):
        for fname in os.listdir(project_agents_dir):
            if fname.startswith("trinity-") and fname.endswith(".md"):
                name = fname[len("trinity-"):-len(".md")]
                if name:
                    found[name] = os.path.join(project_agents_dir, fname)

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
        agent_path = find_agent_file(name, project_dir)
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
    args = sys.argv[1:]

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--version":
        print(VERSION)
        return

    if args[0] == "list":
        global_config = os.path.expanduser("~/.claude/trinity.json")
        project_dir = os.getcwd()

        i = 1
        while i < len(args):
            if args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            elif args[i] == "--project-dir" and i + 1 < len(args):
                project_dir = args[i + 1]
                i += 2
            else:
                print(f"discover.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        cmd_list(global_config, project_dir)

    else:
        print(f"discover.py: unknown command '{args[0]}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

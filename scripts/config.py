#!/usr/bin/env python3
"""
config.py -- Config overlay merge (global + project -> merged JSON)

Usage:
    config.py --version
    config.py merge [--global-config <path>] [--project-dir <dir>]
"""
import sys
import json
import os

VERSION = "1.0.0"


def load_json_file(path):
    """
    Load JSON from path.
    - Missing file: returns {}
    - Invalid JSON: prints error and exits 1
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            content = f.read()
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"trinity-scripts: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"trinity-scripts: IO error reading {path}: {e}", file=sys.stderr)
        sys.exit(1)


def merge_configs(global_data, project_data):
    """
    Merge global and project configs per PRP semantics:
    - providers: dict merge, project key wins on conflict
    - defaults: shallow key-by-key merge, project wins per key;
                missing project key inherits from global;
                project null overrides global;
                project array replaces global array entirely
    - sessions: project-only; global sessions key is ignored
    """
    result = {}

    # providers: dict merge, project wins
    global_providers = global_data.get("providers", {}) or {}
    project_providers = project_data.get("providers", {}) or {}
    merged_providers = {**global_providers, **project_providers}
    if merged_providers:
        result["providers"] = merged_providers

    # defaults: key-by-key shallow merge
    global_defaults = global_data.get("defaults", {}) or {}
    project_defaults = project_data.get("defaults", {}) or {}
    if global_defaults or project_defaults:
        merged_defaults = dict(global_defaults)
        for k, v in project_defaults.items():
            merged_defaults[k] = v  # project value wins, including None
        result["defaults"] = merged_defaults

    # sessions: project-only (never include global sessions)
    project_sessions = project_data.get("sessions")
    if project_sessions is not None:
        result["sessions"] = project_sessions

    return result


def cmd_merge(global_config_path, project_dir):
    project_trinity = os.path.join(project_dir, ".claude", "trinity.json")

    global_data = load_json_file(global_config_path)
    project_data = load_json_file(project_trinity)

    merged = merge_configs(global_data, project_data)
    print(json.dumps(merged, indent=2, ensure_ascii=False), end="")


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--version":
        print(VERSION)
        return

    if args[0] == "merge":
        # Parse optional flags
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
                print(f"config.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        cmd_merge(global_config, project_dir)

    else:
        print(f"config.py: unknown command '{args[0]}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

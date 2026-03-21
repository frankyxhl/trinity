#!/usr/bin/env python3
"""
install.py -- Atomic provider registration in global config

Usage:
    install.py --version
    install.py register <provider> --cli <cli_command> [--global-config <path>]
    install.py unregister <provider> [--global-config <path>]
"""
import sys
import json
import os
import time

VERSION = "1.0.0"

try:
    import fcntl
except ImportError:
    print("trinity-scripts: unsupported platform (fcntl not available). Windows is not supported.", file=sys.stderr)
    sys.exit(1)


def atomic_update(path, update_fn):
    """
    Atomically read-modify-write a JSON file with fcntl.flock.
    Creates file (and dirs) if absent.
    update_fn receives the current data dict and should modify it in place or return new dict.
    """
    dir_path = os.path.dirname(path)
    if dir_path:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            print(f"trinity-scripts: IO error creating directory {dir_path}: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content.strip():
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as e:
                        print(f"trinity-scripts: invalid JSON in {path}: {e}", file=sys.stderr)
                        sys.exit(1)
                else:
                    data = {}
                data = update_fn(data)
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error writing {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_register(provider, cli_command, global_config):
    def update(data):
        if "providers" not in data:
            data["providers"] = {}
        data["providers"][provider] = {
            "cli": cli_command,
            "installed": True,
        }
        return data

    atomic_update(global_config, update)


def cmd_unregister(provider, global_config):
    if not os.path.exists(global_config):
        # no-op
        return

    def update(data):
        if "providers" in data:
            data["providers"].pop(provider, None)
        return data

    atomic_update(global_config, update)


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--version":
        print(VERSION)
        return

    if args[0] == "register":
        if len(args) < 2:
            print("install.py register <provider> --cli <cli_command> [--global-config <path>]", file=sys.stderr)
            sys.exit(1)

        provider = args[1]
        cli_command = None
        global_config = os.path.expanduser("~/.claude/trinity.json")

        i = 2
        while i < len(args):
            if args[i] == "--cli" and i + 1 < len(args):
                cli_command = args[i + 1]
                i += 2
            elif args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            else:
                print(f"install.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        if cli_command is None:
            print("install.py register: --cli is required", file=sys.stderr)
            sys.exit(1)

        cmd_register(provider, cli_command, global_config)

    elif args[0] == "unregister":
        if len(args) < 2:
            print("install.py unregister <provider> [--global-config <path>]", file=sys.stderr)
            sys.exit(1)

        provider = args[1]
        global_config = os.path.expanduser("~/.claude/trinity.json")

        i = 2
        while i < len(args):
            if args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            else:
                print(f"install.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        cmd_unregister(provider, global_config)

    else:
        print(f"install.py: unknown command '{args[0]}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

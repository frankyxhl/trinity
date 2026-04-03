#!/usr/bin/env python3
"""
session.py -- Session CRUD for .claude/trinity.json

Usage:
    session.py --version
    session.py read <project_dir> <instance_key>
    session.py write <project_dir> <instance_key> <session_id> <task_summary>
    session.py clear <project_dir> <instance_key|all>
    session.py heartbeat <output_file>
"""

import importlib.util
import json
import os
import sys
import time


def _load_version():
    _init = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py")
    _spec = importlib.util.spec_from_file_location("_scripts_init", _init)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod.__version__


__version__ = _load_version()

try:
    import fcntl
except ImportError:
    print(
        "trinity-scripts: unsupported platform (fcntl not available). Windows is not supported.",
        file=sys.stderr,
    )
    sys.exit(1)


def trinity_path(project_dir):
    return os.path.join(project_dir, ".claude", "trinity.json")


def cmd_read(project_dir, instance_key):
    path = trinity_path(project_dir)
    if not os.path.exists(path):
        print("NEW")
        return
    try:
        with open(path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                content = f.read()
                if not content.strip():
                    print(
                        f"trinity-scripts: invalid JSON in {path}: empty file",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as e:
                    print(
                        f"trinity-scripts: invalid JSON in {path}: {e}", file=sys.stderr
                    )
                    sys.exit(1)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error reading {path}: {e}", file=sys.stderr)
        sys.exit(1)
    sessions = data.get("sessions", {})
    entry = sessions.get(instance_key)
    if entry:
        print(entry["session_id"])
    else:
        print("NEW")


def cmd_write(project_dir, instance_key, session_id, task_summary):
    path = trinity_path(project_dir)
    dir_path = os.path.dirname(path)
    try:
        os.makedirs(dir_path, exist_ok=True)
    except OSError as e:
        print(
            f"trinity-scripts: IO error creating directory {dir_path}: {e}",
            file=sys.stderr,
        )
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
                        print(
                            f"trinity-scripts: invalid JSON in {path}: {e}",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                else:
                    data = {}
                if "sessions" not in data:
                    data["sessions"] = {}
                data["sessions"][instance_key] = {
                    "session_id": session_id,
                    "last_used": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "task_summary": task_summary,
                }
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error writing {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_clear(project_dir, key):
    path = trinity_path(project_dir)
    if not os.path.exists(path):
        # no-op
        return

    try:
        with open(path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    print(
                        f"trinity-scripts: invalid JSON in {path}: {e}", file=sys.stderr
                    )
                    sys.exit(1)
                if "sessions" not in data:
                    data["sessions"] = {}
                if key == "all":
                    data["sessions"] = {}
                else:
                    data["sessions"].pop(key, None)
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error writing {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _find_last_assistant_activity(lines):
    """Parse JSONL lines in reverse to find the last assistant tool_use or text."""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if entry.get("type") != "assistant":
            continue
        for block in entry.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name", "?")
                inp = str(block.get("input", ""))[:150]
                return f"tool: {name} | input: {inp}"
            if block.get("type") == "text":
                return f"text: {block.get('text', '')[:150]}"
        break
    return None


def cmd_heartbeat(output_file):
    if not os.path.exists(output_file):
        print("FILE_NOT_FOUND")
        return
    with open(output_file, "r") as f:
        lines = f.readlines()
    print(f"{len(lines)} lines")
    activity = _find_last_assistant_activity(lines)
    if activity:
        print(activity)
    else:
        print("no assistant activity")


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--version":
        print(__version__)
        return

    if args[0] == "read":
        if len(args) < 3:
            print("session.py read <project_dir> <instance_key>", file=sys.stderr)
            sys.exit(1)
        cmd_read(args[1], args[2])

    elif args[0] == "write":
        if len(args) < 5:
            print(
                "session.py write <project_dir> <instance_key> <session_id> <task_summary>",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_write(args[1], args[2], args[3], args[4])

    elif args[0] == "clear":
        if len(args) < 3:
            print("session.py clear <project_dir> <instance_key|all>", file=sys.stderr)
            sys.exit(1)
        cmd_clear(args[1], args[2])

    elif args[0] == "heartbeat":
        if len(args) < 2:
            print("session.py heartbeat <output_file>", file=sys.stderr)
            sys.exit(1)
        cmd_heartbeat(args[1])

    else:
        print(f"session.py: unknown command '{args[0]}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

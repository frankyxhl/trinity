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

import json
import os
import sys
import time

try:
    from ._version import load_version
except ImportError:
    from _version import load_version

__version__ = load_version()

try:
    from ._compat import fcntl
except ImportError:
    from _compat import fcntl


def trinity_path(project_dir):
    return os.path.join(project_dir, ".claude", "trinity.json")


# Sentinel returned by _read_pointer when no pointer file exists. Distinct
# from "file exists but is empty/invalid" (which raises) and from "file exists
# with no matching entry" (caller's job to detect on the returned dict).
POINTER_MISSING = None


def _read_pointer(project_dir):
    """Read `<project_dir>/.claude/trinity.json` under a shared (LOCK_SH) lock.

    Returns:
        dict — parsed JSON contents (top-level object, e.g. ``{"sessions": {...}}``).
        ``POINTER_MISSING`` (None) — when the pointer file does not exist on disk.

    Raises:
        SystemExit(1) — on IO error, empty file, or malformed JSON. Mirrors
        the prior in-line behavior of ``cmd_read``; both ``cmd_read`` and
        ``scripts.session_path`` rely on this single source of truth so the
        ``fcntl.flock(LOCK_SH)`` + ``json.loads`` flow lives in exactly one
        place (per CHG-3040 trade-off table option A).
    """
    path = trinity_path(project_dir)
    if not os.path.exists(path):
        return POINTER_MISSING
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
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    print(
                        f"trinity-scripts: invalid JSON in {path}: {e}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error reading {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_read(project_dir, instance_key):
    data = _read_pointer(project_dir)
    if data is POINTER_MISSING:
        print("NEW")
        return
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

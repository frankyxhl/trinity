#!/usr/bin/env python3
"""Trinity command line front end: parse, call the core, print (NG-06).

Holds no logic. Dispatch goes through `call`; the tree comes from the journal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from . import trinity_core
except ImportError:
    import trinity_core


def _call_request(args: argparse.Namespace) -> dict:
    depth = args.allow_nesting_max_depth
    max_depth = 0 if depth is None else int(depth)
    return {
        "profiles_path": args.profiles,
        "profile": args.profile,
        "step": args.step,
        "session": args.session,
        "prompt": args.prompt,
        "cwd": args.cwd or os.getcwd(),
        "max_depth": max_depth,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trinity")
    commands = parser.add_subparsers(dest="command")

    call = commands.add_parser("call")
    call.add_argument("--profiles", required=True)
    call.add_argument("--profile", required=True)
    call.add_argument("--step", required=True)
    call.add_argument("--session", default="new")
    call.add_argument("--prompt", required=True)
    call.add_argument("--cwd", default=None)
    call.add_argument("--allow-nesting-max-depth", default=None)

    tree = commands.add_parser("tree")
    tree.add_argument("run")

    args = parser.parse_args(argv)
    if args.command == "call":
        result = trinity_core.call(_call_request(args))
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    if args.command == "tree":
        root = trinity_core.journal_root()
        for line in trinity_core.render_tree(root, args.run):
            sys.stdout.write(line + "\n")
        return 0
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

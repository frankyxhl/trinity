import json
import math
import os
from pathlib import Path
import sys

try:
    from . import trinity_core
    from .trinity_core import profile_checks as _profile_checks
except ImportError:
    import trinity_core
    from trinity_core import profile_checks as _profile_checks

_BAD_REQUEST = {
    "run": None,
    "node": None,
    "exit_class": "bad_request",
    "session_id": None,
    "output_kind": "none",
    "journal_complete": True,
}


def _reject_call() -> int:
    sys.stdout.write(json.dumps(_BAD_REQUEST, separators=(",", ":")) + "\n")
    return 0


def cmd_call(args):
    """Build the dispatch-core request and hand it to the core (NG-06)."""
    if args.prompt is not None and args.prompt_file:
        return _reject_call()
    text = args.prompt
    if text is None:
        parts = []
        for path in args.prompt_file or []:
            try:
                parts.append(Path(path).read_bytes().decode("utf-8"))
            except (OSError, UnicodeDecodeError):
                return _reject_call()
        text = "".join(parts)
    if text is None:
        return _reject_call()
    limits = None
    if args.time_s is not None:
        try:
            time_s = float(args.time_s)
        except ValueError:
            return _reject_call()
        if not math.isfinite(time_s) or time_s <= 0:
            return _reject_call()
        limits = {"time_s": time_s}
    gate = args.gate
    if gate is not None and gate not in _profile_checks.GATES:
        return _reject_call()
    allow_nesting = False
    if args.allow_nesting_max_depth is not None:
        allow_nesting = {"max_depth": args.allow_nesting_max_depth}
    request = {
        "profiles_path": args.profiles,
        "profile": args.profile,
        "step": args.step,
        "session": args.session,
        "prompt": {"text": text},
        "cwd": args.cwd,
        "allow_nesting": allow_nesting,
        "limits": limits,
        "output": os.path.abspath(args.output) if args.output else None,
        "model": args.model,
        "gate": args.gate,
        "log_dir": args.log_dir,
    }
    result = trinity_core.call(request)
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return 0

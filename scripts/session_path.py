#!/usr/bin/env python3
"""session_path.py — Resolve a Trinity session pointer to its on-disk JSONL transcript path.

Path-only contract: this module reads `<project>/.claude/trinity.json` (via
the shared `_read_pointer` helper in `scripts/session.py`) and probes the
filesystem for transcript existence. It MUST NOT open, read, parse, or
surface the contents of any JSONL transcript. Stdout is exactly one line —
the absolute path. All errors / diagnostics go to stderr.

Lookup-key normalization (per CHG-3040 Surface 4): the wrapper in `codex.py`
strips a `:default` suffix before delegating to ``cmd_session_path`` here.
This module receives the canonicalized lookup key (`glm`, not `glm:default`)
and looks it up verbatim in `.claude/trinity.json` -> ``sessions``.

Per-provider resolvers cover:
    glm           -> ~/.factory/sessions/<encoded-project-path>/<session-id>.jsonl
    codex         -> ~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<session-id>.jsonl
                     (index-first via ~/.codex/session_index.jsonl;
                      glob fallback `*-<session-id>.jsonl` anchored at the dash
                      boundary; post-filter via `endswith` to defend against
                      suffix-collision on short IDs)
    claude-code   -> ~/.claude-trinity-claude-code/projects/<PROJECT_SLUG>/<session-id>.jsonl
    deepseek      -> ~/.claude-deepseek/projects/<PROJECT_SLUG>/<session-id>.jsonl
    openrouter    -> ~/.claude-openrouter/projects/<PROJECT_SLUG>/<session-id>.jsonl
    gemini        -> stub (exits 3 with explicit "not yet supported" message)

Encoding differs by provider (matches per-wrapper conventions in
``providers/<name>.md``):
    glm                              -> replace "/" with "-"; KEEP leading dash
                                        (matches ~/.factory/sessions/-Users-frank-...)
    claude-code/deepseek/openrouter  -> replace "/" with "-"; KEEP leading dash
                                        (PROJECT_SLUG=$(echo "$PROJECT_DIR"
                                        | sed 's|/|-|g'); matches the claude CLI's
                                        ~/.claude-*/projects/-Users-frank-... layout)

Exit codes:
    0  path printed; file exists on disk.
    2  no session pointer for the provided key.
    3  provider unsupported, file missing, malformed session_id, or codex
       multi-glob residual.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Importing the sibling module's shared pointer reader is the single source
# of truth for the trinity.json read flow (per CHG-3040 module-location
# decision). Both `session.py:cmd_read` and the new resolver below funnel
# through `_read_pointer`.
try:
    from .session import _read_pointer, POINTER_MISSING
except ImportError:
    from session import _read_pointer, POINTER_MISSING

# Conservative regex (per CHG-3040 Surface 1 / Threat Model):
#   - allows letters, digits, underscore, hyphen, dot
#   - rejects "/", whitespace, null bytes, etc.
# The regex itself accepts dots individually but does NOT block consecutive
# `..` (path-traversal) — `_is_valid_session_id` adds the substring guard.
# Validated BEFORE any path construction. Identical regex + guard logic
# appears in the CHG; do not relax without a follow-up CHG.
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def _is_valid_session_id(session_id: str) -> bool:
    """Return True iff `session_id` passes both the regex AND the explicit
    `..` substring guard. The regex allows single dots (for legitimate
    session_id formats that contain them) but `..` is the path-traversal
    sequence we MUST reject — substring check enforces that since the
    character class would otherwise let `..` through.
    """
    return bool(_SESSION_ID_RE.match(session_id)) and ".." not in session_id


def _encode_project_path(project_dir: str) -> str:
    """Encode an absolute project path as droid/claude do: replace '/' with '-'.

    Matches existing layout under ``~/.factory/sessions/`` and
    ``~/.claude/projects/`` (e.g. ``-Users-frank-Projects-trinity``).
    """
    abs_path = os.path.abspath(project_dir)
    return abs_path.replace("/", "-")


# ---------------------------------------------------------------------------
# Per-provider resolvers
# ---------------------------------------------------------------------------


def _encode_project_slug(project_dir: str) -> str:
    """Claude-family encoding (`PROJECT_SLUG`): replace `/` with `-`, KEEPING
    the leading dash. Matches the claude CLI's actual on-disk layout under
    ``~/.claude-*/projects/`` (e.g. ``-Users-frank-Projects-trinity``), per
    the per-wrapper convention in ``providers/<name>.md``:

        PROJECT_SLUG=$(echo "$PROJECT_DIR" | sed 's|/|-|g')

    Post CHG-3045 this is identical to ``_encode_project_path`` (both keep the
    leading dash). Kept as a separate function pending a follow-up collapse
    CHG; do NOT re-introduce a strip here — the claude CLI does not strip.
    """
    abs_path = os.path.abspath(project_dir)
    return abs_path.replace("/", "-")


def _resolve_glm(session_id: str, project_dir: str) -> Path:
    encoded = _encode_project_path(project_dir)
    home = Path(os.path.expanduser("~"))
    return home / ".factory" / "sessions" / encoded / f"{session_id}.jsonl"


# Per-wrapper transcript roots — each claude-CLI variant uses its own
# CLAUDE_CONFIG_DIR (``~/.claude-trinity-claude-code/``, ``~/.claude-deepseek/``,
# ``~/.claude-openrouter/``) NOT the bare ``~/.claude/`` root. Source of truth:
# ``providers/<name>.md`` per-wrapper SESSION_DIR snippets.
_CLAUDE_FAMILY_ROOTS = {
    "claude-code": ".claude-trinity-claude-code",
    "deepseek": ".claude-deepseek",
    "openrouter": ".claude-openrouter",
}


def _resolve_claude_family(session_id: str, project_dir: str, provider: str) -> Path:
    """Resolve transcript path for claude-CLI wrapper providers.

    Each wrapper has its own ``CLAUDE_CONFIG_DIR``; the resolver dispatches
    on `provider` to pick the right root. Encoding uses the wrapper's
    `PROJECT_SLUG` convention (keep leading dash — matches claude CLI layout).
    """
    root = _CLAUDE_FAMILY_ROOTS[provider]  # KeyError → caller bug
    slug = _encode_project_slug(project_dir)
    home = Path(os.path.expanduser("~"))
    return home / root / "projects" / slug / f"{session_id}.jsonl"


def _codex_root() -> Path:
    """Codex transcript root. Honors `$CODEX_HOME` (codex CLI's documented
    override); falls back to `~/.codex/` when unset/empty. Per codex-bot R5
    P2 finding 3214554262 — operators with non-default CODEX_HOME would hit
    "transcript file not found" even with a valid pointer.
    """
    env = os.environ.get("CODEX_HOME") or ""
    if env.strip():
        return Path(env).expanduser()
    return Path(os.path.expanduser("~")) / ".codex"


def _find_codex_transcript(
    session_id: str,
    search_root: Path,
    relative_pattern: str,
) -> Path | None:
    """Return the unique codex transcript matching a relative glob, if any.

    Codex on-disk filenames are `rollout-<ISO-ts>-<session_id>.jsonl`.
    The caller's pattern must include `*-<session_id>.jsonl` so the file glob
    requires a dash immediately before the session_id. Post-filter via
    `.endswith` preserves the exact dash-boundary anchor even if the glob sees
    an unexpected variant. Keep the root as a literal Path so CODEX_HOME/HOME
    values containing glob metacharacters are not reinterpreted as patterns.
    """
    anchor = f"-{session_id}.jsonl"
    matches = sorted(
        p for p in search_root.glob(relative_pattern) if p.name.endswith(anchor)
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        _die_multi_match(session_id)
    return None


def _codex_index_lookup(session_id: str) -> Path | None:
    """Try ~/.codex/session_index.jsonl first.

    Each line is JSON like ``{"id": "...", "thread_name": "...",
    "updated_at": "2026-04-26T03:01:39.838528Z"}``. We extract the date
    components from ``updated_at`` to construct
    ``~/.codex/sessions/<YYYY>/<MM>/<DD>/`` and then glob for
    ``*-<session-id>.jsonl`` within that day directory (codex prepends a
    ``rollout-<timestamp>-`` prefix to the actual filename).

    Robustness: malformed lines are skipped per CHG-3040 AC bullet
    "codex `session_index.jsonl` malformed-line robustness". If no valid
    matching record is found, returns None and the caller falls through
    to the broader glob.
    """
    codex_root = _codex_root()
    index_path = codex_root / "session_index.jsonl"
    if not index_path.is_file():
        return None
    try:
        with open(index_path, "r") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    # Skip malformed lines (per AC robustness bullet).
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("id") != session_id:
                    continue
                updated_at = rec.get("updated_at") or ""
                # Expected ISO-8601: YYYY-MM-DDThh:mm:ss...
                m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T", str(updated_at))
                if not m:
                    continue
                yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
                day_dir = codex_root / "sessions" / yyyy / mm / dd
                match = _find_codex_transcript(
                    session_id,
                    day_dir,
                    f"*-{session_id}.jsonl",
                )
                if match is not None:
                    return match
                # 0 matches in the dated dir — fall through; caller may try
                # the broader glob (covers the "index entry stale" case).
                return None
    except OSError:
        return None
    return None


def _die_multi_match(session_id: str) -> None:
    print(
        f"multiple transcript files matched session_id '{session_id}'",
        file=sys.stderr,
    )
    sys.exit(3)


def _resolve_codex(session_id: str, project_dir: str) -> Path:
    """Resolve codex transcript path; prefer index, fall back to broad glob."""
    indexed = _codex_index_lookup(session_id)
    if indexed is not None:
        return indexed
    codex_root = _codex_root()
    match = _find_codex_transcript(
        session_id,
        codex_root / "sessions",
        f"*/*/*/*-{session_id}.jsonl",
    )
    if match is not None:
        return match
    # No matches — return a synthetic path so the caller's existence check
    # produces the canonical "transcript file not found" message rather than
    # leaking the search glob (per Threat Model: stderr message hygiene).
    return codex_root / "sessions" / f"{session_id}.jsonl"


def _resolve_gemini(session_id: str, project_dir: str) -> Path:
    print(
        "gemini transcript layout not yet supported (TRN-3040)",
        file=sys.stderr,
    )
    sys.exit(3)


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


# Single source of truth for "which providers support session-path" in v1.
# `providers/registry.json` is intentionally unchanged in v1 (per CHG-3040
# Migration §); v2 may unify under a `transcript_path_template` field.


def cmd_session_path(project_dir: str, lookup_key: str) -> int:
    """Resolve `<project>/.claude/trinity.json[<lookup_key>]` to a JSONL path.

    Returns an integer exit code (0/2/3) per the path-only contract. Stdout
    receives exactly one line (the absolute path) on success; stderr
    receives the structured error message on failure.
    """
    data = _read_pointer(project_dir)
    if data is POINTER_MISSING:
        print(f"no session pointer for '{lookup_key}'", file=sys.stderr)
        return 2
    sessions = (data or {}).get("sessions", {}) or {}
    entry = sessions.get(lookup_key)
    if not entry:
        print(f"no session pointer for '{lookup_key}'", file=sys.stderr)
        return 2
    session_id = entry.get("session_id") if isinstance(entry, dict) else None
    if not session_id or not isinstance(session_id, str):
        print(f"no session pointer for '{lookup_key}'", file=sys.stderr)
        return 2

    # Path-traversal defense: validate session_id BEFORE any path construction.
    # `_is_valid_session_id` enforces both the regex AND the explicit `..`
    # substring guard (regex character class allows `.` so `..` would slip
    # through without the guard).
    if not _is_valid_session_id(session_id):
        # Do not echo the malformed value (Threat Model: prevent log-injection).
        print("invalid session_id format", file=sys.stderr)
        return 3

    # Provider name is the lookup_key prefix before any colon.
    provider = lookup_key.split(":", 1)[0]

    try:
        # Droid-family providers (~/.factory/sessions/<encoded-path>/<sid>.jsonl).
        # `glm` and `minimax` both use the droid CLI session store; layout is
        # identical so they share `_resolve_glm`. Source: `providers/glm.md` +
        # `providers/minimax.md` (same `droid exec` flow + same SESSION_DIR
        # convention) + `providers/registry.json` lists both with `cli: droid ...`.
        if provider in {"glm", "minimax"}:
            resolved = _resolve_glm(session_id, project_dir)
        elif provider == "codex":
            resolved = _resolve_codex(session_id, project_dir)
        elif provider in _CLAUDE_FAMILY_ROOTS:
            resolved = _resolve_claude_family(session_id, project_dir, provider)
        elif provider == "gemini":
            resolved = _resolve_gemini(session_id, project_dir)
        else:
            print(
                f"provider '{provider}' not supported by session-path resolver",
                file=sys.stderr,
            )
            return 3
    except SystemExit as exc:
        # Resolvers (gemini stub, codex multi-match) may sys.exit directly;
        # propagate the integer code unchanged.
        code = exc.code if isinstance(exc.code, int) else 3
        return code

    resolved_path = Path(resolved)
    if not resolved_path.is_file():
        print(
            f"transcript file not found at '{resolved_path}'",
            file=sys.stderr,
        )
        return 3

    print(str(resolved_path))
    return 0


def _print_usage() -> None:
    print(
        "session_path.py <project_dir> <provider>[:<instance>]",
        file=sys.stderr,
    )


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        _print_usage()
        return 1
    project_dir, lookup_key = argv
    return cmd_session_path(project_dir, lookup_key)


if __name__ == "__main__":
    sys.exit(main())

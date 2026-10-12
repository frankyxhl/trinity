"""Tree reader and printer.

One line per node, from the journal only (VIEW-001). A done node shows the done
glyph, the new-session mark, the short session id, wall time, tokens, exit class
and output kind. Children are drawn indented under their parent.
"""

from __future__ import annotations

from . import journal

_GLYPHS = {"done": "✓", "running": "●", "failed": "!", "interrupted": "!"}
# LED-017: a node whose session is unknown has no short id; the field shows this.
UNKNOWN_SHORT_ID = "?"


def render(root: str, run_id: str) -> list[str]:
    records = journal.read(root)
    nodes = [r for r in records if r.get("kind") == "node" and r.get("run") == run_id]
    states: dict[str, list[dict]] = {}
    for record in records:
        if record.get("kind") == "state" and record.get("run") == run_id:
            states.setdefault(record.get("node"), []).append(record)
    sessions: dict[str, object] = {}
    for record in records:
        if record.get("kind") == "session" and record.get("run") == run_id:
            sessions[record.get("node")] = record.get("id")
    return [
        _line(node, states.get(node.get("node"), []), sessions, level)
        for node, level in _ordered(nodes)
    ]


def _effective_session_id(node: dict, sessions: dict) -> object:
    node_id = node.get("node")
    if node_id in sessions:
        return sessions[node_id]
    return (node.get("session") or {}).get("id")


def _ordered(nodes: list[dict]) -> list[tuple[dict, int]]:
    ordered: list[tuple[dict, int]] = []

    def walk(node: dict, level: int) -> None:
        ordered.append((node, level))
        for other in nodes:
            if other.get("parent") == node.get("node"):
                walk(other, level + 1)

    for node in nodes:
        if node.get("parent") is None:
            walk(node, 0)
    seen = {node.get("node") for node, _ in ordered}
    for node in nodes:
        if node.get("node") not in seen:
            ordered.append((node, 0))
    return ordered


def _line(node: dict, state_rows: list[dict], sessions: dict, level: int) -> str:
    end = state_rows[-1] if state_rows else {}
    glyph = _GLYPHS.get(end.get("state"), "?")
    session = node.get("session") or {}
    mark = "新" if session.get("mode") == "new" else "续"
    session_id = _effective_session_id(node, sessions)
    short_id = (
        session_id[:8]
        if isinstance(session_id, str) and session_id
        else UNKNOWN_SHORT_ID
    )
    usage = end.get("usage") or {}
    tokens = usage.get("tokens")
    wall = end.get("wall_s")
    fields = [
        glyph,
        str(node.get("step", "")),
        str(node.get("profile") or ""),
        str(node.get("model") or ""),
        mark,
        short_id,
        f"{wall}s",
        str(tokens),
        str(end.get("exit_class") or ""),
        str(end.get("output_kind") or ""),
    ]
    prefix = ("  " * level) + ("└ " if level else "")
    return prefix + " ".join(fields)

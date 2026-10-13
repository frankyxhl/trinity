"""Tree reader and printer.

One line per node, from the journal only (VIEW-001). A done node shows the done
glyph, the new-session mark, the short session id, wall time, tokens, exit class
and output kind. Children are drawn indented under their parent.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from . import claude_code, journal

_GLYPHS = {
    "done": "✓",
    "running": "●",
    "stuck": "!",
    "failed": "!",
    "interrupted": "!",
}
# LED-017: a node whose session is unknown has no short id; the field shows this.
UNKNOWN_SHORT_ID = "?"
# LED-017: a session line after a final session_unknown is a defect; the node
# line carries this marker plus the offending journal line numbers.
SESSION_DEFECT_MARKER = "!session-override"


def _read_lines(root: str) -> list[tuple[int, dict]]:
    path = journal.journal_path(root)
    if not path.exists():
        return []
    records: list[tuple[int, dict]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append((number, record))
    return records


def render(root: str, run_id: str) -> list[str]:
    records = _read_lines(root)
    values = [record for _number, record in records]
    nodes = [
        r for _n, r in records if r.get("kind") == "node" and r.get("run") == run_id
    ]
    states: dict[str, list[dict]] = {}
    for _n, record in records:
        if record.get("kind") == "state" and record.get("run") == run_id:
            states.setdefault(record.get("node"), []).append(record)
    unknown: set[str] = set()
    sessions: dict[str, object] = {}
    defects: dict[str, list[int]] = {}
    for number, record in records:
        if record.get("kind") != "session" or record.get("run") != run_id:
            continue
        node_id = record.get("node")
        if node_id in unknown:
            defects.setdefault(node_id, []).append(number)
            continue
        if record.get("id") is None:
            unknown.add(node_id)
        sessions[node_id] = record.get("id")
    now = None
    if any(
        (states.get(node.get("node")) or [{}])[-1].get("state") == "running"
        for node in nodes
    ):
        now = _core_now()
    return [
        _line(
            node,
            states.get(node.get("node"), []),
            sessions,
            defects,
            level,
            derive_state(values, node.get("node"), now=now),
        )
        for node, level in _ordered(nodes)
    ]


def _parse_timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("malformed core clock: timestamp is not text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("malformed core clock: invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("malformed core clock: timezone is required")
    return parsed


def _core_now() -> datetime:
    return _parse_timestamp(journal.utc_now())


def derive_state(records: list[dict], node_id: str, *, now=None) -> dict:
    """Derive a live node's running/stuck state from its latest stdout evidence."""
    node = next(
        (
            record
            for record in reversed(records)
            if record.get("kind") == "node" and record.get("node") == node_id
        ),
        None,
    )
    if node is None:
        return {"state": "unknown", "age_s": None}
    states = [
        record
        for record in records
        if record.get("kind") == "state" and record.get("node") == node_id
    ]
    latest_state = states[-1].get("state") if states else "unknown"
    if latest_state in {"done", "failed", "interrupted"}:
        return {"state": latest_state, "age_s": None}
    if latest_state != "running":
        return {"state": latest_state, "age_s": None}

    current = _core_now() if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("malformed core clock: current time must be timezone-aware")
    evidence = [
        record
        for record in records
        if record.get("kind") == "heartbeat"
        and record.get("node") == node_id
        and record.get("source") == "stdout"
    ]
    start = (
        evidence[-1]
        if evidence
        else next(
            (record for record in reversed(states) if record.get("state") == "running"),
            node,
        )
    )
    age_s = max(0.0, (current - _parse_timestamp(start.get("t"))).total_seconds())
    limit = node.get("stall_limit_s", claude_code.DEFAULT_STALL_LIMIT_S)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or (isinstance(limit, float) and not math.isfinite(limit))
        or limit < 60
    ):
        limit = claude_code.DEFAULT_STALL_LIMIT_S
    return {"state": "stuck" if age_s > limit else "running", "age_s": age_s}


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


def _line(
    node: dict,
    state_rows: list[dict],
    sessions: dict,
    defects: dict,
    level: int,
    derived: dict | None = None,
) -> str:
    end = state_rows[-1] if state_rows else {}
    state = derived.get("state") if derived else end.get("state")
    glyph = _GLYPHS.get(state, "?")
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
    line = prefix + " ".join(fields)
    numbers = defects.get(node.get("node"))
    if numbers:
        marker = SESSION_DEFECT_MARKER + "@" + ",".join(f"L{n}" for n in numbers)
        line = line + " " + marker
    return line

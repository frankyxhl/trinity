"""ACC-001: one profile, new session, one child, journal and CLI tree (WO-004 RED).

One test per Then line of docs/acceptance/ACCEPTANCE.md ACC-001, so a failure
names the broken line. Product code does not exist yet: nothing here imports a
product module (collection can never fail with ImportError); the path is driven
through the CLI as a subprocess, so a missing CLI or subcommand surfaces as a
failed assertion.

Chosen spellings (contract leaves these open; used consistently here and to be
kept by the implementation):

- CLI: ``python3 scripts/trinity.py`` run from the repository root.
  Dispatch subcommand ``call``; view subcommand ``tree <run>``.
- State root (seam S-1): environment ``TRINITY_ROOT``; the journal is
  ``$TRINITY_ROOT/journal.jsonl``, the error log ``$TRINITY_ROOT/error.log``.
- Profile set: JSON ``{"profiles": [...]}`` passed with ``--profiles <file>``.
  A profile: ``name``, ``adapter``, ``provider``, ``billing``, ``model``,
  ``credential_source`` (``{"env": "<NAME>"}``), ``quota_source``
  (``{"kind": "vendor_cli", "command": "<path>"}``), ``freshness_limit``,
  ``transcript_retention``, ``enabled``.
- Quota stub (DBL-Q): the ``command`` prints one JSON line
  ``{"used_pct": 20, "read_at": "<iso8601 UTC>"}`` and exits 0.
- ``call`` flags: ``--profiles --profile --step --session --prompt --cwd
  --allow-nesting-max-depth`` (run/parent/depth default from the guard env).
  It prints the result object as one JSON line on stdout.
- Guard env (DSP-004): ``TRINITY_GUARD`` holds JSON
  ``{"run","node","depth","max_depth","journal_root"}``; ``TRINITY_DISABLE_DISPATCH=1``
  when nesting is off. A nested ``call`` reads run/parent/depth from it.
- Journal records follow spec-ledger: kinds ``run``, ``node``, ``state``,
  ``check``, ``heartbeat``, ``edge``; node fields ``run node parent step round
  depth harness profile profile_reason session{id,mode,source}``; a ``run``
  record carries ``event`` in ``start|end``; a ``state`` record carries
  ``state``, ``exit_class``, ``output_kind``, ``usage`` and ``wall_s``
  (whole seconds). Adapter-set exit class ``ok``; output_kind enum
  ``commit|verdict|none``.
- Tree: one line per node; ``✓`` = done, ``新`` = new session, short id = first
  8 characters of the session id; children indented under the parent; wall time
  printed as ``<wall_s>s``.

The claude-code adapter pre-assigns the session id (ADP-016), so DBL-H receives
``--session-id <uuid>`` and reports it back; the journal records the assigned id.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "scripts" / "trinity.py"
PROFILE = "pilot"
HEARTBEAT_INTERVAL_S = 15  # DSP-009 default; nodes here run under it
POLL_INTERVAL_S = HEARTBEAT_INTERVAL_S

MARK_PROMPT_ROOT = "FIXTURE-PROMPT-ROOT-MARKER"
MARK_PROMPT_CHILD = "FIXTURE-PROMPT-CHILD-MARKER"
MARK_THINKING = "FIXTURE-THINKING-MARKER"
MARK_TOOL = "FIXTURE-TOOL-MARKER"
MARK_OUTPUT = "FIXTURE-OUTPUT-MARKER"
FAKE_CRED = "test-cred-" + "0" * 32
TOKENS = {0: 48000, 1: 12000}
USAGE = {0: (40000, 8000), 1: (10000, 2000)}

_CACHE: dict = {}


def _run_path() -> SimpleNamespace:
    if "fm" not in _CACHE:
        try:
            _CACHE["fm"] = _build_and_run()
        except Exception as exc:  # pragma: no cover - reported as a failed Then
            _CACHE["fm"] = SimpleNamespace(error=f"{type(exc).__name__}: {exc}")
    return _CACHE["fm"]


def _build_and_run() -> SimpleNamespace:
    root = Path(tempfile.mkdtemp(prefix="wo004-acc001-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    bin_dir = root / "bin"
    capture = root / "capture"
    transcripts = root / "transcripts"
    state = root / "state"
    work = root / "work"
    for d in (bin_dir, capture, transcripts, state, work):
        d.mkdir(parents=True)
    capture_file = capture / "harness.jsonl"

    stub = bin_dir / "quota_stub"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, datetime
            print(json.dumps({{
                "used_pct": 20,
                "read_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }}))
            """
        )
    )
    stub.chmod(0o755)

    profiles = root / "profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "name": PROFILE,
                        "adapter": "claude-code",
                        "provider": "claude-code",
                        "billing": "subscription",
                        "model": "pilot-model",
                        "credential_source": {"env": "TRINITY_PILOT_CRED"},
                        "quota_source": {
                            "kind": "vendor_cli",
                            "command": str(stub),
                        },
                        "freshness_limit": 300,
                        "transcript_retention": "30 days",
                        "enabled": True,
                    }
                ]
            }
        )
    )

    child_prompt = f"child task {MARK_PROMPT_CHILD}"
    harness = bin_dir / "claude"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, os, subprocess, sys, time
            from pathlib import Path

            CAPTURE = Path({str(capture_file)!r})
            TRANSCRIPTS = Path({str(transcripts)!r})
            CLI = {str(CLI)!r}
            PY = {sys.executable!r}
            REPO = {str(REPO)!r}
            PROFILES = {str(profiles)!r}
            CHILD_PROMPT = {child_prompt!r}
            MARK_THINKING = {MARK_THINKING!r}
            MARK_TOOL = {MARK_TOOL!r}
            MARK_OUTPUT = {MARK_OUTPUT!r}
            USAGE = {USAGE!r}

            argv = sys.argv[1:]
            guard = {{}}
            raw = os.environ.get("TRINITY_GUARD")
            if raw:
                try:
                    guard = json.loads(raw)
                except ValueError:
                    guard = {{}}
            depth = int(guard.get("depth", 0))

            session_id = None
            prompt = ""
            for i, a in enumerate(argv):
                if a == "--session-id" and i + 1 < len(argv):
                    session_id = argv[i + 1]
                if a == "-p" and i + 1 < len(argv):
                    prompt = argv[i + 1]
            if session_id is None:
                session_id = guard.get("node") or "unknown"

            with CAPTURE.open("a") as fh:
                fh.write(json.dumps({{
                    "argv": argv,
                    "env_names": sorted(os.environ.keys()),
                    "cwd": os.getcwd(),
                    "depth": depth,
                    "session_id": session_id,
                }}) + "\\n")

            TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
            events = [
                {{"type": "user", "message": {{"role": "user", "content": prompt}}}},
                {{"type": "assistant", "message": {{"role": "assistant", "content": [
                    {{"type": "thinking", "thinking": MARK_THINKING}}]}}}},
                {{"type": "assistant", "message": {{"role": "assistant", "content": [
                    {{"type": "tool_use", "name": "Bash", "input": {{"command": MARK_TOOL}}}}]}}}},
                {{"type": "assistant", "message": {{"role": "assistant", "content": [
                    {{"type": "text", "text": MARK_OUTPUT}}]}}}},
            ]
            (TRANSCRIPTS / (session_id + ".jsonl")).write_text(
                "\\n".join(json.dumps(e) for e in events) + "\\n"
            )

            if depth == 0:
                subprocess.run(
                    [PY, CLI, "call", "--profiles", PROFILES, "--profile", {PROFILE!r},
                     "--step", "child", "--session", "new", "--prompt", CHILD_PROMPT],
                    cwd=REPO, env=os.environ.copy(), capture_output=True,
                )

            time.sleep(1.05)
            tin, tout = USAGE[1 if depth else 0]
            sys.stdout.write(json.dumps({{
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": session_id,
                "result": MARK_OUTPUT,
                "usage": {{"input_tokens": tin, "output_tokens": tout,
                           "tokens": tin + tout}},
            }}) + "\\n")
            sys.stdout.flush()
            """
        )
    )
    harness.chmod(0o755)

    env = dict(os.environ)
    env.update(
        {
            "PATH": os.pathsep.join([str(bin_dir), env.get("PATH", "/usr/bin:/bin")]),
            "HOME": str(root),
            "TRINITY_ROOT": str(state),
            "TRINITY_PILOT_CRED": FAKE_CRED,
            "PYTHONPATH": os.pathsep.join([str(REPO), env.get("PYTHONPATH", "")]),
        }
    )

    root_prompt = f"root task {MARK_PROMPT_ROOT}"
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "call",
            "--profiles",
            str(profiles),
            "--profile",
            PROFILE,
            "--step",
            "root",
            "--session",
            "new",
            "--prompt",
            root_prompt,
            "--cwd",
            str(work),
            "--allow-nesting-max-depth",
            "1",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    run_id = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and result.get("run"):
            run_id = result["run"]
            break

    tree_proc = subprocess.run(
        [sys.executable, str(CLI), "tree", run_id or "none"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    journal_paths = sorted(state.rglob("journal*.jsonl"))
    records = []
    parse_errors = []
    for path in journal_paths:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                parse_errors.append(f"{path.name}:{number}")
    journal_bytes = b"".join(p.read_bytes() for p in journal_paths)

    captures = []
    if capture_file.exists():
        for line in capture_file.read_text().splitlines():
            if line.strip():
                captures.append(json.loads(line))

    return SimpleNamespace(
        error=None,
        root=root,
        env=env,
        call_proc=proc,
        tree_proc=tree_proc,
        run_id=run_id,
        journal=records,
        journal_bytes=journal_bytes,
        journal_parse_errors=parse_errors,
        tree_lines=[line for line in tree_proc.stdout.splitlines() if line.strip()],
        captures=captures,
    )


def _ready(fm) -> None:
    assert fm.error is None, f"setup: {fm.error}"
    assert fm.run_id is not None, (
        f"the root call produced no run id (rc={fm.call_proc.returncode}, "
        f"stderr={fm.call_proc.stderr!r})"
    )
    kinds = [r.get("kind") for r in fm.journal]
    assert len(_nodes(fm)) == 2, f"expected two nodes; journal kinds={kinds}"


def _records(fm, kind: str) -> list[dict]:
    return [r for r in fm.journal if r.get("kind") == kind]


def _nodes(fm) -> list[dict]:
    return _records(fm, "node")


def _node_by_step(fm, step: str) -> dict:
    for node in _nodes(fm):
        if node.get("step") == step:
            return node
    raise AssertionError(f"no node with step {step!r}; nodes={_nodes(fm)}")


def _states(fm, node_id: str) -> list[dict]:
    return [r for r in _records(fm, "state") if r.get("node") == node_id]


def _heartbeats(fm, node_id: str) -> list[dict]:
    return [r for r in _records(fm, "heartbeat") if r.get("node") == node_id]


def _checks(fm, node_id: str, check: str) -> list[dict]:
    return [
        r
        for r in _records(fm, "check")
        if r.get("node") == node_id and r.get("check") == check
    ]


def _tree_line(fm, step: str) -> str:
    for line in fm.tree_lines:
        if step in line:
            return line
    raise AssertionError(f"no tree line for step {step!r}; tree={fm.tree_lines!r}")


def _indent_width(line: str) -> int:
    stripped = line.lstrip(" \t")
    indents = "│├└┌─"
    stripped = stripped.lstrip(indents)
    return len(line) - len(stripped)


# --- Then: one run start and one run end -------------------------------------


def test_journal_holds_one_run_start_and_one_run_end():
    fm = _run_path()
    _ready(fm)
    runs = [r for r in _records(fm, "run") if r.get("run") == fm.run_id]
    starts = [r for r in runs if r.get("event") == "start"]
    ends = [r for r in runs if r.get("event") == "end"]
    assert fm.run_id is not None, "the call printed no run id"
    assert len(starts) == 1, f"expected 1 run start, got {runs}"
    assert len(ends) == 1, f"expected 1 run end, got {runs}"


# --- Then: two nodes; root depth 0, child depth 1, one parent edge -----------


def test_two_nodes_root_depth_0_child_depth_1_with_one_parent_edge():
    fm = _run_path()
    _ready(fm)
    root_node = _node_by_step(fm, "root")
    child_node = _node_by_step(fm, "child")
    assert len(_nodes(fm)) == 2, _nodes(fm)
    assert root_node.get("depth") == 0, root_node
    assert child_node.get("depth") == 1, child_node
    assert root_node.get("parent") is None, root_node
    assert child_node.get("parent") == root_node.get("node"), child_node
    parents = [n for n in _nodes(fm) if n.get("parent") == root_node.get("node")]
    assert len(parents) == 1, f"expected exactly one child of root: {parents}"
    parent_edges = [
        e
        for e in _records(fm, "edge")
        if (e.get("kind") or e.get("type")) == "parent"
    ]
    assert parent_edges == [], "the parent edge must live in the node record (GRF-003)"


# --- Then: a quota check record before each node -----------------------------


def test_quota_check_record_before_each_node():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        checks = _checks(fm, node["node"], "quota")
        assert checks, f"no quota check for {node['step']!r}"
        assert checks[0].get("result") == "ok", checks[0]
        assert checks[0].get("source_kind"), checks[0]
        assert checks[0].get("read_at"), checks[0]
        check_index = fm.journal.index(checks[0])
        running = [
            i
            for i, r in enumerate(fm.journal)
            if r.get("kind") == "state"
            and r.get("node") == node["node"]
            and r.get("state") == "running"
        ]
        assert running, f"node {node['step']!r} never entered running"
        assert check_index < running[0], (
            f"quota check for {node['step']!r} is not before it runs"
        )


# --- Then: at least one heartbeat row per node longer than one poll ----------


def test_heartbeat_rows_per_case_rule():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        states = _states(fm, node["node"])
        wall = next(
            (s.get("wall_s") for s in states if s.get("wall_s") is not None), None
        )
        assert wall is not None, f"node {node['step']!r} has no wall_s"
        rows = _heartbeats(fm, node["node"])
        if wall > POLL_INTERVAL_S:
            assert len(rows) >= 1, (
                f"node {node['step']!r} ran {wall}s with no heartbeat row"
            )
        for row in rows:
            assert row.get("t"), row
            assert row.get("source"), row


# --- Then: state lines queued -> running -> done -----------------------------


def test_state_lines_queued_running_done():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        sequence = [s.get("state") for s in _states(fm, node["node"])]
        assert sequence == ["queued", "running", "done"], (
            f"node {node['step']!r} states: {sequence}"
        )


# --- Then: exit_class ok ------------------------------------------------------


def test_exit_class_ok_on_every_node():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        end = _states(fm, node["node"])[-1]
        assert end.get("exit_class") == "ok", end


# --- Then: profile_reason recorded -------------------------------------------


def test_profile_reason_recorded_for_every_node():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        assert node.get("profile") == PROFILE, node
        assert node.get("profile_reason") == "named", node


# --- Then: tree shows two lines with correct indentation ---------------------


def test_tree_prints_two_lines_with_child_indented():
    fm = _run_path()
    _ready(fm)
    assert len(fm.tree_lines) == 2, fm.tree_lines
    root_line = _tree_line(fm, "root")
    child_line = _tree_line(fm, "child")
    assert _indent_width(root_line) == 0, root_line
    assert _indent_width(child_line) > 0, child_line


# --- Then: 新 session mark with a short id for both --------------------------


def test_tree_marks_new_session_and_short_id():
    fm = _run_path()
    _ready(fm)
    for step in ("root", "child"):
        node = _node_by_step(fm, step)
        session = node.get("session") or {}
        assert session.get("mode") == "new", node
        assert session.get("id"), node
        line = _tree_line(fm, step)
        assert "新" in line, line
        assert session["id"][:8] in line, line


# --- Then: done glyph, wall time, tokens, exit class and output kind ---------


def test_tree_shows_glyph_wall_tokens_exit_class_and_output_kind():
    fm = _run_path()
    _ready(fm)
    for step in ("root", "child"):
        node = _node_by_step(fm, step)
        end = _states(fm, node["node"])[-1]
        line = _tree_line(fm, step)
        assert "✓" in line, line
        assert end.get("exit_class") == "ok", end
        assert "ok" in line, line
        assert end.get("output_kind") in {"commit", "verdict", "none"}, end
        assert end.get("output_kind") in line, line
        assert f"{end.get('wall_s')}s" in line, line


# --- Then: every number shown equals the journal's ---------------------------


def test_tree_numbers_equal_the_journal():
    fm = _run_path()
    _ready(fm)
    for step, depth in (("root", 0), ("child", 1)):
        node = _node_by_step(fm, step)
        end = _states(fm, node["node"])[-1]
        usage = end.get("usage") or {}
        tokens = usage.get("tokens")
        wall = end.get("wall_s")
        assert tokens == TOKENS[depth], end
        assert isinstance(wall, int) and wall >= 0, end
        line = _tree_line(fm, step)
        assert str(tokens) in line, f"tokens {tokens} not in {line!r}"
        assert f"{wall}s" in line, f"wall {wall}s not in {line!r}"


# --- Then: journal contains none of the fixture's text -----------------------


def test_journal_contains_no_fixture_text():
    fm = _run_path()
    _ready(fm)
    assert not fm.journal_parse_errors, fm.journal_parse_errors
    text = fm.journal_bytes.decode("utf-8", errors="replace")
    for marker in (
        MARK_PROMPT_ROOT,
        MARK_PROMPT_CHILD,
        MARK_THINKING,
        MARK_TOOL,
        MARK_OUTPUT,
    ):
        assert marker not in text, f"fixture text {marker!r} reached the journal"

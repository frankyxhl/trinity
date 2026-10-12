"""First end-to-end path: one profile, a new session, one child, journal and tree.

One test per Then line of the acceptance case for the first path, so a failure
names the broken line. Product code is driven through the CLI as a subprocess,
so a missing CLI or subcommand surfaces as a failed assertion.

Spellings the contract leaves open (kept by the implementation):

- CLI: ``bin/trinity`` reached from the repository root; dispatch subcommand
  ``call``; view subcommand ``tree <run>``.
- State root: environment ``TRINITY_ROOT``; the journal is
  ``$TRINITY_ROOT/journal.jsonl``, the error log ``$TRINITY_ROOT/error.log``.
- Profile set: JSON ``{"profiles": [...]}`` passed with ``--profiles <file>``.
  A profile: ``name``, ``adapter``, ``provider``, ``billing``, ``model``,
  ``credential_source`` (``{"wrapper": "<command name>"}``), ``quota_source``
  (``{"kind": "vendor_cli", "command": "<path>"}``), ``freshness_limit``,
  ``transcript_retention``, ``enabled``.
- Quota stub: the ``command`` prints one JSON line
  ``{"used_pct": 20, "read_at": "<iso8601 UTC>"}`` and exits 0.
- ``call`` flags: ``--profiles --profile --step --session --prompt --cwd
  --allow-nesting-max-depth``.
- Guard env: ``TRINITY_GUARD`` holds JSON
  ``{"run","node","depth","max_depth","journal_root"}``.
- Journal records follow the ledger spec: kinds ``run``, ``node``, ``state``,
  ``check``, ``heartbeat``, ``edge``; a ``state`` record carries ``state``,
  ``exit_class``, ``output_kind`` and ``usage``; a ``heartbeat`` record carries
  the observed ``source``.
- Tree: one line per node; ``✓`` = done, ``新`` = new session, short id = first
  8 characters of the session id; children indented under the parent; wall time
  printed as ``<wall_s>s``.

The claude-code adapter pre-assigns the session id, so the harness receives
``--session-id <uuid>`` and reports it back; the journal records the assigned id.
"""

from __future__ import annotations

import atexit
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "bin" / "trinity"
PROFILE = "pilot"
MODEL = "pilot-model"
# The profile names its credential wrapper; the adapter runs that command on
# PATH in place of `claude`. The fixture's fake harness stands in for it.
WRAPPER = "claude-code"
# A node whose session is unknown shows this in the short-id field of the tree.
UNKNOWN_SHORT_ID = "?"

HEARTBEAT_POLL_S = 1.0
DEFAULT_POLL_S = 15.0
POLL_SLEEP_S = 2.2

MARK_PROMPT_ROOT = "FIXTURE-PROMPT-ROOT-MARKER"
MARK_PROMPT_CHILD = "FIXTURE-PROMPT-CHILD-MARKER"
MARK_THINKING = "FIXTURE-THINKING-MARKER"
MARK_TOOL = "FIXTURE-TOOL-MARKER"
MARK_OUTPUT = "FIXTURE-OUTPUT-MARKER"
FAKE_CRED = "test-cred-" + "0" * 32
CRED_NAME = "TRINITY_PILOT_CRED"
DECOY_NAME = "TRINITY_DECOY_TOKEN"
DECOY_VALUE = "decoy-" + "1" * 32
TOKENS = {0: 48000, 1: 12000}
USAGE = {0: (40000, 8000), 1: (10000, 2000)}
WHITELIST = {
    "input_tokens",
    "output_tokens",
    "tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
}
ALLOWED_ENV = {
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LC_NUMERIC",
    "LC_TIME",
    "LC_COLLATE",
    "LC_MONETARY",
    "TRINITY_GUARD",
}
# Injected by CoreFoundation into every Python process on macOS; not passed by
# the adapter, so it is tolerated in this otherwise strict allow-list check.
PLATFORM_ENV = {"__CF_USER_TEXT_ENCODING"}

_CACHE: dict = {}


def _iso(offset_s: float = 0.0) -> str:
    """Every clock value comes from here plus a duration (§0.6: durations only)."""
    moment = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=offset_s)
    return moment.isoformat()


def _secret_marker() -> str:
    """A secret-shaped value built at runtime from parts, never a literal."""
    return "-".join(["sk", "A" * 24])


def _run_path(mode: str = "ok") -> SimpleNamespace:
    if mode not in _CACHE:
        try:
            _CACHE[mode] = _build_and_run(mode)
        except Exception as exc:  # pragma: no cover - reported as a failed Then
            _CACHE[mode] = SimpleNamespace(error=f"{type(exc).__name__}: {exc}")
    return _CACHE[mode]


def _build_and_run(mode: str) -> SimpleNamespace:
    root = Path(tempfile.mkdtemp(prefix="first-path-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    bin_dir = root / "bin"
    capture = root / "capture"
    transcripts = root / "transcripts"
    state = root / "state"
    work = root / "work"
    for directory in (bin_dir, capture, transcripts, state, work):
        directory.mkdir(parents=True)
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
                        "model": MODEL,
                        "credential_source": {"wrapper": WRAPPER},
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
    mismatch_id = "00000000-0000-4000-8000-000000000000"
    harness = bin_dir / WRAPPER
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, os, subprocess, sys, time
            from pathlib import Path

            CAPTURE = Path({str(capture_file)!r})
            TRANSCRIPTS = Path({str(transcripts)!r})
            CLI = {str(CLI)!r}
            PROFILES = {str(profiles)!r}
            PROFILE = {PROFILE!r}
            CHILD_PROMPT = {child_prompt!r}
            MARK_THINKING = {MARK_THINKING!r}
            MARK_TOOL = {MARK_TOOL!r}
            MARK_OUTPUT = {MARK_OUTPUT!r}
            USAGE = {USAGE!r}
            MODE = {mode!r}
            MISMATCH_ID = {mismatch_id!r}
            SLEEP_S = {POLL_SLEEP_S!r}

            argv = sys.argv[1:]
            if "--output-format" not in argv or "json" not in argv:
                sys.stderr.write("harness requires --output-format json\\n")
                sys.exit(2)

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
                    [CLI, "call", "--profiles", PROFILES, "--profile", PROFILE,
                     "--step", "child", "--session", "new", "--prompt", CHILD_PROMPT],
                    env=os.environ.copy(), capture_output=True,
                )

            time.sleep(SLEEP_S)

            if MODE == "error":
                sys.stderr.write("harness failed\\n")
                sys.exit(3)

            reported = MISMATCH_ID if (MODE == "mismatch" and depth == 0) else session_id
            tin, tout = USAGE[1 if depth else 0]
            sys.stdout.write(json.dumps({{
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": reported,
                "result": MARK_OUTPUT,
                "usage": {{"input_tokens": tin, "output_tokens": tout,
                           "tokens": tin + tout, "note": MARK_OUTPUT}},
            }}) + "\\n")
            sys.stdout.flush()
            """
        )
    )
    harness.chmod(0o755)

    env = _call_env(bin_dir, root, state)
    refuse = subprocess.run(
        [str(harness), "-p", "x", "--session-id", "s"],
        cwd=REPO,
        env={**env, "TRINITY_GUARD": json.dumps({"depth": 99})},
        capture_output=True,
        text=True,
        timeout=30,
    )

    root_prompt = f"root task {MARK_PROMPT_ROOT}"
    proc = subprocess.run(
        [
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
        [str(CLI), "tree", run_id or "none"],
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

    error_log = state / "error.log"
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
        refuse_rc=refuse.returncode,
        error_text=error_log.read_text() if error_log.exists() else "",
    )


def _call_env(bin_dir: Path, home: Path, state: Path) -> dict:
    venv_bin = str(Path(sys.executable).resolve().parent)
    env = dict(os.environ)
    env.pop("TRINITY_GUARD", None)
    env.update(
        {
            "PATH": os.pathsep.join([str(bin_dir), venv_bin, "/usr/bin", "/bin"]),
            "HOME": str(home),
            "TRINITY_ROOT": str(state),
            CRED_NAME: FAKE_CRED,
            DECOY_NAME: DECOY_VALUE,
            "TRINITY_HEARTBEAT_POLL_S": str(HEARTBEAT_POLL_S),
        }
    )
    return env


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
    parent_edges = [e for e in _records(fm, "edge") if e.get("type") == "parent"]
    assert parent_edges == [], "the parent edge is the node's own parent field"


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
        interval = HEARTBEAT_POLL_S if node["step"] == "root" else DEFAULT_POLL_S
        rows = _heartbeats(fm, node["node"])
        if wall > interval:
            assert len(rows) >= 1, (
                f"node {node['step']!r} ran {wall}s past a {interval}s poll "
                "with no heartbeat row"
            )
        for row in rows:
            assert row.get("t"), row
            assert row.get("source") == "process_alive", row


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


def _expected_line(node: dict, end: dict, level: int) -> str:
    session = node.get("session") or {}
    mark = "新" if session.get("mode") == "new" else "续"
    short_id = (session.get("id") or "")[:8]
    prefix = ("  " * level) + ("└ " if level else "")
    fields = [
        "✓",
        str(node["step"]),
        str(node["profile"] or ""),
        str(node["model"] or ""),
        mark,
        short_id,
        f"{end['wall_s']}s",
        str((end.get("usage") or {}).get("tokens")),
        str(end["exit_class"]),
        str(end["output_kind"]),
    ]
    return prefix + " ".join(fields)


def test_tree_lines_are_exact_including_short_id_and_numbers():
    fm = _run_path()
    _ready(fm)
    root_node = _node_by_step(fm, "root")
    child_node = _node_by_step(fm, "child")
    root_end = _states(fm, root_node["node"])[-1]
    child_end = _states(fm, child_node["node"])[-1]
    expected = [
        _expected_line(root_node, root_end, 0),
        _expected_line(child_node, child_end, 1),
    ]
    assert fm.tree_lines == expected, (fm.tree_lines, expected)
    for node in (root_node, child_node):
        short_id = (node["session"]["id"])[:8]
        assert len(short_id) == 8
        assert node["session"]["id"] not in "\n".join(fm.tree_lines)


def test_tree_marks_new_session_and_short_id():
    fm = _run_path()
    _ready(fm)
    for step in ("root", "child"):
        node = _node_by_step(fm, step)
        session = node.get("session") or {}
        assert session.get("mode") == "new", node
        assert session.get("id"), node
        line = next(line for line in fm.tree_lines if step in line)
        expected = _expected_line(
            node, _states(fm, node["node"])[-1], 0 if step == "root" else 1
        )
        assert line == expected, (line, expected)
        assert "新" in line, line
        assert "续" not in line, line


def test_tree_shows_glyph_wall_tokens_exit_class_and_output_kind():
    fm = _run_path()
    _ready(fm)
    for step in ("root", "child"):
        node = _node_by_step(fm, step)
        end = _states(fm, node["node"])[-1]
        line = next(line for line in fm.tree_lines if step in line)
        assert line == _expected_line(node, end, 0 if step == "root" else 1)
        assert "✓" in line, line
        assert end.get("exit_class") == "ok", end
        assert end.get("output_kind") in {"commit", "verdict", "none"}, end


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
        line = next(line for line in fm.tree_lines if step in line)
        assert str(tokens) in line.split(), f"tokens {tokens} not a field of {line!r}"
        assert f"{wall}s" in line.split(), f"wall {wall}s not a field of {line!r}"


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


def test_journal_usage_holds_only_whitelisted_numbers():
    fm = _run_path()
    _ready(fm)
    for node in _nodes(fm):
        end = _states(fm, node["node"])[-1]
        for key, value in (end.get("usage") or {}).items():
            assert key in WHITELIST, (key, end)
            assert isinstance(value, (int, float)) and not isinstance(value, bool), end


# --- Then: the harness environment is an allow-list (no credentials leaked) --


def test_harness_environment_is_allow_listed():
    fm = _run_path()
    _ready(fm)
    assert len(fm.captures) == 2, fm.captures
    for capture in fm.captures:
        names = set(capture["env_names"])
        assert CRED_NAME not in names, capture
        assert DECOY_NAME not in names, capture
        assert "TRINITY_ROOT" not in names, capture
        assert "PYTHONPATH" not in names, capture
        assert "TRINITY_HEARTBEAT_POLL_S" not in names, capture
        assert all(
            name in ALLOWED_ENV or name.startswith("LC_") or name in PLATFORM_ENV
            for name in names
        ), capture


def test_harness_is_run_with_json_output():
    fm = _run_path()
    _ready(fm)
    assert fm.refuse_rc != 0, (
        "the double must refuse to run without --output-format json"
    )
    assert fm.captures, "the harness was never invoked"
    for capture in fm.captures:
        argv = capture["argv"]
        assert "--output-format" in argv, argv
        assert argv[argv.index("--output-format") + 1] == "json", argv


# --- Then: session id is compared with the assigned id (DSP-020) -------------


def test_session_mismatch_is_not_success():
    fm = _run_path("mismatch")
    _ready(fm)
    root_node = _node_by_step(fm, "root")
    end = _states(fm, root_node["node"])[-1]
    assert end.get("state") == "failed", end
    assert end.get("exit_class") == "harness_error", end
    assert "session_mismatch" in fm.error_text, fm.error_text


def test_error_exit_is_recorded_as_failed():
    fm = _run_path("error")
    _ready(fm)
    root_node = _node_by_step(fm, "root")
    end = _states(fm, root_node["node"])[-1]
    assert end.get("state") == "failed", end
    assert end.get("exit_class") != "ok", end


def test_state_for_exit_class_maps_ok_errors_and_interrupts():
    from scripts.trinity_core.dispatch import state_for_exit_class

    assert state_for_exit_class("ok") == "done"
    for error in ("unknown", "harness_error", "timeout", "check_failed", "auth_error"):
        assert state_for_exit_class(error) == "failed", error
    assert state_for_exit_class("interrupted") == "interrupted"


# --- Then: labels and usage are validated before any append ------------------


def _profiles_file(tmp_path: Path) -> Path:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "name": PROFILE,
                        "adapter": "claude-code",
                        "provider": "claude-code",
                        "billing": "subscription",
                        "model": MODEL,
                        "credential_source": {"wrapper": WRAPPER},
                        "quota_source": {
                            "kind": "vendor_cli",
                            "command": str(tmp_path / "quota_stub"),
                        },
                        "freshness_limit": 300,
                        "transcript_retention": "30 days",
                        "enabled": True,
                    }
                ]
            }
        )
    )
    return path


def test_bad_step_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    monkeypatch.setenv("TRINITY_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    result = core.call(
        {
            "profiles_path": str(_profiles_file(tmp_path)),
            "profile": PROFILE,
            "step": "bad\x01step",
            "session": "new",
            "prompt": {"text": "x"},
            "cwd": str(tmp_path),
            "allow_nesting": False,
        }
    )
    assert result["exit_class"] == "bad_request", result
    assert not (tmp_path / "state" / "journal.jsonl").exists()


def test_quota_missing_or_invalid_value_is_unknown(tmp_path):
    import scripts.trinity_core.quota as quota

    stub = tmp_path / "stub"
    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\nsys.stdout.write(json.dumps({{}}))\n"
    )
    stub.chmod(0o755)
    profile = {
        "quota_source": {"kind": "vendor_cli", "command": str(stub)},
        "freshness_limit": 300,
    }
    assert quota.check(profile)["result"] == "unknown"

    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"sys.stdout.write(json.dumps({{'used_pct': 'many', 'read_at': {_iso()!r}}}))\n"
    )
    stub.chmod(0o755)
    assert quota.check(profile)["result"] == "unknown"


def test_quota_stale_read_is_unknown(tmp_path):
    import scripts.trinity_core.quota as quota

    stub = tmp_path / "stub"
    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"sys.stdout.write(json.dumps({{'used_pct': 20, 'read_at': {_iso(-100000)!r}}}))\n"
    )
    stub.chmod(0o755)
    profile = {
        "quota_source": {"kind": "vendor_cli", "command": str(stub)},
        "freshness_limit": 300,
    }
    result = quota.check(profile)
    assert result["result"] == "unknown", result


def test_quota_unknown_stops_the_node(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    root = tmp_path / "state"
    monkeypatch.setenv("TRINITY_ROOT", str(root))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    profiles = _profiles_file(tmp_path)
    stub = tmp_path / "quota_stub"
    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"sys.stdout.write(json.dumps({{'used_pct': 20, 'read_at': {_iso(-100000)!r}}}))\n"
    )
    stub.chmod(0o755)
    result = core.call(
        {
            "profiles_path": str(profiles),
            "profile": PROFILE,
            "step": "root",
            "session": "new",
            "prompt": {"text": "x"},
            "cwd": str(tmp_path),
            "allow_nesting": {"max_depth": 1},
        }
    )
    assert result["exit_class"] == "check_failed", result
    states = [
        r.get("state") for r in core.journal.read(root) if r.get("kind") == "state"
    ]
    assert states == ["queued", "failed"], states


# --- Then: a timeout or interrupt kills only the groups this call started ----


def _write_sleeper(directory: Path, name: str, pid_file: Path) -> Path:
    path = directory / name
    path.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    path.chmod(0o755)
    return path


def _proc_state(stat_text: str) -> str:
    """The state field of a /proc/<pid>/stat line, after the command name."""
    try:
        after = stat_text.rsplit(")", 1)[1]
    except IndexError:
        return ""
    fields = after.split()
    return fields[0] if fields else ""


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return _proc_state(stat_text) == "Z"


def test_proc_state_reads_the_state_field_after_the_command_name():
    assert _proc_state("123 (a b) c) Z 1 ...") == "Z"
    assert _proc_state("123 (py) S 1") == "S"


def test_harness_timeout_kills_only_its_process_group(tmp_path, monkeypatch):
    import scripts.trinity_core.claude_code as claude_code

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    _write_sleeper(bin_dir, "claude", pid_file)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    )
    outcome = claude_code.run(
        {"model": MODEL, "credential_source": {"wrapper": "claude"}},
        prompt="x",
        cwd=str(tmp_path),
        session_id="s",
        run_id="r",
        node_id="n",
        depth=0,
        max_depth=0,
        root=str(tmp_path),
        heartbeat=lambda source: None,
        poll_s=100.0,
        time_s=1.0,
    )
    assert outcome["exit_class"] == "timeout", outcome
    pid = int(pid_file.read_text())
    for _ in range(50):
        if _gone(pid):
            break
        import time as _time

        _time.sleep(0.1)
    assert _gone(pid), "the harness process outlived its timeout"


def test_harness_interrupt_kills_only_its_process_group(tmp_path, monkeypatch):
    import scripts.trinity_core.claude_code as claude_code

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    _write_sleeper(bin_dir, "claude", pid_file)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    )

    real_communicate = subprocess.Popen.communicate
    state = {"raised": False}

    def interrupting(self, *args, **kwargs):
        if not state["raised"] and kwargs.get("timeout") is None:
            state["raised"] = True
            import time as _time

            _time.sleep(0.5)
            raise KeyboardInterrupt
        return real_communicate(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupting)
    outcome = claude_code.run(
        {"model": MODEL, "credential_source": {"wrapper": "claude"}},
        prompt="x",
        cwd=str(tmp_path),
        session_id="s",
        run_id="r",
        node_id="n",
        depth=0,
        max_depth=0,
        root=str(tmp_path),
        heartbeat=lambda source: None,
        poll_s=100.0,
    )
    assert outcome["exit_class"] == "interrupted", outcome
    assert state["raised"] is True
    pid = int(pid_file.read_text())
    for _ in range(50):
        if _gone(pid):
            break
        import time as _time

        _time.sleep(0.1)
    assert _gone(pid), "the harness process outlived its interrupt"


def test_quota_hang_is_unknown_and_killed(tmp_path, monkeypatch):
    import scripts.trinity_core.quota as quota

    pid_file = tmp_path / "pid"
    stub = _write_sleeper(tmp_path, "stub", pid_file)
    monkeypatch.setattr(quota, "READ_TIMEOUT_S", 1)
    profile = {
        "quota_source": {"kind": "vendor_cli", "command": str(stub)},
        "freshness_limit": 300,
    }
    result = quota.check(profile)
    assert result["result"] == "unknown", result
    pid = int(pid_file.read_text())
    for _ in range(50):
        if _gone(pid):
            break
        import time as _time

        _time.sleep(0.1)
    assert _gone(pid), "the quota grandchild outlived its timeout"


# --- E1: quota values must be finite before they steer a decision ------------


def _quota_stub(tmp_path: Path, expression: str) -> Path:
    stub = tmp_path / "stub"
    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"sys.stdout.write(json.dumps({expression}))\n"
    )
    stub.chmod(0o755)
    return stub


def test_quota_non_finite_value_is_unknown(tmp_path):
    import scripts.trinity_core.quota as quota

    for expression in (
        '{"used_pct": float("nan"), "read_at": ' + repr(_iso()) + "}",
        '{"used_pct": float("inf"), "read_at": ' + repr(_iso()) + "}",
    ):
        stub = _quota_stub(tmp_path, expression)
        profile = {
            "quota_source": {"kind": "vendor_cli", "command": str(stub)},
            "freshness_limit": 300,
        }
        assert quota.check(profile)["result"] == "unknown", expression


def test_quota_non_finite_freshness_with_stale_read_is_unknown(tmp_path):
    import scripts.trinity_core.quota as quota

    stub = _quota_stub(
        tmp_path, '{"used_pct": 20, "read_at": ' + repr(_iso(-100000)) + "}"
    )
    profile = {
        "quota_source": {"kind": "vendor_cli", "command": str(stub)},
        "freshness_limit": float("nan"),
    }
    assert quota.check(profile)["result"] == "unknown"


# --- E2: secret-shaped step and label are refused ----------------------------


def test_secret_shaped_step_and_label_are_refused(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    monkeypatch.setenv("TRINITY_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    marker = _secret_marker()
    base = {
        "profiles_path": str(_profiles_file(tmp_path)),
        "profile": PROFILE,
        "step": "root",
        "session": "new",
        "prompt": {"text": "x"},
        "cwd": str(tmp_path),
        "allow_nesting": {"max_depth": 1},
    }
    for field in ("step", "label"):
        result = core.call({**base, field: marker})
        assert result["exit_class"] == "bad_request", (field, result)
    assert not (tmp_path / "state" / "journal.jsonl").exists()


# --- E3: a session mismatch records session_unknown --------------------------


def _effective_session(fm, node_id: str):
    node = next(n for n in _nodes(fm) if n["node"] == node_id)
    effective = (node.get("session") or {}).get("id")
    for record in fm.journal:
        if record.get("kind") == "session" and record.get("node") == node_id:
            effective = record.get("id")
    return effective


def test_session_mismatch_records_session_unknown():
    fm = _run_path("mismatch")
    _ready(fm)
    root_node = _node_by_step(fm, "root")
    assert _effective_session(fm, root_node["node"]) is None


# --- E3/R3: a session-unknown node shows no assigned short id in the tree ----


def test_tree_line_for_session_unknown_node_shows_no_assigned_short_id():
    fm = _run_path("mismatch")
    assert fm.run_id is not None, fm.call_proc.stderr
    root_node = _node_by_step(fm, "root")
    assigned_short = (root_node["session"]["id"])[:8]
    line = next(line for line in fm.tree_lines if "root" in line.split())
    assert assigned_short not in line.split(), line
    assert UNKNOWN_SHORT_ID in line.split(), line
    unknown = [
        r
        for r in fm.journal
        if r.get("kind") == "session" and r.get("node") == root_node["node"]
    ]
    assert unknown and unknown[-1].get("source") == "session_unknown", unknown
    assert fm.tree_proc.returncode == 0, (
        fm.tree_proc.returncode,
        fm.tree_proc.stderr,
    )


# Spelling for the tree marker that reports a session line after a final
# session_unknown for the same node (LED-017 says the later line is a defect).
SESSION_DEFECT_MARKER = "!session-override"


def _finality_journal(root):
    from scripts.trinity_core import journal

    run = "r-final"
    node = "n-final"
    other_run = "r-final-other"
    other_node = "n-final-other"
    assigned = "11111111-1111-4111-8111-111111111111"
    later = "22222222-2222-4222-8222-222222222222"
    other_id = "33333333-3333-4333-8333-333333333333"
    journal.append(
        root,
        {
            "kind": "node",
            "run": run,
            "node": node,
            "parent": None,
            "step": "root",
            "depth": 0,
            "profile": PROFILE,
            "model": MODEL,
            "session": {"id": assigned, "mode": "new", "source": "assigned"},
        },
    )
    journal.append(
        root,
        {
            "kind": "state",
            "run": run,
            "node": node,
            "state": "failed",
            "exit_class": "harness_error",
            "output_kind": "none",
            "wall_s": 1,
        },
    )
    journal.append(
        root,
        {
            "kind": "session",
            "run": run,
            "node": node,
            "id": None,
            "source": "session_unknown",
        },
    )
    journal.append(
        root,
        {
            "kind": "session",
            "run": run,
            "node": node,
            "id": later,
            "source": "captured",
        },
    )
    journal.append(
        root,
        {
            "kind": "node",
            "run": other_run,
            "node": other_node,
            "parent": None,
            "step": "root",
            "depth": 0,
            "profile": PROFILE,
            "model": MODEL,
            "session": {"id": other_id, "mode": "new", "source": "assigned"},
        },
    )
    journal.append(
        root,
        {
            "kind": "state",
            "run": other_run,
            "node": other_node,
            "state": "done",
            "exit_class": "ok",
            "output_kind": "none",
            "wall_s": 1,
        },
    )
    return run, node, assigned, later, other_run, other_node, other_id


def _append_line(root, record):
    from scripts.trinity_core import journal

    line_no = len(journal.read(root)) + 1
    journal.append(root, record)
    return line_no


def _override_journal(root):
    run = "r-override"
    node = "n-override"
    _append_line(
        root,
        {
            "kind": "node",
            "run": run,
            "node": node,
            "parent": None,
            "step": "root",
            "depth": 0,
            "profile": PROFILE,
            "model": MODEL,
            "session": {
                "id": "77777777-7777-4777-8777-777777777777",
                "mode": "new",
                "source": "assigned",
            },
        },
    )
    _append_line(
        root,
        {
            "kind": "state",
            "run": run,
            "node": node,
            "state": "failed",
            "exit_class": "harness_error",
            "output_kind": "none",
            "wall_s": 1,
        },
    )
    _append_line(
        root,
        {
            "kind": "session",
            "run": run,
            "node": node,
            "id": None,
            "source": "session_unknown",
        },
    )
    first = _append_line(
        root,
        {
            "kind": "session",
            "run": run,
            "node": node,
            "id": "88888888-8888-4888-8888-888888888888",
            "source": "captured",
        },
    )
    second = _append_line(
        root,
        {
            "kind": "session",
            "run": run,
            "node": node,
            "id": "99999999-9999-4999-8999-999999999999",
            "source": "captured",
        },
    )
    return run, first, second


def test_tree_keeps_session_unknown_final_and_flags_later_record(tmp_path):
    from scripts.trinity_core import render_tree

    root = tmp_path / "state"
    run, _node, assigned, later, _other_run, _other_node, _other_id = _finality_journal(
        root
    )
    lines = render_tree(str(root), run)
    assert len(lines) == 1, lines
    line = lines[0]
    assert UNKNOWN_SHORT_ID in line.split(), line
    assert assigned[:8] not in line.split(), line
    assert later[:8] not in line.split(), line
    assert any(token.startswith(SESSION_DEFECT_MARKER) for token in line.split()), line


def test_tree_defect_names_offending_journal_lines(tmp_path):
    from scripts.trinity_core import render_tree

    root = tmp_path / "state"
    run, first, second = _override_journal(root)
    lines = render_tree(str(root), run)
    assert len(lines) == 1, lines
    expected = f"{SESSION_DEFECT_MARKER}@L{first},L{second}"
    assert expected in lines[0].split(), (lines[0], expected)


def test_tree_session_unknown_defect_is_scoped_to_its_run(tmp_path):
    from scripts.trinity_core import render_tree

    root = tmp_path / "state"
    run, _node, _assigned, _later, other_run, _other_node, other_id = _finality_journal(
        root
    )
    other_lines = render_tree(str(root), other_run)
    assert len(other_lines) == 1, other_lines
    other_line = other_lines[0]
    assert other_id[:8] in other_line.split(), other_line
    assert not any(
        token.startswith(SESSION_DEFECT_MARKER) for token in other_line.split()
    ), other_line
    assert len(render_tree(str(root), run)) == 1


# --- E5: a reported session id never lands raw in the error log --------------


def test_mismatch_error_log_has_no_reported_id(tmp_path, monkeypatch):
    import scripts.trinity_core.claude_code as claude_code

    marker = _secret_marker()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    harness = bin_dir / "claude"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, sys
            sys.stdout.write(json.dumps({{
                "type": "result", "is_error": False, "session_id": {marker!r},
            }}) + "\\n")
            """
        )
    )
    harness.chmod(0o755)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    )
    root = tmp_path / "state"
    outcome = claude_code.run(
        {"model": MODEL, "credential_source": {"wrapper": "claude"}},
        prompt="x",
        cwd=str(tmp_path),
        session_id="assigned-session-1",
        run_id="r",
        node_id="n",
        depth=0,
        max_depth=0,
        root=str(root),
        heartbeat=lambda source: None,
        poll_s=100.0,
    )
    assert outcome["exit_class"] == "harness_error", outcome
    error_text = (root / "error.log").read_text()
    assert "session_mismatch" in error_text
    assert marker not in error_text


# --- E6: prompt {file: path} is read in the core -----------------------------


def _capturing_harness(bin_dir: Path, capture: Path) -> None:
    script = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        argv = sys.argv[1:]
        with open({str(capture)!r}, "a") as handle:
            handle.write(json.dumps({{"argv": argv}}) + "\\n")
        sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else ""
        sys.stdout.write(json.dumps({{
            "type": "result", "is_error": False, "session_id": sid,
        }}) + "\\n")
        """
    )
    for name in (WRAPPER, "claude"):
        path = bin_dir / name
        path.write_text(script)
        path.chmod(0o755)


def test_prompt_file_reaches_adapter_and_missing_file_is_refused(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    monkeypatch.setenv("TRINITY_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    stub = tmp_path / "quota_stub"
    stub.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"sys.stdout.write(json.dumps({{'used_pct': 20, 'read_at': {_iso()!r}}}))\n"
    )
    stub.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.jsonl"
    _capturing_harness(bin_dir, capture)
    venv_bin = str(Path(sys.executable).resolve().parent)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(bin_dir), venv_bin, "/usr/bin", "/bin"])
    )
    prompt_file = tmp_path / "task.txt"
    prompt_text = "file " + "prompt-marker"
    prompt_file.write_text(prompt_text)
    base = {
        "profiles_path": str(_profiles_file(tmp_path)),
        "profile": PROFILE,
        "step": "root",
        "session": "new",
        "cwd": str(tmp_path),
        "allow_nesting": {"max_depth": 1},
    }
    result = core.call({**base, "prompt": {"file": str(prompt_file)}})
    assert result["exit_class"] == "ok", result
    captures = [json.loads(line) for line in capture.read_text().splitlines()]
    assert captures and prompt_text in captures[0]["argv"], captures

    missing_state = tmp_path / "state2"
    monkeypatch.setenv("TRINITY_ROOT", str(missing_state))
    missing = core.call({**base, "prompt": {"file": str(tmp_path / "nope.txt")}})
    assert missing["exit_class"] == "bad_request", missing
    assert not (missing_state / "journal.jsonl").exists()


# --- E7: an unknown run is reported on stderr and exits 1 --------------------


def test_tree_unknown_run_reports_on_stderr_and_exits_1(tmp_path):
    env = dict(os.environ)
    env["TRINITY_ROOT"] = str(tmp_path / "state")
    env.pop("TRINITY_GUARD", None)
    proc = subprocess.run(
        [str(CLI), "tree", "r-does-not-exist"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "r-does-not-exist" in proc.stderr
    assert len([line for line in proc.stderr.splitlines() if line.strip()]) == 1


# --- E8: nesting depth is validated in the core ------------------------------


def test_bad_nesting_depth_is_refused(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    monkeypatch.setenv("TRINITY_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    base = {
        "profiles_path": str(_profiles_file(tmp_path)),
        "profile": PROFILE,
        "step": "root",
        "session": "new",
        "prompt": {"text": "x"},
        "cwd": str(tmp_path),
    }
    for bad in (0, -1, 6, "two", 2.5, True):
        result = core.call({**base, "allow_nesting": {"max_depth": bad}})
        assert result["exit_class"] == "bad_request", (bad, result)
    assert not (tmp_path / "state" / "journal.jsonl").exists()


def test_nesting_depth_shapes():
    from scripts.trinity_core.dispatch import _max_depth

    assert _max_depth({}) == 0
    assert _max_depth({"allow_nesting": False}) == 0
    assert _max_depth({"allow_nesting": True}) == 2
    assert _max_depth({"allow_nesting": {"max_depth": 1}}) == 1
    assert _max_depth({"allow_nesting": {"max_depth": "2"}}) == 2


# --- E4: group cleanup survives a reaped leader ------------------------------


def test_harness_timeout_kills_group_after_leader_reaped(tmp_path, monkeypatch):
    import scripts.trinity_core.claude_code as claude_code

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gpid_file = tmp_path / "gpid"
    harness = bin_dir / "claude"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import subprocess, sys
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(5)"]
            )
            open({str(gpid_file)!r}, "w").write(str(child.pid))
            sys.exit(0)
            """
        )
    )
    harness.chmod(0o755)
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    )
    import time as _time

    started = _time.monotonic()
    outcome = claude_code.run(
        {"model": MODEL, "credential_source": {"wrapper": "claude"}},
        prompt="x",
        cwd=str(tmp_path),
        session_id="s",
        run_id="r",
        node_id="n",
        depth=0,
        max_depth=0,
        root=str(tmp_path),
        heartbeat=lambda source: None,
        poll_s=0.05,
        time_s=1.0,
    )
    elapsed = _time.monotonic() - started
    assert outcome["exit_class"] == "timeout", outcome
    assert elapsed < 2.5, (
        f"a reaped leader let a grandchild hold the call for {elapsed:.1f}s"
    )
    for _ in range(50):
        if gpid_file.exists():
            break
        _time.sleep(0.05)
    gpid = int(gpid_file.read_text())
    for _ in range(50):
        if _gone(gpid):
            break
        _time.sleep(0.1)
    assert _gone(gpid), "the harness grandchild outlived its timeout group kill"


# --- E9: no literal clock timestamps in this public test file ----------------


def test_no_literal_clock_timestamps_in_this_file():
    text = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    assert not re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", text)

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
  ``credential_source`` (``{"env": "<NAME>"}``), ``quota_source``
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
CLI = REPO / "bin" / "trinity"
PROFILE = "pilot"
MODEL = "pilot-model"

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
                        "credential_source": {"env": CRED_NAME},
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
            "PATH": os.pathsep.join([str(bin_dir), venv_bin, env.get("PATH", "/usr/bin:/bin")]),
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
        expected = _expected_line(node, _states(fm, node["node"])[-1], 0 if step == "root" else 1)
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
        assert CRED_NAME in names, capture
        assert DECOY_NAME not in names, capture
        assert "TRINITY_ROOT" not in names, capture
        assert "PYTHONPATH" not in names, capture
        assert "TRINITY_HEARTBEAT_POLL_S" not in names, capture
        assert all(
            name in ALLOWED_ENV
            or name.startswith("LC_")
            or name == CRED_NAME
            or name in PLATFORM_ENV
            for name in names
        ), capture


def test_harness_is_run_with_json_output():
    fm = _run_path()
    _ready(fm)
    assert fm.refuse_rc != 0, "the double must refuse to run without --output-format json"
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
                        "credential_source": {"env": CRED_NAME},
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
    stub.write_text(f"#!{sys.executable}\nimport json,sys\nsys.stdout.write(json.dumps({{}}))\n")
    stub.chmod(0o755)
    profile = {
        "quota_source": {"kind": "vendor_cli", "command": str(stub)},
        "freshness_limit": 300,
    }
    assert quota.check(profile)["result"] == "unknown"

    stub.write_text(f'#!{sys.executable}\nimport json,sys\nsys.stdout.write(json.dumps({{"used_pct": "many", "read_at": "2030-01-01T00:00:00+00:00"}}))\n')
    stub.chmod(0o755)
    assert quota.check(profile)["result"] == "unknown"


def test_quota_stale_read_is_unknown(tmp_path):
    import scripts.trinity_core.quota as quota

    stub = tmp_path / "stub"
    stub.write_text(
        f'#!{sys.executable}\nimport json,sys\n'
        'sys.stdout.write(json.dumps({"used_pct": 20, "read_at": "2000-01-01T00:00:00+00:00"}))\n'
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
        f'#!{sys.executable}\nimport json,sys\n'
        'sys.stdout.write(json.dumps({"used_pct": 20, "read_at": "2000-01-01T00:00:00+00:00"}))\n'
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
    states = [r.get("state") for r in core.journal.read(root) if r.get("kind") == "state"]
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


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def test_harness_timeout_kills_only_its_process_group(tmp_path, monkeypatch):
    import scripts.trinity_core.claude_code as claude_code

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    _write_sleeper(bin_dir, "claude", pid_file)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")]))
    outcome = claude_code.run(
        {"model": MODEL},
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
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")]))

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
        {"model": MODEL},
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

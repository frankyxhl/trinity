"""WO-006 RED contract: every wait in one Trinity call has a deadline.

These tests are deliberately synthetic. They never launch Claude, authenticate,
or touch the network; every child is a local Python stub under ``tmp_path``.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import codex
from scripts.trinity_core import claude_code, dispatch, journal, profiles, tree

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
RUN = "r-wo006"
NODE = "n-wo006"
HUGE_LIMIT = int("9" * 401)


def _iso(seconds: float = 0) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def _heartbeat(seconds: float = 0, *, source: str = "stdout") -> dict:
    return {
        "kind": "heartbeat",
        "run": RUN,
        "node": NODE,
        "source": source,
        "t": _iso(seconds),
    }


def _records(limit: int | float = 120, *, heartbeat: bool = True) -> list[dict]:
    rows = [
        {
            "kind": "node",
            "run": RUN,
            "node": NODE,
            "parent": None,
            "step": "wo006",
            "harness": "claude-code",
            "profile": "wo006-profile",
            "stall_limit_s": limit,
            "session": {"id": "wo006-session", "mode": "new"},
            "t": _iso(),
        },
        {
            "kind": "state",
            "run": RUN,
            "node": NODE,
            "state": "queued",
            "t": _iso(),
        },
        {"kind": "state", "run": RUN, "node": NODE, "state": "running", "t": _iso()},
    ]
    if heartbeat:
        rows.append(_heartbeat())
    return rows


def _save(root: Path, records: list[dict]) -> None:
    for record in records:
        journal.append(root, record)


def _derive():
    function = getattr(tree, "derive_state", None)
    assert function is not None, "tree must expose pure derive_state"
    return function


def _profile(name: str = "wo006-profile", limit: int | float | None = None) -> dict:
    profile = {
        "name": name,
        "adapter": "claude-code",
        "model": "wo006-model",
        "credential_source": {"wrapper": "wo006-wrapper"},
    }
    if limit is not None:
        profile["stall_limit_s"] = limit
    return profile


def _dispatch(
    monkeypatch,
    root: Path,
    entries: dict,
    runner,
    *,
    profile: str = "wo006-profile",
    limits: dict | None = None,
) -> dict:
    monkeypatch.setenv("TRINITY_ROOT", str(root))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    monkeypatch.delenv("TRINITY_HEARTBEAT_POLL_S", raising=False)
    monkeypatch.setattr(profiles, "load", lambda _path: entries)
    monkeypatch.setattr(dispatch.quota, "check", lambda _profile: {"result": "ok"})
    monkeypatch.setattr(dispatch.claude_code, "run", runner)
    return dispatch.call(
        {
            "profiles_path": "wo006-profiles.json",
            "profile": profile,
            "step": "wo006",
            "prompt": "wo006 synthetic prompt",
            "cwd": str(root),
            "limits": limits or {},
        }
    )


def _ok(_profile: dict, **kwargs) -> dict:
    return {
        "exit_class": "ok",
        "session_id": kwargs["session_id"],
        "output_kind": "none",
        "usage": None,
        "wall_s": 0,
    }


def _adapter_run(root: Path, *, time_s: float | None = None, poll_s: float = 0.01):
    return claude_code.run(
        _profile(),
        prompt="wo006 synthetic prompt",
        cwd=str(root),
        session_id="wo006-session",
        run_id=RUN,
        node_id=NODE,
        depth=0,
        max_depth=0,
        root=str(root),
        heartbeat=lambda _source: None,
        poll_s=poll_s,
        time_s=time_s,
    )


def _write_stream_harness(root: Path, lines: list[dict], *, sleep_s: float = 0) -> Path:
    harness = root / "wo006-wrapper"
    harness.write_text(
        "#!" + sys.executable + "\n"
        "import json, sys, time\n"
        f"lines = {lines!r}\n"
        "for line in lines:\n"
        "    print(json.dumps(line), flush=True)\n"
        f"    time.sleep({sleep_s!r})\n"
    )
    harness.chmod(0o755)
    return harness


# Acceptance 1: output drain is bounded even when a detached child holds stdout.
_A1_WORKER = r'''
import json
import os
import sys
import time
from pathlib import Path
from scripts.trinity_core import claude_code

root = Path(sys.argv[1])
harness = root / "wo006-wrapper"
harness.write_text("#!" + sys.executable + "\n" + """
import json, os, subprocess, sys, time
from pathlib import Path
root = Path.cwd()
Path(root / "leader.pid").write_text(str(os.getpid()))
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        \"import os, time; from pathlib import Path; \"
        \"root = Path.cwd(); os.setsid(); \"
        \"Path(root / 'child-ready').write_text('ready'); \"
        \"os.close(2); time.sleep(10)\",
    ],
    stdout=sys.stdout,
    stderr=subprocess.DEVNULL,
)
Path(root / "child.pid").write_text(str(child.pid))
ready = root / "child-ready"
deadline = time.monotonic() + 2
while not ready.exists() and time.monotonic() < deadline:
    time.sleep(0.001)
assert ready.exists(), "detached child never entered its session"
print(json.dumps({
    "type": "result",
    "is_error": False,
    "session_id": "wo006-session",
}), flush=True)
os._exit(0)
""")
harness.chmod(0o755)
os.environ["PATH"] = str(root)
started = time.monotonic()
outcome = claude_code.run(
    {
        "name": "wo006-profile",
        "credential_source": {"wrapper": "wo006-wrapper"},
    },
    prompt="wo006 synthetic prompt",
    cwd=str(root),
    session_id="wo006-session",
    run_id="r-wo006",
    node_id="n-wo006",
    depth=0,
    max_depth=0,
    root=str(root),
    heartbeat=lambda _source: None,
    poll_s=0.01,
    time_s=0.5,
)
print(json.dumps({
    "outcome": outcome,
    "elapsed": time.monotonic() - started,
}))
'''


def _kill_recorded_tree(root: Path) -> None:
    leader = root / "leader.pid"
    child = root / "child.pid"
    for path in (leader, child):
        if not path.exists():
            continue
        try:
            os.kill(int(path.read_text()), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def test_wo006_a1_detached_stdout_holder_returns_within_deadline_grace(tmp_path):
    worker = None
    exceeded = False
    try:
        try:
            worker = subprocess.run(
                [sys.executable, "-c", _A1_WORKER, str(tmp_path)],
                cwd=str(Path(__file__).resolve().parent.parent),
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            exceeded = True
        assert not exceeded, "adapter waited for EOF after its deadline"
        assert worker is not None and worker.returncode == 0, (
            worker.stderr if worker else None
        )
        observed = json.loads(worker.stdout)
        assert observed["outcome"]["exit_class"] == "timeout", observed
        assert observed["elapsed"] <= 0.5 + 5, observed
    finally:
        _kill_recorded_tree(tmp_path)
        if exceeded:
            # The worker was launched in its own session, so clean up only it.
            pass


def test_wo006_control_a1_normal_child_still_returns_result(tmp_path, monkeypatch):
    final = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "wo006-session",
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    _write_stream_harness(tmp_path, [final])
    monkeypatch.setenv("PATH", str(tmp_path))
    outcome = _adapter_run(tmp_path)
    assert outcome["exit_class"] == "ok", outcome
    assert outcome["session_id"] == "wo006-session", outcome
    assert outcome["usage"] == final["usage"], outcome


# Acceptance 2: stuck is derived from stdout evidence, never a journal state.
def test_wo006_a2_running_and_stuck_boundary_with_age():
    function = _derive()
    records = _records(limit=120)
    before = copy.deepcopy(records)
    for seconds, expected in ((119, "running"), (120, "running"), (121, "stuck")):
        derived = function(records, NODE, now=T0 + timedelta(seconds=seconds))
        assert derived == {"state": expected, "age_s": seconds}, derived
    assert records == before


def test_wo006_a2_new_stdout_heartbeat_restores_running(tmp_path):
    function = _derive()
    _save(tmp_path, _records(limit=60))
    now = T0 + timedelta(seconds=61)
    assert function(journal.read(tmp_path), NODE, now=now)["state"] == "stuck"
    journal.append(tmp_path, _heartbeat(61, source="stdout"))
    derived = function(journal.read(tmp_path), NODE, now=now)
    assert derived == {"state": "running", "age_s": 0}, derived


def test_wo006_a2_stuck_is_never_written(tmp_path, monkeypatch):
    _save(tmp_path, _records())
    before = journal.journal_path(tmp_path).read_bytes()
    refused = False
    try:
        journal.append(
            tmp_path,
            {
                "kind": "state",
                "run": RUN,
                "node": NODE,
                "state": "stuck",
                "t": _iso(121),
            },
        )
    except ValueError:
        refused = True
    assert refused, "journal accepted a written stuck state"
    assert journal.journal_path(tmp_path).read_bytes() == before
    function = _derive()
    touched = []

    def forbidden(*args, **kwargs):
        touched.append((args, kwargs))
        raise AssertionError("derived state touched a process")

    monkeypatch.setattr(claude_code.subprocess, "Popen", forbidden)
    monkeypatch.setattr(claude_code.os, "kill", forbidden)
    monkeypatch.setattr(claude_code.os, "killpg", forbidden)
    monkeypatch.setattr(claude_code.os, "getpgid", forbidden)
    monkeypatch.setattr(claude_code, "_kill_group", forbidden)
    monkeypatch.setattr(journal, "append", lambda *_args, **_kwargs: None)
    assert (
        function(journal.read(tmp_path), NODE, now=T0 + timedelta(seconds=121))["state"]
        == "stuck"
    )
    assert touched == [], touched
    assert journal.journal_path(tmp_path).read_bytes() == before


def test_wo006_a2_stall_limit_60_is_the_floor(monkeypatch, tmp_path):
    calls = []
    entries = {
        "accepted": _profile("accepted", 60),
        "refused": _profile("refused", 59),
    }
    accepted_root = tmp_path / "accepted"
    refused_root = tmp_path / "refused"
    accepted = _dispatch(
        monkeypatch,
        accepted_root,
        entries,
        lambda *a, **kw: calls.append(a) or _ok(*a, **kw),
        profile="accepted",
    )
    refused = _dispatch(
        monkeypatch,
        refused_root,
        entries,
        lambda *a, **kw: calls.append(a) or _ok(*a, **kw),
        profile="refused",
    )
    assert accepted["exit_class"] == "ok", accepted
    assert refused["exit_class"] == "bad_request", refused
    assert len(calls) == 1, calls
    assert not journal.journal_path(refused_root).exists(), refused
    accepted_nodes = [
        row for row in journal.read(accepted_root) if row["kind"] == "node"
    ]
    assert len(accepted_nodes) == 1, accepted_nodes
    assert accepted_nodes[0]["stall_limit_s"] == 60, accepted_nodes[0]


@pytest.mark.parametrize("source", ["profile", "request"])
@pytest.mark.parametrize(
    "value",
    [HUGE_LIMIT, float("nan"), float("inf")],
    ids=["huge-integer", "nan", "infinity"],
)
def test_wo006_a2_unusable_stall_limits_are_refused_without_write(
    monkeypatch, tmp_path, source, value
):
    calls = []
    entries = {"wo006-profile": _profile(limit=60 if source == "request" else value)}
    limits = {"stall_s": value} if source == "request" else {}
    result = _dispatch(
        monkeypatch,
        tmp_path,
        entries,
        lambda *args, **kwargs: calls.append(args) or _ok(*args, **kwargs),
        limits=limits,
    )
    assert result["exit_class"] == "bad_request", result
    assert not calls, calls
    assert not journal.journal_path(tmp_path).exists(), "refusal wrote a journal"


def test_wo006_a2_recorded_huge_limit_derives_without_overflow(tmp_path):
    _save(tmp_path, _records(HUGE_LIMIT))
    before = journal.journal_path(tmp_path).read_bytes()
    function = _derive()
    derived = function(journal.read(tmp_path), NODE, now=T0 + timedelta(seconds=121))
    assert derived == {"state": "running", "age_s": 121}, derived
    assert journal.journal_path(tmp_path).read_bytes() == before


def test_wo006_a2_default_stall_exceeds_longest_tool_timeout():
    limit = getattr(claude_code, "DEFAULT_STALL_LIMIT_S", None)
    assert limit is not None, "claude-code must declare a stall default"
    assert limit > 600, limit
    assert limit >= 660, limit


def test_wo006_a2_stream_json_argv_and_stdout_evidence(tmp_path, monkeypatch):
    events = [
        {"type": "stream_event", "event": {"type": "content_block_delta"}},
        {"type": "stream_event", "event": {"type": "content_block_delta"}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "wo006-session",
            "usage": {"input_tokens": 4, "output_tokens": 1},
        },
    ]
    capture = tmp_path / "argv.json"
    harness = tmp_path / "wo006-wrapper"
    harness.write_text(
        "#!" + sys.executable + "\n"
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "capture = Path('argv.json')\n"
        "capture.write_text(json.dumps(argv))\n"
        f"events = {events!r}\n"
        "for event in events:\n"
        "    print(json.dumps(event), flush=True)\n"
        "    time.sleep(0.02)\n"
    )
    harness.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    rows = []
    outcome = claude_code.run(
        _profile(),
        prompt="wo006 synthetic prompt",
        cwd=str(tmp_path),
        session_id="wo006-session",
        run_id=RUN,
        node_id=NODE,
        depth=0,
        max_depth=0,
        root=str(tmp_path),
        heartbeat=lambda source: rows.append(source),
        poll_s=0.01,
    )
    assert capture.exists(), "stub harness did not run"
    argv = json.loads(capture.read_text())
    assert "--output-format" in argv, argv
    assert argv[argv.index("--output-format") + 1] == "stream-json", argv
    assert "--verbose" in argv, argv
    assert "--include-partial-messages" in argv, argv
    assert outcome["exit_class"] == "ok", outcome
    assert rows, rows
    assert set(rows) == {"stdout"}, rows


class _OneShotStop:
    def __init__(self):
        self.finished = False

    def wait(self, interval: float) -> bool:
        assert interval == 0.01, interval
        return self.finished


def test_wo006_a2_heartbeat_only_on_new_stdout_evidence():
    function = getattr(claude_code, "_poll", None)
    assert function is not None, "missing claude-code poll seam"
    assert "evidence" in inspect.signature(function).parameters
    stop = _OneShotStop()
    evidence = iter([100, 100, 200, 200])
    sources = []
    function(
        stop,
        SimpleNamespace(poll=lambda: None),
        sources.append,
        0.01,
        evidence=lambda: next(evidence),
    )
    assert sources == ["stdout", "stdout"], sources


def test_wo006_a2_no_heartbeat_when_stdout_is_silent():
    function = getattr(claude_code, "_poll", None)
    assert function is not None, "missing claude-code poll seam"
    assert "evidence" in inspect.signature(function).parameters
    sources = []
    function(
        _OneShotStop(),
        SimpleNamespace(poll=lambda: None),
        sources.append,
        0.01,
        evidence=lambda: None,
    )
    assert sources == [], sources


# Acceptance 3: crashes are derived; a dead lock holder cannot wedge a writer.
def test_wo006_a3_crashed_node_without_end_line_reads_stuck_after_limit():
    function = _derive()
    records = _records(limit=60, heartbeat=True)
    records.append(
        {
            "kind": "process",
            "run": RUN,
            "node": NODE,
            "alive": False,
            "t": _iso(1),
        }
    )
    before = copy.deepcopy(records)
    assert function(records, NODE, now=T0 + timedelta(seconds=60))["state"] == "running"
    assert function(records, NODE, now=T0 + timedelta(seconds=61))["state"] == "stuck"
    assert records == before


def test_wo006_control_a3_journal_append_survives_dead_lock_holder(tmp_path):
    path = journal.journal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time\n"
            "path = sys.argv[1]\n"
            "with open(path, 'a', encoding='utf-8') as handle:\n"
            "    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
            "    print('locked', flush=True)\n"
            "    time.sleep(30)\n",
            str(path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        holder.kill()
        holder.wait(timeout=2)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=2)
    append = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from scripts.trinity_core import journal\n"
            "journal.append(sys.argv[1], {'kind': 'state', 'state': 'running'})\n",
            str(tmp_path),
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    assert append.returncode == 0, append.stderr
    rows = journal.read(tmp_path)
    assert rows[-1]["state"] == "running", rows


# Acceptance 4: one clock, with a named error at the CLI boundary.
def test_wo006_a4_malformed_core_clock_is_named_error_and_one_cli_line(
    monkeypatch, tmp_path, capsys
):
    _save(tmp_path, _records())
    before = journal.journal_path(tmp_path).read_bytes()
    monkeypatch.setenv("TRINITY_ROOT", str(tmp_path))
    monkeypatch.setattr(journal, "utc_now", lambda: "malformed-core-clock")
    local_reads = []

    class SentinelDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            local_reads.append(tz)
            return T0

    monkeypatch.setattr(tree, "datetime", SentinelDatetime, raising=False)
    error = None
    try:
        tree.render(str(tmp_path), RUN)
    except ValueError as exc:
        error = exc
    assert error is not None, "malformed core clock was silently accepted"
    assert "core clock" in str(error), error
    assert not local_reads, local_reads
    status = codex.main(["tree", RUN])
    captured = capsys.readouterr()
    assert status == 1, status
    assert captured.err.count("\n") == 1, captured.err
    assert "Traceback" not in captured.err, captured.err
    assert "core clock" in captured.err, captured.err
    assert journal.journal_path(tmp_path).read_bytes() == before


# Acceptance 5: a failed process launch closes both ends of its pipe.
def test_wo006_a5_failed_popen_closes_both_pipe_fds(monkeypatch, tmp_path):
    real_pipe = os.pipe
    allocated = []

    def tracked_pipe():
        pair = real_pipe()
        allocated.extend(pair)
        return pair

    def failed_popen(*_args, **_kwargs):
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(claude_code.shutil, "which", lambda _name: sys.executable)
    monkeypatch.setattr(claude_code.os, "pipe", tracked_pipe)
    monkeypatch.setattr(claude_code.subprocess, "Popen", failed_popen)
    try:
        try:
            _adapter_run(tmp_path)
        except OSError:
            pass
        assert len(allocated) == 2, allocated
        leaked = []
        for descriptor in allocated:
            try:
                os.fstat(descriptor)
                leaked.append(descriptor)
            except OSError:
                continue
        assert leaked == [], leaked
    finally:
        for descriptor in allocated:
            try:
                os.close(descriptor)
            except OSError:
                pass


# Acceptance 6: a time-limit stop writes one deadline check; normal end writes none.
def test_wo006_a6_deadline_stop_writes_exactly_one_check(monkeypatch, tmp_path):
    def runner(_profile: dict, **kwargs):
        outcome = _ok(_profile, **kwargs)
        if kwargs.get("time_s") is not None:
            outcome["exit_class"] = "timeout"
        return outcome

    entries = {"wo006-profile": _profile()}
    timeout_root = tmp_path / "timeout"
    normal_root = tmp_path / "normal"
    timeout = _dispatch(
        monkeypatch,
        timeout_root,
        entries,
        runner,
        limits={"time_s": 0.25},
    )
    normal = _dispatch(monkeypatch, normal_root, entries, runner)
    assert timeout["exit_class"] == "timeout", timeout
    assert normal["exit_class"] == "ok", normal
    deadline_checks = [
        row
        for row in journal.read(timeout_root)
        if row.get("kind") == "check" and row.get("check") == "deadline"
    ]
    assert len(deadline_checks) == 1, journal.read(timeout_root)
    check = deadline_checks[0]
    assert check.get("limit_s") == 0.25, check
    assert check.get("decision") == "stop", check
    assert isinstance(check.get("reason"), str) and check["reason"], check
    assert not [
        row
        for row in journal.read(normal_root)
        if row.get("kind") == "check" and row.get("check") == "deadline"
    ], journal.read(normal_root)


# Acceptance 7: stream parsing keeps _final_result as its single authority.
def test_wo006_a7_ok_and_auth_use_the_existing_final_result_parser(
    tmp_path, monkeypatch
):
    earlier = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "wo006-session",
        "usage": {"input_tokens": 99, "output_tokens": 99},
    }
    final = {"type": "system", "subtype": "notice", "session_id": "other-session"}
    _write_stream_harness(tmp_path, [earlier, final])
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []
    monkeypatch.setattr(
        claude_code,
        "_final_result",
        lambda out: calls.append(out) or None,
    )
    outcome = _adapter_run(tmp_path)
    assert len(calls) == 1, calls
    assert outcome["exit_class"] == "unknown", outcome
    assert outcome["usage"] is None, outcome
    assert outcome["session_id"] == "wo006-session", outcome

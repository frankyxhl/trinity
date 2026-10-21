from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "bin" / "trinity"
FIXTURES = REPO / "tests" / "fixtures" / "oneshot"

PROFILE = "cx"
MODEL = "gpt-6-astra"
SANDBOX = "read-only"
THREAD_ID = "01a15948-76de-79e1-a038-5b353f69aa3a"
PROMPT = "ONESHOT-PROMPT-MARK"
FINAL_MARK = "ONESHOT-FINAL-ANSWER-MARK"

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
PLATFORM_ENV = {"__CF_USER_TEXT_ENCODING"}

OK_FAKE = {
    "stdout_fixture": FIXTURES / "codex-new.jsonl",
    "write_output": True,
    "rollout": {"model": MODEL, "sandbox": SANDBOX},
}


def fake_codex_body(
    capture: Path,
    *,
    stdout_fixture: Path | None = None,
    extra_event: dict | None = None,
    skip_tail: int = 0,
    skip_head: int = 0,
    stderr_text: str = "",
    rc: int = 0,
    sleep_s: float = 0.0,
    write_output: bool = False,
    rollout: dict | None = None,
    pid_file: Path | None = None,
    child_pid_file: Path | None = None,
) -> str:
    excerpt = FIXTURES / "codex-rollout-excerpt.jsonl"
    constants = "\n".join(
        [
            f"CAPTURE = {str(capture)!r}",
            f"STDOUT_FIXTURE = {None if stdout_fixture is None else str(stdout_fixture)!r}",
            f"EXTRA_EVENT = {extra_event!r}",
            f"SKIP_TAIL = {skip_tail!r}",
            f"SKIP_HEAD = {skip_head!r}",
            f"STDERR_TEXT = {stderr_text!r}",
            f"RC = {rc!r}",
            f"SLEEP_S = {sleep_s!r}",
            f"WRITE_OUTPUT = {write_output!r}",
            f"ROLLOUT = {rollout!r}",
            f"PID_FILE = {None if pid_file is None else str(pid_file)!r}",
            (
                "CHILD_PID_FILE = "
                f"{None if child_pid_file is None else str(child_pid_file)!r}"
            ),
            f"EXCERPT = {str(excerpt)!r}",
        ]
    )
    body = """
import json, os, stat, subprocess, sys, time
from pathlib import Path

CAPTURE = Path(CAPTURE)

argv = sys.argv[1:]
try:
    stdin_devnull = (
        stat.S_ISCHR(os.fstat(0).st_mode)
        and os.fstat(0).st_rdev == os.stat(\"/dev/null\").st_rdev
    )
except OSError:
    stdin_devnull = False
CAPTURE.parent.mkdir(parents=True, exist_ok=True)
with CAPTURE.open(\"a\") as fh:
    fh.write(
        json.dumps(
            {
                \"argv\": argv,
                \"env\": dict(os.environ),
                \"cwd\": os.getcwd(),
                \"stdin_is_devnull\": stdin_devnull,
            }
        )
        + \"\\n\"
    )
if PID_FILE:
    Path(PID_FILE).write_text(str(os.getpid()))
if CHILD_PID_FILE:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(CHILD_PID_FILE).write_text(str(child.pid))
lines = []
if STDOUT_FIXTURE:
    lines = Path(STDOUT_FIXTURE).read_text().splitlines()
    if SKIP_HEAD:
        lines = lines[SKIP_HEAD:]
    if SKIP_TAIL:
        lines = lines[: len(lines) - SKIP_TAIL]
events = [json.loads(line) for line in lines if line.strip()]
if EXTRA_EVENT is not None:
    events.append(EXTRA_EVENT)
for event in events:
    sys.stdout.write(json.dumps(event) + \"\\n\")
sys.stdout.flush()
thread_id = next(
    (e.get(\"thread_id\") for e in events if e.get(\"type\") == \"thread.started\"),
    None,
)
if ROLLOUT and thread_id and os.environ.get(\"CODEX_HOME\"):
    base = Path(os.environ[\"CODEX_HOME\"]) / \"sessions\" / \"2026\" / \"10\" / \"20\"
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in Path(EXCERPT).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get(\"type\") == \"turn_context\":
            row[\"payload\"][\"model\"] = ROLLOUT.get(\"model\")
            policy = row.get(\"payload\", {}).get(\"sandbox_policy\")
            if isinstance(policy, dict):
                policy[\"type\"] = ROLLOUT.get(\"sandbox\")
        if ROLLOUT.get(\"no_turn_context\") and row.get(\"type\") == \"turn_context\":
            continue
        rows.append(row)
    (base / (\"rollout-2026-10-20T00-00-00-\" + thread_id + \".jsonl\")).write_text(
        \"\\n\".join(json.dumps(row) for row in rows) + \"\\n\"
    )
if SLEEP_S:
    time.sleep(SLEEP_S)
if WRITE_OUTPUT and \"-o\" in argv:
    answer = None
    for event in events:
        item = event.get(\"item\") or {}
        if event.get(\"type\") == \"item.completed\" and item.get(\"type\") == \"agent_message\":
            answer = item.get(\"text\")
    if answer is not None:
        Path(argv[argv.index(\"-o\") + 1]).write_text(answer)
if STDERR_TEXT:
    sys.stderr.write(STDERR_TEXT)
sys.exit(RC)
"""
    return "#!" + sys.executable + "\n" + constants + "\n" + body


def install_fake_codex(
    bin_dir: Path, capture: Path, *, name: str = "codex", **kwargs
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(fake_codex_body(capture, **kwargs))
    stub.chmod(0o755)
    return stub


def write_profiles(
    root: Path,
    *,
    name: str = PROFILE,
    model: str | None = MODEL,
    sandbox: str | None = SANDBOX,
    codex_home: Path | str | None = None,
    effort: str | None = None,
    binary: str | None = None,
    env_pass: list | None = None,
    gate: str | None = None,
) -> Path:
    profile = {
        "name": name,
        "adapter": "codex",
        "provider": "codex",
        "billing": "subscription",
        "enabled": True,
    }
    if model is not None:
        profile["model"] = model
    if sandbox is not None:
        profile["sandbox"] = sandbox
    if codex_home is not None:
        profile["codex_home"] = str(codex_home)
    if effort is not None:
        profile["effort"] = effort
    if binary is not None:
        profile["binary"] = binary
    if env_pass is not None:
        profile["env_pass"] = env_pass
    if gate is not None:
        profile["gate"] = gate
    path = root / "profiles.json"
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


def make_root(
    tmp_path: Path, *, codex_home_created: bool = True, **fake_kwargs
) -> SimpleNamespace:
    home = tmp_path / "home"
    home.mkdir()
    codex_home = tmp_path / "codex-home"
    if codex_home_created:
        codex_home.mkdir()
    (tmp_path / "work").mkdir()
    capture = tmp_path / "capture" / "codex.jsonl"
    install_fake_codex(tmp_path / "bin", capture, **fake_kwargs)
    profiles = write_profiles(tmp_path, codex_home=codex_home)
    return SimpleNamespace(
        root=tmp_path,
        home=home,
        codex_home=codex_home,
        capture=capture,
        profiles=profiles,
        state=tmp_path / "state",
    )


def call_env(ns: SimpleNamespace, extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.pop("TRINITY_GUARD", None)
    venv_bin = str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join([str(ns.root / "bin"), venv_bin, "/usr/bin", "/bin"])
    env["HOME"] = str(ns.home)
    env["TRINITY_ROOT"] = str(ns.state)
    env["TRINITY_HEARTBEAT_POLL_S"] = "1"
    env.update(extra or {})
    return env


def run_call(
    ns: SimpleNamespace,
    *,
    session: str = "new",
    args: tuple = (),
    env_extra: dict | None = None,
    timeout: int = 30,
):
    try:
        return subprocess.run(
            [
                str(CLI),
                "call",
                "--profiles",
                str(ns.profiles),
                "--profile",
                PROFILE,
                "--step",
                "root",
                "--session",
                session,
                "--prompt",
                PROMPT,
                "--cwd",
                str(ns.root / "work"),
                *args,
            ],
            cwd=str(REPO),
            env=call_env(ns, env_extra),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SimpleNamespace(
            returncode=None, stdout="", stderr="test timeout: the call did not return"
        )


def result_of(proc) -> dict:
    result = None
    for line in proc.stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            result = value
    assert result is not None, (proc.returncode, proc.stdout, proc.stderr)
    return result


def records_of(state: Path) -> list:
    path = state / "journal.jsonl"
    assert path.exists(), f"no journal at {path}"
    records = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def nodes_of(records: list) -> list:
    return [r for r in records if r.get("kind") == "node"]


def node_id_of(records: list) -> str | None:
    nodes = nodes_of(records)
    assert len(nodes) == 1, nodes
    return nodes[0].get("node")


def run_id_of(records: list) -> str | None:
    nodes = nodes_of(records)
    assert nodes, records
    return nodes[0].get("run")


def states_of(records: list, node_id: str | None) -> list:
    return [r for r in records if r.get("kind") == "state" and r.get("node") == node_id]


def session_lines_of(records: list, node_id: str | None) -> list:
    return [
        r for r in records if r.get("kind") == "session" and r.get("node") == node_id
    ]


def captures_of(capture: Path) -> list:
    assert capture.exists(), "the fake harness never ran"
    rows = []
    for line in capture.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    assert rows, "the fake harness recorded no invocation"
    return rows


def error_lines_of(state: Path) -> list:
    path = state / "error.log"
    assert path.exists(), f"no error log at {path}"
    rows = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


OC_MODEL = "opencode-go/deepseek-v4.1-flash"
OC_SESSION = "ses_ea6b71557ffeZT1KD9BtS3vm6s"
OC_VARIANT = "max"
OC_ROWS = json.loads((FIXTURES / "opencode-session-rows.json").read_text())


def fake_opencode_body(
    capture: Path,
    *,
    run_fixture: Path | None = None,
    models_fixture: Path | None = None,
    extra_event: dict | None = None,
    skip_tail: int = 0,
    strip_session_id: bool = False,
    stderr_text: str = "",
    rc: int = 0,
    sleep_s: float = 0.0,
    pid_file: Path | None = None,
    child_pid_file: Path | None = None,
) -> str:
    if run_fixture is None:
        run_fixture = FIXTURES / "opencode-new.jsonl"
    if models_fixture is None:
        models_fixture = FIXTURES / "opencode-models.txt"
    constants = "\n".join(
        [
            f"CAPTURE = {str(capture)!r}",
            f"RUN_FIXTURE = {str(run_fixture)!r}",
            f"MODELS_FIXTURE = {str(models_fixture)!r}",
            f"EXTRA_EVENT = {extra_event!r}",
            f"SKIP_TAIL = {skip_tail!r}",
            f"STRIP_SESSION_ID = {strip_session_id!r}",
            f"STDERR_TEXT = {stderr_text!r}",
            f"RC = {rc!r}",
            f"SLEEP_S = {sleep_s!r}",
            f"PID_FILE = {None if pid_file is None else str(pid_file)!r}",
            (
                "CHILD_PID_FILE = "
                f"{None if child_pid_file is None else str(child_pid_file)!r}"
            ),
        ]
    )
    body = """
import json, os, stat, subprocess, sys, time
from pathlib import Path

CAPTURE = Path(CAPTURE)

argv = sys.argv[1:]
try:
    stdin_devnull = (
        stat.S_ISCHR(os.fstat(0).st_mode)
        and os.fstat(0).st_rdev == os.stat(\"/dev/null\").st_rdev
    )
except OSError:
    stdin_devnull = False
CAPTURE.parent.mkdir(parents=True, exist_ok=True)
with CAPTURE.open(\"a\") as fh:
    fh.write(
        json.dumps(
            {
                \"argv\": argv,
                \"env\": dict(os.environ),
                \"cwd\": os.getcwd(),
                \"stdin_is_devnull\": stdin_devnull,
            }
        )
        + \"\\n\"
    )
if argv and argv[0] == \"models\":
    sys.stdout.write(Path(MODELS_FIXTURE).read_text())
    sys.stdout.flush()
    sys.exit(0)
if PID_FILE:
    Path(PID_FILE).write_text(str(os.getpid()))
if CHILD_PID_FILE:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(CHILD_PID_FILE).write_text(str(child.pid))
lines = []
if RUN_FIXTURE:
    lines = Path(RUN_FIXTURE).read_text().splitlines()
    if SKIP_TAIL:
        lines = lines[: len(lines) - SKIP_TAIL]
events = [json.loads(line) for line in lines if line.strip()]
if EXTRA_EVENT is not None:
    events.append(EXTRA_EVENT)
if STRIP_SESSION_ID:
    for event in events:
        event.pop(\"sessionID\", None)
for event in events:
    sys.stdout.write(json.dumps(event) + \"\\n\")
sys.stdout.flush()
if SLEEP_S:
    time.sleep(SLEEP_S)
if STDERR_TEXT:
    sys.stderr.write(STDERR_TEXT)
sys.exit(RC)
"""
    return "#!" + sys.executable + "\n" + constants + "\n" + body


def install_fake_opencode(
    bin_dir: Path, capture: Path, *, name: str = "opencode", **kwargs
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(fake_opencode_body(capture, **kwargs))
    stub.chmod(0o755)
    return stub


def write_opencode_profiles(
    root: Path,
    *,
    name: str = PROFILE,
    model: str | None = OC_MODEL,
    opencode_config: Path | str | None = None,
    variant: str | None = None,
    binary: str | None = None,
    env_pass: list | None = None,
    gate: str | None = None,
) -> Path:
    profile = {
        "name": name,
        "adapter": "opencode",
        "provider": "opencode",
        "billing": "subscription",
        "enabled": True,
    }
    if model is not None:
        profile["model"] = model
    if opencode_config is not None:
        profile["opencode_config"] = str(opencode_config)
    if variant is not None:
        profile["variant"] = variant
    if binary is not None:
        profile["binary"] = binary
    if env_pass is not None:
        profile["env_pass"] = env_pass
    if gate is not None:
        profile["gate"] = gate
    path = root / "profiles.json"
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


def seed_session_db(db_path: Path, rows: list) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute("CREATE TABLE session (id TEXT, model TEXT)")
        conn.executemany("INSERT INTO session (id, model) VALUES (?, ?)", rows)
    conn.close()


def make_opencode_root(
    tmp_path: Path,
    *,
    run_fixture: Path | None = None,
    models_fixture: Path | None = None,
    extra_event: dict | None = None,
    skip_tail: int = 0,
    strip_session_id: bool = False,
    stderr_text: str = "",
    rc: int = 0,
    sleep_s: float = 0.0,
    pid_file: Path | None = None,
    child_pid_file: Path | None = None,
    seed_rows: str | None = "match",
    model: str | None = OC_MODEL,
    opencode_config: bool = True,
    variant: str | None = None,
    binary: str | None = None,
    env_pass: list | None = None,
    gate: str | None = None,
) -> SimpleNamespace:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "work").mkdir()
    capture = tmp_path / "capture" / "opencode.jsonl"
    install_fake_opencode(
        tmp_path / "bin",
        capture,
        run_fixture=run_fixture,
        models_fixture=models_fixture,
        extra_event=extra_event,
        skip_tail=skip_tail,
        strip_session_id=strip_session_id,
        stderr_text=stderr_text,
        rc=rc,
        sleep_s=sleep_s,
        pid_file=pid_file,
        child_pid_file=child_pid_file,
    )
    config = tmp_path / "opencode.json"
    if opencode_config:
        config.write_text("{}\n")
    xdg_data = tmp_path / "xdg-data"
    xdg_data.mkdir()
    xdg_config = tmp_path / "xdg-config"
    xdg_config.mkdir()
    db_path = xdg_data / "opencode" / "opencode.db"
    if seed_rows == "match":
        rows = [(r["id"], r["model"]) for r in OC_ROWS if r["id"] == OC_SESSION]
        seed_session_db(db_path, rows)
    elif seed_rows == "mismatch":
        bad = next(r for r in OC_ROWS if r["id"] != OC_SESSION)
        seed_session_db(
            db_path, [(OC_SESSION, bad["model"]), (bad["id"], bad["model"])]
        )
    elif seed_rows == "other":
        rows = [(r["id"], r["model"]) for r in OC_ROWS if r["id"] != OC_SESSION]
        seed_session_db(db_path, rows)
    profiles = write_opencode_profiles(
        tmp_path,
        model=model,
        opencode_config=config,
        variant=variant,
        binary=binary,
        env_pass=env_pass,
        gate=gate,
    )
    return SimpleNamespace(
        root=tmp_path,
        home=home,
        work=tmp_path / "work",
        capture=capture,
        profiles=profiles,
        state=tmp_path / "state",
        config=config,
        xdg_data=xdg_data,
        xdg_config=xdg_config,
        db_path=db_path,
        env_extra={"XDG_DATA_HOME": str(xdg_data), "XDG_CONFIG_HOME": str(xdg_config)},
    )


def run_oc_call(
    ns: SimpleNamespace,
    *,
    session: str = "new",
    args: tuple = (),
    env_extra: dict | None = None,
    timeout: int = 30,
):
    merged = dict(ns.env_extra)
    merged.update(env_extra or {})
    return run_call(ns, session=session, args=args, env_extra=merged, timeout=timeout)


def run_captures_of(capture: Path) -> list:
    return [
        row for row in captures_of(capture) if (row.get("argv") or [None])[0] == "run"
    ]


def gate_env(readings: Path, poll_s: str = "0.2") -> dict:
    return {
        "TRINITY_GATE_READINGS": str(readings),
        "TRINITY_GATE_POLL_S": poll_s,
    }


def gate_checks(records: list) -> list:
    return [
        r
        for r in records
        if r.get("kind") == "check" and r.get("check") == "memory_gate"
    ]


def pid_is_live(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        proc = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return True
    if proc.returncode != 0 or not proc.stdout.strip():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return not proc.stdout.strip().startswith("Z")

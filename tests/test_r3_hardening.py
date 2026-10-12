"""Hardening: redaction refusals, prompt encoding, huge quota, mismatch log.

These tests pin fail-closed behaviour for sharp edges found in review:
caller labels that the redaction function would change are refused; an invalid
UTF-8 prompt file is refused like a missing one; a quota source that answers
with an integer too large for a float must not crash the call; and a session
mismatch records run, node and one-way fingerprints instead of a raw id.

Every value is synthetic and built at test time; HOME and the state root are
always temp directories. No test reads a real credential file, and none touches
the network.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "bin" / "trinity"
PROFILE = "pilot"
MODEL = "pilot-model"
WRAPPER = "claude-code"
# A session id the fake harness reports instead of the one it was assigned.
REPORTED_ID = "00000000-0000-4000-8000-000000000000"


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o755)
    return path


def _iso_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _last_json(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _write_executable_stub(path: Path, body: str) -> Path:
    return _executable(path, f"#!{sys.executable}\n{body}")


def _ok_quota_stub(tmp_path: Path, name: str = "quota_stub") -> Path:
    return _write_executable_stub(
        tmp_path / name,
        "import json, datetime\n"
        "print(json.dumps({'used_pct': 20, 'read_at': "
        "datetime.datetime.now(datetime.timezone.utc).isoformat()}))\n",
    )


def _write_profiles(
    tmp_path: Path,
    *,
    quota_command: str,
    freshness=300,
    name: str = "profiles.json",
) -> Path:
    profile = {
        "name": PROFILE,
        "adapter": "claude-code",
        "provider": "claude-code",
        "billing": "subscription",
        "model": MODEL,
        "credential_source": {"wrapper": WRAPPER},
        "quota_source": {"kind": "vendor_cli", "command": quota_command},
        "freshness_limit": freshness,
        "transcript_retention": "30 days",
        "enabled": True,
    }
    path = tmp_path / name
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


# --- shape builders (all synthetic, assembled here) --------------------------


def _synthetic_secret() -> str:
    return "cred-" + ("A1b2C3d4" * 3)


def _redaction_shapes() -> list[dict]:
    secret = _synthetic_secret()
    return [
        {
            "tag": "member-quoted-both",
            "text": f"'password': '{secret}'",
            "secret": secret,
        },
        {
            "tag": "member-single-plain",
            "text": f"'password': {secret}",
            "secret": secret,
        },
        {
            "tag": "member-double-plain",
            "text": f'"api_key": {secret}',
            "secret": secret,
        },
        {
            "tag": "member-unquoted-key",
            "text": f'api_key: "{secret}"',
            "secret": secret,
        },
        {
            "tag": "member-quoted-spaces",
            "text": f"'password': 'lead {secret} trail'",
            "secret": secret,
        },
        {
            "tag": "member-escaped-quote",
            "text": f'"password": "ab\\"{secret}"',
            "secret": secret,
        },
        {
            "tag": "url-user",
            "text": f"https://user:{secret}@example.invalid/x",
            "secret": secret,
        },
        {
            "tag": "url-empty-user",
            "text": f"https://:{secret}@example.invalid/x",
            "secret": secret,
        },
    ]


def _entropy_token() -> str:
    return "".join(["aB3dE7", "gH1jK4", "mN8pQ2", "sT6vW9", "yZ0cF5", "iL"])


def _hex_commit_id() -> str:
    return "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"


def _bits_per_char(text: str) -> float:
    counts = Counter(text)
    total = len(text)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


# --- 1. caller labels the redaction function would change are refused --------


def _refused(tmp_path, monkeypatch, value, field, tag):
    import scripts.trinity_core as core

    state = tmp_path / f"state-{tag}"
    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    profiles = _write_profiles(
        tmp_path,
        quota_command=str(tmp_path / "no-such-quota"),
        name=f"profiles-{tag}.json",
    )
    result = core.call(
        {
            "profiles_path": str(profiles),
            "profile": PROFILE,
            "step": "root",
            "session": "new",
            "prompt": {"text": "x"},
            "cwd": str(tmp_path),
            field: value,
        }
    )
    assert result["exit_class"] == "bad_request", (field, value, result)
    assert not (state / "journal.jsonl").exists(), (field, value)


def test_secret_shapes_are_refused_and_journal_stays_empty(tmp_path, monkeypatch):
    for shape in _redaction_shapes():
        for field in ("step", "label"):
            _refused(
                tmp_path, monkeypatch, shape["text"], field, f"{shape['tag']}-{field}"
            )


def test_entropy_shape_is_refused_and_journal_stays_empty(tmp_path, monkeypatch):
    token = _entropy_token()
    assert 32 <= len(token) <= 64, token
    assert re.fullmatch(r"[A-Za-z0-9_+=-]{32,64}", token), token
    assert any(char.isalpha() for char in token), token
    assert any(char.isdigit() for char in token), token
    assert _bits_per_char(token) >= 4.2, _bits_per_char(token)
    for field in ("step", "label"):
        _refused(tmp_path, monkeypatch, token, field, f"entropy-{field}")


def test_redaction_function_removes_the_whole_secret_from_each_shape():
    from scripts.trinity_core import journal

    values = _redaction_shapes() + [
        {"tag": "entropy", "text": _entropy_token(), "secret": _entropy_token()}
    ]
    for shape in values:
        out = journal.redact(shape["text"])
        assert journal.would_redact(shape["text"]) is True, shape["tag"]
        assert shape["secret"] not in out, (shape["tag"], out)
        assert out != shape["text"], shape["tag"]


def test_ordinary_values_stay_accepted():
    from scripts.trinity_core import journal

    for value in (_hex_commit_id(), "max_tokens-report"):
        assert journal.would_redact(value) is False, value
        assert journal.redact(value) == value, value


def _assignment_lines() -> list[dict]:
    secret = _synthetic_secret()
    return [
        {
            "tag": "ordinary-then-secret",
            "text": f"status=ok password={secret}",
            "secret": secret,
            "keep": ["status=ok", "status", "ok"],
        },
        {
            "tag": "numeric-then-secret",
            "text": f"max_tokens=100 api_key={secret}",
            "secret": secret,
            "keep": ["max_tokens=100"],
        },
        {
            "tag": "secret-in-middle",
            "text": f"a=1 b=2 token={secret} c=3",
            "secret": secret,
            "keep": ["a=1", "b=2", "c=3"],
        },
        {
            "tag": "secret-then-ordinary",
            "text": f"password={secret} status=ok",
            "secret": secret,
            "keep": ["status=ok", "status", "ok"],
        },
    ]


def test_assignment_masks_only_the_secret_and_keeps_ordinary_pairs():
    from scripts.trinity_core import journal

    for case in _assignment_lines():
        out = journal.redact(case["text"])
        assert journal.would_redact(case["text"]) is True, case["tag"]
        assert case["secret"] not in out, (case["tag"], out)
        for token in case["keep"]:
            assert token in out, (case["tag"], token, out)


def test_assignment_lines_are_refused_and_journal_stays_empty(tmp_path, monkeypatch):
    for case in _assignment_lines():
        for field in ("step", "label"):
            _refused(
                tmp_path, monkeypatch, case["text"], field, f"{case['tag']}-{field}"
            )


def test_ordinary_multi_pair_line_is_unchanged_and_accepted(tmp_path, monkeypatch):
    from scripts.trinity_core import journal
    import scripts.trinity_core as core

    line = "status=ok max_tokens=100"
    assert journal.would_redact(line) is False, line
    assert journal.redact(line) == line, line

    state = tmp_path / "state"
    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    profiles = _write_profiles(tmp_path, quota_command=str(tmp_path / "no-such-quota"))
    result = core.call(
        {
            "profiles_path": str(profiles),
            "profile": PROFILE,
            "step": "root",
            "session": "new",
            "prompt": {"text": "x"},
            "cwd": str(tmp_path),
            "label": line,
        }
    )
    assert result["exit_class"] != "bad_request", result


def _edge_a() -> str:
    return "cred-" + ("Q1w2E3r4" * 2)


def _edge_b() -> str:
    return "cred-" + ("Z9y8X7w6" * 2)


def _quoted_edge_shapes() -> list[dict]:
    a = _edge_a()
    b = _edge_b()
    return [
        {"tag": "double-unterminated", "text": f'password="{a}', "secrets": [a]},
        {"tag": "single-unterminated", "text": f"password='{a}", "secrets": [a]},
        {"tag": "concat-double", "text": f'password={a}"{b}"', "secrets": [a, b]},
        {"tag": "concat-mixed", "text": f"password=\"{a}\"'{b}'", "secrets": [a, b]},
    ]


def _inner_secret_shapes() -> list[dict]:
    secret = _synthetic_secret()
    return [
        {
            "tag": "inner-double",
            "text": f'message="hello password={secret}"',
            "secret": secret,
        },
        {
            "tag": "inner-single",
            "text": f"message='hello password={secret}'",
            "secret": secret,
        },
    ]


def test_quoted_edge_assignments_remove_every_secret_part():
    from scripts.trinity_core import journal

    for case in _quoted_edge_shapes():
        out = journal.redact(case["text"])
        assert journal.would_redact(case["text"]) is True, case["tag"]
        for secret in case["secrets"]:
            assert secret not in out, (case["tag"], secret, out)


def test_quoted_edge_assignments_are_refused_and_journal_stays_empty(
    tmp_path, monkeypatch
):
    for case in _quoted_edge_shapes():
        for field in ("step", "label"):
            _refused(
                tmp_path, monkeypatch, case["text"], field, f"{case['tag']}-{field}"
            )


def test_secret_inside_a_quoted_ordinary_value_is_masked():
    from scripts.trinity_core import journal

    for case in _inner_secret_shapes():
        out = journal.redact(case["text"])
        assert journal.would_redact(case["text"]) is True, case["tag"]
        assert case["secret"] not in out, (case["tag"], out)
        assert "message" in out, (case["tag"], out)


def test_secret_inside_a_quoted_ordinary_value_is_refused(tmp_path, monkeypatch):
    for case in _inner_secret_shapes():
        for field in ("step", "label"):
            _refused(
                tmp_path, monkeypatch, case["text"], field, f"{case['tag']}-{field}"
            )


def test_ordinary_step_and_label_are_not_refused(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    for tag, value in (("hex", _hex_commit_id()), ("word", "max_tokens-report")):
        state = tmp_path / f"state-{tag}"
        monkeypatch.setenv("TRINITY_ROOT", str(state))
        monkeypatch.delenv("TRINITY_GUARD", raising=False)
        profiles = _write_profiles(
            tmp_path,
            quota_command=str(tmp_path / "no-such-quota"),
            name=f"profiles-{tag}.json",
        )
        result = core.call(
            {
                "profiles_path": str(profiles),
                "profile": PROFILE,
                "step": "root",
                "session": "new",
                "prompt": {"text": "x"},
                "cwd": str(tmp_path),
                "label": value,
            }
        )
        assert result["exit_class"] != "bad_request", (value, result)


# --- 2. an invalid UTF-8 prompt file is refused ------------------------------


def test_invalid_utf8_prompt_file_is_refused_without_journal(tmp_path, monkeypatch):
    import scripts.trinity_core as core

    state = tmp_path / "state"
    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    profiles = _write_profiles(tmp_path, quota_command=str(tmp_path / "no-such-quota"))
    prompt_file = tmp_path / "prompt.bin"
    prompt_file.write_bytes(b"task \xff\xfe not utf-8")

    raised = None
    result = None
    try:
        result = core.call(
            {
                "profiles_path": str(profiles),
                "profile": PROFILE,
                "step": "root",
                "session": "new",
                "prompt": {"file": str(prompt_file)},
                "cwd": str(tmp_path),
            }
        )
    except Exception as exc:
        raised = exc
    assert raised is None, f"dispatch raised {raised!r} instead of refusing"
    assert result["exit_class"] == "bad_request", result
    assert not (state / "journal.jsonl").exists()


# --- 3. a quota value too large for a float must not crash the call ----------


def _cli_env(tmp_path: Path) -> dict:
    venv_bin = str(Path(sys.executable).resolve().parent)
    env = dict(os.environ)
    env.pop("TRINITY_GUARD", None)
    env.update(
        {
            "PATH": os.pathsep.join(
                [str(tmp_path / "bin"), venv_bin, "/usr/bin", "/bin"]
            ),
            "HOME": str(tmp_path / "home"),
            "TRINITY_ROOT": str(tmp_path / "state"),
        }
    )
    return env


def _run_call(tmp_path: Path, profiles: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
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
            "x",
        ],
        cwd=REPO,
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _check_records(tmp_path: Path) -> list[dict]:
    from scripts.trinity_core import journal

    return [
        record
        for record in journal.read(tmp_path / "state")
        if record.get("kind") == "check"
    ]


def test_huge_used_pct_does_not_crash_and_is_unknown(tmp_path):
    stub = _write_executable_stub(
        tmp_path / "quota_huge_used",
        "import json, datetime\n"
        "print(json.dumps({'used_pct': 10 ** 400, 'read_at': "
        "datetime.datetime.now(datetime.timezone.utc).isoformat()}))\n",
    )
    profiles = _write_profiles(
        tmp_path, quota_command=str(stub), name="profiles-huge-used.json"
    )
    proc = _run_call(tmp_path, profiles)
    assert "Traceback" not in proc.stderr, proc.stderr
    result = _last_json(proc.stdout)
    assert result and result["exit_class"] == "check_failed", (
        proc.returncode,
        proc.stdout,
        proc.stderr,
    )
    checks = _check_records(tmp_path)
    assert checks and checks[0].get("result") == "unknown", checks


def test_huge_freshness_limit_does_not_crash_and_is_unknown(tmp_path):
    stub = _ok_quota_stub(tmp_path)
    profiles = _write_profiles(
        tmp_path,
        quota_command=str(stub),
        freshness=10**400,
        name="profiles-huge-freshness.json",
    )
    proc = _run_call(tmp_path, profiles)
    assert "Traceback" not in proc.stderr, proc.stderr
    result = _last_json(proc.stdout)
    assert result and result["exit_class"] == "check_failed", (
        proc.returncode,
        proc.stdout,
        proc.stderr,
    )
    checks = _check_records(tmp_path)
    assert checks and checks[0].get("result") == "unknown", checks


# --- 4. a session mismatch logs run, node and fingerprints, never the id -----


def _mismatch_harness(profiles_path: Path) -> str:
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, os, subprocess, sys

        CLI = {str(CLI)!r}
        PROFILES = {str(profiles_path)!r}
        REPORTED = {REPORTED_ID!r}

        guard = {{}}
        try:
            guard = json.loads(os.environ.get("TRINITY_GUARD") or "{{}}")
        except ValueError:
            guard = {{}}
        if int(guard.get("depth", 0)) == 0:
            subprocess.run(
                [CLI, "call", "--profiles", PROFILES, "--profile", {PROFILE!r},
                 "--step", "child", "--session", "new", "--prompt", "child task"],
                env=os.environ.copy(), capture_output=True,
            )
        sys.stdout.write(json.dumps({{
            "type": "result", "is_error": False, "session_id": REPORTED,
        }}) + "\\n")
        """
    )


def test_mismatch_log_keeps_run_node_and_fingerprints_without_raw_id(
    tmp_path, monkeypatch
):
    from scripts.trinity_core import journal

    work = tmp_path / "work"
    work.mkdir()
    quota = _ok_quota_stub(tmp_path)
    profiles = _write_profiles(
        tmp_path, quota_command=str(quota), name="profiles-mismatch.json"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = _mismatch_harness(profiles)
    _executable(bin_dir / "claude", script)
    _executable(bin_dir / WRAPPER, script)

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
            "root task",
            "--cwd",
            str(work),
            "--allow-nesting-max-depth",
            "1",
        ],
        cwd=REPO,
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    result = _last_json(proc.stdout)
    assert result and result.get("run"), (proc.returncode, proc.stdout, proc.stderr)
    run_id = result["run"]

    nodes = [
        record
        for record in journal.read(tmp_path / "state")
        if record.get("kind") == "node" and record.get("run") == run_id
    ]
    assert len(nodes) == 2, nodes

    error_path = tmp_path / "state" / "error.log"
    assert error_path.exists(), (proc.stdout, proc.stderr)
    error_text = error_path.read_text()
    errors = [json.loads(line) for line in error_text.splitlines() if line.strip()]
    by_node = {record.get("node"): record for record in errors}

    reported_fp = hashlib.sha256(REPORTED_ID.encode()).hexdigest()[:12]
    for node in nodes:
        record = by_node.get(node["node"])
        assert record is not None, (node["node"], errors)
        assert record.get("run") == run_id, record
        assert record.get("reported_fp") == reported_fp, record
        assigned = node["session"]["id"]
        assigned_fp = hashlib.sha256(assigned.encode()).hexdigest()[:12]
        assert record.get("assigned_fp") == assigned_fp, record

    journal_bytes = (tmp_path / "state" / "journal.jsonl").read_bytes()
    assert REPORTED_ID.encode() not in journal_bytes
    assert REPORTED_ID not in error_text


SURROGATE_REPORTED = "\ud800"


def _surrogate_harness() -> str:
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        REPORTED = "\\ud800"
        sys.stdout.write(json.dumps({{
            "type": "result", "is_error": False, "session_id": REPORTED,
        }}) + "\\n")
        """
    )


def test_surrogate_reported_session_id_logs_attributable_failure(tmp_path):
    from scripts.trinity_core import journal

    work = tmp_path / "work"
    work.mkdir()
    quota = _ok_quota_stub(tmp_path)
    profiles = _write_profiles(
        tmp_path, quota_command=str(quota), name="profiles-surrogate.json"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / WRAPPER, _surrogate_harness())

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
            "x",
            "--cwd",
            str(work),
            "--allow-nesting-max-depth",
            "1",
        ],
        cwd=REPO,
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    result = _last_json(proc.stdout)
    assert result and result["exit_class"] == "harness_error", (
        proc.returncode,
        proc.stdout,
        proc.stderr,
    )
    run_id = result["run"]

    states = [
        record
        for record in journal.read(tmp_path / "state")
        if record.get("kind") == "state" and record.get("run") == run_id
    ]
    assert states and states[-1].get("state") == "failed", states

    error_text = (tmp_path / "state" / "error.log").read_text()
    errors = [json.loads(line) for line in error_text.splitlines() if line.strip()]
    record = errors[-1]
    assert record.get("run") == run_id, record
    assert record.get("node") == result["node"], record
    assert record.get("assigned_fp"), record
    expected = hashlib.sha256(
        SURROGATE_REPORTED.encode("utf-8", "surrogatepass")
    ).hexdigest()[:12]
    assert record.get("reported_fp") == expected, record
    assert SURROGATE_REPORTED not in error_text

"""Tests for trinity/scripts/session.py"""

import json
import subprocess
import sys
import re
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "session.py"


def run(args, input_data=None):
    """Run the session script with given args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        input=input_data,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def trinity_path(project_dir):
    return Path(project_dir) / ".claude" / "trinity.json"


# --- read ---


def test_read_returns_new_when_file_absent(tmp_path):
    rc, out, err = run(["read", str(tmp_path), "glm"])
    assert rc == 0
    assert out == "NEW"


def test_read_returns_new_when_key_absent(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"sessions": {"other": {"session_id": "abc"}}}))
    rc, out, err = run(["read", str(tmp_path), "glm"])
    assert rc == 0
    assert out == "NEW"


def test_read_returns_session_id_when_key_present(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"sessions": {"glm": {"session_id": "sess-123", "task_summary": "test"}}}
        )
    )
    rc, out, err = run(["read", str(tmp_path), "glm"])
    assert rc == 0
    assert out == "sess-123"


def test_read_exits_1_on_corrupt_json(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json }")
    rc, out, err = run(["read", str(tmp_path), "glm"])
    assert rc == 1
    assert err  # should have error message on stderr


def test_read_exits_1_on_whitespace_only_file(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("   \n   ")
    rc, out, err = run(["read", str(tmp_path), "glm"])
    assert rc == 1
    assert "empty file" in err


# --- write ---


def test_write_creates_file_if_absent(tmp_path):
    rc, out, err = run(["write", str(tmp_path), "glm", "sess-abc", "my task"])
    assert rc == 0
    p = trinity_path(tmp_path)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["sessions"]["glm"]["session_id"] == "sess-abc"
    assert "last_used" in data["sessions"]["glm"]
    assert re.match(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["sessions"]["glm"]["last_used"]
    )


def test_write_preserves_existing_providers_and_defaults(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "providers": {"codex": {"cli": "codex exec"}},
                "defaults": {"timeout": 120},
                "sessions": {},
            }
        )
    )
    rc, out, err = run(["write", str(tmp_path), "glm", "sess-xyz", "task summary"])
    assert rc == 0
    data = json.loads(p.read_text())
    assert data["providers"]["codex"]["cli"] == "codex exec"
    assert data["defaults"]["timeout"] == 120
    assert data["sessions"]["glm"]["session_id"] == "sess-xyz"


def test_write_handles_task_summary_with_spaces_and_newlines(tmp_path):
    summary = "task with spaces\nand newlines"
    rc, out, err = run(["write", str(tmp_path), "glm", "sess-nl", summary])
    assert rc == 0
    p = trinity_path(tmp_path)
    data = json.loads(p.read_text())
    assert data["sessions"]["glm"]["task_summary"] == summary


def test_write_concurrent_no_corruption(tmp_path):
    """Two processes writing different keys concurrently should not corrupt data."""
    import concurrent.futures

    def do_write(key, session_id):
        return run(["write", str(tmp_path), key, session_id, f"task for {key}"])

    for _ in range(20):
        # Clear file between iterations to test from-scratch creation as well
        p = trinity_path(tmp_path)
        if p.exists():
            p.unlink()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_write, "glm", "sess-glm")
            f2 = executor.submit(do_write, "codex", "sess-codex")
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == 0
        assert r2[0] == 0

        p = trinity_path(tmp_path)
        data = json.loads(p.read_text())
        assert data["sessions"]["glm"]["session_id"] == "sess-glm"
        assert data["sessions"]["codex"]["session_id"] == "sess-codex"


# --- clear ---


def test_clear_removes_specific_key(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "sessions": {
                    "glm": {"session_id": "sess-1"},
                    "codex": {"session_id": "sess-2"},
                }
            }
        )
    )
    rc, out, err = run(["clear", str(tmp_path), "glm"])
    assert rc == 0
    data = json.loads(p.read_text())
    assert "glm" not in data["sessions"]
    assert data["sessions"]["codex"]["session_id"] == "sess-2"


def test_clear_all_empties_sessions_preserves_rest(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "providers": {"glm": {"cli": "droid exec --model glm-5"}},
                "defaults": {"timeout": 60},
                "sessions": {
                    "glm": {"session_id": "sess-1"},
                    "codex": {"session_id": "sess-2"},
                },
            }
        )
    )
    rc, out, err = run(["clear", str(tmp_path), "all"])
    assert rc == 0
    data = json.loads(p.read_text())
    assert data["sessions"] == {}
    assert data["providers"]["glm"]["cli"] == "droid exec --model glm-5"
    assert data["defaults"]["timeout"] == 60


def test_clear_exits_1_on_corrupt_json(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json }")
    rc, out, err = run(["clear", str(tmp_path), "glm"])
    assert rc == 1
    assert err  # should have error message on stderr


def test_clear_on_absent_key_is_noop(tmp_path):
    p = trinity_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"sessions": {"codex": {"session_id": "sess-2"}}}))
    rc, out, err = run(["clear", str(tmp_path), "glm"])
    assert rc == 0
    data = json.loads(p.read_text())
    assert data["sessions"]["codex"]["session_id"] == "sess-2"


# --- heartbeat ---


def test_heartbeat_file_not_found(tmp_path):
    rc, out, err = run(["heartbeat", str(tmp_path / "nonexistent.output")])
    assert rc == 0
    assert out == "FILE_NOT_FOUND"


def test_heartbeat_empty_file(tmp_path):
    f = tmp_path / "empty.output"
    f.write_text("")
    rc, out, err = run(["heartbeat", str(f)])
    assert rc == 0
    assert "0 lines" in out
    assert "no assistant activity" in out


def test_heartbeat_finds_tool_use(tmp_path):
    f = tmp_path / "agent.output"
    lines = [
        json.dumps({"type": "user", "message": {"content": "hello"}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "pytest tests/"},
                        }
                    ]
                },
            }
        ),
    ]
    f.write_text("\n".join(lines) + "\n")
    rc, out, err = run(["heartbeat", str(f)])
    assert rc == 0
    assert "2 lines" in out
    assert "tool: Bash" in out
    assert "pytest" in out


def test_heartbeat_finds_text(tmp_path):
    f = tmp_path / "agent.output"
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Analysis complete."}]
                },
            }
        ),
    ]
    f.write_text("\n".join(lines) + "\n")
    rc, out, err = run(["heartbeat", str(f)])
    assert rc == 0
    assert "1 lines" in out
    assert "text: Analysis complete." in out


def test_heartbeat_skips_malformed_lines(tmp_path):
    f = tmp_path / "agent.output"
    lines = [
        "not json at all",
        json.dumps({"type": "user", "message": {}}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"path": "foo.py"},
                        }
                    ]
                },
            }
        ),
        "another bad line",
    ]
    f.write_text("\n".join(lines) + "\n")
    rc, out, err = run(["heartbeat", str(f)])
    assert rc == 0
    assert "tool: Read" in out


def test_heartbeat_no_assistant_messages(tmp_path):
    f = tmp_path / "agent.output"
    lines = [
        json.dumps({"type": "user", "message": {"content": "hello"}}),
        json.dumps({"type": "user", "message": {"content": "world"}}),
    ]
    f.write_text("\n".join(lines) + "\n")
    rc, out, err = run(["heartbeat", str(f)])
    assert rc == 0
    assert "2 lines" in out
    assert "no assistant activity" in out


# --- version ---


def test_version_returns_parseable_semver():
    rc, out, err = run(["--version"])
    assert rc == 0
    parts = out.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)

"""A dispatch call runs without any quota check.

One test per REQ acceptance case. Each fails on base (0329304) by
AssertionError because the quota gate refuses every profile that does not
carry a fresh `quota_source`, so the harness never runs. On GREEN (the gate
block deleted) each passes.

The fake-harness pattern comes from tests/test_first_path.py: a `claude-code`
wrapper stub on PATH answers `core.call({...})` with `TRINITY_ROOT` in
tmp_path. The stub writes one line to a capture file per invocation, so the
tests can count runs. Quota is never imported here (GREEN deletes it).
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

PROFILE = "pilot"
MODEL = "pilot-model"
WRAPPER = "claude-code"

USAGE = {
    "input_tokens": 40000,
    "output_tokens": 8000,
    "tokens": 48000,
}

_RATE_LIMIT_RESULT = {
    "type": "result",
    "subtype": "error_during_execution",
    "is_error": True,
    "session_id": None,
    "result": "API Error: 429 rate limit exceeded",
    "usage": USAGE,
}


def _write_harness(bin_dir: Path, capture_file: Path, *, ok: bool) -> None:
    """A claude-code wrapper stub that records one line per invocation."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        from pathlib import Path

        CAPTURE = Path({str(capture_file)!r})
        RATE_LIMIT_RESULT = {repr(_RATE_LIMIT_RESULT)}

        argv = sys.argv[1:]
        session_id = None
        for i, a in enumerate(argv):
            if a == "--session-id" and i + 1 < len(argv):
                session_id = argv[i + 1]

        CAPTURE.parent.mkdir(parents=True, exist_ok=True)
        with CAPTURE.open("a") as fh:
            fh.write(json.dumps({{"session_id": session_id}}) + "\\n")

        if {ok}:
            result = {{
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": session_id,
                "result": "FIXTURE-OUTPUT-MARK",
                "usage": {repr(USAGE)},
            }}
            sys.stdout.write(json.dumps(result) + "\\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(json.dumps(RATE_LIMIT_RESULT) + "\\n")
            sys.stdout.flush()
            sys.exit(3)
        """
    )
    stub = bin_dir / WRAPPER
    stub.write_text(body)
    stub.chmod(0o755)


def _profiles_file(
    tmp_path: Path,
    *,
    quota_command: str | None = None,
    freshness_limit: int | None = None,
) -> Path:
    path = tmp_path / "profiles.json"
    profile = {
        "name": PROFILE,
        "adapter": "claude-code",
        "provider": "claude-code",
        "billing": "subscription",
        "model": MODEL,
        "credential_source": {"wrapper": WRAPPER},
        "transcript_retention": "30 days",
        "enabled": True,
    }
    if quota_command is not None:
        profile["quota_source"] = {"kind": "vendor_cli", "command": quota_command}
    if freshness_limit is not None:
        profile["freshness_limit"] = freshness_limit
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


@pytest.fixture()
def harness_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    capture_file = tmp_path / "capture" / "harness.jsonl"
    state = tmp_path / "state"
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    monkeypatch.setenv("TRINITY_HEARTBEAT_POLL_S", "1")
    return bin_dir, capture_file, state


def _call_core(tmp_path, profiles):
    import scripts.trinity_core as core

    return core.call(
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


def _journal_records(state: Path) -> list[dict]:
    from scripts.trinity_core import journal

    return journal.read(state)


def _quota_checks(records: list[dict]) -> list[dict]:
    return [
        r for r in records if r.get("kind") == "check" and r.get("check") == "quota"
    ]


# --- R1: a profile with no quota fields runs the harness ---------------------


def test_profile_without_quota_source_runs(tmp_path, harness_env):
    bin_dir, capture_file, state = harness_env
    _write_harness(bin_dir, capture_file, ok=True)
    profiles = _profiles_file(tmp_path)

    result = _call_core(tmp_path, profiles)

    assert result["exit_class"] == "ok", result
    assert result["journal_complete"] is True, result
    lines = capture_file.read_text().splitlines()
    assert len(lines) == 1, lines
    assert _quota_checks(_journal_records(state)) == []


# --- R2: a provider 429 lands on the existing unknown error path -------------


def test_provider_429_ends_on_existing_error_path(tmp_path, harness_env):
    bin_dir, capture_file, state = harness_env
    _write_harness(bin_dir, capture_file, ok=False)
    profiles = _profiles_file(tmp_path)

    result = _call_core(tmp_path, profiles)

    assert result["exit_class"] == "unknown", result
    assert result["journal_complete"] is True, result
    records = _journal_records(state)
    assert _quota_checks(records) == []
    states = [
        r
        for r in records
        if r.get("kind") == "state" and r.get("exit_class") == "unknown"
    ]
    assert states, records
    assert states[-1].get("usage") == USAGE, states[-1]


# --- R3: old quota fields are ignored, their command never runs --------------


def test_old_quota_fields_are_ignored(tmp_path, harness_env):
    bin_dir, capture_file, state = harness_env
    _write_harness(bin_dir, capture_file, ok=True)
    marker = tmp_path / "quota-ran"
    quota_command = tmp_path / "quota-command"
    quota_command.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            from datetime import datetime, timezone
            from pathlib import Path

            marker = Path({str(marker)!r})
            marker.touch()
            print(
                json.dumps(
                    {{"used_pct": 20, "read_at": datetime.now(timezone.utc).isoformat()}}
                )
            )
            """
        )
    )
    quota_command.chmod(0o755)
    profiles = _profiles_file(
        tmp_path,
        quota_command=str(quota_command),
        freshness_limit=300,
    )

    result = _call_core(tmp_path, profiles)

    assert not marker.exists(), "the old quota command ran"
    assert result["exit_class"] == "ok", result

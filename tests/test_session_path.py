"""Tests for trinity/scripts/session_path.py — CHG-3040.

Path-only contract tests:

- 5 happy-path tests: glm, codex-via-index, codex-via-glob-fallback,
  claude-family parameterized over (claude-code, deepseek, openrouter),
  gemini stub returns exit 3.
- 5 error-exit tests: no-pointer (exit 2), file-missing (exit 3),
  unknown-provider (exit 3), malformed session_id (exit 3),
  codex multi-glob residual (exit 3).
- Lookup-key normalization (parameterized): glm:default <-> glm happy
  path; glm:experimental passthrough.
- Path-only contract: patch all four read targets (`builtins.open`,
  `pathlib.Path.open`, `pathlib.Path.read_text`, `pathlib.Path.read_bytes`)
  and fail if any fires on a JSONL path during a happy-path resolve.
- codex session_index.jsonl malformed-line robustness.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the scripts directory importable so we can drive cmd_session_path
# directly (avoids subprocess overhead and keeps the path-only-contract
# mock-patch test possible — subprocess can't share mocked builtins).
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Each test gets its own fake $HOME, so probes never hit the real one."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Force-reload session_path so module-level imports see the patched HOME
    # via os.path.expanduser when constructing paths inside resolvers (we
    # don't actually need a reload because expanduser is called per-resolve,
    # but be explicit about the contract).
    yield fake_home


def _import_session_path():
    """Import the module under test; reload to pick up env changes if needed."""
    if "session_path" in sys.modules:
        del sys.modules["session_path"]
    if "session" in sys.modules:
        del sys.modules["session"]
    import session_path  # noqa: F401

    return sys.modules["session_path"]


def _write_pointer(project_dir: Path, sessions: dict) -> None:
    p = project_dir / ".claude" / "trinity.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"sessions": sessions}))


def _encoded(project_dir: Path) -> str:
    return str(project_dir.resolve()).replace("/", "-")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_glm_happy_path(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "abc123-session"
    _write_pointer(project, {"glm": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), "glm")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_codex_happy_via_index(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-codex-id"
    _write_pointer(project, {"codex": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    # Build dated transcript and matching index entry.
    day_dir = fake_home / ".codex" / "sessions" / "2026" / "04" / "26"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-04-26T07-32-42-{sid}.jsonl"
    transcript.write_text("")

    index_path = fake_home / ".codex" / "session_index.jsonl"
    index_path.write_text(
        json.dumps({"id": sid, "updated_at": "2026-04-26T07:32:42.000000Z"}) + "\n"
    )

    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_codex_happy_via_glob_fallback(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-glob-fallback"
    _write_pointer(project, {"codex": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    # No session_index.jsonl on disk; transcript exists under date bucket.
    day_dir = fake_home / ".codex" / "sessions" / "2026" / "01" / "15"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-01-15T08-00-00-{sid}.jsonl"
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_codex_index_malformed_line_falls_through_to_glob(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-malformed-robust"
    _write_pointer(project, {"codex": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    # Transcript exists under date bucket.
    day_dir = fake_home / ".codex" / "sessions" / "2026" / "02" / "20"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-02-20T08-00-00-{sid}.jsonl"
    transcript.write_text("")

    # Index has one valid entry pointing to a wrong date (so
    # day-dir glob inside _codex_index_lookup returns 0 matches),
    # plus one malformed line — both must NOT raise; resolver must
    # fall through to the broad glob and find the transcript.
    index_path = fake_home / ".codex" / "session_index.jsonl"
    index_path.write_text(
        "{this is not valid json\n"
        + json.dumps({"id": "other-id", "updated_at": "2026-02-20T08:00:00Z"})
        + "\n"
    )

    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


@pytest.mark.parametrize("provider", ["claude-code", "deepseek", "openrouter"])
def test_claude_family_happy_path(provider, tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = f"{provider}-session-xyz"
    _write_pointer(project, {provider: {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = fake_home / ".claude" / "projects" / _encoded(project) / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), provider)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_gemini_stub_returns_exit_3(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    _write_pointer(project, {"gemini": {"session_id": "g-1"}})

    rc = sp.cmd_session_path(str(project), "gemini")
    err = capsys.readouterr().err
    assert rc == 3
    assert err.strip() == "gemini transcript layout not yet supported (TRN-3040)"


# ---------------------------------------------------------------------------
# Error-exit tests
# ---------------------------------------------------------------------------


def test_no_pointer_file_returns_exit_2(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    # No .claude/trinity.json at all.
    rc = sp.cmd_session_path(str(project), "glm")
    err = capsys.readouterr().err
    assert rc == 2
    assert err.strip() == "no session pointer for 'glm'"


def test_pointer_present_but_key_missing_returns_exit_2(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    _write_pointer(project, {"codex": {"session_id": "c-1"}})
    rc = sp.cmd_session_path(str(project), "glm")
    err = capsys.readouterr().err
    assert rc == 2
    assert err.strip() == "no session pointer for 'glm'"


def test_file_missing_returns_exit_3(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    _write_pointer(project, {"glm": {"session_id": "missing-on-disk"}})
    # Do NOT create the transcript.
    rc = sp.cmd_session_path(str(project), "glm")
    out = capsys.readouterr()
    assert rc == 3
    assert "transcript file not found at " in out.err


def test_unknown_provider_returns_exit_3(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    _write_pointer(project, {"mystery": {"session_id": "abc"}})
    rc = sp.cmd_session_path(str(project), "mystery")
    err = capsys.readouterr().err
    assert rc == 3
    assert err.strip() == "provider 'mystery' not supported by session-path resolver"


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc/passwd",
        "abc/def",
        "abc def",
        "abc\tdef",
        "abc\ndef",
    ],
)
def test_malformed_session_id_returns_exit_3(bad_id, tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    _write_pointer(project, {"glm": {"session_id": bad_id}})
    rc = sp.cmd_session_path(str(project), "glm")
    err = capsys.readouterr().err
    assert rc == 3
    assert err.strip() == "invalid session_id format"
    # Threat Model: the malformed value MUST NOT be echoed.
    assert bad_id not in err


def test_codex_multi_glob_residual_returns_exit_3(tmp_path, capsys):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-collision"
    _write_pointer(project, {"codex": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    # Two transcripts on different days share the same session_id suffix.
    for date in [("2026", "01", "15"), ("2026", "02", "16")]:
        d = fake_home / ".codex" / "sessions" / date[0] / date[1] / date[2]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"rollout-x-{sid}.jsonl").write_text("")

    rc = sp.cmd_session_path(str(project), "codex")
    err = capsys.readouterr().err
    assert rc == 3
    assert err.strip() == f"multiple transcript files matched session_id '{sid}'"


# ---------------------------------------------------------------------------
# Lookup-key normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wrapper_key,trinity_key,should_resolve",
    [
        # `:default` strips at the wrapper layer. cmd_session_path itself
        # receives the canonicalized key, so we test the canonicalization
        # behavior at the codex.py wrapper level. Here we verify the
        # underlying lookup behavior:
        ("glm", "glm", True),
        ("glm:experimental", "glm:experimental", True),
        # Mismatch case: wrapper key not in pointer
        ("glm:experimental", "glm", False),
    ],
)
def test_lookup_key_normalization_at_resolver_level(
    wrapper_key, trinity_key, should_resolve, tmp_path, capsys
):
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "norm-test"
    _write_pointer(project, {trinity_key: {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), wrapper_key)
    if should_resolve:
        assert rc == 0
    else:
        assert rc == 2


def test_codex_wrapper_normalizes_default_suffix(tmp_path, monkeypatch, capsys):
    """End-to-end: codex.cmd_session_path strips ':default' to match the
    unsuffixed trinity.json key."""
    # Reuse the same import path as the rest of the project.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root / "scripts") not in sys.path:
        sys.path.insert(0, str(repo_root / "scripts"))
    if "codex" in sys.modules:
        del sys.modules["codex"]
    import codex as codex_mod

    project = tmp_path / "proj"
    project.mkdir()
    # Make project a git repo so resolve_root succeeds.
    import subprocess

    subprocess.run(["git", "init", "-q", str(project)], check=True)
    sid = "wrapper-norm"
    _write_pointer(project, {"glm": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    project_str = str(project)

    class _Args:
        provider_spec = "glm:default"
        project = project_str

    rc = codex_mod.cmd_session_path(_Args())
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


# ---------------------------------------------------------------------------
# Path-only contract: no JSONL is ever opened/read.
# ---------------------------------------------------------------------------


def test_path_only_contract_no_jsonl_read(tmp_path, capsys):
    """Patch all four read targets; fail if any fires on a JSONL path
    during a happy-path resolve.

    Pointer file (`.claude/trinity.json`) reads ARE allowed and go through
    the shared `_read_pointer` helper. The patch only fails on JSONL paths.
    """
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "path-only-contract"
    _write_pointer(project, {"glm": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    real_open = __builtins__["open"] if isinstance(__builtins__, dict) else open
    real_path_open = Path.open
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes

    violations: list[str] = []

    def _check_jsonl(arg, label):
        s = str(arg)
        if s.endswith(".jsonl"):
            violations.append(f"{label} on {s}")

    def fake_open(file, *a, **kw):
        _check_jsonl(file, "builtins.open")
        return real_open(file, *a, **kw)

    def fake_path_open(self, *a, **kw):
        _check_jsonl(self, "Path.open")
        return real_path_open(self, *a, **kw)

    def fake_read_text(self, *a, **kw):
        _check_jsonl(self, "Path.read_text")
        return real_read_text(self, *a, **kw)

    def fake_read_bytes(self, *a, **kw):
        _check_jsonl(self, "Path.read_bytes")
        return real_read_bytes(self, *a, **kw)

    with (
        mock.patch("builtins.open", side_effect=fake_open),
        mock.patch.object(Path, "open", autospec=True, side_effect=fake_path_open),
        mock.patch.object(Path, "read_text", autospec=True, side_effect=fake_read_text),
        mock.patch.object(
            Path, "read_bytes", autospec=True, side_effect=fake_read_bytes
        ),
    ):
        rc = sp.cmd_session_path(str(project), "glm")

    out = capsys.readouterr()
    assert rc == 0, out.err
    assert violations == [], (
        "Path-only contract violation — JSONL was opened/read: " + "; ".join(violations)
    )


def test_non_git_project_dir_resolves(tmp_path, monkeypatch):
    """`--project` pointing at a non-git directory carrying .claude/trinity.json
    must resolve, not exit-via-resolve_root. Per codex-bot R0 P2 finding on
    PR #119: session-path only needs the pointer file, never git toplevel.

    Uses resolve_health_root (graceful fallback) instead of resolve_root
    (which hard-exits on non-git via SystemExit). Inside a git tree, behavior
    is identical (resolve to toplevel); outside, the literal path is used.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import codex

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))

    non_git_proj = tmp_path / "scratch"
    non_git_proj.mkdir()
    sid = "non-git-test-id"
    _write_pointer(non_git_proj, {"glm": {"session_id": sid}})

    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(non_git_proj) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    class Args:
        project = str(non_git_proj)
        provider_spec = "glm"

    rc = codex.cmd_session_path(Args())
    assert rc == 0, f"non-git --project must resolve, got exit {rc}"

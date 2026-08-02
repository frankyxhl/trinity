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
import shutil
import subprocess
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
    """Each test gets its own fake $HOME, so probes never hit the real one.

    Also clears env-var overrides that affect resolver paths so a CI host
    with `CODEX_HOME` (or similar) set in the runner environment does not
    leak into test fixtures (per codex-bot R6 P2 finding 3214566835 — the
    bot environment exports `CODEX_HOME=/opt/codex`, which made the codex
    resolver bypass the fake `$HOME` and look under `/opt/codex/sessions`).
    Individual tests that want to set `CODEX_HOME` (e.g.
    test_codex_honors_codex_home_env_var) can re-set it via their own
    monkeypatch.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
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
    """GLM encoding (`~/.factory/sessions/...`): keep leading dash."""
    return str(project_dir.resolve()).replace("/", "-")


def _claude_slug(project_dir: Path) -> str:
    """Independent dynamic fixture encoder for Claude-family transcript paths.

    This mirrors Claude Code 2.1.220 UTF-16 behavior for temporary paths used
    by end-to-end resolver tests. Literal expected vectors below remain
    hardcoded and do not call this helper.
    """
    project_path = os.path.abspath(str(project_dir))
    encoded = project_path.encode("utf-16-le", errors="surrogatepass")
    units = [encoded[i] | (encoded[i + 1] << 8) for i in range(0, len(encoded), 2)]
    sanitized = "".join(
        chr(unit)
        if ord("0") <= unit <= ord("9")
        or ord("A") <= unit <= ord("Z")
        or ord("a") <= unit <= ord("z")
        else "-"
        for unit in units
    )
    if len(sanitized) <= 200:
        return sanitized

    hash_value = 0
    for unit in units:
        hash_value = (hash_value * 31 + unit) & 0xFFFFFFFF
    if hash_value >= 0x80000000:
        hash_value -= 0x100000000

    magnitude = abs(hash_value)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    suffix = "0"
    if magnitude:
        encoded_digits = []
        while magnitude:
            magnitude, remainder = divmod(magnitude, 36)
            encoded_digits.append(digits[remainder])
        suffix = "".join(reversed(encoded_digits))
    return sanitized[:200] + "-" + suffix


_CLAUDE_FAMILY_ROOTS = {
    "claude-code": ".claude-trinity-claude-code",
    "deepseek": ".claude-deepseek",
    "openrouter": ".claude-openrouter",
}


# Literal Claude Code 2.1.220 fixtures.  The expected values and base-36 hash
# suffixes are runtime-provenance constants, not outputs from test-side encoder
# logic.  Repetition only keeps the 200-unit boundary vectors readable.
_CLAUDE_2_1_220_SLUG_FIXTURES = [
    pytest.param(
        "/Users/frank/my_project",
        "-Users-frank-my-project",
        id="underscore",
    ),
    pytest.param(
        "/Users/frank/my.project",
        "-Users-frank-my-project",
        id="dot",
    ),
    pytest.param(
        "/Users/frank/my project",
        "-Users-frank-my-project",
        id="space",
    ),
    pytest.param("/a_b.c d!?", "-a-b-c-d--", id="punctuation"),
    pytest.param("/café/東京", "-caf----", id="bmp-unicode"),
    pytest.param("/rocket🚀/project", "-rocket---project", id="astral-unicode"),
    pytest.param("/Users/frank", "-Users-frank", id="leading-dash"),
    pytest.param(
        "/" + ("a" * 199),
        "-" + ("a" * 199),
        id="exactly-200-utf16-units",
    ),
    pytest.param(
        "/" + ("a" * 200),
        "-" + ("a" * 199) + "-b6ymvl",
        id="201-utf16-units",
    ),
    pytest.param(
        "/long/" + ("g" * 220),
        "-long-" + ("g" * 194) + "-2495lw",
        id="long-positive-signed-hash",
    ),
    pytest.param(
        "/long/" + ("a" * 220),
        "-long-" + ("a" * 194) + "-kh3ffg",
        id="long-negative-signed-hash",
    ),
    pytest.param(
        "/" + ("a" * 198) + "😀z",
        "-" + ("a" * 198) + "--92ehu0",
        id="astral-long-path",
    ),
]


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
    """Each claude-CLI wrapper has its own CLAUDE_CONFIG_DIR root + uses the
    canonical Claude Code 2.1.220 PROJECT_SLUG. Per providers/<name>.md:
    SESSION_DIR=$HOME/.claude-trinity-claude-code/projects/${PROJECT_SLUG}
    SESSION_DIR=$HOME/.claude-deepseek/projects/${PROJECT_SLUG}
    SESSION_DIR=$HOME/.claude-openrouter/projects/${PROJECT_SLUG}
    The installed shared helper supplies PROJECT_SLUG for all three wrappers.
    """
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = f"{provider}-session-xyz"
    _write_pointer(project, {provider: {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home
        / _CLAUDE_FAMILY_ROOTS[provider]
        / "projects"
        / _claude_slug(project)
        / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), provider)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_claude_slug_matches_real_claude_cli_layout():
    """Literal anchor (CHG-3045): the claude-family slug MUST keep the leading
    dash to match the claude CLI's real on-disk projects dir. Hardcoded expected
    values NOT routed through `_claude_slug`, so a coordinated re-break of
    helper + resolver cannot ship green (closes the f(resolver)==f(helper)
    tautology the §4 glm reviewer flagged).

    Provenance: macOS form observed 2026-06-27 at
    ~/.claude-deepseek/projects/-Users-frank-Projects-trinity/ (real transcript,
    11868 bytes); Linux form matches the actions/checkout layout used by the
    CI (ubuntu-latest) matrix.
    """
    sp = _import_session_path()
    assert (
        sp._encode_project_slug("/Users/frank/Projects/trinity")
        == "-Users-frank-Projects-trinity"
    )
    assert (
        sp._encode_project_slug("/home/runner/work/trinity/trinity")
        == "-home-runner-work-trinity-trinity"
    )


@pytest.mark.parametrize("project_dir,expected_slug", _CLAUDE_2_1_220_SLUG_FIXTURES)
def test_claude_project_slug_matches_2_1_220_fixtures(project_dir, expected_slug):
    sp = _import_session_path()

    assert sp._encode_project_slug(project_dir) == expected_slug


@pytest.mark.parametrize(
    "lookup_key,root_name",
    [
        ("claude-code", ".claude-trinity-claude-code"),
        ("deepseek:hbp-smoke", ".claude-deepseek"),
        ("openrouter", ".claude-openrouter"),
    ],
)
def test_claude_family_resolves_canonical_slug(
    lookup_key, root_name, monkeypatch, capsys
):
    sp = _import_session_path()
    project_dir = "/Users/frank/Projects/project_name.with space!"
    session_id = "canonical-slug-session"
    monkeypatch.setattr(
        sp,
        "_read_pointer",
        lambda _project_dir: {"sessions": {lookup_key: {"session_id": session_id}}},
    )

    transcript = (
        Path(os.environ["HOME"])
        / root_name
        / "projects"
        / "-Users-frank-Projects-project-name-with-space-"
        / f"{session_id}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(project_dir, lookup_key)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out == f"{transcript}\n"


@pytest.mark.parametrize("provider", ["glm", "minimax"])
def test_droid_family_preserves_underscore_in_project_path(
    provider, monkeypatch, capsys
):
    sp = _import_session_path()
    project_dir = "/Users/frank/Projects/droid_project"
    session_id = f"{provider}-underscore-session"
    monkeypatch.setattr(
        sp,
        "_read_pointer",
        lambda _project_dir: {"sessions": {provider: {"session_id": session_id}}},
    )

    transcript = (
        Path(os.environ["HOME"])
        / ".factory"
        / "sessions"
        / "-Users-frank-Projects-droid_project"
        / f"{session_id}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(project_dir, provider)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out == f"{transcript}\n"


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
        # Path-traversal `..` without slash — regex allows individual dots,
        # so without the explicit `..` substring guard these would slip
        # through (per codex-bot R2 finding 3214517921 on PR #119).
        "..",
        "abc..def",
        "abc..",
        "..abc",
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


def test_codex_wrapper_normalizes_deepseek_default(monkeypatch):
    sp = _import_session_path()
    if "codex" in sys.modules:
        del sys.modules["codex"]
    import codex as codex_mod

    captured = []

    def fake_cmd_session_path(project_dir, lookup_key):
        captured.append((project_dir, lookup_key))
        return 0

    monkeypatch.setattr(sp, "cmd_session_path", fake_cmd_session_path)

    class _Args:
        provider_spec = "deepseek:default"
        project = "/Users/frank/Projects/project_name"

    assert codex_mod.cmd_session_path(_Args()) == 0
    assert captured == [("/Users/frank/Projects/project_name", "deepseek")]


def test_claude_slug_helper_runs_from_fake_installed_layout(tmp_path):
    fake_home = tmp_path / "home"
    installed_scripts = fake_home / ".claude" / "skills" / "trinity" / "scripts"
    installed_scripts.mkdir(parents=True)
    for filename in (
        "__init__.py",
        "_compat.py",
        "_version.py",
        "session.py",
        "session_path.py",
    ):
        shutil.copy2(SCRIPTS_DIR / filename, installed_scripts / filename)

    result = subprocess.run(
        [
            sys.executable,
            str(installed_scripts / "session_path.py"),
            "--encode-claude-project-slug",
            "/Users/frank/Projects/project_name.with space!",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(fake_home)},
    )

    assert result.returncode == 0
    assert result.stdout == "-Users-frank-Projects-project-name-with-space-\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "helper_args",
    [
        ["--encode-claude-project-slug"],
        ["--encode-claude-project-slug", "/Users/frank/project", "extra"],
    ],
    ids=["missing-project-dir", "extra-argument"],
)
def test_claude_slug_helper_invalid_arity_contract(helper_args):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "session_path.py"), *helper_args],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert (
        result.stderr == "session_path.py --encode-claude-project-slug <project_dir>\n"
    )


def test_codex_wrapper_package_import_resolves_session_path(tmp_path, capsys):
    """Package imports of scripts.codex must resolve the session-path sibling
    without temporarily mutating sys.path in cmd_session_path."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    for module_name in (
        "scripts.codex",
        "scripts.session_path",
        "scripts.session",
    ):
        sys.modules.pop(module_name, None)
    import scripts.codex as codex_mod

    project = tmp_path / "proj"
    project.mkdir()
    sid = "wrapper-package-import"
    _write_pointer(project, {"glm": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    project_str = str(project)

    class _Args:
        provider_spec = "glm"
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


def test_codex_glob_anchored_no_suffix_collision(tmp_path, monkeypatch, capsys):
    """Codex glob must anchor to the dash boundary before session_id —
    a short `id == "abc"` MUST NOT silently resolve to a longer
    `xabc.jsonl` (suffix-match collision per codex-bot R3 P2 finding
    3214522376 on PR #119).

    Setup: project pointer has session_id="abc". On disk under the
    expected codex day directory we plant ONE colliding file
    `rollout-...-xabc.jsonl` (would suffix-match the old glob) and NO
    file with the actual `-abc.jsonl` anchor. Resolver MUST report
    "transcript file not found" (exit 3), NOT print the colliding path.
    """
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "abc"
    _write_pointer(project, {"codex": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    day_dir = fake_home / ".codex" / "sessions" / "2026" / "05" / "10"
    day_dir.mkdir(parents=True, exist_ok=True)
    # Collision file: ends with "xabc.jsonl" — would match `*abc.jsonl`
    collider = day_dir / "rollout-2026-05-10T08-00-00-xabc.jsonl"
    collider.write_text("")

    # No index — resolver falls through to the broad-glob path.
    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    # Anchored glob does NOT match the collider; resolver returns the
    # synthetic "transcript file not found" exit-3 path.
    assert rc == 3, f"expected exit 3 (no anchor match), got {rc}; stdout={out.out!r}"
    assert str(collider) not in out.out, (
        f"resolver leaked collision path to stdout: {out.out!r}"
    )


def test_nested_cwd_inside_git_repo_uses_literal_dir(tmp_path, monkeypatch):
    """`--project` pointing at a subdirectory of a git repo MUST resolve to
    the literal subdirectory, NOT the git toplevel. session.py writes
    .claude/trinity.json under the literal project dir; session-path must
    read from the same path. Per codex-bot R3 P2 finding 3214530179 on PR
    #119 — earlier R1 used resolve_health_root which rewrote subdirs to
    toplevel and caused pointer-miss.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import codex
    import subprocess as sp_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))

    # Create a git repo with a nested project subdir
    repo = tmp_path / "repo"
    repo.mkdir()
    sp_mod.run(["git", "init", "-q"], cwd=str(repo), check=True)
    sp_mod.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        cwd=str(repo),
        check=True,
    )
    nested = repo / "subproject"
    nested.mkdir()

    sid = "nested-session-id"
    # Pointer is written under the NESTED dir (matches session.py:cmd_write)
    _write_pointer(nested, {"glm": {"session_id": sid}})

    # Pre-create transcript at nested-dir-encoded path
    transcript = fake_home / ".factory" / "sessions" / _encoded(nested) / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    # Wrapper invoked with --project pointing at nested subdir
    class Args:
        project = str(nested)
        provider_spec = "glm"

    rc = codex.cmd_session_path(Args())
    assert rc == 0, (
        f"nested --project must use literal dir, not git toplevel; "
        f"got exit {rc} (would be 2 if wrapper rewrote to repo toplevel)"
    )


def test_minimax_uses_droid_factory_layout(tmp_path, capsys):
    """`minimax` shares the droid `~/.factory/sessions/` layout with `glm`
    (per providers/minimax.md + providers/registry.json — both use the
    droid CLI). Per codex-bot R4 P2 finding 3214543731 on PR #119: the
    R5 dispatch was missing minimax, so `trinity session-path minimax`
    hit the unknown-provider branch instead of resolving the transcript.
    """
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "minimax-session-id"
    _write_pointer(project, {"minimax": {"session_id": sid}})

    fake_home = Path(os.environ["HOME"])
    transcript = (
        fake_home / ".factory" / "sessions" / _encoded(project) / f"{sid}.jsonl"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), "minimax")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_symlinked_project_dir_uses_literal_path(tmp_path, monkeypatch):
    """`--project` pointing at a SYMLINK must use the symlink path, NOT the
    resolved target. session.py:cmd_write writes .claude/trinity.json
    under the literal $PROJECT_DIR; the resolver's encoding must match.
    Per codex-bot R4 P2 finding 3214543729 on PR #119 — R5 used
    `Path.resolve()` which followed symlinks and broke this case.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import codex

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))

    # Real project dir + symlink alias pointing at it
    real_dir = tmp_path / "real-proj"
    real_dir.mkdir()
    link_dir = tmp_path / "link-proj"
    link_dir.symlink_to(real_dir)

    sid = "symlinked-session-id"
    # Pointer is written under the LINK path (via symlink — actual file
    # ends up at real_dir/.claude/trinity.json on disk, but session.py
    # was invoked with PROJECT_DIR=link_dir)
    _write_pointer(link_dir, {"glm": {"session_id": sid}})

    # Pre-create transcript at the LINK-encoded path (matches what the
    # session.py write flow used as $PROJECT_DIR — i.e., the link path).
    # `_encoded` (test helper) uses `.resolve()` which follows symlinks
    # → would encode the real-dir path and miss the test's purpose. The
    # resolver under test uses `os.path.abspath` (no symlink follow), so
    # match that here.
    link_encoded = os.path.abspath(str(link_dir)).replace("/", "-")
    transcript = fake_home / ".factory" / "sessions" / link_encoded / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")

    class Args:
        project = str(link_dir)
        provider_spec = "glm"

    rc = codex.cmd_session_path(Args())
    assert rc == 0, (
        f"symlink --project must use literal link path, not resolved target; "
        f"got exit {rc} (would be 3 if wrapper called .resolve() and looked "
        f"under the real-dir slug instead)"
    )


def test_codex_honors_codex_home_env_var(tmp_path, monkeypatch, capsys):
    """When `$CODEX_HOME` is set, the codex resolver must read the index +
    glob the dated transcript dir under that root, NOT under `~/.codex/`.
    Per codex-bot R5 P2 finding 3214554262 on PR #119: codex CLI supports
    a non-default CODEX_HOME (per openai/codex#2288), and operators using
    that setup were getting "transcript file not found" even with valid
    pointers.
    """
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-codex-home-id"
    _write_pointer(project, {"codex": {"session_id": sid}})

    # Set CODEX_HOME to a different dir than ~/.codex
    fake_home = Path(os.environ["HOME"])
    custom_codex = fake_home / "custom-codex-store"
    custom_codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(custom_codex))

    # Pre-create transcript under CODEX_HOME-rooted day dir
    day_dir = custom_codex / "sessions" / "2026" / "05" / "10"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-05-10T08-00-00-{sid}.jsonl"
    transcript.write_text("")

    # Index entry under CODEX_HOME (NOT ~/.codex)
    index_path = custom_codex / "session_index.jsonl"
    index_path.write_text(
        json.dumps({"id": sid, "updated_at": "2026-05-10T08:00:00.000000Z"}) + "\n"
    )

    # If the resolver hardcoded ~/.codex/, it would miss this transcript.
    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, (
        f"expected exit 0 (CODEX_HOME-rooted transcript resolved); "
        f"got {rc}; stderr={out.err!r}"
    )
    assert out.out.strip() == str(transcript)


def test_codex_home_glob_metacharacters_resolve_via_index(
    tmp_path, monkeypatch, capsys
):
    """CODEX_HOME is a literal root, even when it contains glob metacharacters."""
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-codex-meta-index"
    _write_pointer(project, {"codex": {"session_id": sid}})

    custom_codex = tmp_path / "codex[meta]"
    custom_codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(custom_codex))

    day_dir = custom_codex / "sessions" / "2026" / "05" / "11"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-05-11T08-00-00-{sid}.jsonl"
    transcript.write_text("")

    index_path = custom_codex / "session_index.jsonl"
    index_path.write_text(
        json.dumps({"id": sid, "updated_at": "2026-05-11T08:00:00.000000Z"}) + "\n"
    )

    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)


def test_codex_home_glob_metacharacters_resolve_via_broad_fallback(
    tmp_path, monkeypatch, capsys
):
    """The broad Codex fallback also treats CODEX_HOME as a literal root."""
    sp = _import_session_path()
    project = tmp_path / "proj"
    project.mkdir()
    sid = "019dc7bc-codex-meta-fallback"
    _write_pointer(project, {"codex": {"session_id": sid}})

    custom_codex = tmp_path / "codex[meta]"
    custom_codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(custom_codex))

    day_dir = custom_codex / "sessions" / "2026" / "05" / "12"
    day_dir.mkdir(parents=True, exist_ok=True)
    transcript = day_dir / f"rollout-2026-05-12T08-00-00-{sid}.jsonl"
    transcript.write_text("")

    rc = sp.cmd_session_path(str(project), "codex")
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.strip() == str(transcript)

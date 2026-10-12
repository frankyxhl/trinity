"""Credentials stay inside the per-account wrapper, never in the parent.

Owner rule: callers never read credentials. A claude-code profile names its
credential by a wrapper command (``{"credential_source": {"wrapper": ...}}``);
Trinity runs that command on PATH in place of ``claude`` and never reads the
env var or file itself. An env-form or wrapperless claude-code profile is
refused before the journal is touched.

Every value here is synthetic and built at test time; HOME is always a temp
directory. No test reads a real credential file and none touches the network.
"""

from __future__ import annotations

import builtins
import json
import os
import pathlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODEL = "pilot-model"
WRAPPER_NAME = "claude-code"
ACCOUNTS = ("a", "b", "c")
BAIT_ENV_NAME = "TRINITY_BAIT_CREDENTIAL"


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o755)
    return path


class _RecordingEnviron(dict):
    """A stand-in for os.environ that records every value access.

    Bulk accessors (``items``/``values``/``copy``) are recorded as sentinels so
    a parent that sweeps every value — even while filtering names — is caught.
    """

    def __init__(self, source) -> None:
        super().__init__(source)
        self.reads: list[str] = []

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self:
            self.reads.append(key)
        return super().get(key, default)

    def items(self):
        self.reads.append("|items|")
        return super().items()

    def values(self):
        self.reads.append("|values|")
        return super().values()

    def copy(self):
        self.reads.append("|copy|")
        return super().copy()


def _bulk_read(reads: list) -> list:
    return [entry for entry in reads if entry.startswith("|")]


def _record_opens(monkeypatch) -> list:
    opened: list[str] = []
    real_builtin_open = builtins.open
    real_os_open = os.open
    real_path_open = pathlib.Path.open
    real_read_text = pathlib.Path.read_text
    real_read_bytes = pathlib.Path.read_bytes

    def record(target) -> None:
        try:
            opened.append(os.fspath(target))
        except TypeError:
            pass

    def fake_builtin_open(file, *args, **kwargs):
        record(file)
        return real_builtin_open(file, *args, **kwargs)

    def fake_os_open(path, *args, **kwargs):
        record(path)
        return real_os_open(path, *args, **kwargs)

    def fake_path_open(self, *args, **kwargs):
        record(self)
        return real_path_open(self, *args, **kwargs)

    def fake_read_text(self, *args, **kwargs):
        record(self)
        return real_read_text(self, *args, **kwargs)

    def fake_read_bytes(self, *args, **kwargs):
        record(self)
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_builtin_open)
    monkeypatch.setattr(os, "open", fake_os_open)
    monkeypatch.setattr(pathlib.Path, "open", fake_path_open)
    monkeypatch.setattr(pathlib.Path, "read_text", fake_read_text)
    monkeypatch.setattr(pathlib.Path, "read_bytes", fake_read_bytes)
    return opened


# --- (a) the adapter never reads a credential env var or credential file -----


def _marker_stub(marker: str, capture: Path) -> str:
    return textwrap.dedent(
        f"""\
        #!{sys.executable}
        import json, sys
        with open({str(capture)!r}, "a") as handle:
            handle.write({marker!r} + "\\n")
        argv = sys.argv[1:]
        sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else ""
        sys.stdout.write(json.dumps({{
            "type": "result", "is_error": False, "session_id": sid,
        }}) + "\\n")
        """
    )


def _run_adapter(tmp_path, profile, *, time_s=10.0):
    import scripts.trinity_core.claude_code as claude_code

    return claude_code.run(
        profile,
        prompt="task",
        cwd=str(tmp_path),
        session_id="assigned-session-0001",
        run_id="r-1",
        node_id="n-1",
        depth=0,
        max_depth=0,
        root=str(tmp_path / "state"),
        heartbeat=lambda source: None,
        poll_s=100.0,
        time_s=time_s,
    )


def test_adapter_never_touches_a_credential_env_value_or_file(tmp_path, monkeypatch):
    bait_value = "synthetic-" + ("b" * 24)
    bait_file = tmp_path / "bait-credential"
    bait_file.write_text("synthetic-" + ("c" * 24))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "ran.txt"
    _executable(bin_dir / WRAPPER_NAME, _marker_stub("WRAPPER", capture))
    _executable(bin_dir / "claude", _marker_stub("BARE", capture))

    environ = _RecordingEnviron(os.environ)
    environ["PATH"] = os.pathsep.join(
        [str(bin_dir), os.environ.get("PATH", "/usr/bin:/bin")]
    )
    environ[BAIT_ENV_NAME] = bait_value
    monkeypatch.setattr(os, "environ", environ)

    opened = _record_opens(monkeypatch)

    _run_adapter(
        tmp_path, {"model": MODEL, "credential_source": {"wrapper": WRAPPER_NAME}}
    )
    assert BAIT_ENV_NAME not in environ.reads, environ.reads
    assert _bulk_read(environ.reads) == [], environ.reads
    assert str(bait_file) not in opened, opened
    assert capture.read_text().split() == ["WRAPPER"], capture.read_text()


def test_adapter_runs_only_the_named_wrapper_not_bare_claude(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "ran.txt"
    _executable(bin_dir / WRAPPER_NAME, _marker_stub("WRAPPER", capture))
    _executable(bin_dir / "claude", _marker_stub("BARE", capture))
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]))

    outcome = _run_adapter(
        tmp_path, {"model": MODEL, "credential_source": {"wrapper": WRAPPER_NAME}}
    )
    assert outcome["exit_class"] == "ok", outcome
    assert capture.read_text().split() == ["WRAPPER"], capture.read_text()


def test_adapter_refuses_a_profile_with_no_wrapper(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "ran.txt"
    _executable(bin_dir / "claude", _marker_stub("BARE", capture))
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]))

    outcome = _run_adapter(tmp_path, {"model": MODEL})
    assert outcome["exit_class"] != "ok", outcome
    assert not capture.exists(), "a wrapperless run still executed a harness"


# --- (b) env-form and wrapperless claude-code profiles are refused -----------


def _profiles_json(tmp_path: Path, credential_source) -> Path:
    profile = {
        "name": "pilot",
        "adapter": "claude-code",
        "provider": "claude-code",
        "billing": "subscription",
        "model": MODEL,
        "quota_source": {"kind": "vendor_cli", "command": str(tmp_path / "quota")},
        "freshness_limit": 300,
        "transcript_retention": "30 days",
        "enabled": True,
    }
    if credential_source is not None:
        profile["credential_source"] = credential_source
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"profiles": [profile]}))
    return path


@pytest.mark.parametrize(
    "credential_source",
    [{"env": BAIT_ENV_NAME}, {}, None],
    ids=["env", "empty", "absent"],
)
def test_env_or_wrapperless_profile_is_refused_without_journal_line(
    tmp_path, monkeypatch, credential_source
):
    import scripts.trinity_core as core

    state = tmp_path / "state"
    state.mkdir()
    journal_path = state / "journal.jsonl"
    sentinel = json.dumps({"kind": "sentinel"})
    journal_path.write_text(sentinel + "\n")

    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    # No `claude` on PATH, so the unfixed path cannot reach a harness.
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    result = core.call(
        {
            "profiles_path": str(_profiles_json(tmp_path, credential_source)),
            "profile": "pilot",
            "step": "root",
            "session": "new",
            "prompt": {"text": "x"},
            "cwd": str(tmp_path),
            "allow_nesting": {"max_depth": 1},
        }
    )
    assert result["exit_class"] == "bad_request", result
    assert journal_path.read_text() == sentinel + "\n", (
        "a refused credential form still wrote a journal line"
    )


@pytest.mark.parametrize(
    "credential_source",
    ["claude-code", ["claude-code"], 7],
    ids=["string", "list", "number"],
)
def test_malformed_credential_source_is_refused_without_journal_line(
    tmp_path, monkeypatch, credential_source
):
    import scripts.trinity_core as core

    state = tmp_path / "state"
    state.mkdir()
    journal_path = state / "journal.jsonl"
    sentinel = json.dumps({"kind": "sentinel"})
    journal_path.write_text(sentinel + "\n")

    monkeypatch.setenv("TRINITY_ROOT", str(state))
    monkeypatch.delenv("TRINITY_GUARD", raising=False)
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    raised = None
    result = None
    try:
        result = core.call(
            {
                "profiles_path": str(_profiles_json(tmp_path, credential_source)),
                "profile": "pilot",
                "step": "root",
                "session": "new",
                "prompt": {"text": "x"},
                "cwd": str(tmp_path),
                "allow_nesting": {"max_depth": 1},
            }
        )
    except Exception as exc:
        raised = exc
    assert raised is None, f"dispatch raised {raised!r} instead of refusing"
    assert result["exit_class"] == "bad_request", result
    assert journal_path.read_text() == sentinel + "\n", (
        "a malformed credential source still wrote a journal line"
    )


# --- (c) the per-account wrappers -------------------------------------------


def _wrapper_path(account: str) -> Path:
    return REPO / "providers" / "bin" / f"{WRAPPER_NAME}-{account}"


def _synthetic_token(account: str) -> str:
    return "synthetic-" + account + "-" + ("0123456789abcdef" * 2)


def _write_recording_claude(bin_dir: Path) -> None:
    _executable(
        bin_dir / "claude",
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, os, sys
            token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
            record = {{
                "argv": sys.argv[1:],
                "env_names": sorted(os.environ),
                "token": token,
                "matches_expected": token
                    == os.environ.get("TRINITY_FAKE_EXPECTED_TOKEN"),
            }}
            with open(os.environ["TRINITY_FAKE_CAPTURE"], "a") as handle:
                handle.write(json.dumps(record) + "\\n")
            sys.stdout.write("fake-claude-ok\\n")
            """
        ),
    )


@pytest.mark.parametrize("account", ACCOUNTS)
def test_account_wrapper_pins_its_account_and_never_echoes_token(tmp_path, account):
    wrapper = _wrapper_path(account)
    assert wrapper.exists(), f"missing wrapper script providers/bin/{wrapper.name}"
    assert os.access(wrapper, os.X_OK), wrapper

    home = tmp_path / "home"
    token_dir = home / ".claude"
    token_dir.mkdir(parents=True)
    tokens = {name: _synthetic_token(name) for name in ACCOUNTS}
    for name, value in tokens.items():
        token_file = token_dir / f"fleet-token.{name}"
        token_file.write_text(value)
        token_file.chmod(0o600)

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    _write_recording_claude(fake_bin)
    capture = tmp_path / "capture.jsonl"

    inherited = {"a": "c", "b": "a", "c": "b"}[account]
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env.pop("TRINITY_CLAUDE_CODE_ACCOUNT", None)
    env.update(
        {
            "HOME": str(home),
            "PATH": os.pathsep.join([str(fake_bin), "/usr/bin", "/bin"]),
            "TRINITY_CLAUDE_CODE_ACCOUNT": inherited,
            "TRINITY_FAKE_CAPTURE": str(capture),
            "TRINITY_FAKE_EXPECTED_TOKEN": tokens[account],
        }
    )

    proc = subprocess.run(
        [
            str(wrapper),
            "-p",
            "task",
            "--session-id",
            "session-1",
            "--output-format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stderr)

    records = [
        json.loads(line) for line in capture.read_text().splitlines() if line.strip()
    ]
    assert records, "the fake claude never ran"
    last = records[-1]
    assert last["token"] == tokens[account], last
    assert last["matches_expected"] is True, last

    output = proc.stdout + proc.stderr
    for name, value in tokens.items():
        assert value not in output, f"wrapper echoed the token for account {name}"


# --- (d) the manifest ships the wrappers ------------------------------------


def test_install_manifest_lists_account_wrappers_with_mode_755():
    manifest = json.loads((REPO / "install-manifest.json").read_text())
    entries = {entry["src"]: entry for entry in manifest["files"]}
    for account in ACCOUNTS:
        src = f"providers/bin/{WRAPPER_NAME}-{account}"
        entry = entries.get(src)
        assert entry, f"{src} is not in install-manifest.json"
        assert entry.get("mode") == "755", entry
        assert entry.get("dest") == (
            f".claude/skills/trinity/bin/{WRAPPER_NAME}-{account}"
        ), entry

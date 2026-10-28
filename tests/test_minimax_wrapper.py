import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MINIMAX_BIN = ROOT / "providers" / "bin" / "minimax"

KEY = "mm-test-key-123"
OTHER_KEY = "mm-other-key-456"

PINNED_SETTINGS = (
    "model=MiniMax-M3",
    "model_provider=minimax",
    "model_providers.minimax.base_url=https://api.minimaxi.com/v1",
    "model_providers.minimax.wire_api=responses",
    "model_providers.minimax.env_key=MINIMAX_API_KEY",
)


@pytest.fixture
def stub_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record_path = tmp_path / "codex.invoked.json"
    stub = bin_dir / "codex"
    stub.write_text(
        "\x23!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(record_path)!r}, 'w').write(json.dumps({{\n"
        "    'argv': sys.argv[1:],\n"
        "    'key': os.environ.get('MINIMAX_API_KEY'),\n"
        "    'routed': os.environ.get('CODEX_PROVIDER_ROUTED'),\n"
        "}))\n"
        "sys.exit(0)\n"
    )
    stub.chmod(0o755)
    (tmp_path / ".secrets").mkdir()

    def make_env(env_extra=None):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
        }
        if env_extra:
            env.update(env_extra)
        return env, record_path

    return make_env


def _run(args, env, cwd=None):
    assert MINIMAX_BIN.is_file(), f"{MINIMAX_BIN} missing"
    proc = subprocess.Popen(
        [str(MINIMAX_BIN), *args],
        env=env,
        cwd=cwd,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        assert False, "wrapper did not exit within 30 s"
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _assert_keys_not_leaked(res, argv, *keys):
    for key in keys:
        assert all(key not in arg for arg in argv), f"key in argv {argv!r}"
        assert key not in res.stdout
        assert key not in res.stderr


def _write_key_file(home, content, mode=0o600):
    p = Path(home) / ".secrets" / "minimax_api_key"
    p.write_text(content)
    p.chmod(mode)
    return p


def _record(path):
    return json.loads(path.read_text())


def test_m1_env_key_runs_codex_exec_with_minimax_settings(stub_env):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    data = _record(rec)
    argv = data["argv"]
    assert argv[:2] == ["exec", "--skip-git-repo-check"]
    for setting in PINNED_SETTINGS:
        assert any(
            argv[i] == "-c" and argv[i + 1] == setting for i in range(len(argv) - 1)
        ), f"missing -c {setting!r} in {argv!r}"
    assert argv[-1:] == ["hello"]
    assert data["key"] == KEY


def test_m2_key_file_mode_600_is_used(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], KEY + "\n", mode=0o600)
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    data = _record(rec)
    assert data["key"] == KEY
    _assert_keys_not_leaked(res, data["argv"], KEY)


def test_m3_key_file_mode_400_is_used(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], KEY + "\n", mode=0o400)
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    data = _record(rec)
    assert data["key"] == KEY
    _assert_keys_not_leaked(res, data["argv"], KEY)


def test_m4_key_file_wrong_mode_is_refused(stub_env):
    env, rec = stub_env()
    _write_key_file(env["HOME"], KEY + "\n", mode=0o644)
    res = _run(["hello"], env)
    assert res.returncode != 0
    assert not rec.exists(), "codex stub should not have been invoked"
    assert "minimax_api_key" in res.stderr
    assert KEY not in res.stderr
    assert KEY not in res.stdout


def test_m5_no_key_is_refused(stub_env):
    env, rec = stub_env()
    res = _run(["hello"], env)
    assert res.returncode != 0
    assert not rec.exists(), "codex stub should not have been invoked"
    assert "MINIMAX_API_KEY" in res.stderr


def test_m6_env_key_wins_over_file(stub_env):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    _write_key_file(env["HOME"], OTHER_KEY + "\n", mode=0o600)
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    data = _record(rec)
    assert data["key"] == KEY
    _assert_keys_not_leaked(res, data["argv"], KEY, OTHER_KEY)


def test_m7_key_never_in_argv_or_output(stub_env, tmp_path):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    argv = _record(rec)["argv"]
    assert all(KEY not in arg for arg in argv)
    assert KEY not in res.stdout
    assert KEY not in res.stderr
    leaked = [
        str(p)
        for p in tmp_path.rglob("*")
        if p.is_file() and p != rec and KEY.encode() in p.read_bytes()
    ]
    assert leaked == [], f"key written to {leaked}"


def test_m8_resume_args_follow_settings(stub_env):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    res = _run(["resume", "sid-123", "next"], env)
    assert res.returncode == 0, res.stderr
    argv = _record(rec)["argv"]
    assert argv[-3:] == ["resume", "sid-123", "next"]
    flag_positions = [i for i, arg in enumerate(argv) if arg == "-c"]
    assert flag_positions, f"no -c settings in {argv!r}"
    assert all(i < len(argv) - 3 for i in flag_positions)


def test_m9_no_codex_config_needed(stub_env, tmp_path):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    assert not (tmp_path / ".codex").exists()
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    argv = _record(rec)["argv"]
    assert "--profile" not in argv
    assert "-p" not in argv


def test_m11_caller_args_forwarded_exactly(stub_env, tmp_path):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    (tmp_path / "a.txt").write_text("")
    res = _run(["two words", "", "*"], env, cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    argv = _record(rec)["argv"]
    assert argv[-3:] == ["two words", "", "*"]


def test_m10_wrapper_is_executable_sh():
    assert MINIMAX_BIN.is_file(), f"{MINIMAX_BIN} missing"
    assert os.access(MINIMAX_BIN, os.X_OK), f"{MINIMAX_BIN} not executable"
    first_line = MINIMAX_BIN.read_text().splitlines()[0]
    assert first_line == "#!/bin/sh", f"expected POSIX sh shebang, got {first_line!r}"


def test_m11_wrapper_marks_provider_routed(stub_env):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY})
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    assert _record(rec)["routed"] == "1"


def test_m12_routed_flag_set_even_when_caller_unsets_it(stub_env):
    env, rec = stub_env({"MINIMAX_API_KEY": KEY, "CODEX_PROVIDER_ROUTED": "0"})
    res = _run(["hello"], env)
    assert res.returncode == 0, res.stderr
    assert _record(rec)["routed"] == "1"

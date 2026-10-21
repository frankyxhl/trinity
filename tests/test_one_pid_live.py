from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from tests import one_support as one


def test_pid_is_live_treats_a_zombie_as_gone(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        pid_file = tmp_path / "child.pid"
        pid_file.write_text(str(proc.pid))
        assert one.pid_is_live(pid_file) is True
        os.kill(proc.pid, signal.SIGKILL)
        state = ""
        for _ in range(100):
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(proc.pid)],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if state.startswith("Z"):
                break
            time.sleep(0.05)
        assert state.startswith("Z"), state
        assert one.pid_is_live(pid_file) is False, "a zombie must not count as live"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_pid_is_live_keeps_a_live_process_when_ps_fails(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ps = bin_dir / "ps"
    fake_ps.write_text("#!/bin/sh\nexit 1\n")
    fake_ps.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        pid_file = tmp_path / "child.pid"
        pid_file.write_text(str(proc.pid))
        assert one.pid_is_live(pid_file) is True, (
            "a running process must stay live when ps fails"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)

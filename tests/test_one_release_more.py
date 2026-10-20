from __future__ import annotations

import json
import os
import stat

import pytest

from tests import one_support as one


@pytest.mark.parametrize(
    "name",
    ["start", "end", "rc.txt", "out.jsonl", "err.txt", "gate.txt"],
)
def test_release_f12_fifo_log_name_is_not_written(tmp_path, name):
    logs = tmp_path / "logs"
    logs.mkdir()
    os.mkfifo(logs / name)
    try:
        if name == "gate.txt":
            readings = tmp_path / "readings.json"
            readings.write_text(
                json.dumps({"level": 1, "free_pct": 90, "swap_mb": 0, "load5": 1})
            )
            ns = one.make_root(tmp_path, **one.OK_FAKE)
            one.write_profiles(ns.root, codex_home=ns.codex_home, gate="light")
            proc = one.run_call(
                ns,
                args=("--log-dir", str(logs)),
                env_extra=one.gate_env(readings),
                timeout=15,
            )
        else:
            ns = one.make_root(tmp_path, **one.OK_FAKE)
            proc = one.run_call(ns, args=("--log-dir", str(logs)), timeout=15)
        assert proc.returncode is not None, (
            f"the call hung on a FIFO log name: returncode={proc.returncode}"
        )
        result = one.result_of(proc)
        assert result.get("exit_class") == "ok", (result, proc.stderr)
        mode = (logs / name).lstat().st_mode
        assert stat.S_ISFIFO(mode), oct(mode)
        rows = one.error_lines_of(ns.state)
        assert any(r.get("error") == "log_unwritable" for r in rows), rows
    finally:
        (logs / name).unlink(missing_ok=True)


@pytest.mark.parametrize(
    "key",
    ["level", "free_pct", "swap_mb", "load5"],
)
def test_release_huge_integer_reading_is_refused(tmp_path, key):
    fields = {"level": 1, "free_pct": 90, "swap_mb": 0, "load5": 1}
    fields[key] = 10**400
    readings = tmp_path / "readings.json"
    readings.write_text(json.dumps(fields))
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, codex_home=ns.codex_home, gate="light")
    proc = one.run_call(ns, env_extra=one.gate_env(readings), timeout=30)
    result = one.result_of(proc)
    assert result.get("exit_class") == "check_failed", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert [c.get("decision") for c in checks] == ["refused"], checks
    assert not ns.capture.exists(), (
        f"the harness ran despite a refused reading: capture={ns.capture.exists()}"
    )

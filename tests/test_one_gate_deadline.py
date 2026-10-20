from __future__ import annotations

import json
import os
import threading
import time

from tests import one_support as one

BLOCK = {"level": 4, "free_pct": 90, "swap_mb": 0, "load5": 1}
PASS = {"level": 1, "free_pct": 90, "swap_mb": 0, "load5": 1}


def test_one_064_go_after_time_s_is_stop(tmp_path):
    readings = tmp_path / "readings.json"
    readings.write_text(json.dumps(BLOCK))
    ns = one.make_root(
        tmp_path, stdout_fixture=one.FIXTURES / "codex-new.jsonl", sleep_s=8
    )
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    logs = tmp_path / "logs"

    def write_readings(values):
        tmp = readings.with_name("readings.json.tmp")
        tmp.write_text(json.dumps(values))
        os.replace(tmp, readings)

    def flip_after_first_wait():
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if (ns.state / "journal.jsonl").exists():
                    checks = one.gate_checks(one.records_of(ns.state))
                    if any(c.get("decision") == "wait" for c in checks):
                        write_readings(PASS)
                        return
            except Exception:
                pass
            time.sleep(0.02)

    flipper = threading.Thread(target=flip_after_first_wait)
    flipper.start()
    try:
        proc = one.run_call(
            ns,
            args=("--time-s", "3", "--log-dir", str(logs)),
            env_extra=one.gate_env(readings, poll_s="5"),
            timeout=30,
        )
    finally:
        flipper.join(timeout=10)
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert states[-1].get("exit_class") == "timeout", states[-1]
    checks = one.gate_checks(records)
    assert [c.get("decision") for c in checks] == ["wait", "stop"], checks
    assert checks[-1].get("level") == PASS["level"], checks[-1]
    assert not ns.capture.exists(), "the harness started after the deadline"
    gate_txt = logs / "gate.txt"
    assert gate_txt.exists(), f"no gate.txt under {logs}"
    assert gate_txt.read_text().strip().endswith("decision=stop"), gate_txt.read_text()

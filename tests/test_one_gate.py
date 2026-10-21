from __future__ import annotations

import json
import threading

from tests import one_support as one

GO = {"level": 1, "free_pct": 90, "swap_mb": 100, "load5": 1.5}
LIGHT_PASS = {"level": 2, "free_pct": 5, "swap_mb": 5000, "load5": 29}
LIGHT_BLOCK = {"level": 4, "free_pct": 90, "swap_mb": 0, "load5": 1}
HEAVY_PASS = {"level": 1, "free_pct": 40, "swap_mb": 1799, "load5": 99}
HEAVY_BLOCK = {"level": 2, "free_pct": 90, "swap_mb": 0, "load5": 1}
LIGHT_LOAD_BLOCK = {"level": 1, "free_pct": 90, "swap_mb": 100, "load5": 30}
HEAVY_FREE_BLOCK = {"level": 1, "free_pct": 39, "swap_mb": 1799, "load5": 99}
HEAVY_SWAP_BLOCK = {"level": 1, "free_pct": 40, "swap_mb": 1800, "load5": 99}
CHECK_KEYS = {
    "kind",
    "run",
    "node",
    "check",
    "gate",
    "level",
    "free_pct",
    "swap_mb",
    "load5",
    "decision",
    "t",
    "v",
}


def _readings(tmp_path, values, name="readings.json"):
    path = tmp_path / name
    path.write_text(json.dumps(values))
    return path


def _run(ns, readings, *, args=(), timeout=30):
    return one.run_call(
        ns, args=args, env_extra=one.gate_env(readings), timeout=timeout
    )


def _decisions(checks):
    return [c.get("decision") for c in checks]


def test_one_060_gate_none_has_no_check_line(tmp_path):
    readings = _readings(tmp_path, GO)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    proc = _run(ns, readings)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    assert one.gate_checks(one.records_of(ns.state)) == [], "gate none read readings"
    assert ns.capture.exists(), "the harness never ran"


def test_one_061_light_passes_at_level_2(tmp_path):
    readings = _readings(tmp_path, LIGHT_PASS)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "go", checks
    assert ns.capture.exists(), "the harness never ran"


def test_one_061_heavy_passes_at_thresholds(tmp_path):
    readings = _readings(tmp_path, HEAVY_PASS)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="heavy", codex_home=ns.codex_home)
    proc = _run(ns, readings)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "go", checks


def test_one_061_heavy_blocks_above_level_1(tmp_path):
    readings = _readings(tmp_path, HEAVY_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="heavy", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started through a blocked gate"


def test_one_061_light_blocks_on_load5_at_level_1(tmp_path):
    readings = _readings(tmp_path, LIGHT_LOAD_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started through a blocked gate"


def test_one_061_heavy_blocks_on_free_pct_at_level_1(tmp_path):
    readings = _readings(tmp_path, HEAVY_FREE_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="heavy", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started through a blocked gate"


def test_one_061_heavy_blocks_on_swap_mb_at_level_1(tmp_path):
    readings = _readings(tmp_path, HEAVY_SWAP_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="heavy", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started through a blocked gate"


def test_one_062_check_line_carries_reading_values(tmp_path):
    readings = _readings(tmp_path, GO)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings)
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert checks, "no memory_gate check line"
    check = checks[-1]
    assert check.get("gate") == "light", check
    assert check.get("level") == GO["level"], check
    assert check.get("free_pct") == GO["free_pct"], check
    assert check.get("swap_mb") == GO["swap_mb"], check
    assert check.get("load5") == GO["load5"], check


def test_one_062_readings_reread_each_poll_wait_then_go(tmp_path):
    readings = _readings(tmp_path, LIGHT_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    timer = threading.Timer(0.6, lambda: readings.write_text(json.dumps(GO)))
    timer.start()
    try:
        proc = _run(ns, readings, args=("--time-s", "5"))
    finally:
        timer.join()
    result = one.result_of(proc)
    assert result.get("exit_class") == "ok", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert _decisions(checks) == ["wait", "go"], checks
    assert checks[-1].get("level") == GO["level"], checks[-1]
    assert ns.capture.exists(), "the harness never ran after go"


def test_one_063_check_line_fields_exact_one_line_per_decision(tmp_path):
    readings = _readings(tmp_path, LIGHT_BLOCK)
    ns = one.make_root(tmp_path)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "2"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    checks = one.gate_checks(one.records_of(ns.state))
    assert _decisions(checks) == ["wait", "stop"], checks
    for check in checks:
        assert set(check) == CHECK_KEYS, sorted(check)
        assert check["v"] == 1, check


def test_one_064_time_s_out_while_waiting_stops(tmp_path):
    readings = _readings(tmp_path, LIGHT_BLOCK)
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "1"))
    result = one.result_of(proc)
    assert result.get("exit_class") == "timeout", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert states[-1].get("exit_class") == "timeout", states[-1]
    checks = one.gate_checks(records)
    assert checks and checks[-1].get("decision") == "stop", checks
    assert not ns.capture.exists(), "the harness started after the stop"


def _refused_asserts(ns, proc):
    result = one.result_of(proc)
    assert result.get("exit_class") == "check_failed", (result, proc.stderr)
    records = one.records_of(ns.state)
    node_id = one.node_id_of(records)
    states = one.states_of(records, node_id)
    assert [s.get("state") for s in states] == ["queued", "failed"], states
    assert states[-1].get("exit_class") == "check_failed", states[-1]
    checks = one.gate_checks(records)
    assert checks and checks[-1].get("decision") == "refused", checks
    assert not ns.capture.exists(), "the harness started despite a refused gate"


def test_one_065_missing_reading_key_is_refused(tmp_path):
    readings = _readings(tmp_path, {"level": 1, "free_pct": 90, "swap_mb": 100})
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, readings, args=("--time-s", "2"))
    _refused_asserts(ns, proc)


def test_one_065_missing_readings_file_is_refused(tmp_path):
    ns = one.make_root(tmp_path, **one.OK_FAKE)
    one.write_profiles(ns.root, gate="light", codex_home=ns.codex_home)
    proc = _run(ns, tmp_path / "absent.json", args=("--time-s", "2"))
    _refused_asserts(ns, proc)

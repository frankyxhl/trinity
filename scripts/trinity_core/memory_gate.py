from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


class GateUnreadable(Exception):
    pass


READING_KEYS = ("level", "free_pct", "swap_mb", "load5")
_FREE_PCT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_SWAP_USED_RE = re.compile(r"used\s*=\s*([0-9]+(?:\.[0-9]+)?)M")
_PSI_AVG60_RE = re.compile(r"avg60=([0-9]+(?:\.[0-9]+)?)")
_MEMINFO_RE = {
    key: re.compile(rf"^{key}:\s*([0-9]+)", re.MULTILINE)
    for key in ("MemAvailable", "MemTotal", "SwapTotal", "SwapFree")
}
_SUBPROCESS_TIMEOUT_S = 10
_DEFAULT_POLL_S = 20.0


def _output(command: list[str]) -> str:
    try:
        proc = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateUnreadable() from None
    return proc.stdout


def _int_output(command: list[str]) -> int:
    try:
        return int(_output(command).strip())
    except ValueError:
        raise GateUnreadable() from None


def _match_or_unreadable(text: str, pattern: re.Pattern) -> re.Match:
    match = pattern.search(text)
    if match is None:
        raise GateUnreadable()
    return match


def _meminfo_value(text: str, key: str) -> int:
    return int(_match_or_unreadable(text, _MEMINFO_RE[key]).group(1))


def _macos_level() -> int:
    return _int_output(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])


def _macos_free_pct() -> float:
    output = _output(["memory_pressure"])
    line = next((ln for ln in output.splitlines() if "free percentage" in ln), None)
    if line is None:
        raise GateUnreadable()
    return float(_match_or_unreadable(line, _FREE_PCT_RE).group(1))


def _macos_swap_mb() -> float:
    return float(
        _match_or_unreadable(
            _output(["sysctl", "-n", "vm.swapusage"]), _SWAP_USED_RE
        ).group(1)
    )


def _psi_level() -> int:
    try:
        text = Path("/proc/pressure/memory").read_text(encoding="utf-8")
    except OSError:
        raise GateUnreadable() from None
    for line in text.splitlines():
        if not line.startswith("some "):
            continue
        avg60 = float(_match_or_unreadable(line, _PSI_AVG60_RE).group(1))
        if avg60 < 10:
            return 1
        if avg60 < 40:
            return 2
        return 4
    raise GateUnreadable()


def _machine_reading() -> dict:
    try:
        load5 = os.getloadavg()[1]
    except OSError:
        raise GateUnreadable() from None
    if sys.platform == "darwin":
        reading = {
            "level": _macos_level(),
            "free_pct": _macos_free_pct(),
            "swap_mb": _macos_swap_mb(),
        }
    else:
        try:
            text = Path("/proc/meminfo").read_text(encoding="utf-8")
        except OSError:
            raise GateUnreadable() from None
        mem_available = _meminfo_value(text, "MemAvailable")
        mem_total = _meminfo_value(text, "MemTotal")
        swap_total = _meminfo_value(text, "SwapTotal")
        swap_free = _meminfo_value(text, "SwapFree")
        reading = {
            "level": _psi_level(),
            "free_pct": 100 * mem_available / mem_total,
            "swap_mb": (swap_total - swap_free) / 1024,
        }
    reading["load5"] = load5
    return reading


def _file_reading(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateUnreadable() from None
    if not isinstance(data, dict):
        raise GateUnreadable()
    reading = {}
    for key in READING_KEYS:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateUnreadable()
        reading[key] = value
    return reading


def read() -> dict:
    seam = os.environ.get("TRINITY_GATE_READINGS")
    reading = _file_reading(seam) if seam else _machine_reading()
    try:
        finite = all(math.isfinite(value) for value in reading.values())
    except OverflowError:
        raise GateUnreadable() from None
    if not finite:
        raise GateUnreadable()
    return reading


def passes(gate: str, reading: dict) -> bool:
    if gate == "light":
        return reading["level"] <= 2 and reading["load5"] < 30
    if gate == "heavy":
        return (
            reading["level"] == 1
            and reading["free_pct"] >= 40
            and reading["swap_mb"] < 1800
        )
    return False


def poll_s() -> float:
    raw = os.environ.get("TRINITY_GATE_POLL_S")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _DEFAULT_POLL_S
        if value > 0:
            return value
    return _DEFAULT_POLL_S

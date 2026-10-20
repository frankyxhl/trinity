from __future__ import annotations

from . import journal

GATES = frozenset({"none", "light", "heavy"})
AUTH_MARKERS = ("401", "unauthorized", "not logged in")
QUOTA_MARKERS = ("429", "rate limit", "usage limit", "quota")


def non_empty_str(value) -> bool:
    return isinstance(value, str) and bool(value)


def binary_ok(profile: dict) -> bool:
    binary = profile.get("binary")
    return binary is None or non_empty_str(binary)


def gate_ok(profile: dict) -> bool:
    gate = profile.get("gate")
    return gate is None or (isinstance(gate, str) and gate in GATES)


def env_pass_ok(profile: dict) -> bool:
    names = profile.get("env_pass")
    if names is None:
        return True
    if not isinstance(names, list):
        return False
    if not all(isinstance(name, str) for name in names):
        return False
    return not any(journal._is_secret_name(name) for name in names)


def matches(text: str, markers) -> bool:
    return any(marker in text for marker in markers)

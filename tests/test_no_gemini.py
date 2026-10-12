"""R1: check every tracked file against the contract's exact allow list."""

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ALLOW = {
    "providers/bin/agy-opus",
    "tests/test_agy_opus_wrapper.sh",
    ".gitleaks.toml",
    "CHANGELOG.md",
    "tests/test_no_gemini.py",
    "tests/test_codex_adapter.py",
    "tests/test_codex_compat.py",
    "tests/test_config.py",
    "tests/test_discover.py",
    "tests/test_doctor_preflight.py",
    "tests/test_provider_registry.py",
    "tests/test_session_path.py",
    "tests/test_status_latest.py",
    "tests/test_install_sh.sh",
    "tests/test_build_providers.sh",
    "tests/features/provider_discovery.feature",
    "docs/acceptance/ACCEPTANCE.md",
    "docs/method/METHOD.md",
    "docs/method/spec-provider-adapters.md",
}


def _matching_lines(path, content):
    is_rule_doc = re.fullmatch(r"rules/[^/]+\.md", path) is not None
    in_history = False
    hits = []
    for number, line in enumerate(content.splitlines(), 1):
        if is_rule_doc and line.startswith(b"## "):
            in_history = line == b"## Change History"
        if in_history:
            continue
        if re.search(b"gemini", line, re.IGNORECASE):
            hits.append((number, line))
    return hits


def test_change_history_skip_is_limited_to_rule_section():
    content = (
        b"# Rule\n"
        b"gemini before history\n"
        b"## Change History\n"
        b"Gemini historical entry\n"
        b"### Details\n"
        b"GEMINI historical detail\n"
        b"## Current guidance\n"
        b"gEmInI after history\n"
    )
    assert _matching_lines("rules/TRN-1001-SOP-Example.md", content) == [
        (2, b"gemini before history"),
        (8, b"gEmInI after history"),
    ]
    for path in ("docs/example.md", "rules/nested/example.md", "rules/example.txt"):
        assert [number for number, _ in _matching_lines(path, content)] == [2, 4, 6, 8]


def _tracked_hits():
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    hits = []
    for raw_path in tracked.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if (
            path in ALLOW
            or path.startswith("rules/archive/")
            or re.fullmatch(r"rules/TRN-[23][0-9]*-(?:CHG|PRP|PLN)-[^/]+", path)
        ):
            continue
        source = ROOT / path
        if not source.is_file():
            continue  # A tracked file deleted in the working tree has no hits.
        for number, line in _matching_lines(path, source.read_bytes()):
            hits.append(f"{path}:{number}: {line.decode('utf-8', errors='replace')}")
    return hits


def test_tracked_files_have_no_removed_provider_outside_allow_list():
    hits = _tracked_hits()
    assert not hits, "Forbidden provider references outside R1 ALLOW:\n" + "\n".join(
        hits
    )

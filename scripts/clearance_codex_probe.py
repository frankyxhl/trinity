"""Temporary Clearance/Codex review-thread probe.

This file is intentionally unsafe so the real Codex connector has a concrete
security issue to review. The test PR that carries it is not intended to merge.
"""

from __future__ import annotations

import subprocess


def run_operator_command(command: str) -> str:
    """Run a user-supplied command and return stdout."""
    completed = subprocess.run(
        command,
        shell=True,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout

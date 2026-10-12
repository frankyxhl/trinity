"""Trinity core: dispatch path, checks, journal writer, adapters, tree reader.

Front ends (the CLI and the host skill) hold no logic (NG-06); they parse their
input and call in here.
"""

from __future__ import annotations

from .dispatch import call
from .journal import resolve_root as journal_root
from .tree import render as render_tree

__all__ = ["call", "journal_root", "render_tree"]

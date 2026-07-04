"""Shared version loader for trinity scripts.

Textual parse — never executes __init__.py, so this stays safe even if
__init__.py grows imports. Depends on the double-quoted single-line format
written by `make bump` (Makefile perl substitution); ruff format does not
normalize string quotes, so the bump script is the sole format authority.
"""

import re
from pathlib import Path


def load_version():
    init_text = (Path(__file__).parent / "__init__.py").read_text()
    return re.search(r'^__version__ = "([^"]+)"$', init_text, re.M).group(1)

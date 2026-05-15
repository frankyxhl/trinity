"""Shared version loader for trinity scripts.

Reads __version__ from scripts/__init__.py via importlib so each script
can be invoked directly (python scripts/foo.py) without requiring
package-import context.
"""

import importlib.util
import os


def load_version():
    init_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py")
    spec = importlib.util.spec_from_file_location("_scripts_init", init_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.__version__

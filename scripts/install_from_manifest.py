"""Install files from install-manifest.json to ~/.claude/.

Called by both `make install` and `install.sh` (via python3 inline).

Reads install-manifest.json from the repo root, copies each source file to
its destination under ~/.claude/, and applies executable mode when set.
"""

import json
import os
import shutil


def main() -> None:
    with open("install-manifest.json") as f:
        entries = json.load(f)["files"]

    for entry in entries:
        dest = os.path.expanduser("~/" + entry["dest"])
        shutil.copy2(entry["src"], dest)
        if entry.get("mode"):
            os.chmod(dest, 0o755)


if __name__ == "__main__":
    main()

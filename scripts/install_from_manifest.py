"""Install files from install-manifest.json to the user's home directory.

Called by both `make install` and `install.sh` (via python3 inline).

Reads install-manifest.json from the repo root and copies each source file to
its destination under ~/. Two sections:

- "files": always installed.
- "conditional_files": installed only when the runtime they target is already
  present on this machine (auto-detection). Each entry names a "condition_dir"
  (relative to ~); if ``~/<condition_dir>`` does not exist, the entry is skipped.
  This lets a single `make install` also place the ZCode-runtime peer skill
  (trinity-zc) into ~/.agents/ when that runtime is installed, without creating
  ~/.agents on machines that do not use it.

Destination parent directories are created as needed.
"""

import json
import os
import shutil


def _install(src, dest_rel, mode):
    dest = os.path.expanduser("~/" + dest_rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    if mode:
        os.chmod(dest, 0o755)


def main() -> None:
    with open("install-manifest.json") as f:
        manifest = json.load(f)

    for entry in manifest["files"]:
        _install(entry["src"], entry["dest"], entry.get("mode"))

    for entry in manifest.get("conditional_files", []):
        cond = os.path.expanduser("~/" + entry["condition_dir"])
        if not os.path.isdir(cond):
            print(
                f"skip {entry['dest']} "
                f"(~/{entry['condition_dir']} not present — runtime not installed)"
            )
            continue
        _install(entry["src"], entry["dest"], entry.get("mode"))
        print(f"installed {entry['dest']} (detected ~/{entry['condition_dir']})")


if __name__ == "__main__":
    main()

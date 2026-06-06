#!/usr/bin/env python3
"""
install.py -- Atomic provider registration in global config

Usage:
    install.py --version
    install.py register <provider> --cli <cli_command> [--global-config <path>]
    install.py unregister <provider> [--global-config <path>]
    install.py register-from-registry <registry_path> [--global-config <path>]
"""

import json
import os
import re
import sys
import tempfile

try:
    from ._version import load_version
except ImportError:
    from _version import load_version

__version__ = load_version()

try:
    from ._compat import fcntl
except ImportError:
    from _compat import fcntl


def atomic_update(path, update_fn):
    """
    Atomically read-modify-write a JSON file with fcntl.flock.
    Creates file (and dirs) if absent.
    update_fn receives the current data dict and should modify it in place or return new dict.
    """
    dir_path = os.path.dirname(path)
    if dir_path:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            print(
                f"trinity-scripts: IO error creating directory {dir_path}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        dir_path = "."

    base_name = os.path.basename(path)
    lock_path = os.path.join(dir_path, f".{base_name}.lock")
    tmp_path = None
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(lock_fd, "r+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                try:
                    with open(path, encoding="utf-8") as current:
                        content = current.read()
                except FileNotFoundError:
                    content = ""

                if not content.strip():
                    data = {}
                else:
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as e:
                        print(
                            f"trinity-scripts: invalid JSON in {path}: {e}",
                            file=sys.stderr,
                        )
                        sys.exit(1)

                updated = update_fn(data)
                if updated is not None:
                    data = updated

                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=dir_path,
                    prefix=f".{base_name}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp:
                    tmp_path = tmp.name
                    json.dump(data, tmp, indent=2, ensure_ascii=False)
                    tmp.write("\n")
                    tmp.flush()
                    os.fsync(tmp.fileno())

                os.replace(tmp_path, path)
                tmp_path = None
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass
                fcntl.flock(lock_file, fcntl.LOCK_UN)
    except OSError as e:
        print(f"trinity-scripts: IO error writing {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_register(provider, cli_command, global_config):
    def update(data):
        if "providers" not in data:
            data["providers"] = {}
        data["providers"][provider] = {
            "cli": cli_command,
            "installed": True,
        }
        return data

    atomic_update(global_config, update)


def _validate_registry(data):
    """Validate providers/registry.json shape. Raises SystemExit on schema mismatch.

    Schema (TRN-3020):
      version: int (must be 1)
      providers: dict[str, ProviderEntry]
        ProviderEntry:
          cli: str (required, non-empty)
          supports_resume: bool (optional, default False)
          resume_arg: str (required iff supports_resume; non-empty)
          timeout: int (optional, positive)
    """
    if not isinstance(data, dict):
        raise SystemExit("trinity-scripts: registry must be a JSON object")
    version = data.get("version")
    if version != 1:
        raise SystemExit(
            f"trinity-scripts: registry.version must be 1 (got {version!r})"
        )
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise SystemExit(
            "trinity-scripts: registry.providers must be a non-empty object"
        )
    for name, entry in providers.items():
        if not isinstance(entry, dict):
            raise SystemExit(
                f"trinity-scripts: registry.providers.{name} must be an object"
            )
        cli = entry.get("cli")
        if not isinstance(cli, str) or not cli.strip():
            raise SystemExit(
                f"trinity-scripts: registry.providers.{name}.cli must be a non-empty string"
            )
        sr = entry.get("supports_resume", False)
        if not isinstance(sr, bool):
            raise SystemExit(
                f"trinity-scripts: registry.providers.{name}.supports_resume must be bool"
            )
        if sr:
            ra = entry.get("resume_arg")
            if not isinstance(ra, str) or not ra.strip():
                raise SystemExit(
                    f"trinity-scripts: registry.providers.{name}.resume_arg must be "
                    "a non-empty string when supports_resume is true"
                )
        if "timeout" in entry:
            t = entry["timeout"]
            if not isinstance(t, int) or t <= 0:
                raise SystemExit(
                    f"trinity-scripts: registry.providers.{name}.timeout must be a "
                    "positive integer"
                )


# droid BYOK model references embedded in a provider cli string, e.g.
# "droid exec --auto medium --model custom:MiniMax-M3".
_CUSTOM_MODEL_RE = re.compile(r"(custom:[^\s\"']+)")


def _declared_custom_model_ids(factory_settings_path):
    """Return the set of explicit custom-model ids declared in
    ~/.factory/settings.json customModels. Missing/unreadable file -> empty set."""
    try:
        with open(factory_settings_path, encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    ids = set()
    models = settings.get("customModels")
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("id"), str):
                ids.add(m["id"])
    return ids


def warn_missing_custom_models(provider_name, cli, factory_settings_path=None):
    """Warn (stderr) when a cli references a droid `custom:` model id that has
    no matching explicit `\"id\"` in ~/.factory/settings.json customModels.

    Warning-only by design: install.sh has never smoke-tested provider CLIs,
    and droid may be configured after install. This surfaces the BYOK
    prerequisite at install time instead of first dispatch (PR #196 review).
    """
    refs = _CUSTOM_MODEL_RE.findall(cli)
    if not refs:
        return
    path = factory_settings_path or os.path.join(
        os.path.expanduser("~"), ".factory", "settings.json"
    )
    declared = _declared_custom_model_ids(path)
    for ref in refs:
        if ref not in declared:
            print(
                f"trinity-install: warning: provider '{provider_name}' references "
                f"droid custom model '{ref}', but {path} has no customModels entry "
                f'with an explicit "id": "{ref}" — dispatch will fail until that '
                f"entry is added.",
                file=sys.stderr,
            )


def cmd_register_from_registry(registry_path, global_config):
    """Read providers/registry.json and call cmd_register() per provider.

    Substitutes {HOME} -> os.path.expanduser('~') in the cli string at iteration
    time. Drops registry's metadata fields (supports_resume, resume_arg, timeout)
    when calling cmd_register — those fields are codex-side metadata only and do
    NOT propagate to ~/.claude/trinity.json (TRN-3020 §"Field disposition").
    """
    try:
        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"trinity-scripts: registry not found: {registry_path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"trinity-scripts: invalid JSON in {registry_path}: {e}")

    _validate_registry(data)

    home = os.path.expanduser("~")
    for provider_name, entry in data["providers"].items():
        cli = entry["cli"].replace("{HOME}", home)
        cmd_register(provider_name, cli, global_config)
        warn_missing_custom_models(provider_name, cli)


def cmd_unregister(provider, global_config):
    if not os.path.exists(global_config):
        # no-op
        return

    def update(data):
        if "providers" in data:
            data["providers"].pop(provider, None)
        return data

    atomic_update(global_config, update)


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--version":
        print(__version__)
        return

    if args[0] == "register":
        if len(args) < 2:
            print(
                "install.py register <provider> --cli <cli_command> [--global-config <path>]",
                file=sys.stderr,
            )
            sys.exit(1)

        provider = args[1]
        cli_command = None
        global_config = os.path.expanduser("~/.claude/trinity.json")

        i = 2
        while i < len(args):
            if args[i] == "--cli" and i + 1 < len(args):
                cli_command = args[i + 1]
                i += 2
            elif args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            else:
                print(f"install.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        if cli_command is None:
            print("install.py register: --cli is required", file=sys.stderr)
            sys.exit(1)

        cmd_register(provider, cli_command, global_config)

    elif args[0] == "register-from-registry":
        if len(args) < 2:
            print(
                "install.py register-from-registry <registry_path> "
                "[--global-config <path>]",
                file=sys.stderr,
            )
            sys.exit(1)

        registry_path = args[1]
        global_config = os.path.expanduser("~/.claude/trinity.json")

        i = 2
        while i < len(args):
            if args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            else:
                print(f"install.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        cmd_register_from_registry(registry_path, global_config)

    elif args[0] == "unregister":
        if len(args) < 2:
            print(
                "install.py unregister <provider> [--global-config <path>]",
                file=sys.stderr,
            )
            sys.exit(1)

        provider = args[1]
        global_config = os.path.expanduser("~/.claude/trinity.json")

        i = 2
        while i < len(args):
            if args[i] == "--global-config" and i + 1 < len(args):
                global_config = args[i + 1]
                i += 2
            else:
                print(f"install.py: unknown argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)

        cmd_unregister(provider, global_config)

    else:
        print(f"install.py: unknown command '{args[0]}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Drift detection for `providers/registry.json` (TRN-3020).

Asserts that the registry is the single source of truth for provider CLI
strings across:
  - .agents/trinity.codex.json (codex-side runtime config)
  - Makefile install: target
  - install.sh
  - providers/<name>.md, providers/<name>.delta.md, providers/_base/*.md
  - README.md
  - SKILL.md
  - tests/test_codex_adapter.py fixture
  - tests/test_install_sh.sh + tests/test_build_providers.sh hard-coded
    glm CLI strings

Direct-invocation providers (glm, codex) match the full registry CLI string
verbatim. Wrapper-style providers (openrouter, deepseek, claude-code) match
the bin-path component only — their docs use shell wrapper functions like
`run_<provider>() { "$HOME/.claude/skills/trinity/bin/<provider>" "$@"; }`
and never inline the full registry CLI string.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Ensure project root is importable so we can reuse install.py's validator.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import install as install_py  # noqa: E402

REGISTRY_PATH = ROOT / "providers" / "registry.json"
CODEX_JSON_PATH = ROOT / ".agents" / "trinity.codex.json"
MAKEFILE_PATH = ROOT / "Makefile"
INSTALL_SH_PATH = ROOT / "install.sh"
README_PATH = ROOT / "README.md"
SKILL_PATH = ROOT / "SKILL.md"
PROVIDERS_DIR = ROOT / "providers"

DIRECT_PROVIDERS = {"glm", "codex", "minimax"}
WRAPPER_PROVIDERS = {"openrouter", "deepseek", "claude-code"}
REGISTRY_PROVIDERS = DIRECT_PROVIDERS | WRAPPER_PROVIDERS

GEMINI_EXCEPTION = "gemini"  # Deferred from registry per TRN-3020.

HOME_LITERAL = os.path.expanduser("~")


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text())


def _registry_cli(provider, registry=None):
    """Registry's cli string with {HOME} expanded."""
    if registry is None:
        registry = _load_registry()
    cli = registry["providers"][provider]["cli"]
    return cli.replace("{HOME}", HOME_LITERAL)


def _bin_path_for_wrapper(provider):
    """Render the bin-path-only component for wrapper-style providers,
    in shell-script style ($HOME, not literal home)."""
    return f"$HOME/.claude/skills/trinity/bin/{provider}"


# ---------------------------------------------------------------------------
# A3.a — schema validates
# ---------------------------------------------------------------------------


def test_a3a_registry_schema_validates():
    """_validate_registry() does not raise on the actual file."""
    install_py._validate_registry(_load_registry())


def test_a3a_registry_version_is_one():
    assert _load_registry()["version"] == 1


def test_a3a_registry_has_expected_providers():
    registry = _load_registry()
    assert set(registry["providers"].keys()) == REGISTRY_PROVIDERS


# ---------------------------------------------------------------------------
# A3.b — codex JSON consistency, with two-step normalizer
# ---------------------------------------------------------------------------


def _normalize_codex_path(s):
    """Normalize a codex-side path string for comparison with the
    registry's claude-side path string. Two-step:
      1. ~/ ↔ {HOME}/  (codex JSON uses ~/, registry uses {HOME}/)
      2. .codex/skills/trinity ↔ .claude/skills/trinity
    Strings without `/skills/trinity/` are returned unchanged.
    """
    s = s.replace("~/", "{HOME}/")
    if "/skills/trinity/" in s:
        s = s.replace(".codex/skills/trinity", ".claude/skills/trinity")
    return s


def test_a3b_codex_json_overlap_matches_registry():
    """For each provider present in BOTH registry and codex JSON, cli strings
    match after path normalization. The overlap set is loudly logged so
    accidental drops surface in CI output."""
    registry = _load_registry()
    codex = json.loads(CODEX_JSON_PATH.read_text())
    overlap = set(registry["providers"].keys()) & set(codex["providers"].keys())
    print(f"[A3.b] codex JSON ↔ registry overlap: {sorted(overlap)}", file=sys.stderr)
    assert overlap, "expected at least one overlapping provider"
    for provider in overlap:
        reg_cli = registry["providers"][provider]["cli"]
        codex_cli = codex["providers"][provider]["cli"]
        normalized = _normalize_codex_path(codex_cli)
        assert normalized == reg_cli, (
            f"drift on {provider}: registry={reg_cli!r}, "
            f"codex.json={codex_cli!r}, normalized={normalized!r}"
        )


# ---------------------------------------------------------------------------
# A3.d — Makefile invokes register-from-registry, no orphan register blocks
# ---------------------------------------------------------------------------


def test_a3d_makefile_uses_register_from_registry():
    body = MAKEFILE_PATH.read_text()
    assert body.count("register-from-registry") >= 1, (
        "Makefile install: must invoke register-from-registry"
    )
    # Whitelist: only `gemini` may have a hard-coded register block.
    for provider in REGISTRY_PROVIDERS:
        pattern = rf"install\.py register {re.escape(provider)}\s"
        assert not re.search(pattern, body), (
            f"Makefile must not contain hard-coded register block for "
            f"{provider} (it should derive from registry.json)"
        )


# ---------------------------------------------------------------------------
# A3.e — install.sh invokes register-from-registry
# ---------------------------------------------------------------------------


def test_a3e_install_sh_uses_register_from_registry():
    body = INSTALL_SH_PATH.read_text()
    assert "register-from-registry" in body
    for provider in REGISTRY_PROVIDERS:
        pattern = rf"install\.py\" register {re.escape(provider)}\s"
        assert not re.search(pattern, body), (
            f"install.sh must not contain hard-coded register block for "
            f"{provider} (it should derive from registry.json)"
        )


# ---------------------------------------------------------------------------
# A3.f — provider doc drift (split by invocation style)
# ---------------------------------------------------------------------------


def _provider_doc_contents(provider):
    """Return concatenated text of all provider-doc files for `provider`,
    so a verbatim substring match can hit any of them."""
    files = [
        PROVIDERS_DIR / f"{provider}.md",
        PROVIDERS_DIR / f"{provider}.delta.md",
    ]
    base_dir = PROVIDERS_DIR / "_base"
    if base_dir.is_dir():
        files.extend(sorted(base_dir.glob("*.md")))
    parts = []
    for f in files:
        if f.exists():
            parts.append(f.read_text())
    return "\n".join(parts)


def test_a3f_direct_provider_full_cli_in_docs():
    registry = _load_registry()
    for provider in DIRECT_PROVIDERS:
        cli = registry["providers"][provider]["cli"]
        haystack = _provider_doc_contents(provider)
        assert cli in haystack, (
            f"providers/{provider}.md or {provider}.delta.md must contain "
            f"the full registry CLI {cli!r}"
        )


def test_a3f_wrapper_provider_bin_path_in_docs():
    for provider in WRAPPER_PROVIDERS:
        bin_path = _bin_path_for_wrapper(provider)
        haystack = _provider_doc_contents(provider)
        assert bin_path in haystack, (
            f"providers/{provider}.md or {provider}.delta.md must contain "
            f"the bin path {bin_path!r}"
        )


# ---------------------------------------------------------------------------
# A3.g — README + SKILL drift (same direct/wrapper split)
# ---------------------------------------------------------------------------


def test_a3g_direct_provider_full_cli_in_readme_skill():
    registry = _load_registry()
    docs = {
        "README.md": README_PATH.read_text(),
        "SKILL.md": SKILL_PATH.read_text(),
    }
    for provider in DIRECT_PROVIDERS:
        cli = registry["providers"][provider]["cli"]
        for name, body in docs.items():
            if provider in body:  # only assert if mentioned
                assert cli in body, (
                    f"{name} mentions {provider!r} but does not contain "
                    f"the full registry CLI {cli!r}"
                )


def _bin_path_forms(provider):
    """Both shell-script ($HOME) and tilde (~) renderings; either is acceptable
    in human-facing docs."""
    return [
        f"$HOME/.claude/skills/trinity/bin/{provider}",
        f"~/.claude/skills/trinity/bin/{provider}",
    ]


def test_a3g_wrapper_provider_bin_path_in_readme_skill():
    """For wrapper-style providers, IF the doc has a JSON `cli` line or a
    bin-path-style reference for that provider, the bin path must match
    one of the registry forms. We don't require every prose mention of
    'deepseek' to include a bin path — only config/path-style references."""
    docs = {
        "README.md": README_PATH.read_text(),
        "SKILL.md": SKILL_PATH.read_text(),
    }
    for provider in WRAPPER_PROVIDERS:
        bin_paths = _bin_path_forms(provider)
        for name, body in docs.items():
            # Heuristic: only assert if the doc has a path/config-style
            # reference to the provider (something more specific than a
            # bare name mention).
            has_cli_line = (
                re.search(rf'"{re.escape(provider)}"\s*:.*?"cli"', body) is not None
            )
            has_path_style = any(
                f"/bin/{provider}" in body or f"trinity-{provider}" in body
                for _ in [None]
            )
            if has_cli_line or has_path_style:
                assert any(bp in body for bp in bin_paths), (
                    f"{name} has cli/path reference for {provider!r} but no "
                    f"matching bin path (expected one of {bin_paths})"
                )


# ---------------------------------------------------------------------------
# A3.h — test fixture realignment
# ---------------------------------------------------------------------------


def test_a3h_codex_adapter_glm_fixture_matches_registry():
    """tests/test_codex_adapter.py:131 hard-codes glm.cli; must equal registry."""
    body = (ROOT / "tests" / "test_codex_adapter.py").read_text()
    registry_glm_cli = _load_registry()["providers"]["glm"]["cli"]
    assert registry_glm_cli in body, (
        "test_codex_adapter.py glm fixture must equal registry's glm.cli "
        f"({registry_glm_cli!r})"
    )


# ---------------------------------------------------------------------------
# A3.i — no-orphan check: every register call covers a known provider
# ---------------------------------------------------------------------------


def test_a3i_makefile_no_orphan_registers():
    body = MAKEFILE_PATH.read_text()
    # Find all hard-coded `register <provider>` calls (not register-from-registry).
    matches = re.findall(r"install\.py register ([\w-]+)\s", body)
    matches = [m for m in matches if m != "register-from-registry"]
    for provider in matches:
        assert provider == GEMINI_EXCEPTION or provider in REGISTRY_PROVIDERS, (
            f"Makefile registers unknown provider {provider!r}"
        )


def test_a3i_install_sh_no_orphan_registers():
    body = INSTALL_SH_PATH.read_text()
    matches = re.findall(r'install\.py" register ([\w-]+)\s', body)
    matches = [m for m in matches if m != "register-from-registry"]
    for provider in matches:
        assert provider == GEMINI_EXCEPTION or provider in REGISTRY_PROVIDERS, (
            f"install.sh registers unknown provider {provider!r}"
        )


# ---------------------------------------------------------------------------
# A3.j — shell-test fixtures hard-code glm CLI
# ---------------------------------------------------------------------------


def test_a3j_test_install_sh_glm_cli_matches_registry():
    body = (ROOT / "tests" / "test_install_sh.sh").read_text()
    registry_glm_cli = _load_registry()["providers"]["glm"]["cli"]
    # Anchor on `custom:GLM-5.2` (the glm BYOK model id) to find the line.
    assert "custom:GLM-5.2" in body
    assert registry_glm_cli in body, (
        f"tests/test_install_sh.sh must contain registry glm.cli ({registry_glm_cli!r})"
    )


def test_a3j_test_build_providers_sh_glm_cli_matches_registry():
    body = (ROOT / "tests" / "test_build_providers.sh").read_text()
    registry_glm_cli = _load_registry()["providers"]["glm"]["cli"]
    assert registry_glm_cli in body, (
        f"tests/test_build_providers.sh must contain registry glm.cli "
        f"({registry_glm_cli!r})"
    )


# ---------------------------------------------------------------------------
# Sanity: registry-driven cmd_register actually populates trinity.json correctly
# ---------------------------------------------------------------------------


def test_register_from_registry_populates_global_config(tmp_path):
    """End-to-end: cmd_register_from_registry writes all 5 providers' cli
    strings (with {HOME} expanded) into a fresh global config."""
    target = tmp_path / "trinity.json"
    install_py.cmd_register_from_registry(str(REGISTRY_PATH), str(target))
    written = json.loads(target.read_text())
    registry = _load_registry()
    home = os.path.expanduser("~")
    for provider in REGISTRY_PROVIDERS:
        expected_cli = registry["providers"][provider]["cli"].replace("{HOME}", home)
        assert written["providers"][provider] == {
            "cli": expected_cli,
            "installed": True,
        }, f"register-from-registry failed for {provider}"


def test_register_from_registry_warns_on_undeclared_custom_model(tmp_path, capsys):
    """A provider cli referencing a droid `custom:` model id must emit an
    install-time stderr warning when ~/.factory/settings.json lacks a
    customModels entry with that explicit id (PR #196 review gate)."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    install_py.warn_missing_custom_models(
        "minimax",
        "droid exec --auto medium --model custom:MiniMax-M3",
        str(settings),
    )
    err = capsys.readouterr().err
    assert "custom:MiniMax-M3" in err
    assert "minimax" in err


def test_register_from_registry_no_warning_when_custom_model_declared(tmp_path, capsys):
    """No warning when the explicit id is declared in customModels."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": [{"id": "custom:MiniMax-M3"}]}))
    install_py.warn_missing_custom_models(
        "minimax",
        "droid exec --auto medium --model custom:MiniMax-M3",
        str(settings),
    )
    assert capsys.readouterr().err == ""


def test_register_from_registry_no_warning_for_builtin_models(tmp_path, capsys):
    """CLI strings without a `custom:` reference never warn — even when the
    factory settings file is absent."""
    install_py.warn_missing_custom_models(
        "codex",
        "codex exec --skip-git-repo-check -m gpt-5.5",
        str(tmp_path / "missing.json"),
    )
    assert capsys.readouterr().err == ""


def test_register_from_registry_warns_when_settings_file_missing(tmp_path, capsys):
    """Missing ~/.factory/settings.json counts as undeclared (fresh machine)."""
    install_py.warn_missing_custom_models(
        "minimax",
        "droid exec --auto medium --model custom:MiniMax-M3",
        str(tmp_path / "missing.json"),
    )
    assert "custom:MiniMax-M3" in capsys.readouterr().err


def test_register_from_registry_drops_metadata_fields(tmp_path):
    """Verify that supports_resume/resume_arg/timeout do NOT propagate to
    ~/.claude/trinity.json (they are codex-side metadata only — TRN-3020
    §"Field disposition")."""
    target = tmp_path / "trinity.json"
    install_py.cmd_register_from_registry(str(REGISTRY_PATH), str(target))
    written = json.loads(target.read_text())
    for provider, entry in written["providers"].items():
        assert set(entry.keys()) == {"cli", "installed"}, (
            f"{provider} entry leaked metadata fields: {entry.keys()}"
        )


def test_validate_registry_rejects_wrong_version():
    bad = {"version": 2, "providers": {"x": {"cli": "y"}}}
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "version" in str(e)


def test_validate_registry_rejects_missing_resume_arg():
    bad = {
        "version": 1,
        "providers": {"x": {"cli": "y", "supports_resume": True}},
    }
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "resume_arg" in str(e)


def test_validate_registry_rejects_empty_cli():
    bad = {"version": 1, "providers": {"x": {"cli": ""}}}
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "cli" in str(e)


def test_validate_registry_rejects_non_bool_supports_resume():
    bad = {
        "version": 1,
        "providers": {"x": {"cli": "y", "supports_resume": "yes"}},
    }
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "supports_resume" in str(e)


def test_validate_registry_rejects_non_positive_timeout():
    bad = {"version": 1, "providers": {"x": {"cli": "y", "timeout": 0}}}
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "timeout" in str(e)


def test_validate_registry_rejects_empty_providers():
    bad = {"version": 1, "providers": {}}
    try:
        install_py._validate_registry(bad)
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "providers" in str(e)

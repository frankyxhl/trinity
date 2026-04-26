# Changelog

## [Unreleased]
### Added
- **One-click release** via Actions UI (TRN-2007). The `workflow_dispatch` trigger on `release.yml` now accepts an optional `tag_name` input; leaving it empty derives `vX.Y.Z` from the `VERSION` file on the dispatched ref, creates and pushes the tag, then publishes — all in one workflow run. Click "Run workflow" from the Actions tab on `main` and you're done. A new main-only guard rejects one-click attempts from feature branches; the explicit-`tag_name` retry path remains unchanged. New `tests/test_release_workflow.sh` T10 covers the optional input, main-only guard, version-derivation logic, pre-flight tag-exists check, and per-step `if:` gating. TRN-1004 SOP restructured into Path A (one-click) / Path B (tag push CLI) / Path C (retry).

### Changed
- `.github/workflows/release.yml`: bump action pins to Node 24 majors — `actions/checkout@v4`→`@v6`, `actions/upload-artifact@v4`→`@v5`, `astral-sh/setup-uv@v5`→`@v6`. Resolves Node 20 deprecation annotation surfaced on the v1.7.0 release run. setup-uv@v8 was skipped because it removed floating major tags (`@v8` no longer resolves) — staying on `@v6` keeps the workflow low-maintenance. `tests/test_release_workflow.sh` assertions updated.

### Fixed
- `.github/workflows/release.yml`: add `cache-dependency-glob: 'Makefile'` to the `setup-uv` step. Resolves the "No file matched to [**/uv.lock,**/requirements*.txt]. The cache will never get invalidated." annotation surfaced on the v1.7.0 release run. Trinity has neither `uv.lock` nor `requirements*.txt`; deps live in `Makefile` (`uv pip install pytest ruff`), so that file is the right cache key.

## [1.7.0] - 2026-04-26
### Added
- `.github/workflows/release.yml`: tag-push triggers automated GitHub Release publish (TRN-2006). Strict semver glob `v[0-9]+.[0-9]+.[0-9]+` for trigger; `workflow_dispatch` with `tag_name` input for manual retry. Defense-in-depth tag/VERSION validation, tag-must-be-on-main check, CHANGELOG section extraction (fail on empty), least-privilege permissions (global `contents: read`, only the publish job gets `contents: write`). No third-party publish actions — direct `gh release create` only.
- `make release-prep`: local-only target replacing `make release`. Runs verify-built/test/lint, stages 4 metadata files, commits `Release vX.Y.Z`, creates local tag. Does NOT push, does NOT publish. CI handles the publish on tag push.
- `tests/test_release_workflow.sh`: 52 assertions covering workflow structure, semver regex, CHANGELOG awk extractor (4 fixture cases: full / last / missing / header-only), tag↔VERSION matcher (whitespace-trim + leading-`v` handling), Makefile invariants. Wired into `make test`.

### Changed
- `make setup`: uv → pip fallback. Local devs and macOS keep using uv (faster); CI installs uv via `astral-sh/setup-uv@v5`. If neither, falls back to stdlib `python3 -m venv` + `pip`.
- TRN-1003 step 4: now references `make release-prep` instead of `make release`. Adds explicit warning that `make bump` uses BSD `sed -i ''` and must NEVER run in CI.
- TRN-1004: full rewrite for the new flow (PR-merge → `release-prep` → tag push → CI publishes). Documents `workflow_dispatch` as the only sanctioned retry path.
- TRN-1000 decision tree path 4 wording.

### Removed
- `make release`: deleted (not deprecated). Calling it now prints `make: *** No rule to make target 'release'` — intended footgun-prevention.

### Notes for users
- **One-time setup required**: protect the `v[0-9]+.[0-9]+.[0-9]+` tag pattern in repo settings → Rules → Rulesets, restricting create/update/delete to maintainers. Without this, anyone with write access can publish a release by pushing a tag.
- The release workflow uses the workflow-issued `GITHUB_TOKEN` only — no PAT, no OIDC, no secrets. Supply chain is `actions/checkout@v4` + `astral-sh/setup-uv@v5` + `actions/upload-artifact@v4` + direct `gh` calls.

## [1.6.0] - 2026-04-26
### Changed
- `trinity-codex`: pin model to `gpt-5.5` via `-m gpt-5.5` on every `codex exec` / `codex exec resume` call (TRN-2005). Default codex CLI registration in `Makefile` and `install.sh` now includes the flag, so `make install` / remote `install.sh` produce a deterministic codex provider regardless of the user's local `~/.codex/config.toml` default model.
- `trinity-codex` agent prose: GPT-5.4 → GPT-5.5.

### Notes for users
- **Requires codex-cli ≥ 0.125** (when `gpt-5.5` became available). Older CLIs will fail with "unknown model"; upgrade codex-cli before reinstalling Trinity.
- **Reinstall recommended** to pick up the pinned `-m gpt-5.5` flag in `~/.claude/trinity.json` and the refreshed `trinity-codex.md` agent file.

## [1.5.0] - 2026-04-25
### Changed
- **Provider templates now built from shared partials** (TRN-2004). `providers/*.md` are generated from `providers/_base/{common-session,common-tail,family-wrapper}.md` + `providers/<name>.delta.md` via `scripts/build_providers.sh`. Single source of truth, single edit propagates to all 5 providers. Source LOC reduced ~200 lines; install footprint and runtime behavior unchanged.

### Fixed
- `trinity-codex`: replace `-c reasoning.effort=high` (silently ignored by codex-cli 0.124+) with `-c model_reasoning_effort=$EFFORT`. Default `xhigh`. Per-prompt `EFFORT=<level>` override parsing (valid values: `none`, `low`, `medium`, `high`, `xhigh`).
- `trinity-openrouter` / `trinity-deepseek`: replace race-unsafe `ls -t | head -1` JSONL selector with prompt-marker grep (`TRINITY_TRACE`). Bash 3.2 compatible (works on macOS default `/bin/bash`); robust under sub-second concurrent dispatches in the same project.
- All 5 providers: lifted "If the provider produces code, verify it looks reasonable before returning" rule into common partial — previously inconsistent (codex/glm only).

### Added
- `make build`: regenerate `providers/*.md` from partials.
- `make verify-built`: assert committed providers match generated output (drift gate). Runs as part of `make test` and `make release`.
- `make install-hooks`: install pre-commit hook that runs `verify-built`.
- `tests/test_build_providers.sh`: 96 assertions (T1 determinism, T2 frontmatter, T3 trailing LF, T4 partial invariants, T5 no stale `@include`, T6 semantic section presence + H3-under-H2 hierarchy walker, T7 drift sentinels for the 3 bundled fixes).
- SOP updates: TRN-1003 notes `make build` runs in `make bump`; TRN-1004 adds `make verify-built` prerequisite.

### Notes for users
- **Reinstall recommended** to pick up the three bundled bug fixes — especially the codex reasoning-effort fix, which silently degraded Codex output on 1.4.0.
- **Local hand-patches will be overwritten on reinstall.** If you previously hand-patched `~/.claude/agents/trinity-codex.md` or `trinity-deepseek.md`, the upstream fixes subsume those patches; reinstalling 1.5.0 overwrites your local edits (intended behavior).

## [1.4.0] - 2026-04-24
### Added
- DeepSeek V4 provider (default model: `deepseek-v4-pro`, 1M context, session resume via `claude --resume`)

### Fixed
- `install.sh`: download + register `openrouter` provider (missing since v1.3.0)
- `providers/codex.md`: replace removed `-r xhigh` short flag with `-c reasoning.effort=high` (codex CLI 0.124+ dropped the short form)

## [1.3.0] - 2026-04-04
### Added
- `session.py heartbeat <output_file>`: parse JSONL output files and report agent activity
- OpenRouter provider with portable `run_openrouter()` fallback (no custom wrapper required)
- 6 new heartbeat tests (46 total)

### Changed
- Release SOPs (TRN-1003, TRN-1004): require code commit before version bump

## [1.2.1] - 2026-04-03
### Fixed
- Include heartbeat code in release (v1.2.0 only had version-bump files)

## [1.2.0] - 2026-04-01
### Added
- `session.py heartbeat <output_file>`: parse JSONL output files and report agent activity, replacing inline Python snippets

## [1.1.1] - 2026-03-22
### Added
- README: "If You Are an AI" installation guide for LLM agents

## [1.1.0] - 2026-03-22
### Added
- Remote install script (`install.sh`): `curl -fsSL .../install.sh | bash`
- Shell test suite (`tests/test_install_sh.sh`): 8 integration tests (T1-T7, T3b)
- Default provider registration (glm, codex, gemini) on install via `install.py register`
- trinity-gemini: specify `--model gemini-3.1-pro-preview` for all CLI calls
- 2 new session tests (whitespace-only file, corrupt JSON) — 40 pytest tests total

## [1.0.0] - 2026-03-21
### Added
- Initial release: session.py, config.py, discover.py, install.py
- Provider templates: glm, codex, gemini
- SKILL.md with full /trinity command set
- 38 pytest tests

# Changelog

## [Unreleased]

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

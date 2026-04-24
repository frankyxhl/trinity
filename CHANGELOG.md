# Changelog

## [Unreleased]
### Added
- DeepSeek V4 provider (default model: `deepseek-v4-pro`, 1M context, session resume via `claude --resume`)

### Fixed
- `install.sh`: download + register `openrouter` provider (missing since v1.3.0)

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

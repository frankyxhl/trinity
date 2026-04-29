# Changelog

## [Unreleased]

## [3.0.0] - 2026-04-29

### Added
- Codex compatibility packaging: repo-local skill at `.agents/skills/trinity/SKILL.md`, local plugin manifest at `plugins/trinity/.codex-plugin/plugin.json`, bundled plugin skill at `plugins/trinity/skills/trinity/SKILL.md`, and repo marketplace entry at `.agents/plugins/marketplace.json`. Added `tests/test_codex_compat.py` to validate the import surfaces and README smoke-check documentation while preserving the existing Claude Code install path.

## [2.0.5] - 2026-04-26

### Fixed
- `Makefile` `bump` target: replace BSD-only `sed -i ''` with portable `perl -i -pe` for both `__version__` (in `scripts/__init__.py`) and `REQUIRED_VERSION` (in `SKILL.md`) rewrites. The prior form failed on Linux because GNU sed treats `''` as the input file path — a Linux maintainer running `make bump` would have hit the same trap class as the v2.0.0 stat-order incident. Found by the first run of the TRN-1801 evolve cycle (signal: cross-platform shell trap grep). Pre-existing version pins were already in sync (VERSION=2.0.3 / `__version__=2.0.3` / `REQUIRED_VERSION=2.0.3`), so this is preventive, not a fix-after-incident. New `tests/test_make_bump.sh` adds two regression cases — T1 verifies `perl -i -pe` rewrites both pin files and preserves unrelated lines; T2 is a static guard that fails if anyone re-introduces `sed -i ''` in the bump target. Wired into `make test`.
- `rules/TRN-1006-SOP-Provider-Model-IDs.md`: backfill canonical SOP structure — add `Last reviewed` metadata, `## When to Use`, `## When NOT to Use`, and rename `## Steps — Updating a Model ID` to `## Steps` with a one-line preamble (the suffix tripped `af validate`'s exact-match section check). Brings the SOP added in v2.0.3 to the same shape as TRN-1801 / TRN-1000.
- Metadata backfill across 8 PRJ docs flagged by `af validate`: `TRN-1004-SOP-Release.md` and `TRN-1005-SOP-Install.md` now carry `Last reviewed: 2026-04-26`; `TRN-2003/2004/2005/2006/2007/2009-CHG-*.md` now carry both `Last updated` (matching their original `Date`) and `Last reviewed: 2026-04-26`. Drops `af validate` issue count from 43 → 24.
- `rules/TRN-1003-SOP-Version-Bump.md` line 24: replace stale "BSD `sed -i ''` syntax" note with the new portable `perl -i -pe` form and a pointer to `tests/test_make_bump.sh`. Caught by Codex in the §5 Reviewer A gate on the diff — active-SOP drift would have left a future contributor reading "never invoke `make bump` from CI" while the actual implementation was already cross-platform. Added `Last reviewed` while touching the metadata.

### Notes
- First run of the TRN-1801 evolve cycle. Four-reviewer gate met (Codex 9.1 / DeepSeek 9.5 / GLM 9.2 / Gemini 9.3, mean 9.275, all PASS ≥9.0). Codex initially returned 8.4/FAIL on the diff (caught the TRN-1003:24 active-SOP drift blocker that lead missed); resolved by C5 patch then re-gated to PASS. Shipped as merged PR #14. Skipped C3 (TRN-1001/1002/1003/1004 structural-section retrofit) — atomicity rule splits it into 16 sub-candidates, deferred for a future cycle.
- **v2.0.4 was skipped.** A `v2.0.4` tag was pushed to origin pointing at the cycle-1 PR-merge commit (where VERSION was still 2.0.3), without the `Release v2.0.4` commit having reached origin. CI's `verify` job correctly rejected the mismatch (TRN-2007 working as designed — no GitHub Release was published). Per TRN-1801 guard rail "fix forward with a patch bump, do not force-push the tag," the cycle ships as v2.0.5. The dead `v2.0.4` tag remains on origin with no Release attached.

## [2.0.3] - 2026-04-26
### Added
- `rules/TRN-1800-REF-Evolution-Philosophy.md` — PRJ-layer override of COR-1800 for the trinity repo. Defines trinity-specific behaviour baseline (the union of `make test` / `make verify-built` / `make lint` / `install.sh` share-readiness against tmp HOME / Linux CI parity / dispatch sample), and overrides COR-1800's code-evolution and document-evolution weight tables plus the signal-source table with trinity-specific axes (cross-platform parity, generated-vs-source build via `_base/`, `Makefile`↔`install.sh` provider-parity, model-ID drift vs vendor docs).
- `rules/TRN-1801-SOP-Evolve-Trinity.md` — concrete evolve loop wired to TRN-1800. Six-step Signal → Candidate → Evaluation → Implementation → Review → PR cycle; signal-collection commands are runnable shell snippets (build drift, provider parity, BSD/GNU shell traps, model-ID drift, install.sh smoke against `mktemp -d`, CHANGELOG `[Unreleased]` lag, SOP↔code drift, `af validate`); surface taxonomy distinguishes single-purpose files vs multi-section docs vs symmetric multi-file refactors (the two recognised symmetric classes are `_base/*.md` → 5-provider cascade and the two Anthropic-compat `bin/` wrappers); guard rails explicitly call out the v2.0.0 stat-order class of macOS-only-test-passes-but-Linux-CI-fails bug. Mirrors the CLD-1800/1801 shape used in the `~/.claude/` repo.
- `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` decision tree: paths 6 (TRN-1006 model-ID pinning) and 7 (TRN-1801 evolve cycle) added with explicit trigger phrases ("run evolve", "audit trinity", "bump model"); existing feature/incident/TDD paths shifted to 8/9/10. Future sessions reach the new SOPs from a cold start via `af read TRN-1000`.

### Fixed
- `rules/TRN-1801-SOP-Evolve-Trinity.md` §1 parity-diff command produced false positives — Makefile uses TAB indent + `$(HOME)` while install.sh uses 4-space indent + `${HOME}`, so a literal `diff` reported every line as drift even when parity was fine. Now normalised via a `_norm` shell function (`sed -E 's/^[[:space:]]+//; s/\$\(HOME\)/${HOME}/g'`) before sort. Caught by DeepSeek in Round-1 of the 3-model strict review on the docs.
- `rules/TRN-1000-SOP-Workflow-Routing-PRJ.md` metadata: `Last updated` and `Last reviewed` were stuck at 2026-03-21 despite multiple 2026-04-26 edits to the decision tree. Bumped to current date. Caught by Codex in the same review.
### Changed
- `providers/bin/deepseek`: pin `ANTHROPIC_MODEL` to `deepseek-v4-pro[1m]` (1M-context tier) instead of the bare `deepseek-v4-pro` (default-context tier). The `[1m]` suffix is a literal model-ID convention for the 1M-context variant — same shape as Anthropic's `claude-opus-4-7[1m]` — NOT an ANSI escape. Regression assertion in `tests/test_anthropic_compat_wrappers.py::test_t1_deepseek_env_key_sets_anthropic_env_and_passes_argv` guards future copy-paste from accidentally stripping the suffix. `ANTHROPIC_SMALL_FAST_MODEL` stays at `deepseek-v4-flash` (small-fast tier rarely needs 1M context).
- New SOP `rules/TRN-1006-SOP-Provider-Model-IDs.md` documenting the `[1m]` suffix convention, where each provider's model ID is pinned (native-CLI providers vs Anthropic-compat wrappers), and the update workflow with shell-quoting guard rails.

### Fixed
- `README.md`: refresh stale version examples (`Trinity 1.4.0` → `2.0.1`, `TRINITY_VERSION=1.1.0` → `2.0.1`) and document the new `bin/` wrappers shipped in v2.0.0. The "What was installed" table now lists `~/.claude/skills/trinity/bin/{deepseek,openrouter}`. The "Or install manually" block was actively misleading on v2.0.0 — it omitted the `mkdir -p .../bin/`, `cp providers/bin/*`, and `chmod +x` steps, so anyone copying it ended up with broken DeepSeek/OpenRouter providers (no wrapper script to invoke). The manual `trinity.json` example also picks up the `-m gpt-5.5` codex pin (TRN-2005, shipped in v1.6.0) that was never reflected.

## [2.0.1] - 2026-04-26
### Fixed
- `providers/bin/{deepseek,openrouter}`: swap `stat` invocation order — try GNU `stat -c '%a'` first, fall back to BSD `stat -f '%Lp'`. The original BSD-first order broke on Linux because GNU `stat`'s `-f` is `--file-system` (filesystem-info mode, not format-string), which returns exit 0 with a multi-line block of filesystem stats, so the `||` fallback never fires and `PERM` ends up as multi-line garbage that fails the `case 600|400)` match. All key-file paths refused with a confusing "perm <multiline> 600" message. macOS local tests passed because BSD stat's `-f '%Lp'` works there. Caught by the v2.0.0 release CI on Linux runner — TRN-2007's verify/publish split prevented a broken release from being published. After the swap: GNU `-c '%a'` is the unambiguous primary path (Linux); BSD `-c` is invalid and fails fast (macOS), letting the `-f '%Lp'` fallback return the right value. Existing tests T2/T5/T6/T6b/T7 are the regression — they were the ones that failed on Linux CI and now pass on both platforms.

## [2.0.0] - 2026-04-26
### Changed (BREAKING for re-install)
- **Removed `.zshrc` dependency from `deepseek` and `openrouter` providers** (TRN-2008 PRP / TRN-2009 CHG). Both providers now use portable POSIX `sh` wrappers shipped at `providers/bin/{deepseek,openrouter}` and installed to `~/.claude/skills/trinity/bin/` by `install.sh` and `make install`. Fresh users no longer need to copy any shell-rc snippet to use these providers. API key resolves from `$<PROVIDER>_API_KEY` (env wins, 12-factor) or `~/.secrets/<provider>_api_key` (mode `0600` or `0400`; anything more permissive is hard-refused with a stderr message). The wrappers `exec claude --dangerously-skip-permissions "$@"` so signals propagate cleanly. **Migration:** existing users with `"cli": "deepseek_cy -p"` / `"openrouter_cy -p"` in `~/.claude/trinity.json` MUST re-run `install.sh` (or `make install`) — it overwrites those two `cli` entries to absolute-path form. After re-install, the legacy `deepseek_cy` / `openrouter_cy` zsh functions in `.zshrc` are no longer reached and can be deleted at leisure. Other providers (`glm`, `codex`, `gemini`) untouched. Approved per COR-1602 strict review (4 reviewers, converged in 2 iterations: Codex 8.9, Gemini 9.8, GLM 8.8, DeepSeek 10.0) plus a final GLM implementation review. New `tests/test_anthropic_compat_wrappers.py` (17 cases) covering env precedence, perm-check refusal, mode-400 acceptance, `--resume` argv ordering, and the BSD/GNU `stat`-fails-on-exotic-FS branch; new T9 + T11 in `tests/test_install_sh.sh` covering bin-script install + legacy migration. PR #13.

### Fixed
- `.github/workflows/release.yml` `Publish GitHub Release` step: when a `push.tags` event finds a release already published (Path A duplicate-trigger or Path B re-run), the step exits cleanly (exit 0) instead of failing with "Release already exists". Surfaced on the v1.8.0 end-to-end run — TRN-2007 D11's PAT path re-triggers the workflow on every Path A push (PAT-pushed tags fire workflows; GITHUB_TOKEN-pushed ones don't, which the original review missed). The `workflow_dispatch` retry path still fails loud on existing release (operator explicitly asked to re-publish; tell them it's already done). Trade-off documented inline: a maintainer admin-bypass force-push to a tag with a stale release will silently skip publish — the tag-protection ruleset's "Restrict updates" rule narrows the risk window. Multi-model review on the initial fix (Codex PASS / Gemini FAIL on force-push concern) → log message neutralized + 5 T11 assertions covering control-flow placement, not just string presence.
- `.github/workflows/release.yml`: new `preflight` job short-circuits the duplicate tag-push trigger before `verify`/`publish` run (issue #11). Prior fix exited cleanly at the publish step but still burned ~3 min on `verify` (checkout + setup-uv + install + verify-built + test + lint + extract-notes). Preflight runs a single ~5s `gh release view` check; on tag-push events for already-published tags it sets `skip=true` and both `verify` and `publish` are skipped via `if: needs.preflight.outputs.skip != 'true'`. `workflow_dispatch` events bypass the preflight check entirely (operator intent: run it). The publish step's in-script `EVENT_NAME == push` exit-0 branch is retained as defense-in-depth for the race window between preflight and publish. New T12 (9 assertions) + T1/T11 updates (3 changes) cover the new job structure (103/103 total).

## [1.8.0] - 2026-04-26
### Added
- **One-click release** via Actions UI (TRN-2007). The `workflow_dispatch` trigger on `release.yml` now accepts an optional `tag_name` input; leaving it empty derives `vX.Y.Z` from the `VERSION` file on the dispatched ref, creates and pushes the tag, then publishes — all in one workflow run. Click "Run workflow" from the Actions tab on `main` and you're done. A new main-only guard rejects one-click attempts from feature branches; the explicit-`tag_name` retry path remains unchanged. TRN-1004 SOP restructured into Path A (one-click) / Path B (tag push CLI) / Path C (retry).
- **2-job verify/publish split + concurrency + env-mapping hardening** (TRN-2007 D9–D12, post multi-model review). The release workflow is now `verify` (read-only, runs verify-built/test/lint/extract-notes/upload-artifact — third-party actions like `astral-sh/setup-uv` cannot push tags) → `publish` (write, only first-party actions, downloads artifact, creates+pushes tag, calls `gh release create`). New `concurrency: { group: release, cancel-in-progress: false }` prevents simultaneous dispatches from racing. All `${{ github.* }}` references in `run:` blocks moved to `env:` mapping. `gh release create` scoped via explicit `--repo "$GITHUB_REPOSITORY"`. New `tests/test_release_workflow.sh` T10 (12 assertions) + T11 (17 assertions) cover all of the above (81/81 total).

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

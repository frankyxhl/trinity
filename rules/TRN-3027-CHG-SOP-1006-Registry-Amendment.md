# CHG-3027: TRN-1006 SOP Amendment — Registry as Authoritative Pin Source

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** TRN-3020 follow-up (deferred from PR #66 round-2 review)
**Priority:** Low
**Change Type:** Doc-only amendment
**Targets:** `rules/TRN-1006-SOP-Provider-Model-IDs.md` (single file)
**Builds on:** TRN-3020 (introduced `providers/registry.json` as install-time authoritative source)

---

## What

Amend `TRN-1006-SOP-Provider-Model-IDs.md` to reference `providers/registry.json` as the authoritative source for the `cli` string of native-CLI providers (codex, glm). Anthropic-compat wrapper providers (deepseek, openrouter, claude-code) keep their model pins inside `providers/bin/<name>` env blocks — those pins remain out of registry scope until TRN-3026 lands.

Specifically:

1. The pin-location table (current §"Where Model IDs Are Pinned") replaces "Makefile + install.sh register" entries with "providers/registry.json" for codex and glm; deepseek and openrouter rows updated to note registry holds only the bin-script wrapper path.
2. Section A "Native-CLI providers (codex, glm)" replaces step 1+2 ("update Makefile, update install.sh") with a single step: "edit `providers/registry.json`'s `cli` field". Steps 4-9 unchanged.
3. Add a Guard Rail bullet: "After editing `providers/registry.json`, run `make install` against `HOME=$(mktemp -d)` to confirm the registered cli matches".
4. Add a Change History row noting the amendment + reference to this CHG.

## Why

PR #66 (TRN-3020) introduced `providers/registry.json` as the install-time source consumed by `scripts/install.py` (Makefile + install.sh both call it). Before TRN-3020, model pins for native-CLI providers lived in the Makefile and install.sh `register` lines (two locations, drift-prone). After TRN-3020, the registry IS the source — Makefile and install.sh derive from it. TRN-1006 still describes the old two-location pattern. Without the amendment, future model bumps will edit the wrong files (or duplicate effort); the SOP must reflect the post-TRN-3020 reality.

This was explicitly deferred to TRN-3027 in TRN-3020's "Out of Scope" section ("currently lists pin locations + step-by-step pin-update procedure; will become partially obsolete once registry exists. Cannot amend in-CHG without scope creep").

## Out of Scope

- Bringing deepseek/openrouter/claude-code env-var pins into the registry (that's TRN-3026 — needs a registry shape extension for `env_vars` mapping).
- Adding `gemini` to the registry (deferred to TRN-3025 pending canonical CLI value decision).
- Amending TRN-1003 (release SOP) — release-prep already references the right files via `make verify-built`; no SOP drift there.

## Surfaces

| # | Surface | Change |
|---|---------|--------|
| 1 | `rules/TRN-1006-SOP-Provider-Model-IDs.md` | Pin-location table updated (5 rows), Section A steps 1-2 replaced with single "edit registry.json" step, new Guard Rail bullet, Change History row |
| 2 | `CHANGELOG.md` | `[Unreleased] ### Changed` entry |

## Acceptance Criteria

- **A1**: Pin-location table row for `codex` reads "providers/registry.json" (was Makefile + install.sh register codex).
- **A2**: Pin-location table row for `glm` reads "providers/registry.json + providers/glm.delta.md + .agents/trinity.codex.json" (registry replaces Makefile + install.sh; glm has additional caller-side flags in delta + codex config).
- **A3**: Pin-location table rows for `deepseek` and `openrouter` reference both `providers/bin/<name>` (the model pin) AND `providers/registry.json` (the bin-path entry) — the env-var pin is registry-out-of-scope until TRN-3026.
- **A4**: Section A step 1 reads "Edit `providers/registry.json`'s `providers.<name>.cli` field" — replaces the previous 2 steps that updated Makefile + install.sh separately.
- **A5**: New Guard Rail: "After editing `providers/registry.json`, run `make install` against `HOME=$(mktemp -d)` to confirm the registered cli matches".
- **A6**: Section B (Anthropic-compat providers) — unchanged. Model pins for deepseek/openrouter still live in `providers/bin/<name>`.
- **A7**: `af validate --root .` still passes (structural validity preserved).
- **A8**: Change History table appends a 2026-05-08 row referencing this CHG.

## Implementation Order

1. Edit `rules/TRN-1006-SOP-Provider-Model-IDs.md` — table + Section A + Guard Rails + Change History.
2. Add `CHANGELOG.md` `[Unreleased] ### Changed` entry.
3. Run `af validate --root .` — confirm 0 issues.
4. Open PR with `Closes` reference to TRN-3027 follow-up note.

## Risk Assessment

Doc-only change. No code paths affected. No tests change. The only "behavioral" risk is the SOP being internally inconsistent with current code — confirmed not the case (registry IS authoritative as of TRN-3020 merge).

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft, marked Approved (doc-only, scope clear from TRN-3020 deferral) | Claude Code |

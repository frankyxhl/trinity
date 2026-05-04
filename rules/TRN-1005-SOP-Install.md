# SOP-1005: Install — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** Active

---

## What Is It?

Install Trinity to `~/.claude/`.

---

## Why

The Claude Code adapter loads from `~/.claude/`, so local and remote installs must put the skill, scripts, providers, wrapper binaries, and provider registry in the expected paths.

---

## When to Use

- Installing Trinity for Claude Code
- Refreshing an existing local install after a version bump or provider change
- Verifying install behavior before release

## When NOT to Use

- Installing the Codex-native adapter; use `make install-codex`
- Testing code without mutating the user's home directory; use a temporary `HOME`

---

## Steps

**Remote install (no git clone required):**

1. Run: `curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash`
2. To install a specific version: `curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=1.0.0 bash`
3. Verify: `python3 ~/.claude/skills/trinity/scripts/session.py --version`

**Local install (from cloned repo):**

1. Run `make install`
2. Verify: `python3 ~/.claude/skills/trinity/scripts/session.py --version`

Expected output: the version constant from `scripts/__init__.py` (matches `VERSION` file).

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-05-04 | Backfill Why/When sections and clarify Codex install is separate | Codex |
| 2026-03-21 | Add remote install path (TRN-2002) | Claude Code |
| 2026-03-21 | Initial version | Claude Code |

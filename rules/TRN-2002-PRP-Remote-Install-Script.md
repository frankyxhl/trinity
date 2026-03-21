# PRP-2002: Remote Install Script

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Last updated:** 2026-03-21
**Last reviewed:** 2026-03-21
**Status:** Approved
**Reviewed by:** Codex 8.7/10 FIX, Gemini 8.4/10 FIX (Rev 1, 2026-03-21); Codex 9.2/10 PASS, Gemini 9.8/10 PASS (Rev 2, 2026-03-21)
**Related:** TRN-2001 (Release Infrastructure, Completed), TRN-1005 (SOP Install)

---

## What Is It?

Add `install.sh` to the trinity repo root so that any user — or LLM — can install Trinity with a single command line, without cloning the repo:

```bash
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
```

---

## Problem

1. **Installation requires local clone.** Current path: `git clone` → `cd trinity` → `make install`. Three steps, requires git, requires knowing the repo URL, requires the working directory to be correct.

2. **LLM agents cannot self-install.** An LLM running `make install` needs the repo already present on disk. A one-liner curl command can be run directly from a Bash tool call with no prior setup.

3. **No version pinning for remote install.** There is no way to install a specific release without cloning. A remote installer should support `TRINITY_VERSION=x.y.z` override.

---

## Proposed Solution

### Single file: `install.sh` (repo root)

The script mirrors the logic of `make install` but downloads files from GitHub raw URLs instead of copying from local disk.

### Invocation forms

```bash
# Install latest (main branch)
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash

# Install specific version (pass without leading v — script normalizes internally)
curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=1.0.0 bash
```

### Script contract

**Inputs:**

| Variable | Format | Default | Notes |
|----------|--------|---------|-------|
| `TRINITY_VERSION` | semver without leading `v` (e.g. `1.0.0`) | unset | If user passes `v1.0.0`, script strips the leading `v` and proceeds normally |
| `TRINITY_BASE_URL` | full URL prefix, no trailing slash | derived from `TRINITY_VERSION` | Override for testing; if set, skips all GitHub URL logic |

**Base URL resolution (applied only when `TRINITY_BASE_URL` is not set):**
- `TRINITY_VERSION` set → `https://raw.githubusercontent.com/frankyxhl/trinity/v${TRINITY_VERSION}`
- `TRINITY_VERSION` unset → `https://raw.githubusercontent.com/frankyxhl/trinity/main`

Note: `raw.githubusercontent.com` uses `/{ref}/path` — tag refs are bare tag names (`v1.0.0`), not `refs/tags/v1.0.0`.

**Directories created (idempotent, `mkdir -p`):**
```
~/.claude/skills/trinity/scripts/
~/.claude/agents/
```

**Files downloaded and their destinations:**

| Source (relative to base URL) | Destination |
|-------------------------------|-------------|
| `SKILL.md` | `~/.claude/skills/trinity/SKILL.md` |
| `scripts/__init__.py` | `~/.claude/skills/trinity/scripts/__init__.py` |
| `scripts/session.py` | `~/.claude/skills/trinity/scripts/session.py` |
| `scripts/config.py` | `~/.claude/skills/trinity/scripts/config.py` |
| `scripts/discover.py` | `~/.claude/skills/trinity/scripts/discover.py` |
| `scripts/install.py` | `~/.claude/skills/trinity/scripts/install.py` |
| `providers/glm.md` | `~/.claude/agents/trinity-glm.md` |
| `providers/codex.md` | `~/.claude/agents/trinity-codex.md` |
| `providers/gemini.md` | `~/.claude/agents/trinity-gemini.md` |

All 9 files are required. There are no optional downloads.

**Download mechanism:** For each file, the script sets `CURRENT_FILE=<source path>` immediately before calling `curl -fsSL "${BASE_URL}/${CURRENT_FILE}" -o <dest>`. The `-f` flag causes curl to exit non-zero on HTTP 4xx/5xx errors.

**Error handling:**

```bash
set -e
CURRENT_FILE=""
trap 'echo "trinity-install: failed downloading ${CURRENT_FILE}" >&2' ERR
```

- `set -e` — any failed curl or mkdir aborts immediately.
- `CURRENT_FILE` is set to the source path string (e.g. `scripts/session.py`) before each curl call. The ERR trap reads this variable to identify the failing file.
- On failure, the partial destination file may exist (curl writes directly to dest). This is acceptable — the installer is idempotent and a re-run overwrites the partial file.

**Success output** (printed after all downloads complete):

```
Trinity <version> installed to ~/.claude/
```

Version is extracted from the installed file using:
```bash
grep '^__version__ = ' ~/.claude/skills/trinity/scripts/__init__.py \
  | sed 's/__version__ = "\(.*\)"/\1/'
```

If the grep/sed extraction fails for any reason, fall back to printing `Trinity installed to ~/.claude/` (without version).

**No smoke test.** The installer does not invoke python3 or verify the installed scripts run correctly. Runtime verification is handled by the SKILL.md startup check (`python3 session.py --version`), which already exists.

### Idempotency

Running the script multiple times is safe. Files are overwritten silently. No state is tracked between runs.

---

## Scope

**In scope:**
- `install.sh` (new file, repo root)
- Update `TRN-0000` to add entry for TRN-2002
- Update `TRN-1005` (SOP Install) to document the remote install path alongside `make install`
- Update `README.md` Quick Start section to show the curl one-liner as the primary install method

**Out of scope:**
- Auto-registering providers in `~/.claude/trinity.json` (user does this via `/trinity install <provider>`)
- Windows support (curl pipe bash doesn't work on Windows cmd)
- Uninstall script
- Checksum verification of downloaded files
- Making any provider files optional (all 9 files are required; see Design Decisions)

---

## Design Decisions

**OQ-1 resolved — No smoke test.**
The SKILL.md startup check already verifies `python3 session.py --version` on every Claude Code session start. Adding a duplicate check in `install.sh` adds complexity and a python3 dependency to the installer for no net gain.

**OQ-2 resolved — All provider files are required (hard exit on 404).**
Making providers optional adds conditional logic and silently incomplete installs. The three provider files (`glm.md`, `codex.md`, `gemini.md`) are committed to the repo and will always be present. If a future provider is added, it must be added to `install.sh` at the same time — this is the same discipline as updating `make install`. Maintenance drift between `make install` and `install.sh` is explicitly accepted as a known risk (see Risk table).

---

## Test Cases

All tests run against `install.sh` with `$HOME` redirected to a tmp dir and `TRINITY_BASE_URL` pointing to a local directory served via `python3 -m http.server`. No network access required.

| # | Test | Expected |
|---|------|----------|
| T1 | Run install.sh with no env vars (TRINITY_BASE_URL set to local server) | All 9 files present in correct destinations; exit 0; success output contains version string |
| T2 | Run install.sh twice (idempotent) | Second run succeeds; files overwritten; exit 0 |
| T3 | `TRINITY_VERSION=1.0.0` set; TRINITY_BASE_URL set to local server | Exit 0; all 9 files installed |
| T4 | `TRINITY_VERSION=v1.0.0` (leading v) | Script strips leading v, proceeds as `1.0.0`; exit 0 |
| T5 | Destination dirs do not exist before run | Dirs created by script; exit 0 |
| T6 | One file missing from local server (returns 404) | Script exits non-zero; stderr contains `failed downloading <filename>` |
| T7 | `__init__.py` contains `__version__ = "2.3.4"` | Success output prints `Trinity 2.3.4 installed to ~/.claude/` |

Tests are shell-level (`bash install.sh`) using `TRINITY_BASE_URL` to redirect downloads. No pytest required.

---

## Risk

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| GitHub raw URL changes structure | Low | Tag-based URLs are stable; main is best-effort |
| User's curl doesn't support `-f` flag | Very low | `-f` is POSIX curl, available everywhere |
| Partial install if user Ctrl-C mid-run | Low | Idempotent — re-run overwrites partial files |
| `install.sh` file list drifts from `make install` | Medium | Both must be updated together when adding files; no automated sync check exists — accepted trade-off for simplicity |
| Interrupted curl writes truncated file to dest | Low | Idempotent — re-run overwrites; not a silent corruption risk since scripts fail loudly if truncated |

#!/usr/bin/env bash
# install.sh — Install Trinity to ~/.claude/ without cloning the repo.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/main/install.sh | TRINITY_VERSION=1.0.0 bash
#
# Environment variables:
#   TRINITY_VERSION   Semver tag to install (e.g. 1.0.0 or v1.0.0). Defaults to main.
#   TRINITY_BASE_URL  Override base URL (no trailing slash). Used for testing.

set -eE

CURRENT_FILE=""
trap 'echo "trinity-install: failed downloading ${CURRENT_FILE}" >&2' ERR

# Resolve base URL
if [ -n "${TRINITY_BASE_URL}" ]; then
    BASE_URL="${TRINITY_BASE_URL}"
elif [ -n "${TRINITY_VERSION}" ]; then
    # Strip leading v if present, then prepend v for the tag ref
    VERSION="${TRINITY_VERSION#v}"
    BASE_URL="https://raw.githubusercontent.com/frankyxhl/trinity/v${VERSION}"
else
    BASE_URL="https://raw.githubusercontent.com/frankyxhl/trinity/main"
fi

# Probe: does the target version include providers/registry.json?
# This file is required by the install flow as of TRN-3020. Older tags
# don't have it, and their scripts/install.py doesn't have the
# register-from-registry subcommand — piping main's install.sh against
# an old TRINITY_VERSION would fail mid-install with a confusing error.
# Detect early and direct the user to the tag's own install.sh, which
# is self-contained for that version.
if ! curl -fsSL --head "${BASE_URL}/providers/registry.json" -o /dev/null 2>/dev/null; then
    echo "trinity-install: TRINITY_VERSION '${TRINITY_VERSION:-main}' does not include providers/registry.json." >&2
    echo "trinity-install: This file was added in the TRN-3020 release. To install an older tag," >&2
    echo "trinity-install: use that tag's own install.sh directly:" >&2
    echo "" >&2
    echo "    curl -fsSL https://raw.githubusercontent.com/frankyxhl/trinity/v\${TRINITY_VERSION}/install.sh | bash" >&2
    echo "" >&2
    echo "trinity-install: Each tagged release ships a self-contained installer for that version." >&2
    exit 1
fi

# Create destination directories
mkdir -p "${HOME}/.claude/skills/trinity/scripts"
mkdir -p "${HOME}/.claude/skills/trinity/bin"
mkdir -p "${HOME}/.claude/skills/trinity/providers"
mkdir -p "${HOME}/.claude/agents"

# Download each file
_download() {
    CURRENT_FILE="$1"
    curl -fsSL "${BASE_URL}/${CURRENT_FILE}" -o "$2"
}

_download "SKILL.md"                  "${HOME}/.claude/skills/trinity/SKILL.md"
_download "scripts/__init__.py"       "${HOME}/.claude/skills/trinity/scripts/__init__.py"
_download "scripts/session.py"        "${HOME}/.claude/skills/trinity/scripts/session.py"
_download "scripts/config.py"         "${HOME}/.claude/skills/trinity/scripts/config.py"
_download "scripts/discover.py"       "${HOME}/.claude/skills/trinity/scripts/discover.py"
_download "scripts/install.py"        "${HOME}/.claude/skills/trinity/scripts/install.py"
_download "scripts/scan_rocket_issues.sh" "${HOME}/.claude/skills/trinity/scripts/scan_rocket_issues.sh"
chmod +x "${HOME}/.claude/skills/trinity/scripts/scan_rocket_issues.sh"
_download "providers/glm.md"          "${HOME}/.claude/agents/trinity-glm.md"
_download "providers/codex.md"        "${HOME}/.claude/agents/trinity-codex.md"
_download "providers/gemini.md"       "${HOME}/.claude/agents/trinity-gemini.md"
_download "providers/openrouter.md"   "${HOME}/.claude/agents/trinity-openrouter.md"
_download "providers/deepseek.md"     "${HOME}/.claude/agents/trinity-deepseek.md"
_download "providers/claude-code.md"  "${HOME}/.claude/agents/trinity-claude-code.md"
_download "providers/bin/deepseek"    "${HOME}/.claude/skills/trinity/bin/deepseek"
_download "providers/bin/openrouter"  "${HOME}/.claude/skills/trinity/bin/openrouter"
_download "providers/bin/claude-code" "${HOME}/.claude/skills/trinity/bin/claude-code"
_download "providers/registry.json"   "${HOME}/.claude/skills/trinity/providers/registry.json"
chmod +x "${HOME}/.claude/skills/trinity/bin/deepseek" \
         "${HOME}/.claude/skills/trinity/bin/openrouter" \
         "${HOME}/.claude/skills/trinity/bin/claude-code"

# Validate the downloaded registry is parseable JSON before invoking
# register-from-registry (TRN-3020 §"Surfaces" item 4: a truncated download
# would otherwise produce a partial-install where some providers register
# and some don't).
python3 -c "import json,sys; json.load(open('${HOME}/.claude/skills/trinity/providers/registry.json'))" || {
    echo "trinity: registry.json corrupt or unparseable" >&2
    exit 1
}

CURRENT_FILE=""

# Register default providers in ~/.claude/trinity.json from the canonical
# registry (5 providers: glm, codex, openrouter, deepseek, claude-code).
# Gemini is registered separately below — deferred from registry per
# TRN-3020 (canonical CLI value pending; tracked as TRN-3025 follow-up).
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register-from-registry \
    "${HOME}/.claude/skills/trinity/providers/registry.json" \
    --global-config "${HOME}/.claude/trinity.json"
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register gemini \
    --cli "gemini -p" \
    --global-config "${HOME}/.claude/trinity.json"

# Print success with version
VERSION_STRING=$(grep '^__version__ = ' "${HOME}/.claude/skills/trinity/scripts/__init__.py" \
    | sed 's/__version__ = "\(.*\)"/\1/' 2>/dev/null || true)
if [ -n "${VERSION_STRING}" ]; then
    echo "Trinity ${VERSION_STRING} installed to ~/.claude/"
else
    echo "Trinity installed to ~/.claude/"
fi

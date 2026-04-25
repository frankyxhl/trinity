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

# Create destination directories
mkdir -p "${HOME}/.claude/skills/trinity/scripts"
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
_download "providers/glm.md"          "${HOME}/.claude/agents/trinity-glm.md"
_download "providers/codex.md"        "${HOME}/.claude/agents/trinity-codex.md"
_download "providers/gemini.md"       "${HOME}/.claude/agents/trinity-gemini.md"
_download "providers/openrouter.md"   "${HOME}/.claude/agents/trinity-openrouter.md"
_download "providers/deepseek.md"     "${HOME}/.claude/agents/trinity-deepseek.md"

CURRENT_FILE=""

# Register default providers in ~/.claude/trinity.json
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register glm \
    --cli "droid exec --model glm-5" \
    --global-config "${HOME}/.claude/trinity.json"
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register codex \
    --cli "codex exec --skip-git-repo-check -m gpt-5.5" \
    --global-config "${HOME}/.claude/trinity.json"
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register gemini \
    --cli "gemini -p" \
    --global-config "${HOME}/.claude/trinity.json"
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register openrouter \
    --cli "openrouter_cy -p" \
    --global-config "${HOME}/.claude/trinity.json"
python3 "${HOME}/.claude/skills/trinity/scripts/install.py" register deepseek \
    --cli "deepseek_cy -p" \
    --global-config "${HOME}/.claude/trinity.json"

# Print success with version
VERSION_STRING=$(grep '^__version__ = ' "${HOME}/.claude/skills/trinity/scripts/__init__.py" \
    | sed 's/__version__ = "\(.*\)"/\1/' 2>/dev/null || true)
if [ -n "${VERSION_STRING}" ]; then
    echo "Trinity ${VERSION_STRING} installed to ~/.claude/"
else
    echo "Trinity installed to ~/.claude/"
fi

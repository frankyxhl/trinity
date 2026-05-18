#!/usr/bin/env bash
# scripts/build_codex_skill.sh
#
# Build-time copy for the Codex skill text (TRN-3043 / issue #76).
#
# Source of truth: .agents/skills/trinity/SKILL.md
# Generated copy : plugins/trinity/skills/trinity/SKILL.md
#
# Both files must exist on disk because the two consumers read from different
# package roots: `.agents/` for repo-local Codex skill loading, `plugins/` for
# Codex plugin-marketplace packaging. A symlink would not survive every
# packaging path (tar archives, cross-filesystem checkouts, Windows hosts), so
# we keep both as regular files and enforce parity at build time.
#
# Usage:
#   scripts/build_codex_skill.sh [--check]
#
#   --check   Verify the committed plugin copy is byte-identical to the source.
#             Exit 0 if identical, 1 if drift. Used by `make verify-built` and
#             the pre-commit hook.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SOURCE=".agents/skills/trinity/SKILL.md"
TARGET="plugins/trinity/skills/trinity/SKILL.md"

CHECK_MODE=0
case "${1:-}" in
  "")
    CHECK_MODE=0
    ;;
  "--check")
    CHECK_MODE=1
    ;;
  *)
    echo "build_codex_skill: ERROR: unknown argument: $1" >&2
    echo "usage: scripts/build_codex_skill.sh [--check]" >&2
    exit 2
    ;;
esac

if [ ! -f "$SOURCE" ] || [ -L "$SOURCE" ]; then
  echo "build_codex_skill: ERROR: source missing or not regular: $SOURCE" >&2
  exit 2
fi

if [ "$CHECK_MODE" = "1" ]; then
  if [ ! -f "$TARGET" ]; then
    echo "build_codex_skill --check: drift detected:" >&2
    echo "  $TARGET: NOT COMMITTED" >&2
    exit 1
  fi
  if [ -L "$TARGET" ]; then
    echo "build_codex_skill --check: drift detected:" >&2
    echo "  $TARGET: NOT A REGULAR FILE" >&2
    exit 1
  fi
  if ! cmp -s "$SOURCE" "$TARGET"; then
    echo "build_codex_skill --check: drift detected:" >&2
    echo "  $TARGET: DRIFT (committed differs from $SOURCE)" >&2
    exit 1
  fi
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    staged=$(git diff --cached --name-only -- "$SOURCE" "$TARGET")
    if [ -n "$staged" ]; then
      if ! git cat-file -e ":$SOURCE" 2>/dev/null; then
        echo "build_codex_skill --check: drift detected:" >&2
        echo "  $SOURCE: NOT STAGED" >&2
        exit 1
      fi
      if ! git cat-file -e ":$TARGET" 2>/dev/null; then
        echo "build_codex_skill --check: drift detected:" >&2
        echo "  $TARGET: NOT STAGED" >&2
        exit 1
      fi
      if ! cmp -s <(git show ":$SOURCE") <(git show ":$TARGET"); then
        echo "build_codex_skill --check: staged drift detected:" >&2
        echo "  index:$TARGET differs from index:$SOURCE" >&2
        exit 1
      fi
    fi
  fi
  echo "build_codex_skill --check: OK (working tree and staged copies match source)"
else
  mkdir -p "$(dirname "$TARGET")"
  rm -f "$TARGET"
  cp "$SOURCE" "$TARGET"
  echo "  built: $TARGET"
fi

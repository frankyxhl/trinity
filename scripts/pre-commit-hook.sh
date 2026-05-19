#!/usr/bin/env bash
# scripts/pre-commit-hook.sh
#
# Pre-commit hook: ensure committed generated artifacts match their sources.
# Installed via `make install-hooks`. Prevents the failure mode where someone
# hand-edits a generated file but forgets the corresponding source — next
# `make build` would silently revert it.
#
# Covered artifacts:
#   - providers/*.md  ← providers/_base/*.md + providers/*.delta.md (TRN-2004)
#   - plugins/trinity/skills/trinity/SKILL.md  ← .agents/skills/trinity/SKILL.md (TRN-3043)
#
# Bypass with `git commit --no-verify` only if you understand the risk.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if ! bash scripts/build_providers.sh --check; then
  echo "" >&2
  echo "pre-commit: provider drift detected. Either:" >&2
  echo "  - run 'make build' and stage the regenerated providers/*.md, or" >&2
  echo "  - revert your edit to providers/<name>.md and edit the matching" >&2
  echo "    providers/<name>.delta.md or providers/_base/*.md instead." >&2
  exit 1
fi

if ! bash scripts/build_codex_skill.sh --check; then
  echo "" >&2
  echo "pre-commit: codex skill drift detected. Either:" >&2
  echo "  - run 'make build' and stage the regenerated plugins/trinity/skills/trinity/SKILL.md, or" >&2
  echo "  - revert your edit to plugins/trinity/skills/trinity/SKILL.md and edit" >&2
  echo "    .agents/skills/trinity/SKILL.md (source of truth) instead." >&2
  exit 1
fi

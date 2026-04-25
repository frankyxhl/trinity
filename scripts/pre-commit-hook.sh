#!/usr/bin/env bash
# scripts/pre-commit-hook.sh
#
# Pre-commit hook: ensure committed providers/*.md matches partial sources.
# Installed via `make install-hooks`. Prevents the failure mode where someone
# hand-edits a generated providers/<name>.md but forgets the corresponding
# *.delta.md or _base/ partial — next `make build` would silently revert it.
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

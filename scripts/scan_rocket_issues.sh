#!/usr/bin/env bash
# scripts/scan_rocket_issues.sh
# GraphQL label-narrower for the TRN-1008 §1 rocket-gate Phase 1 scan.
# Returns OPEN issues with the blueprint-ready label currently present.
# NOT authoritative — verify_rocket_eligibility (REST per-issue) is the
# truth. This script just narrows the candidate set cheaply.
#
# Min bash: 3.2 (macOS default). POSIX-only constructs.
# Required tools: gh (GitHub CLI), jq.
#
# Usage:
#   ./scripts/scan_rocket_issues.sh
#   REPO=owner/repo ./scripts/scan_rocket_issues.sh
#
# Output: one issue number per line, or empty.
# Exit: 0 on success; non-zero on missing jq / gh api failure / auth error.
#
# Architecture: script returns SUPERSET of eligible issues (label-only
# filter). Per-candidate verify_rocket_eligibility (REST, paginated) does
# the full 5-check gate including reactor identity + applier identity +
# timeline events. Splitting these responsibilities avoids nested-
# connection truncation bugs (reactions, timeline, labels) that any
# GraphQL-only scanner would hit.
set -e

command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq is required. Install via brew/apt." >&2
  exit 2
}

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
OWNER="${REPO%/*}"
NAME="${REPO#*/}"

cursor=""
while :; do
  if [ -z "$cursor" ]; then
    after=""
  else
    after=", after: \"$cursor\""
  fi

  resp=$(gh api graphql -f query="
    {
      repository(owner: \"$OWNER\", name: \"$NAME\") {
        issues(states: OPEN, labels: [\"blueprint-ready\"], first: 100$after) {
          pageInfo { hasNextPage endCursor }
          nodes { number }
        }
      }
    }
  ") || exit 1

  echo "$resp" | jq -r '.data.repository.issues.nodes[].number'

  has_next=$(echo "$resp" | jq -r '.data.repository.issues.pageInfo.hasNextPage')
  [ "$has_next" != "true" ] && break
  cursor=$(echo "$resp" | jq -r '.data.repository.issues.pageInfo.endCursor')
done

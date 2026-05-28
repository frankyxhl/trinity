#!/usr/bin/env bash
set -euo pipefail
PR="${TRINITY_PR_UPDATE_PR:?}"; MODE="${TRINITY_PR_UPDATE_MODE:-amend}"; MSG="${TRINITY_PR_UPDATE_MESSAGE:?}"
DRY_RUN="${TRINITY_PR_UPDATE_DRY_RUN:-0}"; REVIEW="${TRINITY_PR_UPDATE_REVIEW:-}"
git diff --quiet || { echo "pr-update: dirty working tree" >&2; exit 1; }
[ -z "$(git ls-files --others --exclude-standard)" ] || { echo "pr-update: untracked files" >&2; exit 1; }
git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1 || { echo "pr-update: no upstream" >&2; exit 1; }
[ "$MODE" = "comment-only" ] || ! git diff --cached --quiet 2>/dev/null || { echo "pr-update: no staged changes to $MODE" >&2; exit 1; }
make test && make lint && af validate --root .
c=$(mktemp); trap 'rm -f "$c"' EXIT
{
  echo "$MSG"; echo; echo "Validation:"
  echo "- \`make test\`: PASS"; echo "- \`make lint\`: PASS"; echo "- \`af validate --root .\`: PASS"
  [ -n "$REVIEW" ] && { echo; echo "Review evidence:"; echo "$REVIEW"; }
  echo; echo "Update:"; echo "- mode: \`$MODE\`"
  case "$MODE" in
    amend) echo "- push: \`git push --force-with-lease origin HEAD\`" ;;
    commit) echo "- push: \`git push origin HEAD\`" ;;
    *) echo "- push: not requested" ;;
  esac
} > "$c"
[ "$DRY_RUN" = "1" ] && { cat "$c"; echo "DRY RUN — no changes pushed or commented"; exit 0; }
[ "$MODE" = "amend" ] && { git commit --amend --no-edit; git push --force-with-lease origin HEAD; }
[ "$MODE" = "commit" ] && { git commit -m "$MSG"; git push origin HEAD; }
gh pr comment "$PR" --body-file "$c"; echo "Updated PR #$PR"

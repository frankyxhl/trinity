#!/usr/bin/env bash
set -euo pipefail
PR="${TRINITY_PR_UPDATE_PR:?}"; MODE="${TRINITY_PR_UPDATE_MODE:-amend}"; MSG="${TRINITY_PR_UPDATE_MESSAGE:?}"
DRY_RUN="${TRINITY_PR_UPDATE_DRY_RUN:-0}"; REVIEW="${TRINITY_PR_UPDATE_REVIEW:-}"
case "$MODE" in amend|commit|comment-only) ;; *) echo "pr-update: unknown mode '$MODE'" >&2; exit 1 ;; esac
git diff --quiet || { echo "pr-update: dirty working tree" >&2; exit 1; }
[ -z "$(git ls-files --others --exclude-standard)" ] || { echo "pr-update: untracked files" >&2; exit 1; }
BRANCH=$(git symbolic-ref --quiet --short HEAD) || { echo "pr-update: detached HEAD" >&2; exit 1; }
REMOTE=$(git config "branch.$BRANCH.remote" || true); MERGE_REF=$(git config "branch.$BRANCH.merge" || true)
[ -n "$REMOTE" ] && [ -n "$MERGE_REF" ] || { echo "pr-update: no upstream" >&2; exit 1; }
UPSTREAM_BRANCH="${MERGE_REF#refs/heads/}"
[ "$MERGE_REF" != "$UPSTREAM_BRANCH" ] || { echo "pr-update: invalid upstream" >&2; exit 1; }
[ "$MODE" = "comment-only" ] || ! git diff --cached --quiet 2>/dev/null || { echo "pr-update: no staged changes to $MODE" >&2; exit 1; }
if [ "$DRY_RUN" = "1" ]; then V=DRY-RUN; else make test && make lint && af validate --root . || exit 1; V=PASS; fi
c=$(mktemp); trap 'rm -f "$c"' EXIT
{
  echo "$MSG"; echo; echo "Validation:"
  echo "- \`make test\`: $V"; echo "- \`make lint\`: $V"; echo "- \`af validate --root .\`: $V"
  [ -n "$REVIEW" ] && { echo; echo "Review evidence:"; echo "$REVIEW"; }
  echo; echo "Update:"; echo "- mode: \`$MODE\`"
  case "$MODE" in
    amend) echo "- commit: \`git commit --amend --no-edit\`"; echo "- push: \`git push --force-with-lease $REMOTE HEAD:$UPSTREAM_BRANCH\`" ;;
    commit) echo '- commit: `git commit -m "$TRINITY_PR_UPDATE_MESSAGE"`'; echo "- push: \`git push $REMOTE HEAD:$UPSTREAM_BRANCH\`" ;;
    comment-only) echo "- commit: not requested"; echo "- push: not requested" ;;
  esac; echo "- comment: \`gh pr comment $PR --body-file <generated-comment>\`"
} > "$c"
[ "$DRY_RUN" = "1" ] && { cat "$c"; echo "DRY RUN — no changes pushed or commented"; exit 0; }
[ "$MODE" = "amend" ] && { git commit --amend --no-edit; git push --force-with-lease "$REMOTE" "HEAD:$UPSTREAM_BRANCH"; }
[ "$MODE" = "commit" ] && { git commit -m "$MSG"; git push "$REMOTE" "HEAD:$UPSTREAM_BRANCH"; }
gh pr comment "$PR" --body-file "$c"; echo "Updated PR #$PR"

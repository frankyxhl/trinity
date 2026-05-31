#!/usr/bin/env bash
# tests/test_codeql_workflow.sh
#
# Tests for .github/workflows/codeql.yml per #153.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/codeql.yml"

PASS=0
FAIL=0
FAILS=()

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
    printf "  ok  %s\n" "$name"
  else
    FAIL=$((FAIL+1))
    FAILS+=("$name")
    printf "  FAIL %s\n" "$name"
  fi
}

echo "== #153: CodeQL workflow tests =="

check "CodeQL workflow exists" test -f "$WORKFLOW"
check "workflow name is CodeQL" grep -qE '^name: CodeQL$' "$WORKFLOW"
check "push trigger present" grep -qE '^  push:$' "$WORKFLOW"
check "push targets main" grep -qF 'branches: [main]' "$WORKFLOW"
check "pull_request trigger present" grep -qE '^  pull_request:$' "$WORKFLOW"
check "pull_request targets main" grep -qF 'branches: [main]' "$WORKFLOW"
check "weekly schedule present" grep -qE '^  schedule:$' "$WORKFLOW"
check "schedule uses weekly cron" grep -qF "cron: '17 4 * * 1'" "$WORKFLOW"
check "manual dispatch present" grep -qE '^  workflow_dispatch:$' "$WORKFLOW"

check "global contents read permission" grep -qE '^  contents: read$' "$WORKFLOW"
check "global security-events write permission" grep -qE '^  security-events: write$' "$WORKFLOW"

check "concurrency group set" grep -qF 'group: codeql-${{ github.event_name }}-${{ github.ref }}' "$WORKFLOW"
check "concurrency cancels stale runs" grep -qF 'cancel-in-progress: true' "$WORKFLOW"
check "analyze job present" grep -qE '^  analyze:$' "$WORKFLOW"
check "analyze runs on ubuntu latest" grep -qF 'runs-on: ubuntu-latest' "$WORKFLOW"
check "analyze has timeout" grep -qF 'timeout-minutes: 15' "$WORKFLOW"
check "strategy fail-fast false" grep -qF 'fail-fast: false' "$WORKFLOW"
check "python language configured" grep -qF 'language: python' "$WORKFLOW"
check "python build-mode none" grep -qF 'build-mode: none' "$WORKFLOW"

check "checkout uses pinned major" grep -qF 'uses: actions/checkout@v6' "$WORKFLOW"
check "CodeQL init uses pinned major" grep -qF 'uses: github/codeql-action/init@v4' "$WORKFLOW"
check "CodeQL analyze uses pinned major" grep -qF 'uses: github/codeql-action/analyze@v4' "$WORKFLOW"
check "CodeQL init receives language" grep -qF 'languages: ${{ matrix.language }}' "$WORKFLOW"
check "CodeQL init receives build mode" grep -qF 'build-mode: ${{ matrix.build-mode }}' "$WORKFLOW"
check "CodeQL analyze category set" grep -qF 'category: "/language:${{ matrix.language }}"' "$WORKFLOW"

echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  printf "\nFailures:\n"
  printf "  - %s\n" "${FAILS[@]}"
  exit 1
fi

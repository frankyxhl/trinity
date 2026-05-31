#!/usr/bin/env bash
# tests/test_dependency_audit_workflow.sh
#
# Tests for .github/workflows/dependency-audit.yml per #155.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/dependency-audit.yml"
PYPROJECT="pyproject.toml"
REQUIREMENTS="requirements-dev.txt"

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

echo "== #155: Dependency audit workflow tests =="

check "dependency audit workflow exists" test -f "$WORKFLOW"
check "workflow name is Dependency Audit" grep -qE '^name: Dependency Audit$' "$WORKFLOW"
check "push trigger present" grep -qE '^  push:$' "$WORKFLOW"
check "push targets main" grep -qF 'branches: [main]' "$WORKFLOW"
check "pull_request trigger present" grep -qE '^  pull_request:$' "$WORKFLOW"
check "weekly schedule present" grep -qE '^  schedule:$' "$WORKFLOW"
check "schedule uses weekly cron" grep -qF "cron: '23 5 * * 2'" "$WORKFLOW"
check "manual dispatch present" grep -qE '^  workflow_dispatch:$' "$WORKFLOW"
check "global contents read permission" grep -qE '^  contents: read$' "$WORKFLOW"
check "concurrency group set" grep -qF 'group: dependency-audit-${{ github.event_name }}-${{ github.ref }}' "$WORKFLOW"
check "concurrency cancels stale runs" grep -qF 'cancel-in-progress: true' "$WORKFLOW"
check "pip-audit job present" grep -qE '^  pip-audit:$' "$WORKFLOW"
check "pip-audit runs on ubuntu latest" grep -qF 'runs-on: ubuntu-latest' "$WORKFLOW"
check "pip-audit has timeout" grep -qF 'timeout-minutes: 10' "$WORKFLOW"
check "checkout uses pinned SHA with version comment" grep -qE 'uses: actions/checkout@[0-9a-f]{40} # v6' "$WORKFLOW"
check "setup-python uses pinned SHA with version comment" grep -qE 'uses: actions/setup-python@[0-9a-f]{40} # v6' "$WORKFLOW"
check "workflow uses Python 3.11" grep -qF "python-version: '3.11'" "$WORKFLOW"
check "setup-uv uses pinned SHA with version comment" grep -qE 'uses: astral-sh/setup-uv@[0-9a-f]{40} # v6' "$WORKFLOW"
check "workflow installs locked deps" grep -qF 'run: make setup' "$WORKFLOW"
check "workflow runs audit target" grep -qF 'run: make audit' "$WORKFLOW"
check "workflow does not ignore audit failures" bash -c "! grep -qE 'continue-on-error: true|\\|\\| true' '$WORKFLOW'"

check "Makefile declares audit phony target" grep -qE '^\.PHONY: .* audit( |$)' Makefile
check "Makefile audit target present" grep -qE '^audit: +## Check locked dev dependencies with pip-audit' Makefile
check "Makefile audit uses pip-audit" grep -qF '.venv/bin/pip-audit --disable-pip --require-hashes -r requirements-dev.txt' Makefile
check "Makefile audit does not ignore failures" bash -c "! awk '/^audit:/{f=1; next} /^[a-zA-Z0-9_-]+:/{f=0} f {print}' Makefile | grep -qE '^\\s*-|\\|\\| true'"

check "pyproject includes pip-audit" grep -qF '"pip-audit' "$PYPROJECT"
check "requirements fallback pins pip-audit" grep -qE '^pip-audit==' "$REQUIREMENTS"
check "requirements fallback keeps hashes" bash -c "awk '/^pip-audit==/{f=1; next} f && /^    --hash=sha256:/{found=1} f && /^[a-zA-Z0-9_.-]+==/{exit} END{exit !found}' '$REQUIREMENTS'"

echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  printf "\nFailures:\n"
  printf "  - %s\n" "${FAILS[@]}"
  exit 1
fi

#!/usr/bin/env bash
# tests/test_dependabot_config.sh
#
# Tests for .github/dependabot.yml per #152.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

CONFIG=".github/dependabot.yml"

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

echo "== #152: Dependabot config tests =="

check "dependabot config exists" test -f "$CONFIG"
check "dependabot config uses version 2" grep -qE '^version: 2$' "$CONFIG"
check "dependabot config has updates list" grep -qE '^updates:$' "$CONFIG"

check "uv ecosystem configured" grep -qF 'package-ecosystem: "uv"' "$CONFIG"
check "github-actions ecosystem configured" grep -qF 'package-ecosystem: "github-actions"' "$CONFIG"

check "uv uses root directory" bash -c '
  awk "/package-ecosystem: \"uv\"/{f=1; next} f && /package-ecosystem:/{exit} f && /directory: \"\\/\"/{found=1} END{exit !found}" .github/dependabot.yml
'
check "github-actions uses root directory" bash -c '
  awk "/package-ecosystem: \"github-actions\"/{f=1; next} f && /package-ecosystem:/{exit} f && /directory: \"\\/\"/{found=1} END{exit !found}" .github/dependabot.yml
'

check "uv schedule is weekly" bash -c '
  awk "/package-ecosystem: \"uv\"/{f=1; next} f && /package-ecosystem:/{exit} f && /interval: \"weekly\"/{found=1} END{exit !found}" .github/dependabot.yml
'
check "github-actions schedule is weekly" bash -c '
  awk "/package-ecosystem: \"github-actions\"/{f=1; next} f && /package-ecosystem:/{exit} f && /interval: \"weekly\"/{found=1} END{exit !found}" .github/dependabot.yml
'

echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  printf "\nFailures:\n"
  printf "  - %s\n" "${FAILS[@]}"
  exit 1
fi

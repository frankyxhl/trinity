#!/usr/bin/env bash
# tests/test_gitleaks_config.sh
#
# Tests for .github/workflows/gitleaks.yml and .gitleaks.toml per #154.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/gitleaks.yml"
CONFIG=".gitleaks.toml"
IGNORE=".gitleaksignore"

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

echo "== #154: Gitleaks secret scanning tests =="

check "Gitleaks workflow exists" test -f "$WORKFLOW"
check "workflow name is Secret Scan" grep -qE '^name: Secret Scan$' "$WORKFLOW"
check "push trigger present" grep -qE '^  push:$' "$WORKFLOW"
check "push targets main" grep -qF 'branches: [main]' "$WORKFLOW"
check "pull_request trigger present" grep -qE '^  pull_request:$' "$WORKFLOW"
check "manual dispatch present" grep -qE '^  workflow_dispatch:$' "$WORKFLOW"
check "global contents read permission" grep -qE '^  contents: read$' "$WORKFLOW"
check "concurrency group set" grep -qF 'group: secret-scan-${{ github.event_name }}-${{ github.ref }}' "$WORKFLOW"
check "concurrency cancels stale runs" grep -qF 'cancel-in-progress: true' "$WORKFLOW"
check "gitleaks job present" grep -qE '^  gitleaks:$' "$WORKFLOW"
check "gitleaks runs on ubuntu latest" grep -qF 'runs-on: ubuntu-latest' "$WORKFLOW"
check "gitleaks has timeout" grep -qF 'timeout-minutes: 10' "$WORKFLOW"
check "checkout uses pinned SHA with version comment" grep -qE 'uses: actions/checkout@[0-9a-f]{40} # v[0-9]+' "$WORKFLOW"
check "checkout fetches full history" grep -qF 'fetch-depth: 0' "$WORKFLOW"
check "no gitleaks-action reference" bash -c "! grep -qF 'gitleaks/gitleaks-action' '$WORKFLOW'"
check "gitleaks version pinned" grep -qF 'GITLEAKS_VERSION: 8.30.1' "$WORKFLOW"
check "x64 checksum present" grep -qF '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb' "$WORKFLOW"
check "arm64 checksum present" grep -qF 'e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080' "$WORKFLOW"
check "checksum verified" grep -qF 'sha256sum -c' "$WORKFLOW"
check "download URL from gitleaks releases" grep -qF 'https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${tarball}' "$WORKFLOW"
check "scan uses custom config" grep -qF -- '--config .gitleaks.toml' "$WORKFLOW"
check "scan fails on findings" grep -qF -- '--exit-code 1' "$WORKFLOW"

check ".gitleaksignore exists" test -f "$IGNORE"
check "ignore list has exactly 3 fingerprints" bash -c "test \"\$(grep -vcE '^[[:space:]]*(#|$)' '$IGNORE')\" -eq 3"

check "Gitleaks config exists" test -f "$CONFIG"
check "config extends default rules" grep -qF 'useDefault = true' "$CONFIG"
check "provider API-key rule exists" grep -qF 'id = "trinity-provider-api-key-assignment"' "$CONFIG"
check "bearer header rule exists" grep -qF 'id = "trinity-bearer-header"' "$CONFIG"
check "provider rule uses secretGroup" bash -c "grep -A5 'trinity-provider-api-key-assignment' '$CONFIG' | grep -qF 'secretGroup = 1'"
check "bearer rule uses secretGroup" bash -c "grep -A5 'trinity-bearer-header' '$CONFIG' | grep -qF 'secretGroup = 1'"

check "planted fake secrets match configured rules" python3 - <<'PY'
import re
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path(".gitleaks.toml").read_text())
rules = {rule["id"]: rule for rule in config["rules"]}

provider = re.compile(rules["trinity-provider-api-key-assignment"]["regex"])
bearer = re.compile(rules["trinity-bearer-header"]["regex"])

planted_provider = 'DEEPSEEK_API_KEY = "' + "sk-test-" + "0123456789abcdef012345" + '"'
planted_bearer = "Authorization: Bearer " + "trn_" + "0123456789abcdef0123456789"

safe_placeholders = [
    'export DEEPSEEK_API_KEY=sk-...',
    'DEEPSEEK_API_KEY = "from-env"',
    'Authorization: Bearer <token>',
]

if not provider.search(planted_provider):
    sys.exit("provider fake key was not matched")
if not bearer.search(planted_bearer):
    sys.exit("bearer fake token was not matched")
if any(provider.search(line) or bearer.search(line) for line in safe_placeholders):
    sys.exit("placeholder text should not match")
PY

echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  printf "\nFailures:\n"
  printf "  - %s\n" "${FAILS[@]}"
  exit 1
fi

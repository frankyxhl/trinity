#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

failures=0

pass() {
    printf 'PASS %s\n' "$1"
}

fail() {
    printf 'FAIL %s\n' "$1" >&2
    failures=$((failures + 1))
}

require_file_contains() {
    local file="$1"
    local pattern="$2"
    local label="$3"

    if grep -Eq "$pattern" "$file"; then
        pass "$label"
    else
        fail "$label"
    fi
}

require_file_absent() {
    local file="$1"
    local pattern="$2"
    local label="$3"

    if grep -Eq "$pattern" "$file"; then
        fail "$label"
    else
        pass "$label"
    fi
}

test -f scripts/provider_runtime.py && pass "provider_runtime module exists" || fail "provider_runtime module exists"
test -f scripts/provider_state.py && pass "provider_state module exists" || fail "provider_state module exists"
test -f scripts/review_schema.py && pass "review_schema module exists" || fail "review_schema module exists"

require_file_contains scripts/codex.py 'provider_runtime' "codex imports provider runtime module"
require_file_contains scripts/codex.py 'review_schema' "codex imports review schema module"
require_file_contains scripts/provider_runtime.py '^def run_provider\(' "provider runtime owns run_provider"
require_file_contains scripts/provider_runtime.py '^def run_providers\(' "provider runtime owns run_providers"
require_file_contains scripts/provider_runtime.py '^def build_provider_env\(' "provider runtime owns provider env sanitization"
require_file_contains scripts/review_schema.py '^def parse_structured_review\(' "review schema module owns structured parser"
require_file_contains scripts/provider_state.py '_review_metadata' "provider state adapter owns metadata dependency"
require_file_absent scripts/provider_runtime.py '_review_metadata' "provider runtime does not import review metadata directly"

if python3 - <<'PY'
from scripts import codex, provider_runtime, provider_state, review_schema

assert codex.run_provider is not None
assert provider_runtime.run_provider is not None
assert provider_state.append_result is not None
assert review_schema.parse_structured_review is not None
PY
then
    pass "split modules import through package entry points"
else
    fail "split modules import through package entry points"
fi

codex_lines=$(wc -l < scripts/codex.py | tr -d ' ')
if [[ "${codex_lines}" -lt 2500 ]]; then
    pass "codex.py remains below 2500 lines after split"
else
    fail "codex.py remains below 2500 lines after split"
fi

require_file_absent scripts/codex.py 'mcp_loopback|MCP loopback server' "withdrawn MCP loopback code stays out of codex.py"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

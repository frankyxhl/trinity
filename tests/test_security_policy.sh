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

if [[ -f SECURITY.md ]]; then
    pass "SECURITY.md exists at repo root"
else
    fail "SECURITY.md exists at repo root"
fi

require_file_contains SECURITY.md '^## Supported Versions$' "supported versions section present"
require_file_contains SECURITY.md 'Latest release' "latest release support documented"
require_file_contains SECURITY.md '^## Reporting a Vulnerability$' "reporting section present"
require_file_contains SECURITY.md 'private vulnerability reporting' "private GitHub reporting channel documented"
require_file_contains SECURITY.md 'franky\.xhl@gmail\.com' "fallback private email channel documented"
require_file_contains SECURITY.md '^## Response Expectations$' "response expectations section present"
require_file_contains SECURITY.md '3 business days' "acknowledgement target documented"
require_file_contains SECURITY.md '^## Security Scope$' "scope section present"
require_file_contains SECURITY.md 'Credential and token loading' "credential scope documented"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

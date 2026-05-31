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

if [[ -f .github/CODEOWNERS ]]; then
    pass "CODEOWNERS exists under .github"
else
    fail "CODEOWNERS exists under .github"
fi

require_file_contains .github/CODEOWNERS '^\* @frankyxhl$' "default owner present"
require_file_contains .github/CODEOWNERS '^/\.github/workflows/ @frankyxhl$' "workflow owner present"
require_file_contains .github/CODEOWNERS '^/scripts/ @frankyxhl$' "scripts owner present"
require_file_contains .github/CODEOWNERS '^/providers/ @frankyxhl$' "providers owner present"
require_file_contains .github/CODEOWNERS '^/rules/ @frankyxhl$' "rules owner present"
require_file_contains .github/CODEOWNERS '^/tests/ @frankyxhl$' "tests owner present"
require_file_contains .github/CODEOWNERS '^/install\.sh @frankyxhl$' "installer owner present"
require_file_contains .github/CODEOWNERS '^/Makefile @frankyxhl$' "Makefile owner present"
require_file_contains .github/CODEOWNERS '^/pyproject\.toml @frankyxhl$' "pyproject owner present"

if grep -Ev '^(#.*)?$|^[^[:space:]]+[[:space:]]+@frankyxhl$' .github/CODEOWNERS >/dev/null; then
    fail "CODEOWNERS entries use path plus @frankyxhl owner"
else
    pass "CODEOWNERS entries use path plus @frankyxhl owner"
fi

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

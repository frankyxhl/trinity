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

if [[ -f LICENSE ]]; then
    pass "LICENSE exists at repo root"
else
    fail "LICENSE exists at repo root"
fi

require_file_contains LICENSE '^MIT License$' "LICENSE uses MIT template heading"
require_file_contains LICENSE '^Copyright \(c\) 2026 Frank Xu$' "LICENSE has owner copyright"
require_file_contains LICENSE 'Permission is hereby granted, free of charge' "LICENSE has MIT grant text"
require_file_contains pyproject.toml '^license = "MIT"$' "pyproject declares MIT license"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

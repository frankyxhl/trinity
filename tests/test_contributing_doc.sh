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

if [[ -f CONTRIBUTING.md ]]; then
    pass "CONTRIBUTING.md exists at repo root"
else
    fail "CONTRIBUTING.md exists at repo root"
fi

require_file_contains README.md '\[CONTRIBUTING\.md\]\(CONTRIBUTING\.md\)' "README links to contributing guide"
require_file_contains CONTRIBUTING.md '^## Development Setup$' "setup section present"
require_file_contains CONTRIBUTING.md '`make setup`|make setup' "setup command documented"
require_file_contains CONTRIBUTING.md '`make test`|make test' "test command documented"
require_file_contains CONTRIBUTING.md '`make lint`|make lint' "lint command documented"
require_file_contains CONTRIBUTING.md '`make coverage`|make coverage' "coverage command documented"
require_file_contains CONTRIBUTING.md '`make audit`|make audit' "audit command documented"
require_file_contains CONTRIBUTING.md '^## Branch Naming$' "branch naming section present"
require_file_contains CONTRIBUTING.md 'codex/<issue-number>-short-description' "issue branch pattern documented"
require_file_contains CONTRIBUTING.md '^## Pull Requests$' "PR expectations section present"
require_file_contains CONTRIBUTING.md 'make pr-update PR=<number>' "PR update helper documented"
require_file_contains CONTRIBUTING.md '^## Release Flow$' "release flow section present"
require_file_contains CONTRIBUTING.md 'make release-prep' "release-prep documented"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

WORKFLOW=".github/workflows/test.yml"
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

if [[ -f "${WORKFLOW}" ]]; then
    pass "test workflow exists"
else
    fail "test workflow exists"
fi

require_file_contains "${WORKFLOW}" 'name: test / \$\{\{ matrix\.os \}\} / Python \$\{\{ matrix\.python-version \}\}' "matrix job name includes OS and Python version"
require_file_contains "${WORKFLOW}" 'os: \[ubuntu-latest, macos-latest\]' "OS matrix keeps ubuntu and macos"
require_file_contains "${WORKFLOW}" "python-version: \\['3\\.11', '3\\.12', '3\\.13'\\]" "Python matrix covers 3.11, 3.12, and 3.13"
require_file_contains "${WORKFLOW}" 'runs-on: \$\{\{ matrix\.os \}\}' "runner uses OS matrix"
require_file_contains "${WORKFLOW}" 'uses: actions/setup-python@[0-9a-f]{40} # v6' "setup-python action is pinned to SHA"
require_file_contains "${WORKFLOW}" 'python-version: \$\{\{ matrix\.python-version \}\}' "setup-python uses Python matrix"
require_file_contains "${WORKFLOW}" '^  ubuntu-latest:$' "legacy ubuntu required-check gate present"
require_file_contains "${WORKFLOW}" '^    name: ubuntu-latest$' "legacy ubuntu required-check name preserved"
require_file_contains "${WORKFLOW}" '^  macos-latest:$' "legacy macos required-check gate present"
require_file_contains "${WORKFLOW}" '^    name: macos-latest$' "legacy macos required-check name preserved"
require_file_contains "${WORKFLOW}" 'needs: test' "required-check gates depend on matrix job"
require_file_contains "${WORKFLOW}" '\$\{\{ needs\.test\.result \}\}' "required-check gates inspect matrix result"

setup_line=$(grep -nE 'uses: actions/setup-python@[0-9a-f]{40} # v6' "${WORKFLOW}" | head -1 | cut -d: -f1)
install_line=$(grep -nF 'run: make setup' "${WORKFLOW}" | head -1 | cut -d: -f1)
lint_line=$(grep -nF 'run: make lint' "${WORKFLOW}" | head -1 | cut -d: -f1)
test_line=$(grep -nF 'run: make test' "${WORKFLOW}" | head -1 | cut -d: -f1)
coverage_line=$(grep -nF 'run: make coverage' "${WORKFLOW}" | head -1 | cut -d: -f1)

if [[ "${setup_line}" -lt "${install_line}" && "${install_line}" -lt "${lint_line}" && "${lint_line}" -lt "${test_line}" && "${test_line}" -lt "${coverage_line}" ]]; then
    pass "matrix leg order remains setup, install, lint, test, coverage"
else
    fail "matrix leg order remains setup, install, lint, test, coverage"
fi

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

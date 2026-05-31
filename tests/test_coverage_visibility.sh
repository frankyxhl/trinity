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

require_file_contains Makefile 'coverage xml -o coverage\.xml' "coverage target emits XML report"
require_file_contains Makefile 'coverage html -d htmlcov' "coverage target emits HTML report"
require_file_contains Makefile 'coverage report --include='\''scripts/\*'\'' --fail-under=80' "coverage target preserves fail-under gate"

xml_line=$(grep -nF 'coverage xml -o coverage.xml' Makefile | head -1 | cut -d: -f1)
html_line=$(grep -nF 'coverage html -d htmlcov' Makefile | head -1 | cut -d: -f1)
report_line=$(grep -nF "coverage report --include='scripts/*' --fail-under=80" Makefile | head -1 | cut -d: -f1)

if [[ "${xml_line}" -lt "${report_line}" && "${html_line}" -lt "${report_line}" ]]; then
    pass "coverage artifacts are generated before fail-under report"
else
    fail "coverage artifacts are generated before fail-under report"
fi

require_file_contains "${WORKFLOW}" 'name: Upload coverage report' "test workflow uploads coverage report"
require_file_contains "${WORKFLOW}" 'if: always\(\) && steps\.changes\.outputs\.run_tests == '\''true'\''' "coverage upload runs even after coverage failure"
require_file_contains "${WORKFLOW}" 'uses: actions/upload-artifact@v7' "coverage upload uses pinned artifact action"
require_file_contains "${WORKFLOW}" 'name: coverage-\$\{\{ matrix\.os \}\}-py\$\{\{ matrix\.python-version \}\}' "coverage artifact name is unique per matrix leg"
require_file_contains "${WORKFLOW}" 'coverage\.xml' "coverage upload includes XML report"
require_file_contains "${WORKFLOW}" 'htmlcov/' "coverage upload includes HTML report"
require_file_contains "${WORKFLOW}" 'if-no-files-found: warn' "coverage upload does not hide coverage command failures"
require_file_contains "${WORKFLOW}" 'retention-days: 14' "coverage artifact retention is bounded"

coverage_line=$(grep -nF 'run: make coverage' "${WORKFLOW}" | head -1 | cut -d: -f1)
upload_line=$(grep -nF 'name: Upload coverage report' "${WORKFLOW}" | head -1 | cut -d: -f1)

if [[ "${coverage_line}" -lt "${upload_line}" ]]; then
    pass "coverage upload runs after coverage command"
else
    fail "coverage upload runs after coverage command"
fi

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

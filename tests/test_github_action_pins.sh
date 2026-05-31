#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

failures=0
action_count=0

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

for workflow in .github/workflows/*.yml; do
    line_no=0
    while IFS= read -r line; do
        line_no=$((line_no + 1))
        if [[ "${line}" =~ ^[[:space:]]*(-[[:space:]]*)?uses:[[:space:]]+([^[:space:]#]+)@([^[:space:]#]+)([[:space:]]+#.*)?$ ]]; then
            action_count=$((action_count + 1))
            action="${BASH_REMATCH[2]}"
            ref="${BASH_REMATCH[3]}"
            comment="${BASH_REMATCH[4]:-}"

            if [[ "${ref}" =~ ^[0-9a-f]{40}$ ]]; then
                pass "${workflow}:${line_no} ${action} uses a full commit SHA"
            else
                fail "${workflow}:${line_no} ${action} uses mutable ref ${ref}"
            fi

            if [[ "${comment}" =~ ^[[:space:]]+#[[:space:]]+v[0-9]+([.][0-9]+)*$ ]]; then
                pass "${workflow}:${line_no} ${action} records version comment"
            else
                fail "${workflow}:${line_no} ${action} missing trailing version comment"
            fi
        fi
    done < "${workflow}"
done

if [[ "${action_count}" -gt 0 ]]; then
    pass "workflow action references were checked"
else
    fail "workflow action references were checked"
fi

require_file_contains .github/dependabot.yml 'package-ecosystem: "github-actions"' "Dependabot keeps GitHub Actions updated"
require_file_contains .github/dependabot.yml 'directory: "/"' "Dependabot scans repository workflows"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

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
test -f scripts/_doctor.py && pass "_doctor module exists" || fail "_doctor module exists"
test -f scripts/_review.py && pass "_review module exists" || fail "_review module exists"
test -f scripts/_status.py && pass "_status module exists" || fail "_status module exists"

require_file_contains scripts/codex.py 'provider_runtime' "codex imports provider runtime module"
require_file_contains scripts/codex.py 'review_schema' "codex imports review schema module"
require_file_contains scripts/codex.py '_doctor' "codex imports _doctor module"
require_file_contains scripts/codex.py '_review' "codex imports _review module"
require_file_contains scripts/codex.py '_status' "codex imports _status module"
require_file_contains scripts/provider_runtime.py '^def run_provider\(' "provider runtime owns run_provider"
require_file_contains scripts/provider_runtime.py '^def run_providers\(' "provider runtime owns run_providers"
require_file_contains scripts/provider_runtime.py '^def build_provider_env\(' "provider runtime owns provider env sanitization"
require_file_contains scripts/review_schema.py '^def parse_structured_review\(' "review schema module owns structured parser"
require_file_contains scripts/provider_state.py '_review_metadata' "provider state adapter owns metadata dependency"
require_file_absent scripts/provider_runtime.py '_review_metadata' "provider runtime does not import review metadata directly"

# Issue #206: subcommand bodies must live in the new modules, not codex.py
require_file_contains scripts/_doctor.py '^def cmd_doctor\(' "_doctor module owns cmd_doctor body"
require_file_contains scripts/_doctor.py '^def provider_health\(' "_doctor module owns provider_health body"
require_file_contains scripts/_doctor.py '^def detect_env_pollution\(' "_doctor module owns detect_env_pollution body"
require_file_contains scripts/_review.py '^def cmd_review\(' "_review module owns cmd_review body"
require_file_contains scripts/_review.py '^def write_synthesis\(' "_review module owns write_synthesis body"
require_file_contains scripts/_review.py '^def render_prompt\(' "_review module owns render_prompt body"
require_file_contains scripts/_status.py '^def cmd_status\(' "_status module owns cmd_status body"
require_file_contains scripts/_status.py '^def _print_review_summary\(' "_status module owns _print_review_summary body"

# codex.py must not contain the function bodies (only routing / re-exports)
require_file_absent scripts/codex.py '^def cmd_doctor\(' "cmd_doctor body absent from codex.py"
require_file_absent scripts/codex.py '^def cmd_review\(' "cmd_review body absent from codex.py"
require_file_absent scripts/codex.py '^def cmd_status\(' "cmd_status body absent from codex.py"
require_file_absent scripts/codex.py '^def write_synthesis\(' "write_synthesis body absent from codex.py"
require_file_absent scripts/codex.py '^def render_prompt\(' "render_prompt body absent from codex.py"

if python3 - <<'PY'
from scripts import codex, provider_runtime, provider_state, review_schema
import scripts._doctor as _doctor
import scripts._review as _review
import scripts._status as _status

assert codex.run_provider is not None
assert provider_runtime.run_provider is not None
assert provider_state.append_result is not None
assert review_schema.parse_structured_review is not None

# Issue #206: re-exported names accessible via codex module
assert codex.cmd_review is not None
assert codex.cmd_doctor is not None
assert codex.cmd_status is not None
assert codex.write_synthesis is not None
assert codex.provider_health is not None
assert codex.detect_env_pollution is not None
assert codex._probe_provider is not None
assert codex._LIVE_PROBE_TIMEOUT is not None
PY
then
    pass "split modules import through package entry points"
else
    fail "split modules import through package entry points"
fi

codex_lines=$(wc -l < scripts/codex.py | tr -d ' ')
if [[ "${codex_lines}" -lt 700 ]]; then
    pass "codex.py reduced below 700 lines after split"
else
    fail "codex.py reduced below 700 lines after split"
fi

require_file_absent scripts/codex.py 'mcp_loopback|MCP loopback server' "withdrawn MCP loopback code stays out of codex.py"

if [[ "${failures}" -ne 0 ]]; then
    exit 1
fi

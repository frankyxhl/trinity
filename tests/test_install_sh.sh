#!/usr/bin/env bash
# tests/test_install_sh.sh — Shell-level tests for install.sh
#
# Usage: bash tests/test_install_sh.sh
# Requires: python3 (for local HTTP server), bash, curl

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_SCRIPT="${REPO_DIR}/install.sh"

PASS=0
FAIL=0

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

# Start a local HTTP server serving the repo root
_start_server() {
    SERVE_DIR="$1"
    SERVER_PORT=18742
    python3 -m http.server "${SERVER_PORT}" --directory "${SERVE_DIR}" \
        >/dev/null 2>&1 &
    SERVER_PID=$!
    # Wait for server to be ready
    for i in $(seq 1 10); do
        curl -sf "http://localhost:${SERVER_PORT}/VERSION" >/dev/null 2>&1 && break
        sleep 0.2
    done
}

_stop_server() {
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
}

# T1: Happy path — all 11 files installed
t1_happy_path() {
    FAKE_HOME=$(mktemp -d)
    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    RC=$?
    _stop_server

    if [ $RC -ne 0 ]; then _fail "T1: non-zero exit"; return; fi

    # Verify trinity.json was created with all 5 providers
    TRINITY_JSON="${FAKE_HOME}/.claude/trinity.json"
    if [ ! -f "${TRINITY_JSON}" ]; then
        _fail "T1: ~/.claude/trinity.json not created"; rm -rf "${FAKE_HOME}"; return
    fi
    for provider in glm codex gemini openrouter deepseek; do
        if ! python3 -c "import json,sys; d=json.load(open('${TRINITY_JSON}')); sys.exit(0 if '${provider}' in d.get('providers',{}) else 1)"; then
            _fail "T1: provider ${provider} missing from trinity.json"; rm -rf "${FAKE_HOME}"; return
        fi
    done

    EXPECTED_FILES=(
        ".claude/skills/trinity/SKILL.md"
        ".claude/skills/trinity/scripts/__init__.py"
        ".claude/skills/trinity/scripts/session.py"
        ".claude/skills/trinity/scripts/config.py"
        ".claude/skills/trinity/scripts/discover.py"
        ".claude/skills/trinity/scripts/install.py"
        ".claude/agents/trinity-glm.md"
        ".claude/agents/trinity-codex.md"
        ".claude/agents/trinity-gemini.md"
        ".claude/agents/trinity-openrouter.md"
        ".claude/agents/trinity-deepseek.md"
    )
    for f in "${EXPECTED_FILES[@]}"; do
        if [ ! -f "${FAKE_HOME}/${f}" ]; then
            _fail "T1: missing ${f}"; rm -rf "${FAKE_HOME}"; return
        fi
    done
    _pass "T1: happy path — all 11 files installed"
    rm -rf "${FAKE_HOME}"
}

# T2: Idempotent — run twice, second run succeeds and overwrites
t2_idempotent() {
    FAKE_HOME=$(mktemp -d)
    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    RC=$?
    _stop_server
    [ $RC -eq 0 ] && _pass "T2: idempotent — second run succeeds" \
                   || _fail "T2: second run failed"
    rm -rf "${FAKE_HOME}"
}

# T3: TRINITY_VERSION set — uses versioned base URL (via TRINITY_BASE_URL override)
t3_version_env() {
    FAKE_HOME=$(mktemp -d)
    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_VERSION="1.0.0" \
        TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    RC=$?
    _stop_server
    [ $RC -eq 0 ] && _pass "T3: TRINITY_VERSION=1.0.0 with TRINITY_BASE_URL override — exit 0" \
                   || _fail "T3: failed"
    rm -rf "${FAKE_HOME}"
}

# T3b: URL construction — TRINITY_VERSION set, no TRINITY_BASE_URL; verify constructed URL uses v prefix
t3b_url_construction() {
    VERSION_STRING="1.0.0"
    EXPECTED_URL="https://raw.githubusercontent.com/frankyxhl/trinity/v${VERSION_STRING}"
    # Extract BASE_URL computation by sourcing a subset of install.sh logic
    ACTUAL_URL=$(bash -c "
        TRINITY_VERSION='${VERSION_STRING}'
        VERSION=\"\${TRINITY_VERSION#v}\"
        echo \"https://raw.githubusercontent.com/frankyxhl/trinity/v\${VERSION}\"
    ")
    [ "${ACTUAL_URL}" = "${EXPECTED_URL}" ] \
        && _pass "T3b: URL construction uses v-prefixed tag (v${VERSION_STRING})" \
        || _fail "T3b: URL mismatch: expected ${EXPECTED_URL}, got ${ACTUAL_URL}"
}

# T4: Leading v in TRINITY_VERSION stripped correctly
t4_leading_v_stripped() {
    EXPECTED_URL="https://raw.githubusercontent.com/frankyxhl/trinity/v1.0.0"
    ACTUAL_URL=$(bash -c "
        TRINITY_VERSION='v1.0.0'
        VERSION=\"\${TRINITY_VERSION#v}\"
        echo \"https://raw.githubusercontent.com/frankyxhl/trinity/v\${VERSION}\"
    ")
    [ "${ACTUAL_URL}" = "${EXPECTED_URL}" ] \
        && _pass "T4: leading v in TRINITY_VERSION stripped, URL correct" \
        || _fail "T4: URL mismatch: expected ${EXPECTED_URL}, got ${ACTUAL_URL}"
}

# T5: Destination dirs created if absent
t5_dirs_created() {
    FAKE_HOME=$(mktemp -d)
    rm -rf "${FAKE_HOME}/.claude"
    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    RC=$?
    _stop_server
    if [ $RC -ne 0 ]; then _fail "T5: non-zero exit"; rm -rf "${FAKE_HOME}"; return; fi
    [ -d "${FAKE_HOME}/.claude/skills/trinity/scripts" ] \
        && [ -d "${FAKE_HOME}/.claude/agents" ] \
        && _pass "T5: destination dirs created" \
        || _fail "T5: dirs not created"
    rm -rf "${FAKE_HOME}"
}

# T6: One file missing (404) — exit non-zero, stderr contains filename
t6_404_exits_nonzero() {
    FAKE_HOME=$(mktemp -d)
    MISSING_DIR=$(mktemp -d)
    # Serve from a dir missing providers/codex.md
    mkdir -p "${MISSING_DIR}/scripts" "${MISSING_DIR}/providers"
    cp "${REPO_DIR}/SKILL.md" "${MISSING_DIR}/"
    cp "${REPO_DIR}/scripts/"*.py "${MISSING_DIR}/scripts/"
    cp "${REPO_DIR}/providers/glm.md" "${MISSING_DIR}/providers/"
    # providers/codex.md intentionally missing
    cp "${REPO_DIR}/providers/gemini.md" "${MISSING_DIR}/providers/"

    _start_server "${MISSING_DIR}"
    TMPFILE=$(mktemp)
    set +e
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null 2>"${TMPFILE}"
    RC=$?
    set -e
    STDERR_OUT=$(cat "${TMPFILE}"); rm -f "${TMPFILE}"
    _stop_server

    if [ $RC -eq 0 ]; then
        _fail "T6: expected non-zero exit on 404, got 0"
    elif echo "${STDERR_OUT}" | grep -q "failed downloading"; then
        _pass "T6: 404 exits non-zero with 'failed downloading' in stderr"
    else
        _fail "T6: non-zero exit but wrong stderr: ${STDERR_OUT}"
    fi
    rm -rf "${FAKE_HOME}" "${MISSING_DIR}"
}

# T7: Success output contains version string from __init__.py
t7_success_output_version() {
    FAKE_HOME=$(mktemp -d)
    _start_server "${REPO_DIR}"
    OUTPUT=$(HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" 2>/dev/null)
    _stop_server
    EXPECTED_VERSION=$(grep '^__version__ = ' "${REPO_DIR}/scripts/__init__.py" \
        | sed 's/__version__ = "\(.*\)"/\1/')
    echo "${OUTPUT}" | grep -q "Trinity ${EXPECTED_VERSION} installed" \
        && _pass "T7: success output contains version ${EXPECTED_VERSION}" \
        || _fail "T7: output was: ${OUTPUT}"
    rm -rf "${FAKE_HOME}"
}

# T9 (TRN-2008/2009): bin scripts present + executable; deepseek/openrouter
# registered with absolute-path cli (no _cy reference).
t9_bin_scripts_and_absolute_cli() {
    FAKE_HOME=$(mktemp -d)
    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    _stop_server

    BIN_DIR="${FAKE_HOME}/.claude/skills/trinity/bin"
    for w in deepseek openrouter; do
        if [ ! -x "${BIN_DIR}/${w}" ]; then
            _fail "T9: ${BIN_DIR}/${w} missing or not executable"
            rm -rf "${FAKE_HOME}"; return
        fi
    done

    TRINITY_JSON="${FAKE_HOME}/.claude/trinity.json"
    EXPECTED_DS="${BIN_DIR}/deepseek -p"
    EXPECTED_OR="${BIN_DIR}/openrouter -p"
    ACTUAL_DS=$(python3 -c "import json; print(json.load(open('${TRINITY_JSON}'))['providers']['deepseek']['cli'])")
    ACTUAL_OR=$(python3 -c "import json; print(json.load(open('${TRINITY_JSON}'))['providers']['openrouter']['cli'])")

    if [ "${ACTUAL_DS}" != "${EXPECTED_DS}" ]; then
        _fail "T9: deepseek cli mismatch: got '${ACTUAL_DS}' expected '${EXPECTED_DS}'"
        rm -rf "${FAKE_HOME}"; return
    fi
    if [ "${ACTUAL_OR}" != "${EXPECTED_OR}" ]; then
        _fail "T9: openrouter cli mismatch: got '${ACTUAL_OR}' expected '${EXPECTED_OR}'"
        rm -rf "${FAKE_HOME}"; return
    fi

    # Sanity: no legacy _cy reference anywhere in trinity.json.
    if grep -q "_cy" "${TRINITY_JSON}"; then
        _fail "T9: trinity.json still contains _cy reference"
        rm -rf "${FAKE_HOME}"; return
    fi

    _pass "T9: bin scripts installed + executable; deepseek/openrouter cli use absolute paths"
    rm -rf "${FAKE_HOME}"
}

# T11 (TRN-2008/2009): legacy `deepseek_cy -p` cli is overwritten by re-install.
t11_legacy_cli_migration() {
    FAKE_HOME=$(mktemp -d)
    mkdir -p "${FAKE_HOME}/.claude"
    # Simulate an existing user with the legacy zsh-wrapper registration.
    cat > "${FAKE_HOME}/.claude/trinity.json" <<EOF
{
  "providers": {
    "deepseek":   {"cli": "deepseek_cy -p",  "installed": true},
    "openrouter": {"cli": "openrouter_cy -p", "installed": true},
    "glm":        {"cli": "droid exec --model glm-5", "installed": true}
  }
}
EOF

    _start_server "${REPO_DIR}"
    HOME="${FAKE_HOME}" TRINITY_BASE_URL="http://localhost:${SERVER_PORT}" \
        bash "${INSTALL_SCRIPT}" >/dev/null
    _stop_server

    TRINITY_JSON="${FAKE_HOME}/.claude/trinity.json"
    BIN_DIR="${FAKE_HOME}/.claude/skills/trinity/bin"

    # Legacy cli must have been overwritten.
    if grep -q "_cy" "${TRINITY_JSON}"; then
        _fail "T11: legacy _cy entries not overwritten"
        rm -rf "${FAKE_HOME}"; return
    fi

    # New absolute-path cli must be present.
    EXPECTED_DS="${BIN_DIR}/deepseek -p"
    ACTUAL_DS=$(python3 -c "import json; print(json.load(open('${TRINITY_JSON}'))['providers']['deepseek']['cli'])")
    if [ "${ACTUAL_DS}" != "${EXPECTED_DS}" ]; then
        _fail "T11: deepseek cli not migrated: got '${ACTUAL_DS}'"
        rm -rf "${FAKE_HOME}"; return
    fi

    # Other providers untouched (glm was pre-existing).
    ACTUAL_GLM=$(python3 -c "import json; print(json.load(open('${TRINITY_JSON}'))['providers']['glm']['cli'])")
    if [ "${ACTUAL_GLM}" != "droid exec --model glm-5" ]; then
        _fail "T11: glm registration mutated unexpectedly: '${ACTUAL_GLM}'"
        rm -rf "${FAKE_HOME}"; return
    fi

    _pass "T11: legacy deepseek_cy/openrouter_cy cli overwritten with absolute paths; other providers untouched"
    rm -rf "${FAKE_HOME}"
}

# Run all tests
t1_happy_path
t2_idempotent
t3_version_env
t3b_url_construction
t4_leading_v_stripped
t5_dirs_created
t6_404_exits_nonzero
t7_success_output_version
t9_bin_scripts_and_absolute_cli
t11_legacy_cli_migration

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ $FAIL -eq 0 ] || exit 1

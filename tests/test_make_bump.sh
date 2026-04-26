#!/usr/bin/env bash
# tests/test_make_bump.sh — Regression test for cross-platform `make bump` (TRN-1801 cycle 1, evolve C1)
#
# The `bump` target rewrites __version__ in scripts/__init__.py and REQUIRED_VERSION
# in SKILL.md. Prior to this test, the target used `sed -i ''` which is BSD-only —
# on Linux, `''` is interpreted as the input file and the command fails. The fix is
# `perl -i -pe`, which is portable across macOS (BSD) and Linux (GNU).
#
# This test guards against silent regression to the BSD-only form, and verifies the
# substitution semantics on a fixture file.
#
# Usage: bash tests/test_make_bump.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

# T1: portable in-place rewrite of __version__ and REQUIRED_VERSION succeeds and
# preserves unrelated lines, on whichever OS the test runs.
t1_portable_in_place_rewrite() {
    TMP=$(mktemp -d)
    cat > "${TMP}/init.py" <<'EOF'
__version__ = "0.0.0"
keep_me = True
EOF
    cat > "${TMP}/skill.md" <<'EOF'
prefix
REQUIRED_VERSION="0.0.0"
suffix
EOF

    perl -i -pe 's/__version__ = ".*"/__version__ = "9.9.9"/' "${TMP}/init.py"
    perl -i -pe 's/REQUIRED_VERSION=".*"/REQUIRED_VERSION="9.9.9"/' "${TMP}/skill.md"

    grep -qx '__version__ = "9.9.9"' "${TMP}/init.py" \
        || { _fail "T1: __version__ not rewritten"; rm -rf "${TMP}"; return; }
    grep -qx 'keep_me = True' "${TMP}/init.py" \
        || { _fail "T1: unrelated line in init.py lost"; rm -rf "${TMP}"; return; }
    grep -qx 'REQUIRED_VERSION="9.9.9"' "${TMP}/skill.md" \
        || { _fail "T1: REQUIRED_VERSION not rewritten"; rm -rf "${TMP}"; return; }
    grep -qx 'prefix' "${TMP}/skill.md" && grep -qx 'suffix' "${TMP}/skill.md" \
        || { _fail "T1: surrounding lines in skill.md lost"; rm -rf "${TMP}"; return; }

    _pass "T1: perl -i -pe rewrites both pins and preserves unrelated lines"
    rm -rf "${TMP}"
}

# T2: static guard against silent revert to the BSD-only `sed -i ''` form.
# If a future change reintroduces `sed -i ''` in the bump target, this fails.
t2_makefile_uses_portable_form() {
    if grep -nE "^\s*@?sed -i ''" "${REPO_DIR}/Makefile" >/dev/null 2>&1; then
        _fail "T2: Makefile contains BSD-only \`sed -i ''\` — Linux \`make bump\` will break"
        return
    fi
    if ! grep -qE '^\s*@?perl -i -pe' "${REPO_DIR}/Makefile"; then
        _fail "T2: Makefile bump target no longer uses \`perl -i -pe\` — verify portable rewrite"
        return
    fi
    _pass "T2: Makefile uses portable \`perl -i -pe\` (no BSD-only \`sed -i ''\`)"
}

t1_portable_in_place_rewrite
t2_makefile_uses_portable_form

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ ${FAIL} -eq 0 ]

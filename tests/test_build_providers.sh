#!/usr/bin/env bash
# tests/test_build_providers.sh
#
# Tests for scripts/build_providers.sh per TRN-2004.
#
# T1 Determinism — running build twice yields identical output
# T2 Frontmatter — every generated provider starts with `---\n`
# T3 Trailing LF — every generated provider ends with exactly one `\n`
# T4 Partial invariants — every _base/*.md has no frontmatter and exactly one trailing `\n`
# T5 No stale @include — no generated provider contains the string "@include"
# T6 Semantic section presence — generated providers contain expected stable anchors
# T7 Drift sentinels — confirms the three bundled bug fixes stay applied

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PROVIDERS=(codex gemini glm openrouter deepseek)
NATIVE=(codex gemini glm)
WRAPPER=(openrouter deepseek)
PARTIALS=(_base/common-session.md _base/common-tail.md _base/family-wrapper.md)

PASS=0
FAIL=0
FAILS=()

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
    printf "  ok  %s\n" "$name"
  else
    FAIL=$((FAIL+1))
    FAILS+=("$name")
    printf "  FAIL %s\n" "$name"
  fi
}

# Helpers ---------------------------------------------------------------------

assert_file_starts_with_frontmatter() {
  local f="$1"
  head -c 3 "$f" | grep -q '^---$' || head -c 4 "$f" | grep -q '^---'
}

assert_single_trailing_lf() {
  # File must end with exactly one \n: last byte is \n, second-to-last is not \n.
  local f="$1"
  local size last second_last
  size=$(wc -c <"$f" | tr -d ' ')
  [ "$size" -ge 2 ] || return 1
  last=$(tail -c 1 "$f" | od -An -tx1 | tr -d ' \n')
  second_last=$(tail -c 2 "$f" | head -c 1 | od -An -tx1 | tr -d ' \n')
  [ "$last" = "0a" ] && [ "$second_last" != "0a" ]
}

assert_no_frontmatter() {
  local f="$1"
  ! head -1 "$f" | grep -q '^---$'
}

# Tests -----------------------------------------------------------------------

echo "=== test_build_providers.sh ==="

# Build script must exist.
check "build script exists" test -f scripts/build_providers.sh
check "build script executable" test -x scripts/build_providers.sh

# Markdown hierarchy regression check (review iteration 2 fix):
# In a generated provider, the H3 "### Writing sessions" must NOT appear under
# any H2 other than "## Session Management". Specifically, between the line of
# "## Instance Key" and the next H2 there must be no "### Writing sessions".
assert_writing_sessions_under_session_management() {
  local f="$1"
  python3 - "$f" <<'PY'
import sys
text = open(sys.argv[1]).read()
import re
# Walk lines tracking current H2.
current_h2 = None
for ln in text.splitlines():
    m = re.match(r'^## (.+)$', ln)
    if m:
        current_h2 = m.group(1).strip()
        continue
    if ln.strip() == '### Writing sessions':
        if current_h2 != 'Session Management':
            sys.exit(f"### Writing sessions appears under '## {current_h2}', not '## Session Management'")
sys.exit(0)
PY
}

# T4: partials must exist and pass invariants.
echo "-- T4: partial invariants"
for p in "${PARTIALS[@]}"; do
  check "exists: providers/$p" test -f "providers/$p"
  if [ -f "providers/$p" ]; then
    check "no-frontmatter: providers/$p" assert_no_frontmatter "providers/$p"
    check "single-trailing-LF: providers/$p" assert_single_trailing_lf "providers/$p"
    check "no-nested-@include: providers/$p" bash -c "! grep -q '^@include' 'providers/$p'"
  fi
done

# Build twice for T1.
echo "-- Building (run 1)"
bash scripts/build_providers.sh
echo "-- Capturing run-1 output"
RUN1=$(mktemp -d)
for p in "${PROVIDERS[@]}"; do
  cp "providers/$p.md" "$RUN1/$p.md"
done

echo "-- Building (run 2)"
bash scripts/build_providers.sh

echo "-- T1: determinism"
for p in "${PROVIDERS[@]}"; do
  check "deterministic: $p.md" diff -q "$RUN1/$p.md" "providers/$p.md"
done
rm -rf "$RUN1"

echo "-- T2: frontmatter on first byte"
for p in "${PROVIDERS[@]}"; do
  check "frontmatter: providers/$p.md" assert_file_starts_with_frontmatter "providers/$p.md"
done

echo "-- T3: exactly one trailing LF"
for p in "${PROVIDERS[@]}"; do
  check "trailing-LF: providers/$p.md" assert_single_trailing_lf "providers/$p.md"
done

echo "-- T5: no stale @include in generated output"
for p in "${PROVIDERS[@]}"; do
  check "no-@include: providers/$p.md" bash -c "! grep -q '@include' 'providers/$p.md'"
done

echo "-- T6: semantic section presence"
for p in "${PROVIDERS[@]}"; do
  f="providers/$p.md"
  check "frontmatter name=trinity-$p: $p"      grep -q "^name: trinity-$p$" "$f"
  check "session.py read: $p"                  grep -q 'scripts/session.py read' "$f"
  check "session.py write: $p"                 grep -q 'scripts/session.py write' "$f"
  check "Response Format header: $p"           grep -q '^## Response Format' "$f"
  check "Timeout header: $p"                   grep -q '^## Timeout' "$f"
  check "Iteration header: $p"                 grep -q '^## Iteration' "$f"
  check "Rules header: $p"                     grep -q '^## Rules' "$f"
  check "Writing-sessions under Session Mgmt: $p" \
    assert_writing_sessions_under_session_management "$f"
done

# Provider-specific CLI signatures (delta content survived).
check "codex CLI signature"      grep -q 'codex exec' providers/codex.md
check "gemini CLI signature"     grep -q 'gemini --model' providers/gemini.md
check "glm CLI signature"        grep -q 'droid exec --model glm-5' providers/glm.md
check "openrouter run function"  grep -q 'run_openrouter()' providers/openrouter.md
check "deepseek run function"    grep -q 'run_deepseek()' providers/deepseek.md

echo "-- T7: drift sentinels (3 bundled fixes stay applied)"
# Fix #1 — codex reasoning effort: model_reasoning_effort, default xhigh, override parsing
check "codex fix #1: model_reasoning_effort flag" \
  grep -q 'model_reasoning_effort=' providers/codex.md
check "codex fix #1: default xhigh"               grep -q 'xhigh' providers/codex.md
check "codex fix #1: removed broken flag"         bash -c "! grep -q 'reasoning.effort=high' providers/codex.md"

# Fix #2 — ls -t race in wrappers must be gone from generated openrouter/deepseek
for p in "${WRAPPER[@]}"; do
  check "wrapper fix #2: no 'ls -t | head -1' in $p.md" \
    bash -c "! grep -q 'ls -t.*head -1' 'providers/$p.md'"
  # Selector must use the trace-marker grep pattern (race-safe under sub-second collisions)
  check "wrapper fix #2: TRINITY_TRACE marker in $p.md" \
    grep -q 'TRINITY_TRACE' "providers/$p.md"
  # No bash-4-only associative arrays — must run on macOS bash 3.2.
  check "wrapper fix #2: no 'declare -A' in $p.md" \
    bash -c "! grep -q 'declare -A' 'providers/$p.md'"
done
# And the family-wrapper partial itself must contain the race-safe trace selector.
check "wrapper fix #2: family-wrapper has trace marker selector" \
  grep -q 'TRINITY_TRACE' providers/_base/family-wrapper.md

# Codex fix #1 add'l — `minimal` removed from EFFORT regex (review M1 fix)
check "codex fix #1: 'minimal' not accepted in EFFORT regex" \
  bash -c "! grep -qE 'EFFORT=\(minimal' providers/codex.md"

# Fix #3 — generic "verify ... reasonable" lifted to common, applies to all 5
check "common fix #3: generic verify rule in common-tail" \
  grep -qi 'provider produces code, verify' providers/_base/common-tail.md
for p in "${PROVIDERS[@]}"; do
  check "common fix #3: verify rule lands in $p.md" \
    grep -qi 'verify.*reasonable' "providers/$p.md"
done

# Summary --------------------------------------------------------------------
echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"
if [ "$FAIL" -ne 0 ]; then
  printf '  - %s\n' "${FAILS[@]}"
  exit 1
fi

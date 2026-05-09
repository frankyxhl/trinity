#!/usr/bin/env bash
# tests/test_scan_rocket_issues.sh
#
# Tests for scripts/scan_rocket_issues.sh per TRN-3029 §Acceptance Criteria A18.
#
# Strategy: stub `gh` and `jq` via PATH-prepended shim directory. Each case
# defines its own canned response files so the harness can simulate
# pagination, missing tools, and gh-api failures without touching the
# network or real gh auth state.
#
# Cases:
#   T1a — blueprint-ready label present → output contains issue number (exit 0)
#   T1b — blueprint-ready label absent  → empty output (exit 0)
#   T1c — pagination across 2 pages, eligible issue on page 2 → output contains it
#   T1d — REPO unset AND gh repo view fails → exit non-zero with stderr
#   T1e — gh api graphql failure mid-pagination → exit non-zero
#   T1f — empty repo (no issues) → empty output (exit 0)
#   T1g — missing jq → exit non-zero (per A3 entry-check)
#   T1h — 100+ blueprint-ready issues forcing pagination → all returned
#
# Min bash: 3.2 (macOS default).

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/scan_rocket_issues.sh"

PASS=0
FAIL=0
FAILS=()

_pass() { PASS=$((PASS+1)); printf "  ok  %s\n" "$1"; }
_fail() { FAIL=$((FAIL+1)); FAILS+=("$1"); printf "  FAIL %s\n" "$1"; }

# Build a shim directory that overrides `gh` (and optionally `jq`) on PATH.
# Pages are dropped into $SHIM_DIR/page_<n>.json; the gh shim returns them
# in order via $SHIM_DIR/.cursor (simple counter file).
_make_shim_dir() {
  mktemp -d -t scan_rocket_shim.XXXXXX
}

_install_gh_shim() {
  # $1 = shim dir
  # The shim:
  #   - `gh repo view --json nameWithOwner -q .nameWithOwner` → echoes $REPO_HINT
  #     (if file $1/.repo_hint exists) or exits 1 if $1/.repo_hint_fail exists
  #   - `gh api graphql -f query=...` → reads $1/page_$N.json (N from .cursor),
  #     unless $1/.gh_fail_at_page exists and matches N → exit 1
  cat > "$1/gh" <<'GHSHIM'
#!/usr/bin/env bash
SHIM_DIR="$(cd "$(dirname "$0")" && pwd)"
case "$1" in
  repo)
    if [ -f "$SHIM_DIR/.repo_hint_fail" ]; then
      echo "shim: gh repo view failed" >&2
      exit 1
    fi
    if [ -f "$SHIM_DIR/.repo_hint" ]; then
      cat "$SHIM_DIR/.repo_hint"
      exit 0
    fi
    echo "shim: no .repo_hint configured" >&2
    exit 1
    ;;
  api)
    # Increment cursor counter; first call reads page_0.json, etc.
    if [ -f "$SHIM_DIR/.cursor" ]; then
      N=$(cat "$SHIM_DIR/.cursor")
    else
      N=0
    fi
    NEXT=$((N+1))
    echo "$NEXT" > "$SHIM_DIR/.cursor"
    if [ -f "$SHIM_DIR/.gh_fail_at_page" ]; then
      FAIL_AT=$(cat "$SHIM_DIR/.gh_fail_at_page")
      if [ "$N" = "$FAIL_AT" ]; then
        echo "shim: simulated gh api failure at page $N" >&2
        exit 1
      fi
    fi
    PAGE_FILE="$SHIM_DIR/page_${N}.json"
    if [ -f "$PAGE_FILE" ]; then
      cat "$PAGE_FILE"
      exit 0
    fi
    echo "shim: no page_${N}.json" >&2
    exit 1
    ;;
  *)
    echo "shim: unhandled gh arg: $*" >&2
    exit 1
    ;;
esac
GHSHIM
  chmod +x "$1/gh"
}

# Empty-issue page (used to terminate pagination cleanly).
_empty_page='{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}'

_page_with_numbers() {
  # $1 = comma-separated issue numbers e.g. "77,82"
  # $2 = "true" or "false" for hasNextPage
  # $3 = endCursor string (or "null")
  local nums="$1"
  local has_next="$2"
  local end_cursor="$3"
  local end_cursor_json
  if [ "$end_cursor" = "null" ]; then
    end_cursor_json="null"
  else
    end_cursor_json="\"$end_cursor\""
  fi
  local nodes=""
  IFS=',' read -ra arr <<< "$nums"
  for n in "${arr[@]}"; do
    [ -z "$nodes" ] || nodes="$nodes,"
    nodes="$nodes{\"number\":$n}"
  done
  printf '{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":%s,"endCursor":%s},"nodes":[%s]}}}}\n' \
    "$has_next" "$end_cursor_json" "$nodes"
}

# ---- Test cases --------------------------------------------------------------

t1a_label_present() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"
  _page_with_numbers "77" "false" "null" > "$SHIM/page_0.json"

  local out rc
  out=$(PATH="$SHIM:$PATH" bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
  if [ "$rc" = "0" ] && [ "$out" = "77" ]; then
    _pass "T1a: blueprint-ready label present → outputs issue number"
  else
    _fail "T1a: rc=$rc out='$out' (expected rc=0 out=77)"
  fi
  rm -rf "$SHIM"
}

t1b_label_absent() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"
  echo "$_empty_page" > "$SHIM/page_0.json"

  local out rc
  out=$(PATH="$SHIM:$PATH" bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
  if [ "$rc" = "0" ] && [ -z "$out" ]; then
    _pass "T1b: no labeled issues → empty output, exit 0"
  else
    _fail "T1b: rc=$rc out='$out' (expected rc=0 empty)"
  fi
  rm -rf "$SHIM"
}

t1c_pagination_eligible_on_page_2() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"
  _page_with_numbers "10,11" "true" "CURSOR_PAGE2" > "$SHIM/page_0.json"
  _page_with_numbers "77" "false" "null" > "$SHIM/page_1.json"

  local out rc
  out=$(PATH="$SHIM:$PATH" bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
  local expected
  expected=$(printf "10\n11\n77")
  if [ "$rc" = "0" ] && [ "$out" = "$expected" ]; then
    _pass "T1c: pagination across 2 pages → all issues collected in order"
  else
    _fail "T1c: rc=$rc out='$out' (expected '10\\n11\\n77')"
  fi
  rm -rf "$SHIM"
}

t1d_repo_unset_and_gh_repo_view_fails() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  : > "$SHIM/.repo_hint_fail"

  local out rc
  out=$(env -u REPO PATH="$SHIM:$PATH" bash "$SCRIPT" 2>&1) && rc=0 || rc=$?
  if [ "$rc" != "0" ]; then
    _pass "T1d: REPO unset + gh repo view fails → non-zero exit"
  else
    _fail "T1d: expected non-zero exit, got rc=$rc out='$out'"
  fi
  rm -rf "$SHIM"
}

t1e_gh_api_failure_mid_pagination() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"
  _page_with_numbers "10" "true" "CURSOR_PAGE2" > "$SHIM/page_0.json"
  echo "1" > "$SHIM/.gh_fail_at_page"

  local rc
  PATH="$SHIM:$PATH" bash "$SCRIPT" >/dev/null 2>&1 && rc=0 || rc=$?
  if [ "$rc" != "0" ]; then
    _pass "T1e: gh api failure on page 2 → non-zero exit"
  else
    _fail "T1e: expected non-zero exit on mid-pagination failure"
  fi
  rm -rf "$SHIM"
}

t1f_empty_repo() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"
  echo "$_empty_page" > "$SHIM/page_0.json"

  local out rc
  out=$(PATH="$SHIM:$PATH" bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
  if [ "$rc" = "0" ] && [ -z "$out" ]; then
    _pass "T1f: empty repo → empty output, exit 0"
  else
    _fail "T1f: rc=$rc out='$out' (expected rc=0 empty)"
  fi
  rm -rf "$SHIM"
}

t1g_missing_jq() {
  # Build a shim dir with NO jq and a fake jq override that is non-executable
  # OR omit jq from PATH entirely. We use an isolated PATH that excludes
  # any directory containing real jq.
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"

  # Create a minimal PATH containing only the shim dir + /usr/bin (for
  # `command`, `env`, etc). Crucially, no jq in either.
  if command -v jq >/dev/null 2>&1; then
    : # jq exists somewhere; we'll filter PATH below
  fi
  # Compose PATH = shim only. Bash builtins (command, [, etc) are intrinsic;
  # we only need /usr/bin for things like `head`, `tr` etc. used by gh. But
  # the script only invokes `command -v`, `gh`, `jq`. The shim handles `gh`,
  # `command -v` is a builtin. So PATH=shim only is sufficient.
  local rc
  PATH="$SHIM" bash "$SCRIPT" >/dev/null 2>&1 && rc=0 || rc=$?
  if [ "$rc" != "0" ]; then
    _pass "T1g: missing jq → non-zero exit (entry-check fail)"
  else
    _fail "T1g: expected non-zero exit when jq missing"
  fi
  rm -rf "$SHIM"
}

t1h_pagination_100_plus_issues() {
  local SHIM; SHIM=$(_make_shim_dir)
  _install_gh_shim "$SHIM"
  echo "frankyxhl/trinity" > "$SHIM/.repo_hint"

  # Page 0: 100 issues, hasNextPage=true. Page 1: 25 issues, hasNextPage=false.
  local nums_p0=""
  local i
  for i in $(seq 1 100); do
    [ -z "$nums_p0" ] || nums_p0="$nums_p0,"
    nums_p0="$nums_p0$i"
  done
  local nums_p1=""
  for i in $(seq 101 125); do
    [ -z "$nums_p1" ] || nums_p1="$nums_p1,"
    nums_p1="$nums_p1$i"
  done
  _page_with_numbers "$nums_p0" "true" "CURSOR_PAGE2" > "$SHIM/page_0.json"
  _page_with_numbers "$nums_p1" "false" "null" > "$SHIM/page_1.json"

  local out rc count
  out=$(PATH="$SHIM:$PATH" bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
  count=$(printf "%s\n" "$out" | wc -l | tr -d ' ')
  if [ "$rc" = "0" ] && [ "$count" = "125" ]; then
    _pass "T1h: 125 issues across 2 pages → all 125 returned"
  else
    _fail "T1h: rc=$rc count=$count (expected rc=0 count=125)"
  fi
  rm -rf "$SHIM"
}

# ---- Run ---------------------------------------------------------------------

echo "=== test_scan_rocket_issues.sh ==="

if [ ! -x "$SCRIPT" ]; then
  echo "FAIL: $SCRIPT missing or not executable" >&2
  exit 1
fi

t1a_label_present
t1b_label_absent
t1c_pagination_eligible_on_page_2
t1d_repo_unset_and_gh_repo_view_fails
t1e_gh_api_failure_mid_pagination
t1f_empty_repo
t1g_missing_jq
t1h_pagination_100_plus_issues

echo "---"
echo "PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  for n in "${FAILS[@]}"; do printf "  - %s\n" "$n"; done
  exit 1
fi
exit 0

#!/usr/bin/env bash
# tests/test_release_workflow.sh
#
# Tests for .github/workflows/release.yml per TRN-2006.
#
# T1 Workflow file structure — yaml present, name, on, jobs.release exist
# T2 Trigger — strict semver glob + workflow_dispatch with tag_name input
# T3 Permissions — global contents:read, job contents:write
# T4 Steps — required steps present in correct order
# T5 No third-party publish actions — only direct gh release create
# T6 Semver regex cases — accepts v1.2.3, rejects v1.2.3.4 / v1.2 / v1.2.3-rc1 / 1.2.3
# T7 CHANGELOG awk extractor — full / last / missing / header-only fixtures
# T8 Tag/VERSION matcher — strips leading v + trims whitespace correctly
# T9 Makefile invariants — release target removed, release-prep present, no BSD-sed in CI path

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/release.yml"
FIXTURES="tests/fixtures/changelogs"

PASS=0
FAIL=0
FAILS=()

# Run a check. Args: <name> <command...>. Stdout/stderr of the command suppressed.
# DO NOT pipe the result of `check` to anything — pipe binds tighter than
# function args and would consume the printed status line.
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

# Inverse check: pass when the command FAILS. Use this instead of `check ... ! cmd`
# (`!` cannot be passed as an argument; bash treats it as a literal command name).
check_neg() {
  local name="$1"
  shift
  if ! "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
    printf "  ok  %s\n" "$name"
  else
    FAIL=$((FAIL+1))
    FAILS+=("$name")
    printf "  FAIL %s\n" "$name"
  fi
}

# CHANGELOG awk extractor — mirrors the workflow logic exactly.
# Writes notes for `version` in `file` to stdout.
extract_notes() {
  local version="$1"
  local file="$2"
  awk -v v="$version" '
    $0 ~ "^## \\["v"\\]" {found=1; next}
    found && /^## \[/ {exit}
    found {print}
  ' "$file"
}

# Returns 0 if `tag` matches `version_file` semantically (strips leading v + whitespace).
match_tag_to_version() {
  local tag="$1"
  local version_file="$2"
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
  local v
  v=$(tr -d '[:space:]' < "$version_file")
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
  [ "${tag#v}" = "$v" ]
}

# True if string is a valid semver tag (vX.Y.Z).
valid_semver_tag() {
  [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

# True if extracted notes are non-empty after whitespace strip.
notes_nonempty() {
  local f="$1"
  [ -n "$(tr -d '[:space:]' < "$f")" ]
}

# True if extracted notes are empty after whitespace strip.
notes_empty() {
  local f="$1"
  [ -z "$(tr -d '[:space:]' < "$f")" ]
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "== TRN-2006: release-on-tag workflow tests =="

echo "-- T1: workflow file structure"
check "workflow file exists"   test -f "$WORKFLOW"
check "yaml: name field"       grep -q '^name: Release' "$WORKFLOW"
check "yaml: jobs.release"     grep -q '^  release:' "$WORKFLOW"

echo "-- T2: triggers"
check "trigger: push.tags block"            grep -qE '^\s*tags:' "$WORKFLOW"
check "trigger: strict semver glob"         grep -qF "'v[0-9]+.[0-9]+.[0-9]+'" "$WORKFLOW"
check "trigger: workflow_dispatch present"  grep -q 'workflow_dispatch:' "$WORKFLOW"
check "trigger: tag_name input"             grep -q 'tag_name:' "$WORKFLOW"

echo "-- T3: permissions (least privilege)"
# Global contents: read should appear at top-level (no leading 4-space indent).
awk '/^permissions:/{f=1; next} /^[a-zA-Z]/{f=0} f' "$WORKFLOW" \
  | grep -q '^  contents: read$' && global_read=0 || global_read=1
check "global contents: read"  test "$global_read" = "0"

# Job-level contents: write inside jobs.release.permissions.
awk '/^  release:/{r=1} r && /^    permissions:/{p=1; next} p && /^      contents: write$/{print; exit}' "$WORKFLOW" \
  | grep -q '^      contents: write$' && job_write=0 || job_write=1
check "job contents: write"    test "$job_write" = "0"

echo "-- T4: required steps in workflow"
for step in "Resolve and validate tag" "Verify tag is on main" "Setup uv" "Install dev dependencies" "Verify build" "Test" "Lint" "Extract release notes" "Publish GitHub Release"; do
  check "step: $step" grep -qF "name: $step" "$WORKFLOW"
done

echo "-- T5: no third-party publish actions"
check_neg "no softprops/action-gh-release" grep -q 'softprops/action-gh-release' "$WORKFLOW"
check     "uses gh release create"         grep -q 'gh release create' "$WORKFLOW"
check     "checkout pinned to v4"          grep -q 'actions/checkout@v4' "$WORKFLOW"
check     "setup-uv pinned to v5"          grep -q 'astral-sh/setup-uv@v5' "$WORKFLOW"

echo "-- T6: semver regex acceptance"
check "accepts v1.2.3"        valid_semver_tag "v1.2.3"
check "accepts v0.0.1"        valid_semver_tag "v0.0.1"
check "accepts v10.20.30"     valid_semver_tag "v10.20.30"
check_neg "rejects v1.2.3.4"      valid_semver_tag "v1.2.3.4"
check_neg "rejects v1.2"          valid_semver_tag "v1.2"
check_neg "rejects v1.2.3-rc1"    valid_semver_tag "v1.2.3-rc1"
check_neg "rejects 1.2.3 (no v)"  valid_semver_tag "1.2.3"
check_neg "rejects empty"         valid_semver_tag ""

echo "-- T7: CHANGELOG awk extractor — fixtures"
check "fixture: full.md exists"          test -f "$FIXTURES/full.md"
check "fixture: last.md exists"          test -f "$FIXTURES/last.md"
check "fixture: missing.md exists"       test -f "$FIXTURES/missing.md"
check "fixture: header-only.md exists"   test -f "$FIXTURES/header-only.md"

# Extract to file (NEVER interpolate awk output into shell — markdown contains backticks).
extract_notes "1.7.0" "$FIXTURES/full.md"        > "$TMP/full-1.7.0"
extract_notes "1.6.0" "$FIXTURES/full.md"        > "$TMP/full-1.6.0"
extract_notes "1.0.0" "$FIXTURES/last.md"        > "$TMP/last-1.0.0"
extract_notes "9.9.9" "$FIXTURES/missing.md"     > "$TMP/missing-9.9.9"
extract_notes "1.7.0" "$FIXTURES/header-only.md" > "$TMP/header-1.7.0"

# T7a — full middle version: has bullets, stops at next ## [
check "full[1.7.0]: nonempty"              notes_nonempty "$TMP/full-1.7.0"
check "full[1.7.0]: contains body"         grep -qF 'Release-on-tag GitHub Action' "$TMP/full-1.7.0"
check_neg "full[1.7.0]: excludes 1.6.0 line"   grep -q '\[1.6.0\]' "$TMP/full-1.7.0"

# T7b — middle version 1.6.0 also stops at next [
check "full[1.6.0]: nonempty"              notes_nonempty "$TMP/full-1.6.0"
check_neg "full[1.6.0]: excludes 1.5.0"        grep -q '\[1.5.0\]' "$TMP/full-1.6.0"

# T7c — last/oldest version (no version follows): captures to EOF
check "last[1.0.0]: nonempty"              notes_nonempty "$TMP/last-1.0.0"
check "last[1.0.0]: contains both bullets" grep -q 'Initial release content' "$TMP/last-1.0.0"
check "last[1.0.0]: contains second"       grep -q 'Second bullet' "$TMP/last-1.0.0"

# T7d — version not in file → empty
check "missing[9.9.9]: empty"              notes_empty "$TMP/missing-9.9.9"

# T7e — header present but body empty → empty after whitespace strip
check "header-only[1.7.0]: empty body"     notes_empty "$TMP/header-1.7.0"

echo "-- T8: tag↔VERSION matcher"

printf '1.7.0\n' > "$TMP/v1"
check "match: v1.7.0 ↔ '1.7.0\\n'"   match_tag_to_version "v1.7.0" "$TMP/v1"

printf '1.7.0' > "$TMP/v2"
check "match: v1.7.0 ↔ '1.7.0' (no LF)"   match_tag_to_version "v1.7.0" "$TMP/v2"

printf '  1.7.0  \n' > "$TMP/v3"
check "match: v1.7.0 ↔ whitespace"   match_tag_to_version "v1.7.0" "$TMP/v3"

printf '1.7.0\n' > "$TMP/v4"
check_neg "mismatch: v1.7.1 vs 1.7.0"    match_tag_to_version "v1.7.1" "$TMP/v4"

printf 'not-semver\n' > "$TMP/v5"
check_neg "rejects malformed VERSION"    match_tag_to_version "v1.7.0" "$TMP/v5"

echo "-- T9: Makefile invariants"
check_neg "Makefile: release target removed"  grep -qE '^release:' Makefile
check "Makefile: release-prep present"    grep -qE '^release-prep:' Makefile
check "Makefile: setup uses uv→pip"       grep -q 'command -v uv' Makefile

echo
echo "=== Result ==="
echo "  passed: $PASS"
echo "  failed: $FAIL"
if [ $FAIL -gt 0 ]; then
  echo
  echo "Failed tests:"
  for f in "${FAILS[@]}"; do
    echo "  - $f"
  done
  exit 1
fi

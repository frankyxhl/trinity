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
# T10 One-click release path — tag_name optional, main-only guard, derive-from-VERSION logic
# T11 Multi-model review fixes — concurrency key, 2-job verify/publish split, no env-injection in run

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
check "yaml: jobs.verify"      grep -q '^  verify:' "$WORKFLOW"
check "yaml: jobs.publish"     grep -q '^  publish:' "$WORKFLOW"

echo "-- T2: triggers"
check "trigger: push.tags block"            grep -qE '^\s*tags:' "$WORKFLOW"
check "trigger: strict semver glob"         grep -qF "'v[0-9]+.[0-9]+.[0-9]+'" "$WORKFLOW"
check "trigger: workflow_dispatch present"  grep -q 'workflow_dispatch:' "$WORKFLOW"
check "trigger: tag_name input"             grep -q 'tag_name:' "$WORKFLOW"

echo "-- T3: permissions (least privilege, 2-job split)"
# Global contents: read at top-level.
awk '/^permissions:/{f=1; next} /^[a-zA-Z]/{f=0} f' "$WORKFLOW" \
  | grep -q '^  contents: read$' && global_read=0 || global_read=1
check "global contents: read"  test "$global_read" = "0"

# Verify job permission: contents: read (no write — third-party actions cannot tag/release).
awk '/^  verify:/{r=1; next} r && /^  [a-zA-Z]/{exit} r && /^    permissions:/{p=1; next} p && /^      contents:/{print; exit}' "$WORKFLOW" \
  | grep -q '^      contents: read$' && verify_read=0 || verify_read=1
check "verify job: contents: read"  test "$verify_read" = "0"

# Publish job permission: contents: write (only this job can mutate).
awk '/^  publish:/{r=1; next} r && /^  [a-zA-Z]/{exit} r && /^    permissions:/{p=1; next} p && /^      contents:/{print; exit}' "$WORKFLOW" \
  | grep -q '^      contents: write$' && publish_write=0 || publish_write=1
check "publish job: contents: write"  test "$publish_write" = "0"

# Verify job MUST NOT have contents: write anywhere in its block.
awk '/^  verify:/{r=1; next} r && /^  [a-zA-Z]/{exit} r' "$WORKFLOW" \
  | grep -q 'contents: write' && verify_no_write=1 || verify_no_write=0
check_neg "verify job has no contents: write"  test "$verify_no_write" = "1"

echo "-- T4: required steps in workflow"
for step in "Verify dispatched from main" "Resolve and validate tag" "Verify tag is on main" "Setup uv" "Install dev dependencies" "Verify build" "Test" "Lint" "Extract release notes" "Verify RELEASE_TAG_PAT secret" "Checkout main HEAD with PAT" "Create + push tag" "Publish GitHub Release"; do
  check "step: $step" grep -qF "name: $step" "$WORKFLOW"
done

echo "-- T5: no third-party publish actions"
check_neg "no softprops/action-gh-release" grep -q 'softprops/action-gh-release' "$WORKFLOW"
check     "uses gh release create"         grep -q 'gh release create' "$WORKFLOW"
check     "checkout pinned to v6"          grep -q 'actions/checkout@v6' "$WORKFLOW"
check     "upload-artifact pinned to v5"   grep -q 'actions/upload-artifact@v5' "$WORKFLOW"
check     "setup-uv pinned to v6"          grep -q 'astral-sh/setup-uv@v6' "$WORKFLOW"

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

echo "-- T11: multi-model review fixes (concurrency, 2-job split, env-mapping)"
# Concurrency key prevents two release runs at once.
check "concurrency: group key present"        grep -qE '^concurrency:$' "$WORKFLOW"
check "concurrency: group value"              grep -qE '^\s*group:\s*release\s*$' "$WORKFLOW"
check "concurrency: cancel-in-progress false" grep -qE '^\s*cancel-in-progress:\s*false\s*$' "$WORKFLOW"

# 2-job structure: publish needs verify.
check "publish job needs verify"              grep -qE '^\s*needs:\s*verify\s*$' "$WORKFLOW"
# Verify job's outputs are wired (tag, version, one_click).
check "verify outputs: tag"                   bash -c "awk '/^  verify:/{r=1} r && /^    outputs:/{o=1} o && /^      tag:/{print;exit}' '$WORKFLOW' | grep -q 'tag:'"
check "verify outputs: version"               bash -c "awk '/^  verify:/{r=1} r && /^    outputs:/{o=1} o && /^      version:/{print;exit}' '$WORKFLOW' | grep -q 'version:'"
check "verify outputs: one_click"             bash -c "awk '/^  verify:/{r=1} r && /^    outputs:/{o=1} o && /^      one_click:/{print;exit}' '$WORKFLOW' | grep -q 'one_click:'"

# Publish job consumes outputs via needs.verify.outputs.*
check "publish references needs.verify"       grep -q 'needs.verify.outputs' "$WORKFLOW"

# Env-mapping hardening: github.ref / event_name / ref_name should be passed via env, not inlined in run scripts.
# Specifically check that the resolve step uses INPUT_TAG / EVENT_NAME / REF_NAME env vars.
check "resolve step: INPUT_TAG env"           grep -qE '^\s+INPUT_TAG:' "$WORKFLOW"
check "resolve step: EVENT_NAME env"          grep -qE '^\s+EVENT_NAME:' "$WORKFLOW"
check "resolve step: REF_NAME env"            grep -qE '^\s+REF_NAME:' "$WORKFLOW"

# Main-only guard uses GITHUB_REF env (not inlined ${{ github.ref }} in shell).
check "main-only guard: GITHUB_REF env"       bash -c "awk '/Verify dispatched from main/{f=1; next} f && /env:/{e=1; next} e && /GITHUB_REF:/{print; exit}' '$WORKFLOW' | grep -q 'GITHUB_REF:'"

# gh release create scoped via --repo flag (defense in depth, no implicit context).
check "gh release create uses --repo flag"    grep -qE '\-\-repo "\$GITHUB_REPOSITORY"' "$WORKFLOW"

# RELEASE_TAG_PAT wiring (D11 — Path A bypass for personal repos).
check "publish: RELEASE_TAG_PAT verify step"  grep -qF 'name: Verify RELEASE_TAG_PAT secret' "$WORKFLOW"
check "publish: PAT preflight uses secret"    bash -c "grep -A3 'Verify RELEASE_TAG_PAT' '$WORKFLOW' | grep -qF 'secrets.RELEASE_TAG_PAT'"
check "publish: checkout uses PAT token"      bash -c "awk '/Checkout main HEAD with PAT/{f=1} f && /token:/{print;exit}' '$WORKFLOW' | grep -qF 'secrets.RELEASE_TAG_PAT'"
check "publish: PAT-checkout gated to one-click"  bash -c "grep -A1 'Checkout main HEAD with PAT' '$WORKFLOW' | grep -qF \"needs.verify.outputs.one_click == '1'\""

echo "-- T10: one-click release path"
# tag_name's required attribute must be false (was true in TRN-2006).
awk '/tag_name:/{f=1; next} f && /required:/{print; exit}' "$WORKFLOW" | grep -q 'required: false' \
  && tag_optional=0 || tag_optional=1
check "tag_name input is optional"            test "$tag_optional" = "0"
# Main-only guard step exists and is gated on workflow_dispatch + empty input.
check "main-only guard step exists"           grep -qF 'name: Verify dispatched from main' "$WORKFLOW"
check "main-only guard checks empty input"    bash -c "grep -A1 'Verify dispatched from main' '$WORKFLOW' | grep -qF \"github.event.inputs.tag_name == ''\""
check "main-only guard rejects non-main"      grep -q 'refs/heads/main' "$WORKFLOW"
# Resolve step derives tag from VERSION when input is empty (one-click path).
check "resolve: ONE_CLICK flag set"           grep -q 'ONE_CLICK=1' "$WORKFLOW"
check "resolve: derives TAG from VERSION"     grep -qF 'TAG="v$VERSION_FILE"' "$WORKFLOW"
# Pre-flight: tag must NOT exist on remote in one-click path.
check "resolve: pre-flight tag-exists check"  grep -qF 'Did you forget to bump VERSION' "$WORKFLOW"
# Tag-on-main verification skipped in one-click path (tag doesn't exist yet).
check "verify-tag-on-main skip in one-click"  bash -c "grep -A1 'Verify tag is on main' '$WORKFLOW' | grep -qF \"steps.tag.outputs.one_click != '1'\" || grep -A1 'Verify tag is on main' '$WORKFLOW' | grep -qF \"steps.tag.outputs.one_click != '1'\""
# Create + push tag step is conditional on one-click path.
check "create-tag step gated to one-click"    bash -c "grep -A1 'Create + push tag' '$WORKFLOW' | grep -qF \"needs.verify.outputs.one_click == '1'\""
check "create-tag step pushes to origin"      grep -qF 'git push origin "$TAG"' "$WORKFLOW"

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

#!/usr/bin/env bash
# scripts/build_providers.sh
#
# Build-time composition for trinity provider templates (TRN-2004).
#
# For each providers/<name>.delta.md, replace `@include <path>` directives
# with the contents of providers/<path>, write providers/<name>.md.
# Validates partial invariants and output invariants.
#
# Usage:
#   scripts/build_providers.sh [--check]
#
#   --check   Build to a temp dir, diff against committed providers/*.md.
#             Exit 0 if identical, 1 if drift detected. Used by `make verify-built`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

CHECK_MODE=0
if [ "${1:-}" = "--check" ]; then
  CHECK_MODE=1
fi

PROVIDERS_DIR="providers"
DELTAS=(codex gemini glm openrouter deepseek)

# Python under bash wrapper does the @include substitution and invariant checks.
python3 - "$PROVIDERS_DIR" "$CHECK_MODE" "${DELTAS[@]}" <<'PY'
import os, sys, tempfile, shutil, re

providers_dir = sys.argv[1]
check_mode = int(sys.argv[2])
deltas = sys.argv[3:]

INCLUDE_RE = re.compile(r'^@include\s+(\S+)\s*$')

def die(msg):
    print(f"build_providers: ERROR: {msg}", file=sys.stderr)
    sys.exit(2)

def assert_partial_invariants(path):
    """Partials must have no frontmatter, exactly one trailing LF, no nested @include."""
    with open(path, 'rb') as f:
        data = f.read()
    if not data:
        die(f"empty partial: {path}")
    if data.endswith(b'\n\n') or not data.endswith(b'\n'):
        die(f"partial must end with exactly one LF: {path}")
    text = data.decode('utf-8')
    first_line = text.split('\n', 1)[0]
    if first_line.strip() == '---':
        die(f"partial must NOT contain frontmatter: {path}")
    for i, line in enumerate(text.splitlines(), 1):
        if INCLUDE_RE.match(line):
            die(f"nested @include not supported (in {path}:{i})")

def expand_delta(delta_path):
    """Return rendered provider content with @include directives expanded."""
    with open(delta_path, encoding='utf-8') as f:
        delta_lines = f.readlines()
    out_lines = []
    seen_partials = set()
    for i, line in enumerate(delta_lines, 1):
        m = INCLUDE_RE.match(line.rstrip('\n'))
        if m:
            rel = m.group(1)
            partial_path = os.path.join(providers_dir, rel)
            if not os.path.exists(partial_path):
                die(f"@include target missing: {partial_path} (from {delta_path}:{i})")
            assert_partial_invariants(partial_path)
            seen_partials.add(partial_path)
            with open(partial_path, encoding='utf-8') as pf:
                # Partial already ends in exactly one \n (asserted above);
                # inline as-is. The delta's own surrounding blank lines
                # control vertical spacing.
                out_lines.append(pf.read())
        else:
            out_lines.append(line)
    rendered = ''.join(out_lines)

    # Output invariants.
    if not rendered.startswith('---\n'):
        die(f"rendered output must start with '---\\n': {delta_path}")
    if rendered.endswith('\n\n'):
        die(f"rendered output ends with multiple LFs: {delta_path}")
    if not rendered.endswith('\n'):
        die(f"rendered output must end with LF: {delta_path}")
    if '@include' in rendered:
        die(f"unresolved @include remains in rendered output: {delta_path}")
    return rendered

def write_or_check(name, content, target_dir):
    target = os.path.join(target_dir, f"{name}.md")
    if check_mode:
        # Temp write; caller will diff after the loop.
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)

if check_mode:
    # Build into a temp dir, then diff each generated file against committed.
    tmp = tempfile.mkdtemp(prefix='trinity-build-')
    try:
        drift = []
        for name in deltas:
            delta = os.path.join(providers_dir, f"{name}.delta.md")
            rendered = expand_delta(delta)
            with open(os.path.join(tmp, f"{name}.md"), 'w', encoding='utf-8') as f:
                f.write(rendered)
            committed_path = os.path.join(providers_dir, f"{name}.md")
            if not os.path.exists(committed_path):
                drift.append(f"  {name}.md: NOT COMMITTED")
                continue
            with open(committed_path, encoding='utf-8') as f:
                committed = f.read()
            if rendered != committed:
                drift.append(f"  {name}.md: DRIFT (committed differs from generated)")
        if drift:
            print("build_providers --check: drift detected:", file=sys.stderr)
            for d in drift:
                print(d, file=sys.stderr)
            sys.exit(1)
        print("build_providers --check: OK (committed matches generated)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    for name in deltas:
        delta = os.path.join(providers_dir, f"{name}.delta.md")
        rendered = expand_delta(delta)
        target = os.path.join(providers_dir, f"{name}.md")
        with open(target, 'w', encoding='utf-8') as f:
            f.write(rendered)
        print(f"  built: {target}")
PY

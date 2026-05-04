# SOP-1001: Test — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** Active

---

## What Is It?

Run the full pytest test suite for Trinity.

---

## Why

Trinity changes must preserve provider generation, Python helpers, shell installers, and release workflow checks. A single test target keeps those gates repeatable before release or PR review.

---

## When to Use

- Before opening or updating a PR with code, installer, provider, or workflow changes
- Before release preparation
- After changing tests or shared scripts

## When NOT to Use

- For docs-only edits where `af validate --root .` is the relevant gate
- When running a narrower RED/GREEN TDD loop; use the focused pytest target first, then return to this SOP before completion

---

## Prerequisites

- `.venv` exists (`make setup` if not)

## Steps

1. Run `make test` → `.venv/bin/pytest tests/ -v`
2. PASS: 0 failures. Any failure blocks release.

---

## Examples

```bash
make test
```

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-05-04 | Backfill canonical SOP metadata and sections for `af validate` | Codex |
| 2026-03-21 | Initial version | Claude Code |

# SOP-1001: Test — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Run the full pytest test suite for Trinity.

---

## Prerequisites

- `.venv` exists (`make setup` if not)

## Steps

1. Run `make test` → `.venv/bin/pytest tests/ -v`
2. PASS: 0 failures. Any failure blocks release.

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |

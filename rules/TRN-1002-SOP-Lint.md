# SOP-1002: Lint — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Run ruff check and format on Trinity source.

---

## Prerequisites

- `.venv` exists

## Steps

1. Run `make lint` → `ruff check scripts/ tests/` + `ruff format --check scripts/ tests/`
2. PASS: 0 violations. Auto-fix: `ruff format scripts/ tests/`

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |

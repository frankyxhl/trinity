# SOP-1002: Lint — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** Active

---

## What Is It?

Run ruff check and format on Trinity source.

---

## Why

Ruff keeps Trinity's Python scripts and tests mechanically consistent. The lint target also enforces formatting so PR diffs stay focused on behavior and docs.

---

## When to Use

- Before opening or updating a PR with Python or test changes
- After running `ruff format`
- Before release preparation

## When NOT to Use

- For shell-only changes where the shell tests are the relevant focused gate
- As a substitute for `make test`; lint checks style, not behavior

---

## Prerequisites

- `.venv` exists

## Steps

1. Run `make lint` → `ruff check scripts/ tests/` + `ruff format --check scripts/ tests/`
2. PASS: 0 violations. Auto-fix: `ruff format scripts/ tests/`

---

## Examples

```bash
make lint
.venv/bin/ruff format scripts/ tests/
make lint
```

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-05-04 | Backfill canonical SOP metadata and sections for `af validate` | Codex |
| 2026-03-21 | Initial version | Claude Code |

# SOP-1005: Install — Trinity

**Applies to:** trinity/ package
**Last updated:** 2026-03-21
**Status:** Active

---

## What Is It?

Install Trinity to `~/.claude/`.

---

## Steps

1. Run `make install`
2. Verify: `python3 ~/.claude/skills/trinity/scripts/session.py --version`
3. Expected output: the version constant from `scripts/__init__.py` (set by `make bump`, matches `VERSION` file)

---

## Change History

| Date | Change | By |
|------|--------|-----|
| 2026-03-21 | Initial version | Claude Code |

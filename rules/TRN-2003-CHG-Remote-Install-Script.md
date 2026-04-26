# CHG-2003: Remote Install Script

**Applies to:** trinity/ package (`frankyxhl/trinity`)
**Date:** 2026-03-21
**Last updated:** 2026-03-21
**Last reviewed:** 2026-04-26
**Status:** In Progress
**PRP:** TRN-2002 (Approved, Codex 9.2/PASS, Gemini 9.8/PASS)
**Implementer:** Claude Sonnet 4.6

---

## Deliverables

| File | Action |
|------|--------|
| `install.sh` | New — repo root |
| `tests/test_install_sh.sh` | New — shell-level test suite |
| `rules/TRN-0000` | Update — add TRN-2002, TRN-2003 |
| `rules/TRN-1005` | Update — add remote install path |
| `README.md` | Update — curl one-liner as primary install |

---

## Execution Log

| Step | Status | Notes |
|------|--------|-------|
| Write install.sh | ✅ | set -eE for ERR trap propagation into functions |
| Write tests/test_install_sh.sh | ✅ | 8/8 pass; T3b covers URL construction path |
| Update TRN-0000 | ✅ | |
| Update TRN-1005 | ✅ | Added remote install path |
| Update README.md | ✅ | curl one-liner as primary install method |
| git commit + push | — | |

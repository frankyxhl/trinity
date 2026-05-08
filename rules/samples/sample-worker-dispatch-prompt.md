# Sample Worker Dispatch Prompt

> Copy this template and fill the `<...>` slots when dispatching a coding worker via `droid exec`.
> The worker reads the CHG file itself — do NOT inline the full spec.

---

## Provider Role

Provider: **<glm|codex|deepseek|gemini>** (CODING WORKER role).
Project: `/Users/frank/Projects/trinity`.
Branch: `<branch-name>` (head `<short-sha>`, off `origin/main` `<short-sha>`).

INVOKE `droid exec` for the actual edits.

## Task

Implement **<CHG-ID>** per the plan at `rules/<CHG-file>.md`.

Read the CHG document before starting. All implementation details are in that file.

## High-Level Summary

<One paragraph stating intent. e.g. "Add a stderr-sentinel boundary detection helper to the provider result parser, update all call sites to use the new helper, and add ≥5 test cases covering empty input, partial reads, multi-line output, encoding edge cases, and max-size input.">

## Implementation Order

1. <Step 1 — copied from CHG §Implementation Order>
2. <Step 2>
3. <Step 3>
4. <Step 4>
5. <Step 5>
6. <Step 6>

## Constraints (Must-Haves)

- <Bullet 1 — e.g. "Regex MUST use `(?ims)` flags — all 4 panel reviewers caught the missing `s` flag in v2.">
- <Bullet 2 — e.g. "Return type of `parse_result()` MUST remain `dict[str, Any]` — do not widen the contract.">
- <Bullet 3 — e.g. "Legacy path MUST continue to work without the new helper — backwards compat is non-negotiable.">
- <Bullet 4 — e.g. "Error handler exception list MUST include `TimeoutError`, `ConnectionError`, and `ValueError`.">

## Verification

Run the following commands after implementation:

```bash
.venv/bin/pytest tests/ -q | tail -5
.venv/bin/ruff check <changed-paths>
.venv/bin/ruff format --check <changed-paths>
make verify-built 2>&1 | tail -2   # only if providers/ changed
af validate --root /Users/frank/Projects/trinity | tail -2
```

## Expected Outputs

- Test count: **<N>** tests passing (up from <M> baseline).
- Lint: **0 errors** from `ruff check`.
- Format: **0 errors** from `ruff format --check`.
- af validate: **0 issues**.

## Process Constraints

- **Do NOT push or commit.** The orchestrator handles all git operations.
- **Do NOT update the CHG document.** The orchestrator adds the round history row.
- Spec ambiguities → prefer the more conservative interpretation; flag in report.

## Output — Structured Report

At the end of your work, provide a structured report containing:

| Field | Description |
|-------|-------------|
| Files modified | List of every file touched, with brief summary per file |
| Helpers added | `file:line` for each new function/class introduced |
| Modified signatures | `file:line` for every changed function signature |
| Test count + names | Total tests and name of each new test case |
| Verification outputs | Paste of the last 5 lines from each verification command |
| Ambiguities resolved | What was unclear in the spec and how you resolved it |

---

## Worker Dispatch Contract Checklist

Before sending this prompt, confirm all items:

- [ ] CHG path is passed; spec is NOT inlined.
- [ ] Implementation order is specified (numbered steps from CHG).
- [ ] Exact verification commands are listed.
- [ ] Worker is constrained: do NOT push or commit.
- [ ] Structured report format is requested.

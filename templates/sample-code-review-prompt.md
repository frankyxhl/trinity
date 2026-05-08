# Sample Code-Review Prompt

> Copy this template and fill the `<...>` slots for each code-review dispatch.
> Dispatch all 4 providers in parallel.
> Code-review runs AFTER the plan has been approved (phase 4 gate met) and implementation is pushed.

---

Provider: **<gemini|codex|glm|deepseek>** (CODE REVIEWER role).
Project: `<repo-root> ($(pwd) at the orchestrator host)`.
Branch: `<branch-name>` (head `<short-sha>`, off `origin/main` `<short-sha>`).

INVOKE the `<provider>` CLI for the actual review.

## Task

Code-review of the diff on **<branch-name>** against `origin/main`.

Run:

```bash
git diff origin/main..HEAD
```

Read the full diff and the modified files. Evaluate the implementation against the weights below.

## Context

- **CHG:** `<CHG-ID>` at `rules/<CHG-file>.md`
- **Plan-review gate:** Met on round R<N> (all-individual ≥ 9.0, all blocking empty).
- **This review:** Scrutinize the *implementation* — does the code match the approved plan?

## What to Scrutinize

- **Regression risk:** Does the diff introduce behaviour changes not described in the CHG? Do existing tests still cover the unchanged paths?
- **Test coverage of new code:** Is every new function, branch, and error path covered by ≥1 test case? Are edge cases (empty input, max-size, encoding) tested?
- **Lint / format:** Would `ruff check` and `ruff format --check` pass cleanly on every changed file?
- **Contract changes:** Are function signatures, return types, and error types exactly as the CHG specifies? Any undocumented widening or narrowing?
- **Docs match code:** Do inline docstrings, comments, and the CHG's Surfaces table accurately reflect what the code actually does?

## Scoring — TRN-1800 Weights

**IMPORTANT:** Choose the correct weights table based on the change type.

### Code / Test Changes — Use This Table

Use this table when the diff modifies code, tests, scripts, schemas, or any behaviour surface.

| Dimension | Weight |
|-----------|--------|
| Test coverage of changed surface | 30% |
| Cross-platform parity | 20% |
| Compression ratio | 20% (net-positive justified by new tests/SOP) |
| Scope restraint | 15% |
| Necessity | 15% |

### Doc-Only CHGs — Use This Table

Use this table when the diff modifies ONLY documentation files (rules/*.md, README, CHANGELOG, SOPs) with no code or test changes.

| Dimension | Weight |
|-----------|--------|
| Necessity | 25% |
| Generated-vs-source | 25% |
| Atomicity | 15% |
| Compression ratio | 15% |
| Consistency | 10% |
| Actionability | 10% |

**USE TRN-1800, NOT CLD-1800** (the `.claude` repo philosophy doesn't apply here).

## Output Schema (REQUIRED — emit at END)

After your concise free-form review, emit **EXACTLY ONE** fenced JSON block:

```json
{
  "decision": "PASS | FIX",
  "weighted_score": "<0.0-10.0>",
  "blocking": [
    {
      "title": "<short title of the blocking issue>",
      "evidence": "<file:line or diff hunk reference>",
      "fix": "<what needs to change to unblock>"
    }
  ],
  "advisories": [
    {
      "title": "<short title of the advisory>",
      "evidence": "<file:line or diff hunk reference>",
      "fix": "<suggested improvement>"
    }
  ],
  "confidence": "<0.0-1.0>"
}
```

### Rules

- **PASS** only when `blocking == []` AND `weighted_score >= 9.0`.
- Every `blocking` entry must have concrete evidence (file:line or diff location) and a fix.
- `advisories` are non-blocking suggestions; fix convergent advisories before handoff.
- This must be the **LAST** fenced ````json` block in your output.

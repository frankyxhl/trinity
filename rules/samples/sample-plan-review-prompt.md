# Sample Plan-Review Prompt

> Copy this template and fill the `<...>` slots for each plan-review dispatch.
> Dispatch all 4 providers in parallel.

---

Provider: **<gemini|codex|glm|deepseek>** (PLAN REVIEWER role).
Project: `/Users/frank/Projects/trinity`.
Branch: `<branch-name>` (head `<short-sha>`, off `origin/main` `<short-sha>`).

INVOKE the `<provider>` CLI for the actual review.

## Task

Plan-review of **<CHG-ID>** at `rules/<CHG-file>.md`.

Read the CHG document in full. Evaluate the plan against the weights below.

## Scoring — TRN-1800 Weights

**IMPORTANT:** Choose the correct weights table based on the change type.

### Code / Test Changes — Use This Table

Use this table when the CHG modifies code, tests, scripts, schemas, or any behaviour surface.

| Dimension | Weight |
|-----------|--------|
| Test coverage of changed surface | 30% |
| Cross-platform parity | 20% |
| Compression ratio | 20% (net-positive justified by new tests/SOP) |
| Scope restraint | 15% |
| Necessity | 15% |

### Doc-Only CHGs — Use This Table

Use this table when the CHG modifies ONLY documentation files (rules/*.md, README, CHANGELOG, SOPs) with no code or test changes.

| Dimension | Weight |
|-----------|--------|
| Necessity | 25% |
| Generated-vs-source | 25% |
| Atomicity | 15% |
| Compression ratio | 15% |
| Consistency | 10% |
| Actionability | 10% |

**USE TRN-1800, NOT CLD-1800** (the `.claude` repo philosophy doesn't apply here).

## What to Scrutinize

- <Bullet 1 — e.g. "Verdict precedence ordering: is the priority chain unambiguous?">
- <Bullet 2 — e.g. "stderr-sentinel boundary detection: does the plan handle partial reads?">
- <Bullet 3 — e.g. "Backwards-compat invariant in the legacy path: existing callers must not break.">
- <Bullet 4 — e.g. "Test surface coverage: are edge cases (empty input, max-size input, encoding) addressed?">
- <Bullet 5 — e.g. "Scope restraint: nothing in the plan that belongs in a follow-up CHG.">

## Output Schema (REQUIRED — emit at END)

After your concise free-form review, emit **EXACTLY ONE** fenced JSON block:

```json
{
  "decision": "PASS | FIX",
  "weighted_score": "<0.0-10.0>",
  "blocking": [
    {
      "title": "<short title of the blocking issue>",
      "evidence": "<file:line or section reference>",
      "fix": "<what needs to change to unblock>"
    }
  ],
  "advisories": [
    {
      "title": "<short title of the advisory>",
      "evidence": "<file:line or section reference>",
      "fix": "<suggested improvement>"
    }
  ],
  "confidence": "<0.0-1.0>"
}
```

### Rules

- **PASS** only when `blocking == []` AND `weighted_score >= 9.0`.
- Every `blocking` entry must have concrete evidence and a fix.
- `advisories` are non-blocking suggestions; fix convergent advisories before code-review.
- This must be the **LAST** fenced ````json` block in your output.

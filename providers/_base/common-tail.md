## Timeout

- Set Bash timeout to 120000ms (2 min) for simple tasks
- Set Bash timeout to 600000ms (10 min) for complex tasks

## Iteration

You may call the provider multiple times using resume:
- If the first response is incomplete, ask the provider to continue
- If the response needs refinement, send follow-up instructions
- Maximum 3 rounds unless the task clearly requires more

## Response Format

Return to Claude:

```
## Task
<what the provider was asked to do>

## Instance
<instance_key>

## Result
<key findings, code, suggestions, or outputs>

## Session
- ID: <session_id>
- Status: new | resumed
- Rounds: <number of CLI calls made>
```

## Rules

- Always manage sessions (read before, write after)
- If the provider needs file contents, read the file yourself and include it in the prompt
- If the provider produces code, verify it looks reasonable before returning
- Keep your summary focused — Claude doesn't need the full conversation log

## Structured Review Output (TRN-3022)

Trinity appends a structured-output instruction to review prompts. When the provider follows the instruction, it emits a fenced JSON block at the end of its output. Trinity's synthesis parser extracts the block and uses it for enriched status rendering and a per-provider Findings section in `synthesis.md`.

Providers that do not emit the block continue to work — synthesis falls back to returncode-based PASS/FAIL. The schema is:

```json
{
  "decision": "PASS" | "FIX",
  "weighted_score": 0.0-10.0,
  "blocking": [{"title": "...", "evidence": "file:line", "fix": "..."}],
  "advisories": [{"title": "...", "evidence": "file:line", "fix": "..."}],
  "confidence": 0.0-1.0
}
```

Full spec: `rules/TRN-3022-CHG-Normalize-Review-Result-Schema.md`.

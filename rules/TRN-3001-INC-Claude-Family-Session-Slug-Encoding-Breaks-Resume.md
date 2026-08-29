# INC-3001: Claude-Family Session Slug Encoding Breaks Resume

**Applies to:** TRN project
**Last updated:** 2026-08-02
**Last reviewed:** 2026-08-02
**Status:** Open
**Related:** TRN-3002, TRN-3040, TRN-3045
**Date:** 2026-08-02
**Severity:** High

---

## What Happened

Trinity's shared Claude-family transcript resolver and the generated provider
agents encode a project path by replacing `/` only. Claude Code 2.1.220 uses a
different canonical project-key function: replace every non-ASCII alphanumeric
UTF-16 code unit with `-`; keep the resulting leading dash; and, when the
sanitized slug is longer than 200 UTF-16 code units, retain the first 200 units
and append `-<base36(abs(js-string-hash))>`.

The mismatch was reproduced for `deepseek:hbp-smoke` in the read-only project
`/Users/frank/Projects/harry_brownes_permanent_portfolio`. Trinity searched the
underscore-preserving directory
`-Users-frank-Projects-harry_brownes_permanent_portfolio`, while the existing
Claude-written transcript is under
`-Users-frank-Projects-harry-brownes-permanent-portfolio`; the resolver exited
3 with `transcript file not found`.

Canonical-source evidence was extracted read-only from the installed Claude
Code 2.1.220 executable. Its transcript-path flow calls the equivalent of
`join(configHome, "projects", projectKey(cwd))`, where `projectKey` applies the
replacement and 200-UTF-16-unit prefix plus base-36 hash suffix described
above. The real
DeepSeek transcript path independently confirms underscore-to-hyphen behavior.


## Impact

- **DeepSeek:** named-session continuation fails when the absolute project path
  contains `_` or any other non-alphanumeric character beyond `/`.
- **Claude Code and OpenRouter:** share the same resolver/template assumption
  and can fail identically.
- **Long project paths:** can diverge even when they contain only separators,
  because Trinity does not implement Claude's 200-UTF-16-unit prefix plus hash
  suffix.
- **GLM and MiniMax:** not affected; they use the Droid path convention and
  must retain the current slash-only encoding.
- **Data exposure:** none observed. The resolver checks file existence only and
  did not read or print transcript content.


## Resolution

TRN-3002 implements and verifies the source fix. Claude-compatible slug
encoding is centralized in `scripts/session_path.py`; the three Claude-family
provider templates call that helper; and regression coverage pins punctuation,
Unicode UTF-16 semantics, the length cap/hash, leading-dash retention, named
instances, and `:default` normalization. The source helper resolves the known
DeepSeek transcript with exit 0. GLM and MiniMax remain on
`_encode_project_path` unchanged, and the GLM control session also resolves
with exit 0.

Global sync and the optional one-call provider resume remain separately gated
below, so the incident stays Open until Frank decides whether to run them.


## Follow-up

- [x] Implement and verify TRN-3002 through COR-1500 RED/GREEN/REFACTOR.
- [x] Independently review the implementation and independently rerun the
  verification suite.
- [x] Confirm the source helper resolves the existing DeepSeek transcript.
- [ ] Explain and receive acknowledgement for the bounded global sync before
  changing `~/.claude/skills/trinity` or `~/.claude/agents`.
- [ ] If authorized after sync, perform at most one bounded DeepSeek resume
  call with explicit `--model deepseek-v4-flash`, exposing neither secrets nor
  general transcript content.

---

## Change History

| Date       | Change                                                            | By    |
|------------|-------------------------------------------------------------------|-------|
| 2026-08-02 | Recorded runtime-backed root cause, impact, and guarded follow-up | Codex |
| 2026-08-02 | Source fix, review, and verification passed; global sync remains gated | Codex |

# CHG-3022: Normalize Review Result Schema for Synthesis

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-08
**Last reviewed:** 2026-05-08
**Status:** Approved
**Date:** 2026-05-08
**Requested by:** Frank Xu (issue #39)
**Priority:** Medium
**Change Type:** Feature (additive — preserves all existing free-form behavior)
**Closes:** #39
**References:** TRN-3000 (CLI-backend lessons); TRN-3020 (registry); TRN-3021 (doctor preflight); TRN-1007 (PR readiness gate)

---

## What

Define a **structured review output schema** that providers can emit as a fenced JSON block at the end of their review. Add a parser that extracts the block from raw output and a synthesis path that prefers structured fields when present. Existing free-form provider output continues to work — synthesis falls back to today's PASS/FAIL-by-returncode rendering when no schema block is present.

This is the foundation for issue #55 (richer summary output) — once the schema lands, summary rendering can render decision / weighted score / blocking findings / advisories per provider in a comparable form.

**Design hardening (round-2 panel-driven)**: the round-1 panel (3-of-4 FAIL/PASS-with-blocker, codex 7.4 / glm 8.7 / gemini 8.7 / deepseek 9.16) caught 6 substantive design holes that shape the v2 spec:

- **Task-type guard structurally impossible** — `render_prompt(config, root, scope, review_input, strict_review)` (codex.py:1218) has no `task_type` param; the static-template approach would leak the schema addendum into TDD/PRP/general task_types since they all share `review.prompt_template`. Resolved: extend `render_prompt` signature to accept `task_type`; addendum moves from static template into a code-side helper `_review_schema_addendum(task_type)` that returns empty string for non-review.
- **stderr-side JSON breaks last-block-wins** — `raw_output(stdout, stderr)` (codex.py:1391) concatenates with `\n[stderr]\n` sentinel. A provider CLI that emits a fenced JSON block to stderr (telemetry, debug, error wrappers) would override the canonical stdout block. Resolved: parser splits on the sentinel and scans only the pre-sentinel region.
- **Returncode precedence undefined** — without explicit precedence, synthesis could show `PASS` while CLI exits 1. Resolved: returncode wins. Status rendering rule pinned in §"Synthesis behavior".
- **Timeout partial output (rc=124) parsing** is dangerous — partial output may contain a valid JSON block from before the timeout, but the review didn't actually complete. Resolved: parser is called but parsed result is IGNORED for rendering when `returncode != 0`. Findings section excludes non-zero-rc providers.
- **decision="PASS" + blocking non-empty / score < 9.0** logical inconsistency. Resolved: validator coerces `effective_decision = "FIX"` when `decision == "PASS"` AND (`blocking` non-empty OR `weighted_score < 9.0`). Display uses `effective_decision`. Original `decision` preserved in parsed dict for diagnostics.
- **`write_synthesis` I/O contract widening** — function now reads raw files from disk; needs OSError/UnicodeDecodeError handling. Resolved: `_safe_read_raw(path)` returns text-or-None; caller falls back to legacy on None.

### Schema (the contract providers should emit) — v2

Schema unchanged from v1 in shape; semantics tightened per panel feedback.

A single fenced JSON code block at the **end** of the review output:

```json
{
  "decision": "PASS",
  "weighted_score": 9.2,
  "blocking": [],
  "advisories": [
    {
      "title": "Late-binding closure in helper X",
      "evidence": "scripts/foo.py:142-148",
      "fix": "Capture loop var via default arg"
    }
  ],
  "confidence": 0.85
}
```

Field semantics:

| Field | Type | Required | Behavior on missing-when-block-present |
|-------|------|----------|---------------------------------------|
| `decision` | string, `"PASS"` / `"FIX"` (case-insensitive on parse, normalized to upper) | yes | parser returns None → legacy fallback |
| `weighted_score` | number, 0.0–10.0 | yes | parser returns None → legacy fallback |
| `blocking` | list of finding objects (empty list OK; null NOT OK) | yes | parser returns None |
| `advisories` | list of finding objects (empty list OK; null NOT OK) | yes | parser returns None |
| `confidence` | number, 0.0–1.0 | optional | absent OK; non-number → parser returns None |

**Required-vs-default clarification (round-1 codex B6 / spec contradiction fix)**: when the schema block is **PRESENT** and missing a required field, parser returns None → legacy fallback (no partial-parse). When the schema block is **ABSENT entirely**, parser returns None → legacy fallback. The "default" concept doesn't apply at the parser layer — synthesis defaults are a separate concern (returncode-derived rendering when no parsed dict).

Within each finding object:
- `title`: string, required. Empty string accepted but discouraged.
- `evidence`: string, required. Empty string accepted (cross-cutting issues).
- `fix`: string, optional. Missing or empty → renderer omits the trailing `— fix` clause (no dangling em-dash, per deepseek A2).
- **Unknown finding-level keys**: ignored (forward-compat parity with top-level — per deepseek A8 / codex A2). Future fields like `severity` / `category` can land additively.

**Effective decision (round-1 codex B5)**: when `decision == "PASS"` AND (`blocking` non-empty OR `weighted_score < 9.0`), the parser sets `effective_decision = "FIX"` on the parsed dict (preserving original `decision` for diagnostics). Synthesis renders `effective_decision`. This catches lazy LLM compliance where the provider declares PASS while listing blocking findings.

Within each finding object:
- `title`: short one-line label (required)
- `evidence`: `file:line` or `file:line-line` reference (required, may be empty string for cross-cutting issues)
- `fix`: one-line suggested remediation (optional)

### Parsing rules — v2

`parse_structured_review(raw_text)` returns a dict-or-None:

1. **Strip stderr region first** (round-1 codex B4 / glm B2): `raw_output(stdout, stderr)` writes `<stdout>\n[stderr]\n<stderr>` (codex.py:1391). If a provider CLI emits a fenced JSON block to stderr (telemetry, debug logs), last-block-wins would pick that block. Parser splits on the literal sentinel `\n[stderr]\n` and scans only the **pre-sentinel** region. If sentinel absent (custom raw_output writers), scan the full text.
2. **Find last fenced JSON block** with **strict regex**: `(?ims)^```json\s*$\n(.*?)\n^```\s*$` — flags `i` (case-insensitive lang tag), `m` (multiline `^`/`$` anchors), **`s` (DOTALL — REQUIRED so `(.*?)` spans newlines; missing `s` is the entire bug ALL 4 round-2 reviewers flagged independently)**. Language tag `json` REQUIRED (case-insensitive); bare ``` blocks (no language tag) ignored to avoid false positives from prompt's `## Git Diff` ` ```diff ` blocks the model might paraphrase. Last match wins (per deepseek R1 A4).
3. `json.loads` the captured contents.
4. Validate against `_validate_review_schema(data)`:
   - Top-level: dict shape, required fields present, types match, value ranges in spec.
   - Findings (each item in `blocking` and `advisories`): dict with required `title: str`, `evidence: str` (may be empty); optional `fix: str`. Unknown keys at finding-level ignored (forward-compat).
   - Unknown keys at top-level ignored.
5. **Effective-decision coercion**: if validation passes AND `decision == "PASS"` AND (`blocking` non-empty OR `weighted_score < 9.0`), set `effective_decision = "FIX"` on the returned dict. Otherwise `effective_decision = decision`. Original `decision` preserved.
6. On any parse / validation failure → return `None` (fall back to legacy behavior).
7. **Never raises** — synthesis must work even on malformed provider output. Wrapped in try/except for `json.JSONDecodeError`, `TypeError`, `ValueError`, `AttributeError`. (Caller handles `OSError` / `UnicodeDecodeError` from raw-file read separately via `_safe_read_raw`.)

### Synthesis behavior — v2

`write_synthesis` enriched in two layers, with explicit returncode precedence (round-1 codex B2/B3):

**Returncode precedence rule (pinned)**: returncode wins for the Status column. Only `rc == 0` providers get structured rendering.

1. **Status column rendering** (per provider):
   - `rc != 0` (any non-zero, including timeout 124, sigint 130, internal-error -1) → render `FAIL <rc>` regardless of any structured block. Structured data from rc!=0 providers is IGNORED for synthesis (their raw may contain partial pre-timeout output that lies about completion).
   - `rc == 0` AND structured block parses → render `effective_decision (score, N blocking)`:
     - `PASS (9.2)` (no blocking, score ≥ 9.0)
     - `FIX (7.1, 2 blocking)` (effective_decision is FIX — either declared or coerced)
   - `rc == 0` AND no structured block → render `PASS` (legacy, byte-identical to today).

2. **Findings section** below the table — rendered ONLY when at least one rc=0 provider has a parsed structured block. For each such provider (in `results` iteration order, per deepseek A1):
   ```
   ### glm — FIX (7.5, 1 blocking, 2 advisories)
   
   **Blocking:**
   - **Late-binding closure** at `scripts/foo.py:142-148` — Capture loop var via default arg
   - **Cross-cutting concern**  (no evidence cited)  — see review prose
   
   **Advisories:**
   - **Style nit**  at `scripts/foo.py:33`
   ```
   
   Rendering rules:
   - `fix` empty/missing → omit trailing ` — <fix>` to avoid dangling em-dash (per deepseek A2)
   - `evidence` empty → render bare title with `(no evidence cited)` annotation; no broken `at \`\`` markdown (per deepseek A3)
   - Provider with empty `blocking` + empty `advisories` (structured-but-clean) → render `### glm — PASS (9.2, 0 blocking, 0 advisories)` with no sub-sections (per deepseek A5)
   - rc != 0 providers → omitted from Findings entirely (their structured data is untrusted)
   - Providers with rc=0 but no structured block → omitted from Findings (Status column already shows their `PASS` state)

3. **Backwards-compat invariant** (round-1 glm A1, A7): when ALL providers are rc=0-with-no-structured-block, `synthesis.md` is **byte-identical** to today's output (no Findings section, table-only). Implementation: `write_synthesis` early-returns through the legacy path when `not any(parsed)` across all providers.

4. **Raw file I/O** (round-1 glm B1): `_safe_read_raw(path)` returns `str` or `None`. Catches `OSError` (file deleted between `cmd_review` and `write_synthesis`) and `UnicodeDecodeError` (corrupt bytes). On None → that provider falls through to legacy rendering (the parser is never called for that provider).

### Prompt addendum — v2 (code-side helper, not static template)

**Round-1 architectural pivot** (gemini blocker + codex B1 + glm B3): the v1 design embedded the addendum statically in `.agents/trinity.codex.json`'s `review.prompt_template`. That fails on task-type guard: ALL presets (review / tdd / prp / general) route through `cmd_review` → `render_prompt` → the same `review.prompt_template`. Non-review presets would receive the schema instructions inappropriately.

**v2 fix**: addendum lives in code, gated on effective task_type:

- New helper `_review_schema_addendum(task_type) -> str`: returns the addendum text when `task_type == "review"`, empty string otherwise.
- `render_prompt` signature extends to accept `task_type: str | None = None` param. Existing callers pass None (preserves current behavior — no addendum injected when task_type unknown).
- `cmd_review` extracts `task_type = preset_metadata.get("task_type")` from `resolve_review_providers`'s 2nd tuple element (already populated; just read it). Passes to `render_prompt`.
- `render_prompt` appends `_review_schema_addendum(task_type)` to the rendered prompt when non-empty.

`.agents/trinity.codex.json` `review.prompt_template` is NOT modified by this CHG. Custom user templates remain untouched. The addendum is invisible to non-review task types.

Addendum text (returned by `_review_schema_addendum("review")`):

```
## Required: Structured Output

After your free-form review, emit EXACTLY ONE fenced JSON block at the END of your
output, matching this schema:

\```json
{
  "decision": "PASS" | "FIX",
  "weighted_score": <0.0-10.0>,
  "blocking": [{"title": "...", "evidence": "file:line", "fix": "..."}],
  "advisories": [{"title": "...", "evidence": "file:line", "fix": "..."}],
  "confidence": <0.0-1.0, optional>
}
\```

Rules:
- "decision" MUST be "PASS" only when "blocking" is empty AND "weighted_score" >= 9.0.
  (If you write PASS while "blocking" is non-empty or score < 9.0, Trinity will
  display your provider as FIX — the consistency is enforced.)
- "blocking" and "advisories" are required lists (use [] if empty, not null).
- "evidence" is required per finding; use "" for cross-cutting issues.
- This block must be the LAST fenced ```json block in your output. Trinity scans
  for the last match. Earlier illustrative JSON in your prose is fine.
```

Note: the addendum's example uses `"PASS" | "FIX"` placeholder syntax — providers that lazily echo the example verbatim will fail validation (decision is the literal string `"PASS" | "FIX"`, not a value), and Trinity falls back to legacy. Per deepseek A9 + codex F-list, this is desired behavior.

### What's NOT in this CHG (deliberately deferred)

- **JSON Schema validator dependency** — the inline `_validate_review_schema` is sufficient and avoids adding `jsonschema` to setup (consistent with TRN-3020's choice).
- **Schema versioning** — no `schema_version` field for v1. If we ever bump the contract, do it then.
- **Cross-provider finding dedup / clustering** — interesting for #55 (richer summary) but out of scope here. This CHG just *makes findings parseable*; clustering is downstream.
- **Auto-merge / auto-release on PASS** — explicitly out per #39.
- **Forcing all providers to emit the schema** — explicitly out per #39 ("not requiring all providers to be perfectly compliant immediately"). Free-form remains valid forever.
- **Prompt-template variants per task_type** — the schema applies to `review` task_type only; tdd/prp/general task_types keep their existing templates. (Add task-type guard in implementation.)
- **Plain-text or YAML alternatives** — JSON in a fenced code block is the canonical and only schema. Future CHG can add alternatives if real need.

## Why

Issue #39 documents the gap: providers emit varied free-form output, synthesis can't compare PASS/FIX decisions structurally, and downstream consumers (the panel-review orchestrator, future panel-debate via TRN-3024 #63 MCP bridge) have nothing to programmatically read. A simple JSON contract — opt-in, additive, fall-back-friendly — closes the gap without breaking anything.

This is also a foundation move for issue #55 (richer summary): without normalized findings, #55 can only render free-form prose verbatim. With this CHG, #55 gets per-provider structured comparison rendering for free.

## Impact

### Surfaces touched

| # | Surface | Edit |
|---|----|----|
| 1 | `scripts/codex.py` | Add module constants `_REVIEW_PASS_THRESHOLD = 9.0` (shared between coercion logic and addendum text — per glm R2 A3) and `_STDERR_SENTINEL = "\n[stderr]\n"` (mirrors `raw_output` at codex.py:1391-1393 — coupling explicitly documented per glm R2 A6). Add helpers: `_strip_stderr_region(text)`, `_safe_read_raw(path)`, `parse_structured_review(raw_text)` (signature is **only** `(raw_text)` — no `returncode` kwarg; rc filtering happens in `write_synthesis` caller, per codex R2 A1 + glm R2 A1), `_validate_review_schema(data)`, `_review_schema_addendum(task_type)` helpers (~120 lines). Modify `write_synthesis` (line ~1689) for per-provider parsing + rc precedence + Findings section + byte-identical-on-all-legacy fallback (~70 lines). Modify `render_prompt` (line ~1218) signature to accept `task_type: str \| None = None` (default preserves existing callers). **Addendum placement (per glm R2 A2)**: in `render_prompt`, the addendum is appended to the FINAL assembled prompt — after both the `strict_review` block (when present) AND `REVIEW_ONLY_INSTRUCTION` AND `## Review Artifact` body — so the addendum's "LAST in your output" instruction sits literally at the bottom. Modify `cmd_review` (line ~1716) to extract `task_type` from `preset_metadata` and pass through. |
| 2 | (REMOVED in v2) | The v1 plan modified `.agents/trinity.codex.json`'s `review.prompt_template` statically. v2 moves the addendum into code (`_review_schema_addendum(task_type)` returns empty string for non-review task types), so the static template stays unchanged. Custom user templates also remain unchanged. |
| 3 | Provider docs (per codex R2 A4 — files pinned via grep) | Doc-only note about the structured-output schema. Pinned location: `providers/_base/family-wrapper.md` if it exists; otherwise add a short section to each direct-invocation provider doc (`providers/glm.md`, `providers/codex.md`, `providers/gemini.md`) referencing the schema. Implementation step: `git ls-files providers/_base/` to confirm `family-wrapper.md` exists before editing. (TRN-3020 §A3.f drift coverage applies — verify post-implementation.) |
| 4 | `tests/test_review_schema.py` (NEW) | ~25-30 unit tests covering: parser well-formed / malformed / no block / multiple blocks (last wins) / missing required / out-of-range score / unknown top-level key (forward-compat) / unknown finding-level key (forward-compat) / **stderr-side block ignored via sentinel split** / **rc != 0 input → caller ignores parsed result** / **decision="PASS"+blocking-non-empty coerced to effective_decision="FIX"** / decision="PASS"+score<9.0 coerced / lazy-LLM echo of literal `"PASS" \| "FIX"` placeholder rejected / fuzz-style random-bytes input never raises / `_safe_read_raw` returns None on OSError / `_safe_read_raw` returns None on UnicodeDecodeError / `_review_schema_addendum("review")` non-empty / `_review_schema_addendum("tdd")` empty / `_review_schema_addendum(None)` empty / synthesis byte-identical on all-legacy + all-rc-zero / synthesis Findings section omitted when only rc != 0 providers had structured blocks / Findings ordering matches results iteration / empty-fix renders without dangling em-dash / empty-evidence renders bare title with annotation. |
| 5 | `README.md` | Brief mention of the new structured output in the "Run a review" section (per TRN-1007 §1). |
| 6 | `CHANGELOG.md` | `[Unreleased]` `### Added` entry naming the schema + code-side addendum. |

Total: 1 new file, 4-5 modified. Net delta ~+200 lines (mostly tests + helper).

### Behavior change

| Pre-CHG | Post-CHG |
|---------|----------|
| Providers emit free-form prose; returncode determines PASS/FAIL | Same — free-form still valid; returncode fallback intact |
| Default prompt template asks for "PASS only if no blocking issues" but doesn't request structure | Default template appends structured-output addendum; providers may comply or not |
| Synthesis table: `Provider | Status (PASS/FAIL N) | Raw Output` | Same table, but Status enriched with score + blocking count when structured block present; new Findings section appears only when ≥1 provider emitted structured |
| `synthesis.md` content stable across runs | Still deterministic given identical raw inputs |

**Expected user-visible impact**: providers that follow the new prompt addendum produce richer synthesis. Providers that don't comply (older releases, custom prompts, partial responses) continue producing today's synthesis. Free-form output never breaks.

### CI impact

- New `test_review_schema.py` runs in `make test` (~25-30 unit tests per Surface 4 — count was inconsistent in v2; harmonized in v3).
- No CI workflow changes.

### Backwards compatibility

- Existing review directories: synthesis re-runs on them produce the same legacy output (no JSON block in raw → fall back).
- Custom `review.prompt_template` overrides: users who removed the structured addendum (or never had it) continue producing free-form reviews.
- The `results` dict shape passed to `write_synthesis` is unchanged — synthesis itself reads from `raw` files. So `cmd_review`'s metadata.json schema is unchanged.

### Rollback

Revert this PR. Synthesis reverts to today's PASS/FAIL-only table; the schema-emission addendum disappears from the **rendered review prompt** (the static `review.prompt_template` in `.agents/trinity.codex.json` is untouched by this CHG so there's nothing to revert there); providers stop being asked to emit structure (those that already comply will keep emitting; the parser just won't be there to read). Clean rollback.

## Acceptance Criteria (per TRN-1007)

| # | Check | How | TRN-1007 § |
|---|-------|-----|------------|
| A1 | `parse_structured_review` returns parsed dict on well-formed JSON block | Unit test | §2 |
| A2 | `parse_structured_review` returns `None` on malformed JSON, missing required field, out-of-range score, missing block | Unit tests | §2 |
| A3 | `parse_structured_review` picks the LAST JSON block when multiple are present | Unit test (illustrative example earlier in raw + canonical at end) | §2 |
| A4 | `parse_structured_review` is forward-compat: ignores unknown top-level keys | Unit test | §2 |
| A5 | Synthesis enriches Status column when structured block present (e.g., `PASS (9.2)`, `FIX (7.1, 2 blocking)`) | Unit test asserting rendered output | §2 |
| A6 | Synthesis renders "Findings" section only when at least one provider emitted structured | Unit test (mixed + all-legacy + all-structured cases) | §2 |
| A7 | Synthesis falls back to legacy table on all-legacy raw inputs (byte-identical to current output for the table portion) | Unit test pinning legacy snapshot | §2 |
| A8 | `_review_schema_addendum("review")` returns non-empty addendum text containing the schema fields; `_review_schema_addendum("tdd")` and `_review_schema_addendum(None)` return empty string | Unit test (per round-1 universal blocker — task-type guard moved code-side) | §2 |
| A8b | `.agents/trinity.codex.json` `review.prompt_template` is UNCHANGED by this CHG (no in-place modification — addendum lives in code) | Unit test asserting canonical template content | §2 |
| A8c | `render_prompt(..., task_type="review")` includes the addendum; `render_prompt(..., task_type=None)` and `render_prompt(..., task_type="tdd")` do not | Unit test | §2 |
| A8d | Parser strips stderr region: an `\n[stderr]\n` sentinel followed by a fenced JSON block on stderr does NOT win last-block-wins (round-1 codex B4 / glm B2) | Unit test | §2 |
| A8e | `write_synthesis` renders `FAIL <rc>` for rc != 0 providers regardless of any structured block in their raw (round-1 codex B2/B3 — returncode precedence) | Unit test (rc=1 + valid PASS schema → "FAIL 1"; rc=124 + valid PASS schema → "FAIL 124") | §2 |
| A8e2 | rc=124 timeout file containing a syntactically valid PASS schema → `parse_structured_review` returns dict (parser is rc-agnostic, per codex R2 A1) but `write_synthesis` IGNORES it and renders "FAIL 124" with no Findings entry for that provider (per glm R2 A5 explicit test) | Unit test | §2 |
| A8d2 | Parser regex matches MULTI-LINE JSON blocks (the canonical case): given a fenced ` ```json` block containing the **valid** schema example from §"Schema" lines 37-51 (real values: `"decision": "PASS"`, `"weighted_score": 9.2`, populated `blocking[]`/`advisories[]`, `"confidence": 0.85`) with newlines between fields, `parse_structured_review` returns the parsed dict. NOTE: do NOT use the addendum's placeholder example (lines 150-158) as the fixture — it contains literal placeholder syntax (`"PASS" \| "FIX"`, `<0.0-10.0>`) which A8h explicitly requires the parser to REJECT. The two test invariants would conflict on the same fixture (per codex round-3 catch). (Per **all 4** round-2 reviewers' B1/B7/NB1 — DOTALL flag missing in v2 spec; v3 uses `(?ims)`.) | Unit test feeding the §"Schema" valid example block | §2 |
| A8f | Effective-decision coercion: `decision="PASS"` + `blocking` non-empty → `effective_decision="FIX"` (and Status renders FIX, count visible). Same for score < 9.0 (round-1 codex B5) | Unit tests for both inconsistency cases | §2 |
| A8g | `_safe_read_raw(path)` returns None on OSError (file deleted) and on UnicodeDecodeError (corrupt bytes); caller falls through to legacy without raising (round-1 glm B1) | Unit tests | §2 |
| A8h | Lazy-LLM echo of the literal placeholder string `"PASS" | "FIX"` is rejected at validation → None → legacy fallback (round-1 deepseek A9 / codex F-list) | Unit test | §2 |
| A8i | `_REVIEW_PASS_THRESHOLD` constant is the single source of truth: (a) coercion uses it (decision="PASS" + score < `_REVIEW_PASS_THRESHOLD` → effective FIX); (b) addendum text generates the literal threshold from it (no hardcoded "9.0" string in the addendum source). Test substitutes the constant via monkeypatch and asserts both paths reflect the new value (round-3 codex advisory). | Unit test | §2 |
| A9 | Existing tests pass (`make test`, `make lint`, `make coverage` ≥ 80%, `af validate --root .`) | Local + CI | §2 |
| A10 | Manual smoke: a tiny review run on a fixed scope produces synthesis.md containing a Findings section if at least one provider complies; produces today's table-only output if none comply | Manual; documented in PR body | §5 |
| A11 | `README.md` "Run a review" section mentions the structured-output schema briefly | Manual review | §1 |
| A12 | `CHANGELOG.md` `[Unreleased]` `### Added` entry | Manual review | §1 |

### TRN-1007 dogfood mapping

- §1 README: ✅ A11
- §1 CHANGELOG: ✅ A12
- §1 SKILL/providers: ✅ providers/_base/family-wrapper.md doc tweak (Surface 3)
- §2 verification: ✅ A9
- §3 drift: ➖ N/A — no provider CLI changes; if Surface 3 changes prompt-related text, TRN-3020 A3.f covers verification
- §4 6-step methodology: applied during code-review
- §5 manual smoke: ✅ A10
- §6 identity: gh auth status → ryosaeba1985 (verified at PR-open)
- §7 branch hygiene: branch `codex/trn-3022-review-schema`; rebased on origin/main pre-push (per TRN-3021 R5 lesson — must verify against `origin/main` before R1 dispatch, not local main)

## Authority

Standalone single-slice CHG. Operator defaults: identity `ryosaeba1985`, branch `codex/trn-3022-review-schema`, plan-review and code-review via Trinity panel with **all active providers PASS individually at ≥9.0** gate.

Round-1+ panel composition: glm + gemini + deepseek + codex (4 providers; gemini's quota status will be checked by attempting; if it fails, fall back to 3-panel).

### Code-review prompt addendum (7-step methodology rule + PR #68 lessons)

From PR #60/#61/#64/#67/#68. Latest additions:

7. **Self-application check** — apply the new SOP/feature to itself; would it have caught its own omissions?
8. **(NEW after PR #68)** **`git status -uno` against `origin/main` before R1 dispatch** — PR #68 (TRN-3021) had deepseek correctly flag a "phantom TRN-1007 reference" 3 rounds in a row because the orchestrator's branch was created off stale local main. False-positive dismissal cost 2 panel rounds.
9. **(NEW after PR #68)** **Codex bot has been catching real semantic-correctness issues even after 4-provider panel approval** (auth-leak / overlap / display-mismatch / substring-trap on PR #68; 7 consecutive findings on PR #60). Plan should explicitly enumerate "what could go wrong post-merge that the panel might miss" — caller-flow / sibling-code / display-vs-exit consistency / value-handling-helper-mirrors / unverified-comment-invariants.

Specifically for THIS CHG:

- (1) caller flow: `cmd_review` → providers run, write `raw/<provider>.txt` → `write_synthesis(review_dir, scope, results)` → `parse_structured_review(raw_text)` per provider → enriched table + optional Findings section.
- (2) writer schema: `parse_structured_review` returns dict-or-None with explicit fields per spec; `_validate_review_schema` rejects malformed.
- (3) sibling sites: `cmd_status` reads `synthesis.md` for display — verify it doesn't break on the new sections (it just prints the file). `cmd_review`'s metadata.json schema is unchanged.
- (4) sibling helpers: any other place that parses provider raw output? `cmd_status`'s `_print_review_summary` reads `synthesis.md` and `metadata.json`; doesn't touch raw. No siblings to update.
- (5) comment-stated invariants: `parse_structured_review` docstring claims "never raises" — paired with a fuzz-style test feeding random bytes.
- (6) backwards-compat: existing `synthesis.md` shapes preserved when no structured block; `cmd_review` metadata.json schema unchanged.
- (7) self-application: would the new schema, applied to a Trinity panel review of THIS CHG, have caught issues like "the prompt template change might confuse providers running on cached/older prompt"? Probably no — that's a deployment concern, not a schema concern. Schema's self-application is moot.
- (8) `git status -uno` against `origin/main` before R1: VERIFIED — branch `codex/trn-3022-review-schema` is at `b003cc5` (== origin/main, post-PR-#68 merge); only tracked modification is `rules/TRN-0000-REF-Document-Index.md` (auto-regenerated by `af index`).
- (9) "what could go wrong post-merge": (a) provider emits malformed JSON → parser returns None, fallback works; (b) provider emits multiple JSON blocks → last wins; (c) provider's score is 11.0 → out-of-range → None; (d) provider emits the schema in the MIDDLE of output (not at end) → still parsed because we scan for last `^```json` block; (e) `write_synthesis` writes a file with absent provider — handled by per-provider iteration that defaults to legacy on None.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-08 | Initial draft per COR-1616 step 3, with PR #60/#61/#64/#67/#68 9-step methodology rule embedded (PR #68 added steps 8 and 9: git-status-vs-origin-main check + post-merge-failure-mode enumeration). Tight scope: schema, parser, synthesis enrichment, opt-in prompt addendum. Deferred: JSON Schema dep, schema versioning, dedup/clustering, task-type variants. | Claude Opus 4.7 |
| 2026-05-08 | **Status**: Proposed → Approved. Plan-review round 4 (codex-only re-dispatch): codex **9.2 PASS** (was 8.8). All 4 R3 findings RESOLVED with line citations. 5 R4 advisories noted for code-review (numeric-bool rejection test, Markdown sanitization for title/evidence/fix, raw-path resolution test, "6-step" → "9-step" wording, "WILL DO" → "verified"). All 4 panel members now PASS individually at ≥9.0: gemini 9.5 (R2), codex 9.2 (R4), glm 9.2 (R2), deepseek 9.10 (R2). Mean **9.255**. Gate met after 4 plan-review rounds. Ready to implement. | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 3 (codex-only re-dispatch — gemini 9.5 / glm 9.2 / deepseek 9.10 already PASSed conditional on DOTALL fix): codex 8.8 FAIL (was 8.2; ALL 5 R2 blockers RESOLVED, but 1 NEW catch — A8d2 vs A8h fixture conflict: A8d2 said "feed addendum's example" but addendum example uses placeholder syntax that A8h requires parser to REJECT). Round-4 fixes: (1) A8d2 repointed to §"Schema" valid example (lines 37-51) with explicit NOTE not to use the placeholder example; (2) Rollback wording fixed: "rendered review prompt" not "default prompt template" (template is untouched by CHG); (3) Test count harmonized: ~25-30 in both Surface 4 and CI Impact section; (4) New A8i: `_REVIEW_PASS_THRESHOLD` constant single-source-of-truth test (coercion + addendum both use it, no hardcoded literal in addendum text). | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 2 (4-provider panel re-dispatch): all 4 caught **the same regex DOTALL bug** (gemini B1, codex B7, deepseek B1, glm NB1) — `(?im)` lacks `s` flag so `(.*?)` can't span newlines → parser silently fails on every multi-line JSON block (i.e., every realistic schema emission). One-character fix: `(?ims)`. Plus all R1 blockers from R1 (3-of-4 FAILed) confirmed RESOLVED by all reviewers individually with line citations. Round-2 scores: gemini 9.5 PASS-with-blocker, glm 9.2 PASS, deepseek 9.10 PASS, codex 8.2 FAIL. **Round 3 fixes** (all CHG-text only — no architectural change): (1) regex flag `(?im)` → `(?ims)` in parsing rules step 2; (2) parser signature drift — `parse_structured_review(raw_text)` only, drop `*, returncode` kwarg from Surface 1 (rc filtering belongs in `write_synthesis` caller); (3) addendum placement explicit — appended AFTER strict_review block + REVIEW_ONLY_INSTRUCTION + ## Review Artifact body so "LAST in your output" instruction is truly last in the rendered prompt (glm R2 A2); (4) `_REVIEW_PASS_THRESHOLD = 9.0` shared constant between coercion logic and addendum text (glm R2 A3); (5) `_STDERR_SENTINEL` constant explicitly couples to `raw_output` at codex.py:1391-1393 (glm R2 A6); (6) Surface 3 file pinned via grep (codex R2 A4); (7) custom-template behavior: code-side addendum applies regardless of `prompt_template` customization (codex R2 A2 — limitation acknowledged; opt-out via setting non-review task_type, future config flag deferred); (8) end-of-output vs last-block-wins: prompt instruction says "LAST" (provider-facing), parser uses last-block-wins (lenient on misbehaving — per codex R2 A3, different concerns); (9) new ACs A8d2 (multi-line regex test), A8e2 (rc=124 + valid JSON → FAIL 124 explicit). | Claude Opus 4.7 |
| 2026-05-08 | Plan-review round 1 (4-provider panel): deepseek 9.16 PASS, gemini 8.7 PASS-with-blocker, glm 8.7 FAIL, **codex 7.4 FAIL** (mean 8.49). 3-of-4 caught structural / semantic blockers. **Round 2 substantial rewrite** addressing 6 cross-confirmed concerns: (1) **Task-type guard structurally impossible** (gemini/codex/glm) — `render_prompt` had no `task_type` param; static template would leak into TDD/PRP/general. Fix: extend `render_prompt` signature to accept `task_type`; addendum moves from static template into a code-side helper `_review_schema_addendum(task_type)` returning empty for non-review. `.agents/trinity.codex.json` is now UNCHANGED. (2) **stderr-side JSON breaks last-block-wins** (codex B4 / glm B2) — `raw_output` writes `<stdout>\n[stderr]\n<stderr>`. Fix: parser splits on the sentinel and scans only pre-sentinel region. (3) **Returncode precedence undefined** (codex B2) — synthesis could lie about CLI exit. Fix: rc != 0 → `FAIL <rc>` regardless of structured; only rc=0 providers get structured rendering. (4) **rc=124 timeout partial output is dangerous** (codex B3) — partial output may contain valid JSON but review didn't complete. Fix: parsed result IGNORED for rendering when rc != 0. Findings section excludes non-zero-rc providers. (5) **decision="PASS" + blocking non-empty / score < 9.0** logical inconsistency (codex B5). Fix: validator coerces `effective_decision = "FIX"`; original `decision` preserved for diagnostics; display uses `effective_decision`. (6) **`write_synthesis` I/O contract widening** (glm B1) — function reads raw files. Fix: `_safe_read_raw(path)` returns text-or-None on OSError/UnicodeDecodeError. (7) **Required-vs-default contradiction** (codex B6). Fix: removed "Default if missing" column for required fields; clarified parser-layer vs synthesis-layer fallback semantics. Plus advisories adopted: deepseek A1 (Findings ordering = results iteration order), A2 (empty-fix omits em-dash), A3 (empty-evidence renders bare title), A4 (strict regex `^```json\s*$ ... ^```\s*$`, lang tag REQUIRED), A8 (forward-compat extends to finding-level keys), A9 (literal placeholder echo rejected). New ACs A8/A8b–A8h cover the architectural fixes. | Claude Opus 4.7 |

# PRP-2010: Codex Review Adapter

**Applies to:** Trinity project (`frankyxhl/trinity`)
**Last updated:** 2026-05-04
**Last reviewed:** 2026-05-04
**Status:** Approved
**Reviewed by:** User-approved COR-1202 plan in Codex session; implementation remains subject to tests, lint, `af validate`, and draft PR review.
**Related:** TRN-1000, TRN-1005, TRN-1006, TRN-2011

---

## What Is It?

Add a Codex-native adapter layer for Trinity that lets Codex use Trinity review flows without Claude Code's background Agent runtime. The adapter installs a Codex skill, writes a Codex-specific provider config, and exposes a local `trinity review` wrapper that calls provider CLIs directly.

---

## Problem

The existing Trinity root skill is a Claude Code adapter. It discovers `~/.claude/trinity.json`, requires `~/.claude/agents/trinity-<provider>.md`, and dispatches work through Claude's Agent tool. Codex can read those files manually, but it cannot use that runtime contract directly.

Trinity already has Codex packaging for skill/plugin importability, but the package lacks the practical local path the user needs:

- `~/.codex/skills/trinity/SKILL.md` installation from the repo-local Codex skill
- a Codex-owned provider config independent of `~/.claude/trinity.json`
- a direct CLI wrapper for `glm`, `gemini`, and `deepseek` code reviews
- regression tests proving Claude Code installation and runtime docs remain compatible

---

## Scope

**In scope (v1):**
- Add `.agents/trinity.codex.json` as the committed default Codex config.
- Add `scripts/codex.py` with a `review` subcommand.
- Add `bin/trinity` and `make install-codex` so this machine gets a `trinity review ...` command.
- Collect tracked and untracked git changes into a review prompt, including changed file snapshots.
- Save `prompt.md`, raw provider outputs, metadata, and a deterministic `synthesis.md`.
- Add TDD tests for Codex config, wrapper behavior, install behavior, and Claude Code compatibility.
- Document Codex usage and the Claude/Codex host boundary.

**Out of scope (v1):**
- Replacing Claude Code `/trinity` dispatch.
- Changing root `SKILL.md` from Claude Agent runtime semantics.
- Changing `install.sh` remote Claude installer behavior.
- Running real provider reviews in tests.
- Adding OpenRouter to the Codex review default set.

---

## Proposed Solution

### Codex Config

Create `.agents/trinity.codex.json`:

```json
{
  "providers": {
    "glm": {
      "cli": "droid exec --model glm-5",
      "supports_resume": true,
      "resume_arg": "-s",
      "timeout": 360
    },
    "gemini": {
      "cli": "gemini --model gemini-3.1-pro-preview -p",
      "supports_resume": true,
      "resume_arg": "-r",
      "timeout": 360
    },
    "deepseek": {
      "cli": "droid exec --model deepseek-v4-pro[1m]",
      "supports_resume": true,
      "resume_arg": "-s",
      "timeout": 600
    }
  },
  "review": {
    "default_providers": ["glm", "gemini", "deepseek"],
    "output_dir": ".trinity/reviews",
    "prompt_template": "..."
  }
}
```

The bracket suffix in `deepseek-v4-pro[1m]` follows TRN-1006 and must be passed as an argv element, not through an unquoted shell string.

### Wrapper Command

Install `bin/trinity` to `~/.local/bin/trinity`. The wrapper calls:

```bash
python3 ~/.codex/skills/trinity/scripts/codex.py "$@"
```

Primary v1 usage:

```bash
trinity review --providers glm,gemini,deepseek --scope spikes/hardline
```

### Review Behavior

`scripts/codex.py review`:

1. Resolve repo root.
2. Load `~/.codex/trinity.json`, with explicit `--config` override for tests.
3. Collect `git diff HEAD` for tracked changes.
4. Add synthetic diffs and full snapshots for untracked files.
5. Include full snapshots for changed text files.
6. Render the review prompt from the config template.
7. Invoke each selected provider CLI directly with the prompt as the final argv element.
8. Write raw outputs under `raw/<provider>.txt`.
9. Write `synthesis.md` summarizing provider status and linking raw outputs.

No Claude Agent files or `Agent(...)` runtime are required for this path.

---

## Open Questions

1. None blocking for v1. Real provider command tuning can be adjusted after draft PR review if a provider CLI needs a different prompt argument convention.

---

## Implementation Plan

1. Add RED tests for Codex config, wrapper behavior, installation, and Claude compatibility.
2. Implement `.agents/trinity.codex.json`, `scripts/codex.py`, `bin/trinity`, and `make install-codex`.
3. Update README and Codex skill documentation.
4. Run `make test`, `make lint`, `af validate --root .`, and install/smoke checks.
5. Commit, push a branch, and open a draft PR.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-05-04 | Initial approved proposal for Codex-native review adapter | Codex |

---
name: trinity
description: Codex adapter for Trinity multi-model orchestration. Use when the user says /trinity or $trinity in Codex, asks to import Trinity into Codex, or wants to delegate work through Trinity while preserving Claude Code compatibility.
---

# Trinity for Codex

Use this skill when working with Trinity from Codex. Trinity is a multi-model orchestration package that also supports Claude Code through the root `SKILL.md`; this file is the Codex-specific adapter. The repo-local copy lives at `.agents/skills/trinity`, and the plugin-bundled copy lives at `plugins/trinity/skills/trinity`.

## Commands

Support the same user-facing command family as the Claude Code adapter:

```text
/trinity status
/trinity help
/trinity clear [<instance> | all]
/trinity <provider>[:<instance>] "<task>"
/trinity <provider>*N "<task>"
/trinity plan ...
```

Also treat `$trinity` as an explicit Codex skill invocation.

For Codex-native code review from the terminal, use the installed wrapper:

```bash
trinity doctor --providers glm,gemini,deepseek
trinity doctor --preset fast-review
trinity review --providers glm,gemini,deepseek --scope <path-or-label>
trinity review --preset fast-review --scope <path-or-label>
trinity review --preset dr --scope <path-or-label>
trinity review --base main --head HEAD --providers glm,deepseek
trinity review --pr 21 --preset deep-review
trinity review --sop COR-1602 --rubric COR-1609 --scope <path-or-label>
trinity review --sop COR-1602 --rubric COR-1609 --base main --head HEAD --preset fast-review
trinity review --sop COR-1602 --rubric COR-1609 --pr 21 --preset deep-review
```

The wrapper loads `~/.codex/trinity.json`, whose repo default lives at
`.agents/trinity.codex.json`. It calls provider CLIs directly, saves raw outputs,
and writes a deterministic synthesis markdown under `.trinity/reviews/`.
Review providers run concurrently up to `review.max_parallel_providers`
(default: selected provider count). Progress is written to stderr; stdout
remains the review directory path. Interrupted reviews that cannot write final
metadata and synthesis are marked with `incomplete.json` in the review
directory.
The review preset resolver selects providers from explicit `--providers`,
explicit `--preset`, `review.default_preset`, then legacy
`review.default_providers`. `review` expands to `glm`, `gemini`, and
`deepseek`; `fast-review` expands to `glm` and `deepseek`; `deep-review`
expands to `glm`, `gemini`, and `deepseek`. Aliases `r`, `fr`, and `dr` resolve
to those preset names. Optional providers are skipped with stderr warnings when
they lack config or a CLI, and skipped providers are recorded in
`metadata.json`.
`trinity doctor` and `trinity review --check-providers` validate provider config,
command lookup, executable permissions, and timeout values without making network
calls. Use the default review mode for dirty working-tree changes, `--base` /
`--head` for committed branch reviews, and `--pr` for GitHub PR reviews.
Pair `--sop` and `--rubric` for strict COR review mode. The first supported
strict template is `COR-1602` with `COR-1609`; it asks reviewers for findings,
a decision matrix, weighted average, and PASS/FIX, then records the selected
SOP/rubric metadata in `metadata.json`.

## Host Boundary

- The root `SKILL.md` remains the Claude Code adapter and continues to use `~/.claude/` files.
- This Codex adapter must load successfully without requiring Claude Code worker-agent files.
- Do not depend on Claude-specific background worker instructions when checking skill/plugin importability or when running `trinity review`.
- Preserve existing Trinity provider files and installers unless the user explicitly asks to change Claude behavior.

## Codex Workflow

1. Read the user's `/trinity` or `$trinity` request.
2. Inspect the repo first: `README.md`, root `SKILL.md`, `scripts/`, `providers/`, and tests as needed.
3. For status/help/import questions, answer directly from repo files and the Codex package files.
4. For implementation work, follow the repo's `af` routing docs and use TDD.
5. For code-review requests from Codex, prefer `trinity review` when the local adapter is installed; it does not require Claude-specific background worker files.
6. For delegation requests, use Codex-native delegation only when the user explicitly requests background or parallel agent work and the current Codex environment exposes that capability.

## Verification

For Codex load verification, use these smoke checks after changes are installed or committed:

- Repo-local skill: restart/start Codex in this repository, open `/skills` or invoke `$trinity`, and confirm `trinity` is visible/loadable.
- Plugin package: restart Codex, open `/plugins`, select the repo marketplace, and confirm the `trinity` plugin appears and exposes its bundled skill.
- Local wrapper: run `make install-codex`, then `trinity --version`,
  `trinity doctor --providers glm,gemini,deepseek`, and a mocked or low-risk
  `trinity review --providers glm,gemini,deepseek --scope <path>`.

For Claude Code regression verification, keep using the existing Claude checks: install Trinity, restart Claude Code, and run `/trinity status`.

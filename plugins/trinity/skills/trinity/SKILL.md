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

## Host Boundary

- The root `SKILL.md` remains the Claude Code adapter and continues to use `~/.claude/` files.
- This Codex adapter must load successfully without requiring Claude Code worker-agent files.
- Do not depend on Claude-specific background worker instructions when only checking skill/plugin importability.
- Preserve existing Trinity provider files and installers unless the user explicitly asks to change Claude behavior.

## Codex Workflow

1. Read the user's `/trinity` or `$trinity` request.
2. Inspect the repo first: `README.md`, root `SKILL.md`, `scripts/`, `providers/`, and tests as needed.
3. For status/help/import questions, answer directly from repo files and the Codex package files.
4. For implementation work, follow the repo's `af` routing docs and use TDD.
5. For delegation requests, use Codex-native delegation only when the user explicitly requests background or parallel agent work and the current Codex environment exposes that capability.

## Verification

For Codex load verification, use these smoke checks after changes are installed or committed:

- Repo-local skill: restart/start Codex in this repository, open `/skills` or invoke `$trinity`, and confirm `trinity` is visible/loadable.
- Plugin package: restart Codex, open `/plugins`, select the repo marketplace, and confirm the `trinity` plugin appears and exposes its bundled skill.

For Claude Code regression verification, keep using the existing Claude checks: install Trinity, restart Claude Code, and run `/trinity status`.

## Architecture

```
~/.claude/trinity.json          ← global providers, presets, defaults
.claude/trinity.json            ← project sessions + local overrides

~/.claude/skills/trinity/
  SKILL.md                      ← Trinity skill (Claude reads this)
  scripts/                      ← session, config, discover, install helpers
  bin/                          ← deepseek, openrouter, claude-code wrappers

~/.claude/agents/
  trinity-glm.md                ← GLM worker agent
  trinity-minimax.md            ← MiniMax M3 worker agent
  trinity-codex.md              ← Codex worker agent
  trinity-gemini.md             ← Gemini worker agent
  trinity-deepseek.md           ← DeepSeek (Anthropic-compat wrapper)
  trinity-openrouter.md         ← OpenRouter (Anthropic-compat wrapper)
  trinity-claude-code.md        ← isolated nested Claude Code
  trinity-<custom>.md           ← your custom providers
```

**Dispatch flow:**
1. `/trinity <provider> "task"` → Trinity skill (SKILL.md) receives the command
2. Provider discovery: loads `~/.claude/trinity.json` + `.claude/trinity.json`, resolves presets/aliases, verifies agent files
3. Spawns `Agent(subagent_type="general-purpose", run_in_background=true)` pointing to `trinity-<provider>.md`
4. Agent reads instructions from its template, invokes the provider's CLI (`droid exec`, `codex exec`, `gemini -p`, or a wrapper from `bin/`), and manages sessions in `.claude/trinity.json`
5. Agent returns a structured summary when done
6. Trinity captures `output_file` path from the Agent response for health monitoring

**Key design decisions:**
- No tmux, no daemons — pure CLI via Claude's Agent tool
- No external dependencies — works anywhere Claude Code runs
- Provider discovery — new providers added without editing SKILL.md
- Config overlay — global defaults + project overrides
- File locking — `fcntl.flock` prevents concurrent write corruption

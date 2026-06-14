## Troubleshooting

**Provider shows "⚠️ unregistered (missing agent file)"**
The config entry exists but no agent file found. Run `/trinity install <provider>` or copy the agent file manually to `~/.claude/agents/trinity-<provider>.md`.

**Provider shows "⚠️ unregistered (missing config)"**
Agent file exists but no config entry. Add the provider to `~/.claude/trinity.json` under `providers`.

**Agent shows "❌ failed to start" after 30s**
The background agent never wrote to its output file. Check that the CLI tool is installed and authenticated. Run `/trinity install <provider>` to re-verify.

**Session resume fails**
If a session ID has expired, the agent automatically discards it and starts fresh. Use `/trinity clear <provider>` to clean up the stale entry.

**Concurrent writes corrupt trinity.json**
Should not happen — agents use `fcntl.flock`. If it does, inspect the file and repair it manually, then run `/trinity clear all` to start fresh.

**`.claude/` directory doesn't exist**
Trinity creates it automatically on first dispatch. If permission errors occur, run:
```bash
mkdir -p .claude && echo '{}' > .claude/trinity.json
```

## Session Management

Session store location: `<project_dir>/.claude/trinity.json` (under the `sessions` key)

### Reading sessions
```bash
SESSION_ID=$(python3 ~/.claude/skills/trinity/scripts/session.py read "$PROJECT_DIR" "$INSTANCE_KEY")
```
- Returns "NEW" if no existing session.

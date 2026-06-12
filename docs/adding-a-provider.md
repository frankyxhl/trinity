## Adding a Provider

1. **Create an agent file** following the pattern of existing providers:
   ```bash
   cp trinity/providers/glm.md ~/.claude/agents/trinity-myprovider.md
   # Edit: update name, CLI command, session management for your provider's CLI
   ```

2. **Register in config** (`~/.claude/trinity.json` or `.claude/trinity.json`):
   ```json
   {
     "providers": {
       "myprovider": { "cli": "myprovider-cli", "installed": true }
     }
   }
   ```

3. **Test:**
   ```
   /trinity status             # verify provider shows ✅ usable
   /trinity myprovider "hello" # smoke test
   ```

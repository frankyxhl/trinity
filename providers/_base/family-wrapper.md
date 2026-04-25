### Race-safe session file selection

`claude -p` (used by anthropic_cli wrappers) does NOT emit response text to stdout. The response must be read from the session JSONL file under `${SESSION_DIR}/<session_id>.jsonl`.

Picking the right file under concurrent same-project dispatches is the tricky part. Picking by mtime alone is unsafe (TRINITY-2004 bundled fix #2): two simultaneous calls in the same project can grab each other's session. Instead, snapshot mtimes before the call and select files whose mtime advanced past the snapshot:

```bash
# 1) Snapshot mtime of every existing session file BEFORE the call.
declare -A PRECALL_MTIME
if compgen -G "${SESSION_DIR}"/*.jsonl > /dev/null; then
  while IFS= read -r f; do
    PRECALL_MTIME["$f"]=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
  done < <(ls "${SESSION_DIR}"/*.jsonl)
fi
TRINITY_CALL_START=$(date +%s)

# 2) Run the CLI call here (provider-specific).

# 3) Pick the file that's NEW or whose mtime advanced past TRINITY_CALL_START.
JSONL=""
JSONL_MTIME=0
for f in "${SESSION_DIR}"/*.jsonl; do
  [ -e "$f" ] || continue
  m=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
  prev="${PRECALL_MTIME[$f]:-0}"
  if [ "$m" -ge "$TRINITY_CALL_START" ] && [ "$m" -gt "$prev" ]; then
    if [ "$m" -gt "$JSONL_MTIME" ]; then
      JSONL="$f"
      JSONL_MTIME="$m"
    fi
  fi
done
if [ -z "$JSONL" ]; then
  echo "ERROR: no new/updated session file found after call" >&2
  exit 1
fi
SESSION_ID=$(basename "$JSONL" .jsonl)
```

For resumed sessions the JSONL path is already known — read the same file directly:
```bash
JSONL="${SESSION_DIR}/${SESSION_ID}.jsonl"
```

### Extracting the response

Skips malformed lines, thinking blocks, and non-text content; returns the most recent assistant text turn:
```bash
RESPONSE=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    for line in reversed(f.readlines()):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get('type') != 'assistant':
            continue
        msg = d.get('message')
        if not isinstance(msg, dict):
            continue
        texts = []
        for c in (msg.get('content') or []):
            if isinstance(c, dict) and c.get('type') == 'text':
                texts.append(c.get('text', ''))
        if texts:
            print('\n'.join(texts))
            break
" "$JSONL")
```

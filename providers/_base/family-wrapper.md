### Race-safe session file selection

`claude -p` (used by anthropic_cli wrappers) does NOT emit response text to stdout. The response must be read from the session JSONL file under `${SESSION_DIR}/<session_id>.jsonl`.

Picking the right file under concurrent same-project dispatches is the tricky part. Mtime alone is unsafe (TRINITY-2004 bundled fix #2): two simultaneous calls in the same wall-clock second produce JSONL files with identical mtimes, defeating any "newest file" heuristic. Macos APFS and Linux ext4 commonly only expose 1-second mtime resolution.

**Solution: inject a unique trace marker into the prompt and grep the JSONL for it.** This works with bash 3.2+ (no associative arrays), is robust under any concurrency, and survives sub-second collisions.

```bash
# 1) Generate a unique trace ID for this call.
TRINITY_TRACE="trinity-trace-$$-${RANDOM}-$(date +%s)"

# 2) Embed the marker as an HTML comment at the top of the prompt.
#    Anthropic CLI passes the prompt verbatim; the comment lands in the
#    JSONL as part of the user message and is invisible to the model's output.
MARKED_PROMPT=$(printf '<!-- %s -->\n%s' "$TRINITY_TRACE" "$PROMPT")

# 3) Run the CLI call with $MARKED_PROMPT (provider-specific).

# 4) After the call: find the JSONL file that contains the trace marker.
JSONL=""
for f in "${SESSION_DIR}"/*.jsonl; do
  [ -e "$f" ] || continue
  if grep -q "$TRINITY_TRACE" "$f" 2>/dev/null; then
    JSONL="$f"
    break
  fi
done
if [ -z "$JSONL" ]; then
  echo "ERROR: no session file containing trace marker $TRINITY_TRACE found" >&2
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

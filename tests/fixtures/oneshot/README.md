Recorded 2026-10-20 from codex-cli 0.162.1 and opencode 1.19.0; no secrets.
codex-new.jsonl / codex-new-last.txt: `codex exec -m gpt-6-astra -s read-only --json -o` (rc 0).
codex-resume.jsonl: `codex exec -s read-only resume … <thread> "…"` (rc 0, same thread id).
codex-bad-resume.*: resume of an unknown id (rc 1, no stdout).
codex-rollout-excerpt.jsonl: session_meta + turn_context lines of the new session's rollout, cut to the fields the readback uses.
opencode-new.jsonl: `opencode run --format json -m opencode-go/deepseek-v4.1-flash --dir …` (rc 0).
opencode-resume.jsonl: same with `-s <id>` (rc 0).
opencode-bad-model.jsonl: `-m opencode-go/no-such-model` (rc 1).
opencode-permission-rejected.*: asked to write outside --dir; run mode auto-rejected the permission (rc 0, last step_finish reason tool-calls).
opencode-bad-session.stderr.txt: `-s` with an unknown id (rc 1, no stdout).
opencode-session-rows.json: the session table rows (id, model JSON) for the new session and the bad-model session.
opencode-models.txt: deepseek lines of `opencode models`.

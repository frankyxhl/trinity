## Command Reference

```
/trinity <provider>[:<instance>] "task"          # single dispatch
/trinity <p1>[:<i>] "t1" <p2> "t2"              # multi-provider parallel
/trinity <provider>*N "task"                     # N parallel same-provider
/trinity <preset> "task"                         # dispatch to a preset's provider set
/trinity plan <p1> "t1" <p2> "t2"               # plan with diagram, confirm, execute
/trinity plan "high-level description"           # auto-decompose, confirm, execute
/trinity install <provider>                      # install + register provider
/trinity status                                  # registered providers + presets + sessions
/trinity heartbeat [<instance>]                  # on-demand liveness check
/trinity clear [<instance> | all]                # clear sessions
/trinity help                                    # show this README
```

Reserved subcommands (cannot be used as provider, preset, or alias names):
`status`, `clear`, `plan`, `heartbeat`, `install`, `help`.

Built-in presets (when configured): `review`, `fast-review`, `deep-review`,
with aliases `r`, `fr`, `dr`. See [Review presets](usage-guide.md#review-presets).

## Terminal: trinity call

Run one one-shot model call through the dispatch core. The call is journaled,
and the result line is printed as one JSON object.

```
bin/trinity call --profiles <profiles.json> --profile <name> --step <label>
                 (--prompt "<text>" | --prompt-file <path> ...) [options]
```

| Flag | Meaning | Contract |
| --- | --- | --- |
| `--profiles PATH` | Path to the profiles JSON file. | — |
| `--profile NAME` | Profile to run. | DSP-006 |
| `--step LABEL` | Step label for the node. | DSP-017 |
| `--session ID` | Continue this session instead of starting a new one. | DSP-020, ONE-023 |
| `--prompt TEXT` | Prompt text. Mutually exclusive with `--prompt-file`; exactly one form is required. | ONE-010 |
| `--prompt-file PATH` | Read the prompt from a UTF-8 file. Repeatable; files are joined in the given order with nothing added between them. A missing or unreadable file refuses the call (`bad_request`, nothing written). | ONE-010 |
| `--output PATH` | After the call, `PATH` holds the final answer text. The result line then has `output_kind: "file"` and `output_ref` set to the absolute path. When there is no final answer the file is not created. The answer text never enters the journal. | ONE-011 |
| `--log-dir DIR` | Created if missing; the call writes its log files there (see below). | ONE-012 |
| `--time-s N` | Time limit in seconds; a positive number, else `bad_request`. When it is reached the process group is killed and the call ends `timeout`. | ONE-013, ADP-009 |
| `--gate none\|light\|heavy` | Memory gate for this call; overrides the profile's `gate`. | ONE-014, ONE-061 |
| `--model M` | Model for this call; overrides the profile's `model`. The node record reports the model actually passed to the harness. | ONE-015 |
| `--cwd PATH` | Working directory for the call. | — |
| `--allow-nesting-max-depth N` | Allow the call to nest dispatch up to this depth. | DSP-015 |

Adapters:

```json
{
  "profiles": [
    {
      "name": "cx",
      "adapter": "codex",
      "provider": "codex",
      "billing": "subscription",
      "enabled": true,
      "model": "gpt-6-astra",
      "sandbox": "read-only",
      "codex_home": "~/.codex-cx"
    }
  ]
}
```

```json
{
  "profiles": [
    {
      "name": "oc",
      "adapter": "opencode",
      "provider": "opencode",
      "billing": "subscription",
      "enabled": true,
      "model": "opencode-go/deepseek-v4.1-flash",
      "opencode_config": "~/.config/opencode/opencode.json"
    }
  ]
}
```

Optional fields: `effort` (`none|low|medium|high|xhigh`, codex only), `variant`
(opencode only), `binary` (default: the adapter's CLI on `PATH`), `env_pass`
(list of extra environment variable names to pass to the harness), `gate`.

Files `--log-dir` writes (ONE-012): `start` and `end` (Unix seconds), `rc.txt`
(`rc=<harness exit code>`, or `rc=none` when no harness process started),
`out.jsonl` (the child's stdout), `err.txt` (the child's stderr) and, when a
gate ran, `gate.txt` (the latest gate reading, one line
`gate=<g> level=<n> free=<pct> swap_mb=<n> load5=<x> decision=<d>`). Every line
of `out.jsonl` and `err.txt` passes through the journal redaction before it is
written. Every file is mode 600.

The gate (ONE-060–065): `light` passes when the memory pressure level is 2 or
lower and the 5-minute load is under 30. `heavy` passes when the pressure level
is 1, free memory is at least 40 %, and swap used is under 1800 MB. While the
gate says wait, the call re-reads every `TRINITY_GATE_POLL_S` seconds (default
20) and writes a check line when the decision changes. Waiting counts against
`--time-s`; when the time is used up the call ends `timeout` and no harness
starts — a reading that says go with no time left is the same stop. A reading
that cannot be taken refuses the call with `check_failed`.

Two things to know:

- Inside a Codex sandbox the memory readings (`sysctl`) are denied. A gated
  call made from inside a sandboxed Codex run is therefore refused with
  `check_failed`; use `--gate none` there.
- `heavy` compares swap used against a fixed 1800 MB. On a host whose swap
  stays high after memory frees up, a `heavy` call waits until `--time-s` runs
  out.

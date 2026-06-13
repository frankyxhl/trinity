## Codex Compatibility

Trinity also ships a Codex adapter that adds a terminal `trinity` command for
multi-provider code review. It does not change the Claude Code install path.

### Install

From a cloned repo:

```bash
make install-codex
```

| Location | Contents |
|----------|----------|
| `~/.codex/skills/trinity/SKILL.md`           | Codex-specific Trinity skill |
| `~/.codex/skills/trinity/scripts/`           | Shared scripts + Codex wrapper |
| `~/.codex/skills/trinity/bin/deepseek`       | DeepSeek Anthropic-compat wrapper |
| `~/.codex/skills/trinity/trinity.codex.json` | Bundled default Codex config |
| `~/.codex/trinity.json`                      | User-level Codex provider config |
| `~/.local/bin/trinity`                       | Terminal wrapper |

The default config (`.agents/trinity.codex.json`) registers `glm`, `gemini`,
and `deepseek` for direct CLI review and seeds the `review` / `fast-review` /
`deep-review` presets (with `r` / `fr` / `dr` aliases) — same set documented
under [Review presets](usage-guide.md#review-presets). `trinity review` chooses
providers in this order: explicit `--providers`, explicit `--preset`,
`review.default_preset`, then legacy `review.default_providers`.

### Provider health

```bash
trinity doctor --providers glm,gemini,deepseek
trinity doctor --preset fast-review
trinity review --check-providers --preset dr
```

Health checks validate config shape, CLI lookup, executable permissions,
timeouts, **wrapper-provider auth files** (env-or-file precedence with mode
600/400 check, mirroring `providers/bin/<wrapper>` behavior), **timeout
sanity** (warns if `< 60s`), **shell env pollution** (lists vars matching
the TRN-3023 spawn-time clearlist — `*_BASE_URL`, `OTEL_*`, etc. — so
operators can audit their `direnv` / shell setup), and the resolved CLI
string per provider. Output now splits **REQUIRED** vs **OPTIONAL** providers
(driven by the active preset's metadata); REQUIRED-provider auth issues are
fatal (exit 1), OPTIONAL-provider issues are demoted to warnings (exit 0).
The first line per provider stays `{provider}: OK - {executable} (timeout Ns)`
so existing `grep` patterns continue to work.

Doctor still does not call the provider, so API-key or quota errors can
still surface during an actual review.

### Live probe

```bash
trinity doctor --live --providers glm,gemini,deepseek
trinity doctor --live --preset fast-review
```

With `--live`, doctor runs a minimal "reply OK" prompt against each
statically-healthy provider with a short (10s) timeout. Failures are
classified as **auth**, **quota**, **timeout**, or **error**. REQUIRED
providers with live failures exit 1; OPTIONAL provider failures are
demoted to warnings (exit 0), matching the existing static-check
semantics. The first line per provider stays grep-compatible; live
results appear as additional lines in verbose output.

### Run a review

```bash
trinity review --providers glm,gemini,deepseek --scope spikes/hardline
trinity review --preset fast-review --scope spikes/hardline
trinity review --preset dr --scope .
trinity review --base main --head HEAD --providers glm,deepseek
trinity review --pr 21 --preset deep-review
trinity review --sop COR-1602 --rubric COR-1609 --pr 21 --preset deep-review
```

Scope modes:

- **default** — tracked + untracked working-tree changes
- `--base/--head` — committed branch diff (`git diff base...head`) + head snapshot
- `--pr <n>` — `gh pr view` / `gh pr diff` + head snapshot when the commit is local

All modes call provider CLIs directly, run them concurrently up to
`review.max_parallel_providers`, store raw outputs, and write a deterministic
`synthesis.md` under `.trinity/reviews/`. stdout is the review directory path;
Progress is logged to stderr. Interrupted runs leave `incomplete.json` for
cleanup. Optional preset providers with no config entry or no `cli` string
are dropped from the run with a warning recorded in `metadata.json`; once an
optional provider has a `cli` string it is treated like a required provider
for preflight, so any optional or required provider whose CLI is `command
not found`, not executable, or has an invalid timeout fails preflight and
aborts the whole review before any provider runs. This path does not
require Claude Code worker-agent files.

**Strict COR review mode** — pair `--sop COR-1602` with `--rubric COR-1609` to
prepend rubric weights, calibration guidance, the 9.0 PASS threshold, and the
findings / decision-matrix / weighted-average output schema to the prompt.
SOP, rubric, threshold, and schema are recorded in `metadata.json`.

**Structured review output** — when using a preset with `task_type: review`,
Trinity appends a structured-output instruction to the prompt requesting
providers emit a fenced JSON block (`decision`, `weighted_score`, `blocking`,
`advisories`). Providers that comply produce enriched `synthesis.md` output
with per-provider scores and a Findings section. Providers that don't emit
the block continue to work via legacy returncode-based rendering. (#39)

### Check review status

```bash
trinity status              # newest review (default; --latest is reserved for forward-compat)
trinity status --latest     # explicit; same as bare `trinity status` today
```

`trinity status` summarises the most recent review under `.trinity/reviews/`.
With TRN-2018 M1, it shows a **Live state** section for in-progress reviews —
each provider with its current state (`queued`/`running`/`finished`/`failed`/
`timed_out`), pid when running, return code when terminal, and elapsed time:

```text
Latest review: .trinity/reviews/20260516-120000-rules  (started 2m ago)
  Scope: rules/   Mode: working-tree   Preset: fast-review

  Live state:
    glm        running  pid=12345  elapsed 2m 03s
    deepseek   queued

  Providers:
    (no results in metadata)

  Synthesis: missing
  Status: running
```

Provider stdout/stderr stream to `.trinity/reviews/<id>/logs/<provider>.std{out,err}.log`
while the review runs — `tail -f` works on those files for live progress. Stdout
uses a PTY-backed reader so line-buffered CLIs flush progress before exit. The
post-completion `raw/<provider>.txt` is composed from the same logs and remains
backward-compatible. If no reviews exist, `trinity status` exits 0 with `no
reviews found`.

### Update a PR after review fixes

```bash
make pr-update PR=26 MESSAGE="Address review feedback" DRY_RUN=1
make pr-update PR=26 MESSAGE="Address review feedback" REVIEW="Trinity fast-review PASS"
make pr-update PR=26 MESSAGE="Add follow-up fix" MODE=commit REVIEW="Codex found no major issues"
make pr-update PR=26 MESSAGE="Post validation evidence" MODE=comment-only REVIEW="No actionable findings"
```

`make pr-update` runs `scripts/pr-update.sh`. It requires a clean working tree
(no unstaged/untracked files), a configured upstream branch, and staged
changes for `MODE=amend` (default) or `MODE=commit`. It runs `make test`,
`make lint`, and `af validate --root .` before any push or comment unless
`DRY_RUN=1`, which only previews the planned update.

- `MODE=amend` (default): `git commit --amend --no-edit` + `git push --force-with-lease` to the current upstream branch
- `MODE=commit`: new commit + plain `git push` to the current upstream branch
- `MODE=comment-only`: validate and post the PR comment, no push

Always run `DRY_RUN=1` first to preview. Skip the helper if unrelated local
files are dirty, the PR head changed unexpectedly, you need a custom push
target, or COR-1612/COR-1615 needs more precise per-finding replies. When
`MESSAGE` or `REVIEW` contain `$`, single-quote the value so Make passes it
through unexpanded.

Manual fallback:

```bash
make test && make lint && af validate --root .
git commit --amend --no-edit
git push --force-with-lease fork HEAD:codex/example-branch
gh pr comment 26 --body-file comment.md
```

### Codex repo-local skill and Codex plugin

**Codex repo-local skill** — `.agents/skills/trinity/SKILL.md`. Smoke test:
restart Codex in the repo, then open `/skills` or invoke `$trinity` to
confirm the `trinity` skill loads.

**Codex plugin** — packaged under:

| Path | Purpose |
|------|---------|
| `plugins/trinity/.codex-plugin/plugin.json`      | Local plugin manifest |
| `plugins/trinity/skills/trinity/SKILL.md`        | Plugin-bundled skill |
| `.agents/plugins/marketplace.json`               | Repo marketplace entry |

Smoke test: restart Codex, open `/plugins`, select the repo marketplace, and
confirm the `trinity` plugin appears. After installing it, the bundled skill
becomes available.

**Claude Code regression check**

Claude Code still uses the existing install path. After `make install` or
`install.sh`, restart Claude Code and run:

```text
/trinity status
```

Expected result: the command is recognized and registered providers are listed.
Provider CLIs that are not installed or authenticated may warn, but Trinity
itself must load.

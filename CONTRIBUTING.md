# Contributing

Thanks for improving Trinity. This guide documents the local workflow that is
already encoded in the repository Makefile and CI.

## Development Setup

Use Python 3.11 or newer. The repository is a uv-managed virtual project, with
a pip requirements fallback for environments without uv.

```bash
make setup
```

When dependencies intentionally change, refresh both lock artifacts:

```bash
make lock
```

Commit `pyproject.toml`, `uv.lock`, and `requirements-dev.txt` together when a
dependency update affects them.

## Build Artifacts

Some checked-in files are generated from source templates. Before testing or
opening a PR, confirm generated artifacts are current:

```bash
make build
make verify-built
```

`make test` runs `make verify-built` first, but running the explicit target is
useful when changing provider templates, install manifests, or Codex skill
files.

## Tests, Lint, And Coverage

Run the standard local validation before pushing:

```bash
make test
make lint
make coverage
make audit
git diff --check
```

What these targets cover:

- `make test` runs pytest plus shell regression tests for workflows, installers,
  generated artifacts, metadata, release behavior, and governance documents.
- `make lint` runs Ruff check and format verification for `scripts/` and
  `tests/`.
- `make coverage` measures subprocess-aware coverage for `scripts/` and enforces
  the repository threshold.
- `make audit` runs `pip-audit` against the locked dev requirements.
- `git diff --check` rejects whitespace errors before they reach review.

Use focused tests first while iterating, then run the full set before PR handoff.

## Branch Naming

Use a short topic branch. For issue work, prefer:

```text
codex/<issue-number>-short-description
```

Examples:

```text
codex/158-add-contributing-md
codex/160-python-version-matrix
```

The automation also recognizes `claude/` branches. Keep branches scoped to one
issue or one coherent fix.

## Pull Requests

Open PRs against `main`. A PR should include:

- A concise summary of user-visible or maintainer-visible changes.
- The issue it closes, when applicable.
- Validation commands and their results.
- Notes for anything that cannot be fully verified until after merge, such as
  GitHub sidebar or Security tab recognition.

For review-fix updates on an existing PR, the repository provides:

```bash
make pr-update PR=<number> MESSAGE="Address review feedback"
```

`make pr-update` validates, amends or commits the change depending on `MODE`,
pushes to the current upstream branch, and posts a PR comment with evidence. Use
`DRY_RUN=1` to inspect the planned actions before writing.

## Release Flow

Do not publish releases manually from a feature branch. Release preparation is a
local metadata step:

```bash
make release-prep
```

That target verifies generated artifacts, runs tests and lint, stages release
metadata, creates the release commit, and creates the local tag. CI publishes
from the tag after it is pushed according to the release workflow.

## Documentation Changes

Documentation-only changes should still update `CHANGELOG.md` when they affect
maintainer workflows, repository governance, installation, release, or security
behavior. Keep README changes concise and link to focused documents when the
details belong elsewhere.

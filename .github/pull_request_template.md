<!--
Trinity PR template — codifies the shape every recent merged PR has used.
Adjust freely; the headers below are conventions, not strict gates.

For substantial slices delivered under a TRN-NNNN-PRP / PLN execution contract,
also link the parent docs in the Summary and reference the slice CHG.
-->

## Summary

<!-- 1–3 sentences: what changes, why now. If implementing a TRN-NNNN-CHG, link it. -->

## Test plan

<!-- Checklist of what you actually ran. Copy executed commands + output where possible.
     Default validation gates for code changes:
       - [ ] `make verify-built` → OK
       - [ ] `make test` → all green
       - [ ] `make lint` → ruff clean
       - [ ] `af validate --root .` → 0 issues
       - [ ] `make coverage` → TOTAL ≥ 80% (if touching scripts/ or dev/)

     For docs-only PRs touching only `rules/**` or root `*.md`, CI is skipped via paths-ignore.
-->

- [ ] (replace this with your actual checklist)

## Rollback

<!-- One line: how do we revert if something goes wrong? Usually `git revert <sha>` is enough.
     Mention any cleanup needed beyond the revert (e.g. database migration backout, CI workflow disable). -->

<!-- If you used Claude Code or another AI tool to author this PR, the existing convention is:
     🤖 Generated with [Claude Code](https://claude.com/claude-code)
-->

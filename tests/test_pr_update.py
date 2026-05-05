"""Tests for the TRN-2017 PR update helper."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "dev" / "pr_update.py"
MAKEFILE = ROOT / "Makefile"


def write_fake_commands(fake_bin):
    fake_bin.mkdir()
    fake = """#!/usr/bin/env python3
import os
import pathlib
import sys

name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = pathlib.Path(os.environ["FAKE_COMMAND_LOG"])
with log.open("a") as handle:
    handle.write(name + " " + repr(args) + "\\n")

if name == "git":
    if args == ["diff", "--quiet"]:
        raise SystemExit(1 if os.environ.get("FAKE_UNSTAGED", "0") == "1" else 0)
    if args == ["diff", "--name-only"]:
        sys.stdout.write(os.environ.get("FAKE_UNSTAGED_PATHS", "review.txt\\n"))
        raise SystemExit(0)
    if args == ["ls-files", "--others", "--exclude-standard"]:
        sys.stdout.write(os.environ.get("FAKE_UNTRACKED_PATHS", ""))
        raise SystemExit(0)
    if args == ["diff", "--cached", "--quiet"]:
        raise SystemExit(1 if os.environ.get("FAKE_STAGED", "1") == "1" else 0)
    if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
        print(os.environ.get("FAKE_BRANCH", "feature"))
        raise SystemExit(0)
    if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
        if os.environ.get("FAKE_UPSTREAM", "1") != "1":
            print("fatal: no upstream configured", file=sys.stderr)
            raise SystemExit(128)
        print(os.environ.get("FAKE_UPSTREAM_NAME", "fork/feature"))
        raise SystemExit(0)
    if args == ["rev-parse", "--symbolic-full-name", "@{u}"]:
        if os.environ.get("FAKE_UPSTREAM", "1") != "1":
            print("fatal: no upstream configured", file=sys.stderr)
            raise SystemExit(128)
        print(os.environ.get("FAKE_UPSTREAM_REF", "refs/remotes/fork/feature"))
        raise SystemExit(0)
    if args == ["remote"]:
        print(os.environ.get("FAKE_REMOTES", "fork"))
        raise SystemExit(0)
    if args[:1] in (["commit"], ["push"]):
        raise SystemExit(0)
    print(f"unexpected git args: {args}", file=sys.stderr)
    raise SystemExit(99)

if name == "make":
    if os.environ.get("FAKE_VALIDATION_FAIL") == "make":
        raise SystemExit(2)
    raise SystemExit(0)

if name == "af":
    if os.environ.get("FAKE_VALIDATION_FAIL") == "af":
        raise SystemExit(3)
    raise SystemExit(0)

if name == "gh":
    if args[:2] == ["pr", "comment"] and "--body-file" in args:
        body = sys.stdin.read()
        body_path = pathlib.Path(os.environ["FAKE_COMMENT_BODY"])
        body_path.write_text(body)
        raise SystemExit(0)
    print(f"unexpected gh args: {args}", file=sys.stderr)
    raise SystemExit(99)

print(f"unexpected command: {name}", file=sys.stderr)
raise SystemExit(99)
"""
    for name in ["git", "make", "af", "gh"]:
        path = fake_bin / name
        path.write_text(fake)
        path.chmod(0o755)


def run_helper(tmp_path, args, **env_overrides):
    fake_bin = tmp_path / "bin"
    write_fake_commands(fake_bin)
    log = tmp_path / "commands.log"
    comment_body = tmp_path / "comment.md"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_COMMAND_LOG": str(log),
            "FAKE_COMMENT_BODY": str(comment_body),
        }
    )
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    log_text = log.read_text() if log.exists() else ""
    body_text = comment_body.read_text() if comment_body.exists() else ""
    return result, log_text, body_text


def test_pr_update_dry_run_previews_validate_amend_push_and_comment(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Address COR-1602 review",
            "--review",
            "Trinity fast-review PASS",
            "--dry-run",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "make test" in result.stdout
    assert "make lint" in result.stdout
    assert "af validate --root ." in result.stdout
    assert "git commit --amend --no-edit" in result.stdout
    assert "git push --force-with-lease fork HEAD:feature" in result.stdout
    assert "gh pr comment 20 --body-file -" in result.stdout
    assert "Address COR-1602 review" in result.stdout
    assert "Trinity fast-review PASS" in result.stdout
    assert "git ['diff', '--quiet']" in log
    assert body == ""


def test_pr_update_refuses_dirty_worktree_before_side_effects(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        ["--pr", "20", "--message", "Address review", "--dry-run"],
        FAKE_UNTRACKED_PATHS="tmp/local.txt\n",
    )

    assert result.returncode == 1
    assert "refusing to run with dirty working tree" in result.stderr
    assert "tmp/local.txt" in result.stderr
    assert "git ['commit'" not in log
    assert "gh ['pr', 'comment'" not in log
    assert body == ""


def test_pr_update_refuses_missing_upstream_before_side_effects(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        ["--pr", "20", "--message", "Address review", "--dry-run"],
        FAKE_UPSTREAM="0",
    )

    assert result.returncode == 1
    assert "current branch has no upstream" in result.stderr
    assert "git ['commit'" not in log
    assert "gh ['pr', 'comment'" not in log
    assert body == ""


def test_pr_update_refuses_missing_staged_changes_for_amend(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        ["--pr", "20", "--message", "Address review", "--dry-run"],
        FAKE_STAGED="0",
    )

    assert result.returncode == 1
    assert "no staged changes to amend" in result.stderr
    assert "git ['commit'" not in log
    assert "gh ['pr', 'comment'" not in log
    assert body == ""


def test_pr_update_refuses_missing_staged_changes_for_commit(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Address review",
            "--mode",
            "commit",
            "--dry-run",
        ],
        FAKE_STAGED="0",
    )

    assert result.returncode == 1
    assert "no staged changes to commit" in result.stderr
    assert "git ['commit'" not in log
    assert "gh ['pr', 'comment'" not in log
    assert body == ""


def test_pr_update_uses_plain_push_for_new_commit_mode(tmp_path):
    result, _log, _body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Address review",
            "--mode",
            "commit",
            "--dry-run",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "git commit -m 'Address review'" in result.stdout
    assert "git push fork HEAD:feature\n" in result.stdout
    assert "git push --force-with-lease" not in result.stdout


def test_pr_update_parses_upstream_when_remote_name_contains_slash(tmp_path):
    result, _log, _body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Address review",
            "--dry-run",
        ],
        FAKE_REMOTES="foo\nfoo/bar\n",
        FAKE_UPSTREAM_NAME="foo/bar/main",
        FAKE_UPSTREAM_REF="refs/remotes/foo/bar/main",
    )

    assert result.returncode == 0, result.stderr
    assert "git push --force-with-lease foo/bar HEAD:main" in result.stdout


def test_pr_update_executes_fake_commands_and_posts_comment_body(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Address review",
            "--review",
            "GLM PASS 9.2/10",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "make ['test']" in log
    assert "make ['lint']" in log
    assert "af ['validate', '--root', '.']" in log
    assert "git ['commit', '--amend', '--no-edit']" in log
    assert "git ['push', '--force-with-lease', 'fork', 'HEAD:feature']" in log
    assert "gh ['pr', 'comment', '20', '--body-file', '-']" in log
    assert "Address review" in body
    assert "- `make test`: PASS" in body
    assert "- `make lint`: PASS" in body
    assert "- `af validate --root .`: PASS" in body
    assert "GLM PASS 9.2/10" in body


def test_pr_update_comment_only_skips_commit_and_push_but_posts_comment(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Post validation evidence",
            "--mode",
            "comment-only",
            "--review",
            "No actionable findings",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "make ['test']" in log
    assert "make ['lint']" in log
    assert "af ['validate', '--root', '.']" in log
    assert "git ['commit'" not in log
    assert "git ['push'" not in log
    assert "gh ['pr', 'comment', '20', '--body-file', '-']" in log
    assert "Post validation evidence" in body
    assert "- mode: `comment-only`" in body
    assert "- push: not requested" in body
    assert "No actionable findings" in body


def test_pr_update_preserves_special_characters_in_comment_body(tmp_path):
    message = "Fix `null` deref: keep $VAR literal"
    result, _log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            message,
            "--mode",
            "comment-only",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert message in body


def test_pr_update_includes_multiple_review_lines(tmp_path):
    result, _log, body = run_helper(
        tmp_path,
        [
            "--pr",
            "20",
            "--message",
            "Post validation evidence",
            "--mode",
            "comment-only",
            "--review",
            "GLM PASS",
            "--review",
            "DeepSeek PASS",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "- GLM PASS" in body
    assert "- DeepSeek PASS" in body


def test_pr_update_stops_on_validation_failure_before_push_or_comment(tmp_path):
    result, log, body = run_helper(
        tmp_path,
        ["--pr", "20", "--message", "Address review"],
        FAKE_VALIDATION_FAIL="make",
    )

    assert result.returncode == 1
    assert "make test failed" in result.stderr
    assert "make ['test']" in log
    assert "git ['commit'" not in log
    assert "git ['push'" not in log
    assert "gh ['pr', 'comment'" not in log
    assert body == ""


def test_pr_update_requires_pr_number(tmp_path):
    result, _log, _body = run_helper(
        tmp_path,
        ["--message", "Address review", "--dry-run"],
    )

    assert result.returncode == 2
    assert "the following arguments are required: --pr" in result.stderr


def test_makefile_documents_pr_update_target():
    text = MAKEFILE.read_text()

    assert ".PHONY:" in text
    assert "pr-update" in text
    assert "dev/pr_update.py" in text
    assert "scripts/pr_update.py" not in text
    assert "MODE ?= amend" in text
    assert "DRY_RUN=1" in text
    assert "$(filter 1 true yes,$(DRY_RUN))" in text
    assert ".venv/bin/ruff check dev/ scripts/ tests/" in text
    assert ".venv/bin/ruff format --check dev/ scripts/ tests/" in text


def test_makefile_dry_run_zero_does_not_enable_dry_run():
    result = subprocess.run(
        ["make", "-n", "pr-update", "PR=20", "MESSAGE=Address review", "DRY_RUN=0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--dry-run" not in result.stdout

    enabled = subprocess.run(
        ["make", "-n", "pr-update", "PR=20", "MESSAGE=Address review", "DRY_RUN=1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert enabled.returncode == 0, enabled.stderr
    assert "--dry-run" in enabled.stdout


def test_makefile_pr_update_preserves_literal_dollars_in_text_args(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "python.log"
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        f"""#!{sys.executable}
import os
import pathlib
import sys

pathlib.Path(os.environ["FAKE_PYTHON_LOG"]).write_text(repr(sys.argv[1:]))
"""
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "FAKE_PYTHON_LOG": str(log),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )
    result = subprocess.run(
        [
            "make",
            "pr-update",
            "PR=20",
            "MESSAGE=Fix $VAR and $(MODEL) literal",
            "REVIEW=Keep ${TEMPLATE} literal",
            "MODE=comment-only",
            "DRY_RUN=1",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = log.read_text()
    assert "'--message', 'Fix $VAR and $(MODEL) literal'" in args
    assert "'--review', 'Keep ${TEMPLATE} literal'" in args

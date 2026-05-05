#!/usr/bin/env python3
"""Safely update a pull request after local review fixes."""

import argparse
import subprocess
import sys


VALIDATION_COMMANDS = [
    ("make test", ["make", "test"]),
    ("make lint", ["make", "lint"]),
    ("af validate --root .", ["af", "validate", "--root", "."]),
]


def run_command(command, *, input_text=None):
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def shell_join(command):
    return " ".join(shell_quote(part) for part in command)


def shell_quote(value):
    if not value:
        return "''"
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@%_+=:,./-"
    if all(char in safe for char in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def fail(message):
    print(f"pr-update: {message}", file=sys.stderr)
    return 1


def git_stdout(args, error_message):
    result = run_command(["git"] + args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            return None, f"{error_message}: {detail}"
        return None, error_message
    return result.stdout.strip(), None


def unstaged_paths():
    result = run_command(["git", "diff", "--quiet"])
    if result.returncode == 0:
        return [], None
    if result.returncode != 1:
        detail = (result.stderr or result.stdout).strip()
        return None, detail or "unable to inspect unstaged changes"
    output, error = git_stdout(
        ["diff", "--name-only"], "unable to list unstaged changes"
    )
    if error:
        return None, error
    return [line for line in output.splitlines() if line.strip()], None


def untracked_paths():
    output, error = git_stdout(
        ["ls-files", "--others", "--exclude-standard"],
        "unable to inspect untracked files",
    )
    if error:
        return None, error
    return [line for line in output.splitlines() if line.strip()], None


def git_lines(args, error_message):
    output, error = git_stdout(args, error_message)
    if error:
        return None, error
    return [line for line in output.splitlines() if line.strip()], None


def dirty_worktree_paths():
    unstaged, error = unstaged_paths()
    if error:
        return None, error
    untracked, error = untracked_paths()
    if error:
        return None, error
    return unstaged + untracked, None


def branch_context():
    branch, error = git_stdout(
        ["rev-parse", "--abbrev-ref", "HEAD"], "unable to resolve current branch"
    )
    if error:
        return None, None, None, None, error
    upstream, error = git_stdout(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        "current branch has no upstream",
    )
    if error:
        return branch, None, None, None, error
    upstream_ref, error = git_stdout(
        ["rev-parse", "--symbolic-full-name", "@{u}"],
        "current branch has no upstream",
    )
    if error:
        return branch, upstream, None, None, error
    remotes, error = git_lines(["remote"], "unable to list git remotes")
    if error:
        return branch, upstream, upstream_ref, None, error
    return branch, upstream, upstream_ref, remotes, None


def push_target(upstream_ref, remotes):
    prefix = "refs/remotes/"
    if not upstream_ref or not upstream_ref.startswith(prefix):
        return None, None, f"invalid upstream branch: {upstream_ref}"
    relative_ref = upstream_ref[len(prefix) :]
    matches = []
    for remote in remotes:
        remote_prefix = f"{remote}/"
        if relative_ref.startswith(remote_prefix):
            branch = relative_ref[len(remote_prefix) :]
            if branch:
                matches.append((remote, branch))
    if not matches:
        return None, None, f"invalid upstream branch: {upstream_ref}"
    remote, branch = max(matches, key=lambda item: len(item[0]))
    return remote, branch, None


def has_staged_changes():
    result = run_command(["git", "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        return False, None
    if result.returncode == 1:
        return True, None
    detail = (result.stderr or result.stdout).strip()
    return None, detail or "unable to inspect staged changes"


def validate_safety(args):
    dirty_paths, error = dirty_worktree_paths()
    if error:
        return None, error
    if dirty_paths:
        return None, "refusing to run with dirty working tree:\n" + "\n".join(
            dirty_paths
        )

    branch, upstream, upstream_ref, remotes, error = branch_context()
    if error:
        return None, error
    remote, upstream_branch, error = push_target(upstream_ref, remotes)
    if error:
        return None, error

    if args.mode in {"amend", "commit"}:
        staged, error = has_staged_changes()
        if error:
            return None, error
        if not staged:
            action = "amend" if args.mode == "amend" else "commit"
            return None, f"no staged changes to {action}"

    return {
        "branch": branch,
        "upstream": upstream,
        "remote": remote,
        "upstream_branch": upstream_branch,
    }, None


def validation_evidence(dry_run):
    evidence = []
    for label, command in VALIDATION_COMMANDS:
        if dry_run:
            evidence.append((label, "DRY-RUN"))
            continue
        result = run_command(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"{label} failed" + (f": {detail}" if detail else ""))
        evidence.append((label, "PASS"))
    return evidence


def git_update_command(args):
    if args.mode == "amend":
        return ["git", "commit", "--amend", "--no-edit"]
    if args.mode == "commit":
        return ["git", "commit", "-m", args.message]
    return None


def git_push_command(args, context):
    remote = context["remote"]
    refspec = f"HEAD:{context['upstream_branch']}"
    if args.mode == "amend":
        return ["git", "push", "--force-with-lease", remote, refspec]
    if args.mode == "commit":
        return ["git", "push", remote, refspec]
    return None


def build_comment(args, evidence, context):
    lines = [
        args.message,
        "",
        "Validation:",
    ]
    for label, status in evidence:
        lines.append(f"- `{label}`: {status}")
    if args.review:
        lines.extend(["", "Review evidence:"])
        for item in args.review:
            lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "Update:",
            f"- mode: `{args.mode}`",
        ]
    )
    push = git_push_command(args, context)
    if push:
        lines.append(f"- push: `{shell_join(push)}`")
    else:
        lines.append("- push: not requested")
    return "\n".join(lines) + "\n"


def preview(args, evidence, comment, context):
    commands = [command for _label, command in VALIDATION_COMMANDS]
    update = git_update_command(args)
    push = git_push_command(args, context)
    if update:
        commands.append(update)
    if push:
        commands.append(push)
    commands.append(["gh", "pr", "comment", str(args.pr), "--body-file", "-"])

    lines = ["DRY RUN", "", "Commands:"]
    for command in commands:
        lines.append(f"- {shell_join(command)}")
    lines.extend(["", "Comment body:", "", comment])
    return "\n".join(lines)


def execute_or_fail(command, *, input_text=None):
    result = run_command(command, input_text=input_text)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            shell_join(command) + " failed" + (f": {detail}" if detail else "")
        )


def cmd_pr_update(args):
    context, error = validate_safety(args)
    if error:
        return fail(error)

    try:
        evidence = validation_evidence(args.dry_run)
    except RuntimeError as exc:
        return fail(str(exc))

    comment = build_comment(args, evidence, context)
    if args.dry_run:
        print(preview(args, evidence, comment, context))
        return 0

    try:
        update = git_update_command(args)
        if update:
            execute_or_fail(update)
        push = git_push_command(args, context)
        if push:
            execute_or_fail(push)
        execute_or_fail(
            ["gh", "pr", "comment", str(args.pr), "--body-file", "-"],
            input_text=comment,
        )
    except RuntimeError as exc:
        return fail(str(exc))

    print(f"Updated PR #{args.pr}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pr_update.py",
        description="Validate, update, push, and comment on a PR safely.",
        allow_abbrev=False,
    )
    parser.add_argument("--pr", required=True, help="GitHub pull request number")
    parser.add_argument("--message", required=True, help="Concise PR update message")
    parser.add_argument(
        "--mode",
        choices=["amend", "commit", "comment-only"],
        default="amend",
        help="Git update mode before posting the PR comment",
    )
    parser.add_argument(
        "--review",
        action="append",
        default=[],
        help="Review evidence line to include in the PR comment; may be repeated",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands and comment preview without running validation, push, or comment side effects",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_pr_update(args)


if __name__ == "__main__":
    sys.exit(main())

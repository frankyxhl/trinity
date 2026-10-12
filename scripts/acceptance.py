#!/usr/bin/env python3
"""acceptance.py — One command that reports every acceptance case (WO-003).

Case ids are read from the `### ACC-NNN` headings of the acceptance docs, never
from a hand-kept list. Each case ends as exactly one of `pass` / `fail` /
`not_run` / `approved_na` (CraftCode v0.1 §10.3):

- no registered check            -> not_run ("no check"), listed as missing
- registered check, run by pytest:
    all collected tests passed   -> pass
    any test failed or errored   -> fail
    zero tests ran               -> fail (never a silent pass)
    any test skipped             -> not_run (a skipped part is not evidence)
    crash / no report / timeout  -> fail
- complete approvals entry (id, reason, approver) and no check -> approved_na

Exit 0 only when every case is pass or approved_na; 1 otherwise; 2 when no case
is found or the inputs are invalid. A JSON record shaped after Appendix D is
written to --out by every run.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HEADING = re.compile(r"^### (ACC-\d+[a-z]?)\b", re.M)
STATUSES = ("pass", "fail", "not_run", "approved_na")
CHECK_TIMEOUT_S = (
    1800  # ponytail: one bound for every check; per-check limits when a slow case lands
)
REPO_DEFAULT = Path(__file__).resolve().parent.parent


class InputError(Exception):
    pass


def case_ids(docs: Path) -> list[str]:
    ids: list[str] = []
    if docs.is_dir():
        for doc in sorted(docs.glob("*.md")):
            ids += HEADING.findall(doc.read_text(encoding="utf-8"))
    if not ids:
        raise InputError(f"no acceptance cases found under {docs}")
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise InputError(f"duplicate case headings: {', '.join(dupes)}")
    return ids


def load_registry(path: Path, cases: list[str]) -> dict[str, list[str]]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or not all(
        isinstance(v, list) and v and all(isinstance(a, str) for a in v)
        for v in registry.values()
    ):
        raise InputError(
            f"{path}: expected an object of case id -> non-empty list of pytest arguments"
        )
    unknown = sorted(set(registry) - set(cases))
    if unknown:
        raise InputError(
            f"{path}: checks registered for unknown cases: {', '.join(unknown)}"
        )
    return registry


def load_approvals(path: Path, cases: list[str]) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise InputError(f"{path}: expected a JSON list")
    honoured = []
    for entry in entries:
        complete = isinstance(entry, dict) and all(
            isinstance(entry.get(k), str) and entry[k].strip()
            for k in ("id", "reason", "approver")
        )
        if complete and entry["id"] in cases:
            honoured.append({k: entry[k] for k in ("id", "reason", "approver")})
        else:
            print(
                f"acceptance: approval entry ignored (needs a known id, reason, approver): {entry!r}",
                file=sys.stderr,
            )
    return honoured


def _junit_counts(path: Path) -> dict | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    return {
        k: sum(int(s.get(k, 0)) for s in suites)
        for k in ("tests", "failures", "errors", "skipped")
    }


def run_check(args: list[str], repo: Path) -> dict:
    command = shlex.join(["python3", "-m", "pytest", *args])
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        argv = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            *args,
        ]
        try:
            proc = subprocess.run(
                argv, cwd=repo, capture_output=True, text=True, timeout=CHECK_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            return _result(
                "fail", command, None, f"timed out after {CHECK_TIMEOUT_S} s", None
            )
        rc = proc.returncode
        counts = _junit_counts(report)
    if rc == 5 or (counts is not None and counts["tests"] == 0):
        return _result("fail", command, rc, "no tests ran", 0)
    if counts is None:
        return _result(
            "fail", command, rc, f"crashed: no test report (exit {rc})", None
        )
    ran = counts["tests"] - counts["skipped"]
    if rc not in (0, 1):
        return _result("fail", command, rc, f"crashed: pytest exit {rc}", ran)
    if rc == 1 or counts["failures"] or counts["errors"]:
        return _result(
            "fail",
            command,
            rc,
            f"{counts['failures'] + counts['errors']} test(s) failed",
            ran,
        )
    if counts["skipped"]:
        return _result(
            "not_run", command, rc, f"{counts['skipped']} test(s) skipped", ran
        )
    return _result("pass", command, rc, f"{ran} test(s) passed", ran)


def _result(status, command, exit_code, reason, tests_executed) -> dict:
    return {
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "reason": reason,
        "tests_executed": tests_executed,
    }


def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def source_state(repo: Path) -> dict:
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top is None or Path(top.strip()).resolve() != repo.resolve():
        return {"commit": None, "worktree_clean": None}
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain")
    return {
        "commit": head.strip() if head else None,
        "worktree_clean": None if status is None else status.strip() == "",
    }


def build_record(repo, docs, registry_path, approvals_path) -> dict:
    cases = case_ids(docs)
    registry = load_registry(registry_path, cases)
    approvals = load_approvals(approvals_path, cases)
    approved = {a["id"]: a for a in approvals}
    source = source_state(
        repo
    )  # before any check runs, so check output cannot dirty it
    checks = []
    for case in cases:
        if case in registry:
            result = run_check(registry[case], repo)
        elif case in approved:
            result = _result("approved_na", None, None, approved[case]["reason"], None)
        else:
            result = _result("not_run", None, None, "no check", None)
        checks.append({"id": case, "required": True, **result})
    statuses = {c["status"] for c in checks}
    if statuses <= {"pass", "approved_na"}:
        overall = "pass"
    elif "fail" in statuses:
        overall = "fail"
    else:
        overall = "not_run"
    return {
        "record_format_version": "0.1",
        "record_id": str(uuid.uuid4()),
        "work_order": "WO-003",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "checks": checks,
        "overall_status": overall,
        "missing_checks": [
            c["id"] for c in checks if c["status"] == "not_run" and c["command"] is None
        ],
        "exceptions": [],
        "approvals": [a for a in approvals if a["id"] not in registry],
        "known_limitations": [
            "Record is written by a local run; it is not signed or stored tamper-proof.",
            "A timed-out check's pytest process is killed, but processes it started are not.",
        ],
    }


def summary(record: dict, out: Path) -> str:
    checks = record["checks"]
    lines = [f"acceptance: {len(checks)} cases, overall {record['overall_status']}"]
    lines += [f"{s}: {sum(c['status'] == s for c in checks)}" for s in STATUSES]
    ran = [
        c for c in checks if c["command"] is not None or c["status"] == "approved_na"
    ]
    if ran:
        lines.append("checked:")
        lines += [f"  {c['id']} {c['status']} - {c['reason']}" for c in ran]
    missing = record["missing_checks"]
    lines.append(f"missing checks ({len(missing)}):")
    lines += textwrap.wrap(
        " ".join(missing), 96, initial_indent="  ", subsequent_indent="  "
    )
    lines.append(f"record: {out}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    p.add_argument("--docs", type=Path, help="default: <repo>/docs/acceptance")
    p.add_argument(
        "--checks", type=Path, help="default: <repo>/tests/acceptance/checks.json"
    )
    p.add_argument(
        "--approvals", type=Path, help="default: <repo>/docs/acceptance/approvals.json"
    )
    p.add_argument(
        "--out", type=Path, help="default: <repo>/tmp/acceptance/record.json"
    )
    a = p.parse_args(argv)
    repo = a.repo.resolve()
    docs = a.docs or repo / "docs" / "acceptance"
    checks = a.checks or repo / "tests" / "acceptance" / "checks.json"
    approvals = a.approvals or repo / "docs" / "acceptance" / "approvals.json"
    out = a.out or repo / "tmp" / "acceptance" / "record.json"
    try:
        record = build_record(repo, docs, checks, approvals)
    except (InputError, OSError, json.JSONDecodeError) as exc:
        print(f"acceptance: {exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(summary(record, out))
    return 0 if record["overall_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

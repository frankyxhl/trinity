"""Self-tests for the acceptance entry (WO-003, CraftCode v0.1 §10.3, Appendix D).

The entry is `scripts/acceptance.py` (run by `make acceptance`). It reads case
ids from the `### ACC-NNN` headings of the acceptance docs, runs the pytest
check registered for each id, and reports every case as exactly one of
`pass` / `fail` / `not_run` / `approved_na`, plus a list of cases with no
registered check. It writes a JSON record shaped after Appendix D.

Interface pinned here:
- `python3 scripts/acceptance.py --repo R --docs D --checks C --approvals A --out O`
- C: JSON object, case id -> list of pytest arguments (run from R).
- A: JSON list of {"id", "reason", "approver"}; an entry missing a field
  approves nothing.
- exit 0 only when every case is `pass` or `approved_na`; 1 otherwise;
  2 when no case is found or an input is invalid (an error, never a result).

Covered: id extraction equals heading count; missing/empty docs and duplicate
headings -> error exit; bad registry -> error exit; unregistered -> not_run;
skipped -> not_run; zero tests -> fail; crash -> fail; timeout -> fail;
approved_na only from a complete approval entry; exit status; record fields
and commit = HEAD.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "acceptance.py"
DOCS = REPO_ROOT / "docs" / "acceptance"
SHIPPED_CHECKS = REPO_ROOT / "tests" / "acceptance" / "checks.json"
SHIPPED_APPROVALS = REPO_ROOT / "docs" / "acceptance" / "approvals.json"
STATUSES = {"pass", "fail", "not_run", "approved_na"}
HEADING = re.compile(r"^### (ACC-\d+[a-z]?)\b", re.M)

GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid"]

CHECK_FILES = {
    "test_ok.py": "def test_ok():\n    assert True\n",
    "test_bad.py": "def test_bad():\n    assert 1 == 2\n",
    "test_skip.py": "import pytest\n\ndef test_skip():\n    pytest.skip('not ready')\n",
    "test_half_skip.py": textwrap.dedent(
        """\
        import pytest

        def test_ok():
            assert True

        def test_skip():
            pytest.skip('key part not ready')
        """
    ),
    "test_none.py": "# no tests here\nVALUE = 1\n",
    "test_import_error.py": "import module_that_does_not_exist_anywhere\n\ndef test_x():\n    pass\n",
    "test_hard_exit.py": "import os\n\ndef test_dies():\n    os._exit(70)\n",
    "test_sleep.py": "import time\n\ndef test_slow():\n    time.sleep(60)\n",
}

DOC_A = textwrap.dedent(
    """\
    # Cases A
    ### ACC-001 first case
    Body that mentions ACC-099 inline is not a case.
    ### ACC-002 second case
    | ACC-003 | a coverage-table row is not a case |
    #### ACC-004 a deeper heading is not a case
    """
)
DOC_B = textwrap.dedent(
    """\
    # Cases B
    ### ACC-010 tenth case
    ### ACC-010b sub-case with a letter suffix
    """
)
FIXTURE_IDS = ["ACC-001", "ACC-002", "ACC-010", "ACC-010b"]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_repo(root: Path, *, git: bool = True) -> Path:
    repo = root / "repo"
    _write(repo / "docs" / "acceptance" / "A.md", DOC_A)
    _write(repo / "docs" / "acceptance" / "B.md", DOC_B)
    for name, body in CHECK_FILES.items():
        _write(repo / "checks" / name, body)
    if git:
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run([*GIT, "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [*GIT, "-C", str(repo), "commit", "-q", "--no-verify", "-m", "fixture"],
            check=True,
        )
    return repo


def _run(
    tmp_path: Path,
    repo: Path,
    checks: dict | str,
    approvals: list | None = None,
    docs: Path | None = None,
):
    raw = checks if isinstance(checks, str) else json.dumps(checks)
    checks_file = _write(tmp_path / "checks.json", raw)
    approvals_file = _write(tmp_path / "approvals.json", json.dumps(approvals or []))
    out = tmp_path / "out" / "record.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--docs",
            str(docs if docs is not None else repo / "docs" / "acceptance"),
            "--checks",
            str(checks_file),
            "--approvals",
            str(approvals_file),
            "--out",
            str(out),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=300,
    )
    record = json.loads(out.read_text()) if out.exists() else None
    return proc, record


def _by_id(record: dict | None) -> dict:
    assert record is not None, "the run wrote no JSON record"
    return {c["id"]: c for c in record["checks"]}


# --- case ids come from the docs ---------------------------------------------


def test_fixture_ids_are_exactly_the_h3_headings(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {})
    assert sorted(_by_id(record)) == sorted(FIXTURE_IDS), proc.stderr


def test_real_docs_id_count_equals_heading_count(tmp_path):
    # Looser than the entry's own pattern on purpose: a heading shape the entry
    # misses still counts here.
    n_headings = sum(
        len(re.findall(r"^### ACC-", doc.read_text(encoding="utf-8"), re.M))
        for doc in DOCS.glob("*.md")
    )
    assert n_headings, "the acceptance docs hold no ### ACC- headings"
    proc, record = _run(tmp_path, REPO_ROOT, {}, docs=DOCS)
    ids = _by_id(record)
    assert len(record["checks"]) == len(ids) == n_headings
    assert {c["status"] for c in ids.values()} == {"not_run"}
    assert proc.returncode == 1


@pytest.mark.parametrize("layout", ["missing_dir", "empty_dir", "no_headings"])
def test_no_cases_is_an_error_exit(tmp_path, layout):
    repo = _make_repo(tmp_path)
    docs = tmp_path / "other-docs"
    if layout == "empty_dir":
        docs.mkdir()
    elif layout == "no_headings":
        _write(docs / "X.md", "# Title\nNo case headings here, only ACC-001 in text.\n")
    proc, record = _run(tmp_path, repo, {}, docs=docs)
    assert proc.returncode == 2
    assert "no acceptance cases" in proc.stderr.lower()
    assert record is None or all(c["status"] != "pass" for c in record["checks"])


@pytest.mark.parametrize("across_files", [False, True])
def test_duplicate_heading_is_an_error_exit(tmp_path, across_files):
    repo = _make_repo(tmp_path)
    extra = "### ACC-001 the same id again\n"
    if across_files:
        _write(repo / "docs" / "acceptance" / "C.md", "# Cases C\n" + extra)
    else:
        _write(repo / "docs" / "acceptance" / "A.md", DOC_A + extra)
    proc, record = _run(tmp_path, repo, {"ACC-001": ["checks/test_ok.py"]})
    assert proc.returncode == 2
    assert "ACC-001" in proc.stderr
    assert record is None or all(c["status"] != "pass" for c in record["checks"])


@pytest.mark.parametrize(
    "registry",
    [
        '{"ACC-001": ["checks/test_ok.py"]',
        "[]",
        '{"ACC-001": []}',
        '{"ACC-999": ["checks/test_ok.py"]}',
    ],
    ids=["invalid_json", "not_an_object", "empty_arguments", "unknown_id"],
)
def test_bad_registry_is_an_error_exit(tmp_path, registry):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, registry)
    assert proc.returncode == 2, proc.stdout
    assert proc.stderr.strip()
    assert record is None
    if "ACC-999" in registry:
        assert "ACC-999" in proc.stderr


# --- statuses ----------------------------------------------------------------


def test_unregistered_case_is_not_run_and_listed_missing(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {"ACC-001": ["checks/test_ok.py"]})
    ids = _by_id(record)
    for case in ("ACC-002", "ACC-010", "ACC-010b"):
        assert ids[case]["status"] == "not_run"
        assert ids[case]["reason"] == "no check"
        assert ids[case]["command"] is None
        assert ids[case]["exit_code"] is None
    assert sorted(record["missing_checks"]) == ["ACC-002", "ACC-010", "ACC-010b"]
    assert "missing checks" in proc.stdout.lower()
    for case in ("ACC-002", "ACC-010", "ACC-010b"):
        assert case in proc.stdout


def test_passing_and_failing_checks(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(
        tmp_path,
        repo,
        {"ACC-001": ["checks/test_ok.py"], "ACC-002": ["checks/test_bad.py"]},
    )
    ids = _by_id(record)
    assert ids["ACC-001"]["status"] == "pass"
    assert ids["ACC-001"]["exit_code"] == 0
    assert ids["ACC-001"]["tests_executed"] == 1
    assert "checks/test_ok.py" in json.dumps(ids["ACC-001"]["command"])
    assert ids["ACC-002"]["status"] == "fail"
    assert ids["ACC-002"]["exit_code"] == 1


@pytest.mark.parametrize("check", ["test_skip.py", "test_half_skip.py"])
def test_skipped_check_is_not_run(tmp_path, check):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {"ACC-001": [f"checks/{check}"]})
    case = _by_id(record)["ACC-001"]
    assert case["status"] == "not_run"
    assert "skip" in case["reason"].lower()
    assert "ACC-001" not in record["missing_checks"]


def test_zero_test_check_is_fail(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {"ACC-001": ["checks/test_none.py"]})
    case = _by_id(record)["ACC-001"]
    assert case["status"] == "fail"
    assert case["tests_executed"] == 0
    assert "no tests" in case["reason"].lower()


@pytest.mark.parametrize(
    "target",
    [
        "checks/test_import_error.py",
        "checks/test_hard_exit.py",
        "checks/does_not_exist.py",
    ],
)
def test_crashed_check_is_fail(tmp_path, target):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {"ACC-001": [target]})
    case = _by_id(record)["ACC-001"]
    assert case["status"] == "fail"
    assert case["exit_code"] not in (None, 0)
    assert case["reason"]


def test_timed_out_check_is_fail(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("acceptance_entry", SCRIPT)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(entry, "CHECK_TIMEOUT_S", 3)
    repo = _make_repo(tmp_path)
    checks = _write(tmp_path / "checks.json", '{"ACC-001": ["checks/test_sleep.py"]}')
    approvals = _write(tmp_path / "approvals.json", "[]")
    out = tmp_path / "out" / "record.json"
    rc = entry.main(
        ["--repo", str(repo), "--checks", str(checks), "--approvals", str(approvals)]
        + ["--out", str(out)]
    )
    case = _by_id(json.loads(out.read_text()))["ACC-001"]
    assert case["status"] == "fail"
    assert "timed out" in case["reason"]
    assert case["exit_code"] is None
    assert rc == 1


def test_every_case_has_exactly_one_known_status(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(
        tmp_path,
        repo,
        {"ACC-001": ["checks/test_ok.py"], "ACC-002": ["checks/test_skip.py"]},
    )
    ids = _by_id(record)
    assert len(record["checks"]) == len(ids) == len(FIXTURE_IDS)
    assert all(c["status"] in STATUSES for c in ids.values())
    counts = {s: sum(c["status"] == s for c in ids.values()) for s in STATUSES}
    for status, n in counts.items():
        assert re.search(rf"^\s*{status}\s*:?\s*{n}\b", proc.stdout, re.M), (
            status,
            proc.stdout,
        )


# --- approvals ---------------------------------------------------------------


def test_approved_na_only_with_complete_approval_entry(tmp_path):
    repo = _make_repo(tmp_path)
    approvals = [
        {"id": "ACC-002", "reason": "out of scope for this pilot", "approver": "owner"},
        {"id": "ACC-010", "reason": "no approver given"},
        {"id": "ACC-010b", "approver": "owner"},
    ]
    proc, record = _run(tmp_path, repo, {}, approvals=approvals)
    ids = _by_id(record)
    assert ids["ACC-002"]["status"] == "approved_na"
    assert "out of scope" in ids["ACC-002"]["reason"]
    assert ids["ACC-001"]["status"] == "not_run"
    assert ids["ACC-010"]["status"] == "not_run"
    assert ids["ACC-010b"]["status"] == "not_run"
    assert [a["id"] for a in record["approvals"]] == ["ACC-002"]


def test_approval_reason_no_check_is_not_listed_missing(tmp_path):
    repo = _make_repo(tmp_path)
    approvals = [{"id": "ACC-002", "reason": "no check", "approver": "owner"}]
    proc, record = _run(tmp_path, repo, {}, approvals=approvals)
    assert _by_id(record)["ACC-002"]["status"] == "approved_na"
    assert "ACC-002" not in record["missing_checks"]
    assert sorted(record["missing_checks"]) == ["ACC-001", "ACC-010", "ACC-010b"]


def test_no_approvals_means_no_approved_na(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(tmp_path, repo, {})
    assert all(c["status"] != "approved_na" for c in _by_id(record).values())


# --- exit status -------------------------------------------------------------


def test_exit_nonzero_while_any_case_is_not_pass_or_approved(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(
        tmp_path,
        repo,
        {
            "ACC-001": ["checks/test_ok.py"],
            "ACC-002": ["checks/test_ok.py"],
            "ACC-010": ["checks/test_ok.py"],
        },
    )
    assert _by_id(record)["ACC-010b"]["status"] == "not_run"
    assert proc.returncode == 1
    assert record["overall_status"] != "pass"


def test_exit_zero_when_every_case_passes_or_is_approved(tmp_path):
    repo = _make_repo(tmp_path)
    proc, record = _run(
        tmp_path,
        repo,
        {
            "ACC-001": ["checks/test_ok.py"],
            "ACC-002": ["checks/test_ok.py"],
            "ACC-010": ["checks/test_ok.py"],
        },
        approvals=[
            {"id": "ACC-010b", "reason": "covered elsewhere", "approver": "owner"}
        ],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert record["overall_status"] == "pass"


# --- the record --------------------------------------------------------------


def test_record_fields_and_commit_is_head(tmp_path):
    repo = _make_repo(tmp_path)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    proc, record = _run(tmp_path, repo, {"ACC-001": ["checks/test_ok.py"]})
    assert record is not None
    for key in (
        "record_format_version",
        "record_id",
        "generated_at",
        "source",
        "checks",
        "overall_status",
        "approvals",
        "missing_checks",
    ):
        assert key in record, key
    assert record["record_id"]
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d", record["generated_at"])
    assert record["source"]["commit"] == head
    assert record["source"]["worktree_clean"] is True
    for c in record["checks"]:
        for key in (
            "id",
            "required",
            "status",
            "command",
            "exit_code",
            "reason",
            "tests_executed",
        ):
            assert key in c, (c.get("id"), key)
        assert c["required"] is True


def test_record_marks_dirty_worktree(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo / "docs" / "acceptance" / "A.md", DOC_A + "edit\n")
    proc, record = _run(tmp_path, repo, {})
    assert record is not None
    assert record["source"]["worktree_clean"] is False


def test_record_outside_git_has_null_commit(tmp_path):
    repo = _make_repo(tmp_path, git=False)
    proc, record = _run(tmp_path, repo, {})
    assert record is not None
    assert record["source"]["commit"] is None
    assert record["source"]["worktree_clean"] is None
    assert proc.returncode == 1


# --- shipped files -----------------------------------------------------------


def test_shipped_approvals_file_starts_empty():
    assert SHIPPED_APPROVALS.exists()
    assert json.loads(SHIPPED_APPROVALS.read_text()) == []


def test_shipped_registry_names_only_real_cases():
    assert SHIPPED_CHECKS.exists()
    registry = json.loads(SHIPPED_CHECKS.read_text())
    assert isinstance(registry, dict)
    real = set()
    for doc in DOCS.glob("*.md"):
        real |= set(HEADING.findall(doc.read_text(encoding="utf-8")))
    assert set(registry) <= real
    assert all(isinstance(v, list) and v for v in registry.values())


def test_make_acceptance_target_runs_the_entry():
    makefile = (REPO_ROOT / "Makefile").read_text()
    m = re.search(r"^acceptance:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert m, "Makefile has no acceptance target"
    assert "scripts/acceptance.py" in m.group(1)

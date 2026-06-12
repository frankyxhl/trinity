"""Review orchestration subcommand for Trinity.

Extracted from scripts/codex.py as part of issue #206 (module split).
codex.py imports this module and re-exports all public names so
``import codex; codex.cmd_review`` keeps working.

NOTE: write_synthesis calls codex.parse_structured_review (via lazy import)
so that monkeypatch.setattr(codex_mod, "_REVIEW_PASS_THRESHOLD", ...) in
tests still takes effect.  render_prompt likewise calls
codex._review_schema_addendum for the same reason.
"""

import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from . import provider_runtime as _provider_runtime
    from . import _review_metadata as _rm
except ImportError:
    import provider_runtime as _provider_runtime
    import _review_metadata as _rm

timestamp = _provider_runtime.timestamp

STRICT_REVIEW_OUTPUT_SCHEMA = [
    "### Findings",
    "### Decision Matrix",
    "**Weighted Average: X.X/10 - PASS/FIX**",
]
REVIEW_ONLY_INSTRUCTION = (
    "## Review-Only Mode\n\n"
    "Do not run tests, shell commands, network calls, or mutate files unless the "
    "instructions in this review prompt explicitly ask you to. Base findings only "
    "on the provided diff, file snapshots, and review context.\n"
)
STRICT_REVIEW_TEMPLATES = {
    ("COR-1602", "COR-1609"): {
        "pass_threshold": 9.0,
        "decision_rule": (
            "PASS when weighted_average >= 9.0 and no blocking findings remain; "
            "otherwise FIX."
        ),
        "calibration": "COR-1611",
        "rubric_title": "CHG Review Scoring",
        "criteria": [
            ("Correctness", "25%", "Change is technically sound and feasible."),
            ("Completeness", "25%", "CHG covers scope, risks, verification, and docs."),
            (
                "TDD Plan Quality",
                "20%",
                "Plan uses RED/GREEN/REFACTOR where code changes are involved.",
            ),
            ("Consistency", "15%", "Fits local conventions and related COR/TRN docs."),
            ("Rollback Safety", "15%", "Rollback path and blast radius are clear."),
        ],
        "non_code_note": (
            "For non-code CHGs where TDD is not applicable, redistribute the TDD "
            "weight to Completeness (35%) and Consistency (25%)."
        ),
    }
}


def scope_pathspec(root, scope):
    if not scope or scope == ".":
        return []
    candidate = (root / scope).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return []
    if candidate.exists():
        return [scope]
    return []


def git_diff(root, pathspec):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    args = ["diff", "--no-ext-diff", "--binary", "HEAD", "--"]
    return _codex.run_git(root, args + pathspec, allow_error=True)


def git_diff_range(root, base, head, pathspec):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    args = ["diff", "--no-ext-diff", "--binary", f"{base}...{head}", "--"]
    return _codex.run_git(root, args + pathspec)


def changed_paths(root, pathspec):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    args = ["diff", "--name-only", "--diff-filter=ACMRT", "HEAD", "--"]
    output = _codex.run_git(root, args + pathspec, allow_error=True)
    return [line for line in output.splitlines() if line.strip()]


def changed_paths_range(root, base, head, pathspec):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    args = ["diff", "--name-only", "--diff-filter=ACMRT", f"{base}...{head}", "--"]
    output = _codex.run_git(root, args + pathspec)
    return [line for line in output.splitlines() if line.strip()]


def untracked_paths(root, pathspec):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    args = ["ls-files", "--others", "--exclude-standard", "--"]
    output = _codex.run_git(root, args + pathspec, allow_error=True)
    return [line for line in output.splitlines() if line.strip()]


def is_text_file(path):
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" not in sample


def read_text_file(path, max_bytes=200000):
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if b"\0" in data:
        return "[binary file omitted]"
    if len(data) > max_bytes:
        head = data[:max_bytes].decode("utf-8", errors="replace")
        return head + "\n[truncated: file exceeds max snapshot bytes]\n"
    return data.decode("utf-8", errors="replace")


def read_text_file_at_ref(root, ref, rel, max_bytes=200000):
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    data = result.stdout
    if b"\0" in data:
        return "[binary file omitted]"
    if len(data) > max_bytes:
        head = data[:max_bytes].decode("utf-8", errors="replace")
        return head + "\n[truncated: file exceeds max snapshot bytes]\n"
    return data.decode("utf-8", errors="replace")


def synthetic_untracked_diff(root, paths):
    chunks = []
    for rel in paths:
        path = root / rel
        if not path.is_file() or not is_text_file(path):
            chunks.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n")
            chunks.append(
                "--- /dev/null\n+++ b/{0}\n[binary or unreadable]\n".format(rel)
            )
            continue
        lines = read_text_file(path).splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                [],
                lines,
                fromfile="/dev/null",
                tofile=f"b/{rel}",
            )
        )
    return "".join(chunks)


def file_snapshots(root, paths):
    if not paths:
        return "(no changed or untracked file snapshots)\n"

    chunks = []
    seen = set()
    for rel in paths:
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        chunks.append(f"### {rel}\n\n")
        if not path.exists():
            chunks.append("[deleted]\n\n")
            continue
        if path.is_dir():
            chunks.append("[directory omitted]\n\n")
            continue
        content = read_text_file(path)
        chunks.append("```text\n")
        chunks.append(content)
        if content and not content.endswith("\n"):
            chunks.append("\n")
        chunks.append("```\n\n")
    return "".join(chunks)


def file_snapshots_at_ref(root, paths, ref):
    if not paths:
        return "(no changed file snapshots)\n"

    chunks = []
    seen = set()
    for rel in paths:
        if rel in seen:
            continue
        seen.add(rel)
        chunks.append(f"### {rel}\n\n")
        content = read_text_file_at_ref(root, ref, rel)
        if content is None:
            chunks.append("[deleted]\n\n")
            continue
        chunks.append("```text\n")
        chunks.append(content)
        if content and not content.endswith("\n"):
            chunks.append("\n")
        chunks.append("```\n\n")
    return "".join(chunks)


def review_input_sha256(diff, files):
    payload = json.dumps(
        {"diff": diff, "files": files},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_review_input(diff, files, metadata):
    metadata = dict(metadata)
    metadata["review_input_sha256"] = review_input_sha256(diff, files)
    return {"diff": diff, "files": files, "metadata": metadata}


def working_tree_review_input(root, scope):
    pathspec = scope_pathspec(root, scope)
    tracked_diff = git_diff(root, pathspec)
    untracked = untracked_paths(root, pathspec)
    untracked_diff = synthetic_untracked_diff(root, untracked)
    diff = (
        tracked_diff
        + ("\n" if tracked_diff and untracked_diff else "")
        + (untracked_diff)
    )
    paths = changed_paths(root, pathspec) + untracked
    files = file_snapshots(root, paths)
    if not diff.strip():
        diff = "(no tracked or untracked git diff)"
    return make_review_input(
        diff,
        files,
        {
            "mode": "working-tree",
            "base": "HEAD",
            "head": "working-tree",
            "pr": None,
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": "working-tree",
        },
    )


def base_head_review_input(root, base, head, scope):
    pathspec = scope_pathspec(root, scope)
    try:
        diff = git_diff_range(root, base, head, pathspec)
        paths = changed_paths_range(root, base, head, pathspec)
    except RuntimeError as exc:
        raise SystemExit(
            f"trinity-codex: unable to collect git diff for {base}...{head}: {exc}"
        ) from exc
    files = file_snapshots_at_ref(root, paths, head)
    if not diff.strip():
        diff = f"(no git diff for {base}...{head})"
    return make_review_input(
        diff,
        files,
        {
            "mode": "base-head",
            "base": base,
            "head": head,
            "pr": None,
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": f"git:{head}",
        },
    )


def run_gh(root, args, label):
    try:
        result = subprocess.run(
            ["gh"] + args,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "trinity-codex: gh command not found; install/authenticate gh for --pr"
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "gh command failed"
        raise SystemExit(f"trinity-codex: {label} failed: {detail}")
    return result.stdout


def gh_pr_view(root, pr_number):
    output = run_gh(
        root,
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,url,baseRefName,headRefName,headRefOid,files",
        ],
        f"gh pr view {pr_number}",
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"trinity-codex: invalid gh pr view JSON: {exc}")


def gh_pr_diff(root, pr_number):
    return run_gh(
        root,
        ["pr", "diff", str(pr_number), "--patch", "--color", "never"],
        f"gh pr diff {pr_number}",
    )


def git_commit_exists(root, ref):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def ensure_pr_head_available(root, pr_number, head_oid):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    if not head_oid:
        return None
    if git_commit_exists(root, head_oid):
        return head_oid
    _codex.run_git(
        root,
        ["fetch", "--quiet", "origin", f"pull/{pr_number}/head"],
        allow_error=True,
    )
    if git_commit_exists(root, head_oid):
        return head_oid
    return None


def pr_changed_paths(view):
    paths = []
    for item in view.get("files", []) or []:
        path = item.get("path")
        if path:
            paths.append(path)
    return paths


def pr_review_input(root, pr_number, scope):
    view = gh_pr_view(root, pr_number)
    diff = gh_pr_diff(root, pr_number)
    paths = pr_changed_paths(view)
    head_oid = view.get("headRefOid")
    snapshot_ref = ensure_pr_head_available(root, pr_number, head_oid)
    if snapshot_ref:
        files = file_snapshots_at_ref(root, paths, snapshot_ref)
        snapshot_source = f"git:{snapshot_ref}"
    else:
        files = "(PR head snapshots unavailable locally)\n"
        snapshot_source = "unavailable"
    if not diff.strip():
        diff = f"(no GitHub PR diff for PR #{pr_number})"
    return make_review_input(
        diff,
        files,
        {
            "mode": "pr",
            "base": view.get("baseRefName"),
            "head": view.get("headRefName"),
            "head_oid": head_oid,
            "pr": int(view.get("number") or pr_number),
            "pr_url": view.get("url"),
            "scope": scope or ".",
            "changed_paths": paths,
            "snapshot_source": snapshot_source,
        },
    )


def resolve_review_input(args, root):
    if args.pr is not None:
        return pr_review_input(root, args.pr, args.scope)
    if args.base or args.head:
        if not args.base or not args.head:
            raise SystemExit("trinity-codex: --base and --head must be used together")
        return base_head_review_input(root, args.base, args.head, args.scope)
    return working_tree_review_input(root, args.scope)


def normalize_review_doc_id(value, flag):
    normalized = (value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}-\d{4}", normalized):
        raise SystemExit(f"trinity: {flag} must look like COR-1602")
    return normalized


def strict_review_metadata(sop, rubric, template):
    return {
        "enabled": True,
        "sop": sop,
        "rubric": rubric,
        "pass_threshold": template["pass_threshold"],
        "calibration": template["calibration"],
        "decision_rule": template["decision_rule"],
        "output_schema": list(STRICT_REVIEW_OUTPUT_SCHEMA),
    }


def resolve_strict_review(args):
    if bool(args.sop) != bool(args.rubric):
        raise SystemExit("trinity: --sop and --rubric must be used together")
    if not args.sop and not args.rubric:
        return None

    sop = normalize_review_doc_id(args.sop, "--sop")
    rubric = normalize_review_doc_id(args.rubric, "--rubric")
    template = STRICT_REVIEW_TEMPLATES.get((sop, rubric))
    if template is None:
        raise SystemExit(
            f"trinity: unsupported strict review template: SOP {sop} with rubric {rubric}"
        )
    metadata = strict_review_metadata(sop, rubric, template)
    return {**metadata, "template": template}


def render_strict_review_instructions(strict_review):
    template = strict_review["template"]
    lines = [
        "## Strict COR Review Mode",
        "",
        f"SOP: {strict_review['sop']}",
        f"Rubric: {strict_review['rubric']} ({template['rubric_title']})",
        f"Calibration: {strict_review['calibration']}",
        f"PASS threshold: {strict_review['pass_threshold']:.1f}/10",
        "",
        "Follow the SOP workflow and score the artifact with this rubric:",
        "",
        "| Criterion | Weight | Scoring focus |",
        "|-----------|--------|---------------|",
    ]
    for criterion, weight, focus in template["criteria"]:
        lines.append(f"| {criterion} | {weight} | {focus} |")

    matrix_rows = [
        f"| {criterion} | {weight} | X.X | ... |"
        for criterion, weight, _focus in template["criteria"]
    ]
    lines.extend(
        [
            "",
            template["non_code_note"],
            "",
            "Use COR-1611 calibration: cite every deduction, distinguish blocking "
            "findings from advisory improvements, and reserve 10/10 for zero "
            "remaining improvements.",
            "",
            "Required output:",
            "",
            "### Findings",
            "",
            "- List each finding with severity, file/path reference when applicable, "
            "and whether it is blocking or advisory.",
            "",
            "### Decision Matrix",
            "",
            "| Criterion | Weight | Score | Rationale |",
            "|-----------|--------|-------|-----------|",
            *matrix_rows,
            "",
            "**Weighted Average: X.X/10 - PASS/FIX**",
            "",
            template["decision_rule"],
        ]
    )
    return "\n".join(lines) + "\n"


def render_prompt(
    config, root, scope, review_input, strict_review=None, *, task_type=None
):
    # Lazy import to pick up monkeypatched _REVIEW_PASS_THRESHOLD from codex.
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex

    diff = review_input["diff"]
    files = review_input["files"]
    template = config.get("review", {}).get("prompt_template", "{diff}\n\n{files}\n")
    prompt = (
        template.replace("{scope}", scope or ".")
        .replace("{root}", str(root))
        .replace("{diff}", diff)
        .replace("{files}", files)
    )
    if strict_review is None:
        base = REVIEW_ONLY_INSTRUCTION + "\n" + prompt
    else:
        base = (
            render_strict_review_instructions(strict_review)
            + "\n"
            + REVIEW_ONLY_INSTRUCTION
            + "\n## Review Artifact\n\n"
            + prompt
        )
    # TRN-3022: schema addendum appended AFTER all other sections so
    # the "LAST in your output" instruction is truly at the bottom.
    return base + _codex._review_schema_addendum(task_type, strict_review=strict_review)


def slugify(value):
    value = value.strip() or "review"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-") or "review"


def make_review_dir(out_dir, scope):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(out_dir).expanduser()
    slug = slugify(scope)
    for index in range(100):
        suffix = f"{stamp}-{slug}" if index == 0 else f"{stamp}-{slug}-{index}"
        review_dir = base / suffix
        try:
            review_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (review_dir / "raw").mkdir()
        (review_dir / "logs").mkdir()
        return review_dir
    raise SystemExit("trinity-codex: unable to create unique review directory")


def review_parallelism(config, providers):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex
    review_config = _codex.review_section(config)
    raw_value = review_config.get("max_parallel_providers")
    if raw_value is None:
        return len(providers)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise SystemExit(
            "trinity: review.max_parallel_providers must be an integer "
            f"between 1 and {len(providers)}"
        )
    if raw_value < 1 or raw_value > len(providers):
        raise SystemExit(
            f"trinity: review.max_parallel_providers must be between 1 and {len(providers)}"
        )
    return raw_value


def ordered_subset(providers, selected):
    selected = set(selected)
    ordered = [provider for provider in providers if provider in selected]
    ordered.extend(sorted(selected.difference(providers)))
    return ordered


def ordered_cleanup(providers, cleanup):
    payload = {
        provider: cleanup[provider] for provider in providers if provider in cleanup
    }
    for provider in sorted(set(cleanup).difference(payload)):
        payload[provider] = cleanup[provider]
    return payload


def write_incomplete(
    review_dir,
    status,
    providers,
    started_providers,
    cleanup,
    message=None,
):
    cleanup_payload = ordered_cleanup(providers, cleanup)
    payload = {
        "status": status,
        "timestamp": timestamp(),
        "review_dir": str(review_dir),
        "providers_selected": providers,
        "providers_started": ordered_subset(providers, started_providers),
        "providers_running_at_cleanup": ordered_subset(providers, cleanup),
        "cleanup": cleanup_payload,
    }
    if message:
        payload["message"] = message
    (review_dir / "incomplete.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )


def _sanitize_md(text):
    """Strip embedded newlines from Markdown-rendered finding fields."""
    return text.replace("\n", " ") if "\n" in text else text


def _render_finding_items(label, items):
    """Render a labeled list of finding items (blocking or advisories).

    Returns a list of lines including the **Label:** header, one bullet per
    item, and a trailing blank line. Returns an empty list if items is empty.
    """
    if not items:
        return []
    lines = [f"**{label}:**"]
    for item in items:
        title = _sanitize_md(item.get("title", ""))
        evidence = _sanitize_md(item.get("evidence", ""))
        fix = item.get("fix")
        if fix:
            fix = _sanitize_md(fix)
        if evidence:
            line = f"- **{title}** at `{evidence}`"
        else:
            line = f"- **{title}** (no evidence cited)"
        if fix:
            line += f" — {fix}"
        lines.append(line)
    lines.append("")
    return lines


def _render_findings_for(result, parsed):
    """Render a single provider's structured findings block.

    Returns a list of lines for the Findings section, or an empty list
    if the provider has no findings to render (structured-but-clean).
    """
    provider = result["provider"]
    eff = parsed["effective_decision"]
    score = parsed["weighted_score"]
    blocking = parsed.get("blocking", [])
    advisories = parsed.get("advisories", [])
    lines = []
    lines.append(
        f"### {provider} — {eff} "
        f"({score}, {len(blocking)} blocking, {len(advisories)} advisories)"
    )
    lines.append("")
    lines.extend(_render_finding_items("Blocking", blocking))
    lines.extend(_render_finding_items("Advisories", advisories))
    return lines


def _compute_summary(results, parsed_per_provider):
    """Aggregate counts + verdict from per-provider results.

    Returns dict with: verdict, n_pass, n_fix, n_fail, total, mean_score
    (or None), n_blocking, n_advisories, convergence_count.
    """
    n_pass = n_fix = n_fail = 0
    scores = []
    n_blocking = 0
    n_advisories = 0
    title_provider_pairs = []  # (title, provider_name) — for convergence

    for i, result in enumerate(results):
        rc = result.get("returncode", -1)
        if rc != 0:
            n_fail += 1
            continue
        parsed = parsed_per_provider[i]
        if parsed is None:
            n_pass += 1  # legacy rc=0 PASS
            continue
        eff = parsed.get("effective_decision", parsed.get("decision"))
        if eff == "FIX":
            n_fix += 1
        else:
            n_pass += 1
        scores.append(parsed.get("weighted_score"))
        prov = result["provider"]
        for item in parsed.get("blocking", []):
            n_blocking += 1
            title = (item.get("title") or "").strip()
            if title:
                title_provider_pairs.append((title, prov))
        for item in parsed.get("advisories", []):
            n_advisories += 1
            title = (item.get("title") or "").strip()
            if title:
                title_provider_pairs.append((title, prov))

    total = len(results)
    has_structured = any(p is not None for p in parsed_per_provider)

    # Convergence: distinct titles appearing across >=2 distinct providers.
    title_to_providers = {}
    for title, prov in title_provider_pairs:
        title_to_providers.setdefault(title, set()).add(prov)
    convergence_count = sum(
        1 for provs in title_to_providers.values() if len(provs) >= 2
    )

    # Verdict precedence: INCONCLUSIVE > LEGACY > NEEDS_FIXES > ALL_PASS.
    if n_fail > 0:
        verdict = "INCONCLUSIVE"
    elif not has_structured:
        verdict = "LEGACY"
    elif n_fix > 0:
        verdict = "NEEDS_FIXES"
    else:
        verdict = "ALL_PASS"

    valid_scores = [s for s in scores if isinstance(s, (int, float))]
    mean_score = sum(valid_scores) / len(valid_scores) if valid_scores else None

    return {
        "verdict": verdict,
        "n_pass": n_pass,
        "n_fix": n_fix,
        "n_fail": n_fail,
        "total": total,
        "mean_score": mean_score,
        "n_blocking": n_blocking,
        "n_advisories": n_advisories,
        "convergence_count": convergence_count,
    }


def _render_summary_block(summary):
    """Render the aggregate Summary section as markdown lines."""
    lines = ["## Summary", ""]
    lines.append(f"- **Verdict**: {summary['verdict']}")
    providers_line = (
        f"{summary['n_pass']}/{summary['total']} PASS · "
        f"{summary['n_fix']} FIX · "
        f"{summary['n_fail']} FAIL"
    )
    if summary["mean_score"] is not None:
        providers_line += f" (mean score {summary['mean_score']:.2f})"
    lines.append(f"- **Providers**: {providers_line}")
    if summary["verdict"] == "LEGACY":
        lines.append("- **Findings**: —")
        lines.append("- **Convergence**: —")
    else:
        lines.append(
            f"- **Findings**: {summary['n_blocking']} blocking · "
            f"{summary['n_advisories']} advisories"
        )
        conv = summary["convergence_count"]
        conv_text = f"{conv} titles flagged by ≥2 providers" if conv else "none"
        lines.append(f"- **Convergence**: {conv_text}")
    return lines


def _format_cli_summary(summary, synthesis_path):
    """One-line stderr summary for cmd_review completion."""
    providers = (
        f"{summary['n_pass']}/{summary['total']} PASS · "
        f"{summary['n_fix']} FIX · "
        f"{summary['n_fail']} FAIL"
    )
    if summary["mean_score"] is not None:
        providers += f" (mean {summary['mean_score']:.2f})"
    return (
        f"trinity review: {summary['verdict']} — "
        f"{providers} — synthesis: {synthesis_path}"
    )


def write_synthesis(review_dir, scope, results, strict_review=None):
    # TRN-3022: parse structured review schema per provider.
    # rc != 0 → FAIL <rc> regardless of structured content.
    # rc == 0 + parsed → enriched status.
    # rc == 0 + no parsed → legacy PASS.
    #
    # NOTE: calls codex.parse_structured_review (lazy import) so that
    # monkeypatch.setattr(codex_mod, "_REVIEW_PASS_THRESHOLD", ...) works.
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex

    try:
        from . import review_schema as _review_schema
    except ImportError:
        import review_schema as _review_schema

    parsed_per_provider = []
    for result in results:
        rc = result.get("returncode", -1)
        if rc == 0:
            raw_path = review_dir / result["raw"]
            raw_text = _review_schema._safe_read_raw(raw_path)
            if raw_text is not None:
                parsed_per_provider.append(
                    _codex.parse_structured_review(
                        raw_text,
                        pass_threshold=strict_review["pass_threshold"]
                        if strict_review
                        else None,
                    )
                )
            else:
                parsed_per_provider.append(None)
        else:
            parsed_per_provider.append(None)

    any_structured = any(p is not None for p in parsed_per_provider)

    summary = _compute_summary(results, parsed_per_provider)
    summary_lines = _render_summary_block(summary)

    # Legacy path: same Provider Status table + Notes shape as pre-TRN-3022,
    # but TRN-3028 prepends a Summary block (verdict=LEGACY) at the top.
    if not any_structured:
        lines = [
            "# Trinity Review Synthesis",
            "",
            f"Scope: {scope or '.'}",
            "",
        ]
        lines.extend(summary_lines)
        lines.extend(
            [
                "",
                "## Provider Status",
                "",
                "| Provider | Status | Raw Output |",
                "|----------|--------|------------|",
            ]
        )
        for result in results:
            status = (
                "PASS" if result["returncode"] == 0 else f"FAIL {result['returncode']}"
            )
            lines.append(f"| {result['provider']} | {status} | `{result['raw']}` |")
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
                "",
            ]
        )
        path = review_dir / "synthesis.md"
        path.write_text("\n".join(lines) + "\n")
        return summary, path

    # Enriched path: at least one provider has structured output.
    lines = [
        "# Trinity Review Synthesis",
        "",
        f"Scope: {scope or '.'}",
        "",
    ]
    lines.extend(summary_lines)
    lines.extend(
        [
            "",
            "## Provider Status",
            "",
            "| Provider | Status | Raw Output |",
            "|----------|--------|------------|",
        ]
    )
    for i, result in enumerate(results):
        rc = result.get("returncode", -1)
        if rc != 0:
            # Returncode precedence: rc wins regardless of structured content.
            status = f"FAIL {rc}"
        else:
            parsed = parsed_per_provider[i]
            if parsed is not None:
                eff = parsed["effective_decision"]
                score = parsed["weighted_score"]
                n_blocking = len(parsed.get("blocking", []))
                if eff == "FIX":
                    status = f"FIX ({score}, {n_blocking} blocking)"
                else:
                    status = f"PASS ({score})"
            else:
                status = "PASS"
        lines.append(f"| {result['provider']} | {status} | `{result['raw']}` |")

    # Findings section — only rc=0 providers with parsed results.
    has_findings = False
    for i, result in enumerate(results):
        parsed = parsed_per_provider[i]
        rc = result.get("returncode", -1)
        if rc == 0 and parsed is not None:
            if not has_findings:
                lines.append("")
                lines.append("## Findings")
                lines.append("")
                has_findings = True
            lines.extend(_render_findings_for(result, parsed))

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This synthesis is deterministic. Inspect raw provider outputs for findings and conflicts.",
            "",
        ]
    )
    path = review_dir / "synthesis.md"
    path.write_text("\n".join(lines) + "\n")
    return summary, path


def cmd_review(args):
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex

    _codex.progress("preparing review prompt")
    root = _codex.resolve_root(args.root)
    config = _codex.load_config(args.config)
    providers, preset_metadata, resolver_warnings = _codex.resolve_review_providers(
        args, config
    )
    strict_review = resolve_strict_review(args)
    for warning in resolver_warnings:
        print(warning, file=sys.stderr)
    provider_configs = config.get("providers", {})
    health = _codex.provider_health_results(config, providers, root)
    if args.check_providers:
        print(_codex.format_health_results(health))
        return 0 if _codex.health_results_ok(health) else 1
    if not _codex.health_results_ok(health):
        print(_codex.format_health_results(health), file=sys.stderr)
        return 1
    max_workers = review_parallelism(config, providers)
    review_input = resolve_review_input(args, root)

    out_base = args.out_dir or config.get("review", {}).get(
        "output_dir", ".trinity/reviews"
    )
    out_base = Path(out_base)
    if not out_base.is_absolute():
        out_base = root / out_base
    review_dir = make_review_dir(out_base, args.scope)

    try:
        prompt = render_prompt(
            config,
            root,
            args.scope,
            review_input,
            strict_review,
            task_type=preset_metadata.get("task_type") if preset_metadata else None,
        )
        prompt_path = review_dir / "prompt.md"
        _codex.progress("writing prompt")
        prompt_path.write_text(prompt)
        # TRN-2018 M1: write metadata.json with all providers queued BEFORE
        # run_providers. This gives `trinity status --latest` a live view
        # while providers run, instead of waiting until completion.
        # R5 fix (codex R5 P2): strict_review threaded into the initial
        # atomic write — finalize_metadata mutates only finished_at /
        # results / status / provider_states, so strict_review survives
        # through the post-run update without a separate write_text that
        # would race readers.
        strict_review_block = (
            {key: value for key, value in strict_review.items() if key != "template"}
            if strict_review is not None
            else None
        )
        _rm.init_metadata(
            review_dir,
            review_id=review_dir.name,
            review_dir_str=str(review_dir),
            providers=providers,
            preset=preset_metadata,
            scope=args.scope,
            root=str(root),
            input=review_input["metadata"],
            strict_review=strict_review_block,
        )
        results = _codex.run_providers(
            max_workers,
            providers,
            provider_configs,
            prompt_path,
            review_dir,
            root,
        )
        # TRN-2018 R7 fix (codex R6 P2): per CHG L88-89, top-level
        # `finished_at` stays null until synthesis.md is written.
        # finalize_metadata must run AFTER write_synthesis succeeds so
        # a concurrent `trinity status` poll never observes
        # status=finished while synthesis.md is missing. If
        # write_synthesis raises, finalize is skipped; the exception
        # handler writes incomplete.json and metadata.json stays in
        # `status=running` for the partial review.
        _codex.progress("writing synthesis")
        summary, synthesis_path = write_synthesis(
            review_dir, args.scope, results, strict_review=strict_review
        )
        _codex.progress("writing metadata")
        _rm.finalize_metadata(review_dir, results)
        # TRN-3028: emit the completion line directly to stderr without the
        # `trinity: ` progress prefix so callers can key off the documented
        # "trinity review: <verdict> — ..." prefix at the START of the line.
        print(_format_cli_summary(summary, synthesis_path), file=sys.stderr)
    except KeyboardInterrupt:
        started_providers = providers if "results" in locals() else []
        write_incomplete(review_dir, "interrupted", providers, started_providers, {})
        print(review_dir)
        return 130
    except _codex.ReviewInterrupted as exc:
        write_incomplete(
            review_dir,
            "interrupted",
            providers,
            exc.started_providers,
            exc.cleanup,
        )
        print(review_dir)
        return 130
    except _codex.ReviewOrchestrationError as exc:
        write_incomplete(
            review_dir,
            "failed",
            providers,
            exc.started_providers,
            exc.cleanup,
            str(exc),
        )
        print(review_dir)
        return 1
    except Exception as exc:
        started_providers = providers if "results" in locals() else []
        write_incomplete(
            review_dir, "failed", providers, started_providers, {}, str(exc)
        )
        print(review_dir)
        return 1

    print(review_dir)
    return 0 if all(item["returncode"] == 0 for item in results) else 1

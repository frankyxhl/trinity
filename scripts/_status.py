"""Status subcommand for Trinity.

Extracted from scripts/codex.py as part of issue #206 (module split).
codex.py imports this module and re-exports all public names so
``import codex; codex.cmd_status`` keeps working.
"""

import datetime as dt
import json
import sys


def _format_elapsed(started_iso, finished_iso):
    """Compute elapsed seconds between two ISO timestamps, clamped to >= 0.

    `make_review_dir` writes timestamps via `dt.datetime.now().isoformat(...)`
    (naive local time). On fall-back DST a sub-hour run straddling the
    transition can produce finished < started → negative elapsed. Clamp to
    `max(0, ...)` to defend against that without introducing tz handling.
    Returns None if either timestamp is missing or unparseable.
    """
    if not started_iso or not finished_iso:
        return None
    try:
        s = dt.datetime.fromisoformat(started_iso)
        f = dt.datetime.fromisoformat(finished_iso)
        # Subtraction inside the try too — mixed naive/offset-aware datetimes
        # raise TypeError on `f - s`. Current writer (`timestamp()`) emits
        # naive only, so this is defensive against future schema drift.
        delta = (f - s).total_seconds()
    except (TypeError, ValueError):
        return None
    return max(0, int(delta))


def _format_duration(seconds):
    """Render seconds as 'Xm YYs' / 'Ys' / '?' for None."""
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _format_ago(now_iso, then_iso):
    """Render a coarse 'N ago' string. Returns '?' if either is missing."""
    secs = _format_elapsed(then_iso, now_iso)
    if secs is None:
        return "?"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _print_incomplete_only_summary(review_dir, incomplete_path):
    """Render a summary for an interrupted review (no metadata.json yet).

    cmd_review writes incomplete.json from its KeyboardInterrupt /
    ReviewInterrupted / ReviewOrchestrationError handlers BEFORE the
    metadata.json write would have happened, so an interrupted review has
    only incomplete.json. This path renders what's available.
    """
    try:
        incomplete = json.loads(incomplete_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"trinity: malformed incomplete.json at {incomplete_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    status = incomplete.get("status", "interrupted")
    when = incomplete.get("timestamp", "?")
    providers_sel = incomplete.get("providers_selected", []) or []
    providers_started = incomplete.get("providers_started", []) or []
    providers_running = incomplete.get("providers_running_at_cleanup", []) or []
    cleanup = incomplete.get("cleanup", {}) or {}
    message = incomplete.get("message")

    # cmd_review writes status="interrupted" (KeyboardInterrupt /
    # ReviewInterrupted) or status="failed" (ReviewOrchestrationError /
    # bare Exception). Use the stored status as the top-level label so
    # orchestration failures aren't misrendered as user interruptions.
    print(f"Latest review: {review_dir}  ({status} at {when})")
    print(f"  Status: {status}")
    print()
    print(f"  Providers selected: {', '.join(providers_sel) or '(none)'}")
    print(f"  Providers started:  {', '.join(providers_started) or '(none)'}")
    if providers_running:
        print(f"  Running at cleanup: {', '.join(providers_running)}")
    if cleanup:
        # cleanup_active_processes() (scripts/codex.py:1050) writes
        # {"pid": ..., "result": "terminated"|"killed"|"kill_timeout"}
        # per provider. Read 'result' not 'status'.
        cleanup_lines = ", ".join(
            f"{name}: {info if isinstance(info, str) else info.get('result', '?')}"
            for name, info in cleanup.items()
        )
        print(f"  Cleanup: {cleanup_lines}")
    if message:
        print(f"  Message: {message}")
    print()
    print("  (metadata.json not present — review never reached completion)")
    return 0


def _print_review_summary(review_dir):
    """Render a one-screen summary of one review directory. Returns rc."""
    metadata_path = review_dir / "metadata.json"
    incomplete_path = review_dir / "incomplete.json"

    # An interrupted review never reaches the metadata-write step in
    # cmd_review — incomplete.json exists by itself with the structural
    # state. If that's the case, render from incomplete.json alone rather
    # than bailing with "no metadata", since this is the exact artifact
    # the user most wants summarized.
    if not metadata_path.exists() and incomplete_path.exists():
        return _print_incomplete_only_summary(review_dir, incomplete_path)

    if not metadata_path.exists():
        print(
            f"trinity: review in progress or no metadata at {metadata_path}",
            file=sys.stderr,
        )
        return 1
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"trinity: malformed metadata at {metadata_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    # All field reads are defensive — pre-TRN-2019 metadata may lack newer
    # keys (preset, skipped_optional_providers, input.mode).
    scope = metadata.get("scope", "?")
    mode = metadata.get("input", {}).get("mode", "?")
    preset = metadata.get("preset", {}).get("resolved", "?")
    skipped = metadata.get("preset", {}).get("skipped_optional_providers", [])
    results = metadata.get("results", [])

    # "started Xm ago" — earliest started_at across results, vs now.
    # TRN-2018 R3 fix (codex R2 P2): when M1 metadata is mid-review (results
    # still empty because run_providers hasn't finished), fall back to the
    # top-level `started_at` written by init_metadata so the header doesn't
    # render "started ?" in the exact state the live-status feature is for.
    started_isos = [r.get("started_at") for r in results if r.get("started_at")]
    earliest = min(started_isos) if started_isos else metadata.get("started_at")
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    ago = _format_ago(now_iso, earliest) if earliest else "?"

    print(f"Latest review: {review_dir}  (started {ago})")
    print(f"  Scope: {scope}   Mode: {mode}   Preset: {preset}")
    print()
    # TRN-2018 M1: live provider_states section. Rendered when the metadata
    # was written by init_metadata/update_provider_state (M1+ reviews).
    # Pre-M1 metadata lacks this key; rendering falls through to the legacy
    # `Providers:` section below.
    provider_states = metadata.get("provider_states")
    if provider_states:
        print("  Live state:")
        ls_name_width = max([10] + [len(p) for p in provider_states.keys()])
        for prov, state in provider_states.items():
            status_str = state.get("status", "?")
            bits = [f"{prov:{ls_name_width}s}", status_str]
            pid = state.get("pid")
            if pid is not None:
                bits.append(f"pid={pid}")
            rc = state.get("returncode")
            if rc is not None:
                bits.append(f"rc={rc}")
            # TRN-2018 R4 fix (codex R3 P2): for currently-running providers,
            # finished_at is absent; use `now` as the end time so the row
            # shows elapsed-so-far. Terminal states use their finished_at.
            end_iso = state.get("finished_at") or (
                now_iso if status_str == "running" else None
            )
            ls_elapsed = _format_duration(
                _format_elapsed(state.get("started_at"), end_iso)
            )
            if ls_elapsed and ls_elapsed != "?":
                bits.append(f"elapsed {ls_elapsed}")
            print("    " + "  ".join(bits))
        print()
    print("  Providers:")
    if not results:
        print("    (no results in metadata)")
    # Column width = max provider name length (or 10, whichever is larger).
    # Defends against `claude-code` (11 chars) and any future longer name
    # shifting the rest of the columns out of alignment.
    name_width = max([10] + [len(r.get("provider", "?")) for r in results])
    for r in results:
        name = r.get("provider", "?")
        rc = r.get("returncode")
        rc_str = "?" if rc is None else f"rc={rc}"
        marker = "✓" if rc == 0 else "✗"
        elapsed = _format_elapsed(r.get("started_at"), r.get("finished_at"))
        elapsed_str = _format_duration(elapsed)
        suffix = " (timeout)" if rc == 124 else ""
        print(
            f"    {name:{name_width}s} {marker} {rc_str:8s} elapsed {elapsed_str}{suffix}"
        )
    print()
    if skipped:
        skipped_str = ", ".join(
            f"{s.get('provider', '?')} ({s.get('reason', '?')})" for s in skipped
        )
        print(f"  Skipped optional: {skipped_str}")
    synthesis_path = review_dir / "synthesis.md"
    incomplete_path = review_dir / "incomplete.json"
    if synthesis_path.exists():
        print("  Synthesis: ✓ synthesis.md")
    else:
        print("  Synthesis: missing")
    incomplete_status = None
    if incomplete_path.exists():
        try:
            incomplete = json.loads(incomplete_path.read_text())
            incomplete_status = incomplete.get("status", "interrupted")
        except (json.JSONDecodeError, OSError):
            incomplete_status = "interrupted"
        print(f"  Incomplete: ✓ incomplete.json (status={incomplete_status})")

    # Final status line.
    if incomplete_status is not None:
        # Use the stored status directly. cmd_review writes status=
        # "interrupted" (KeyboardInterrupt / ReviewInterrupted) or
        # "failed" (ReviewOrchestrationError / bare Exception) — see
        # scripts/codex.py:1370-1402. Hard-coding "interrupted" here
        # would mislabel an exception-after-metadata-write (e.g. inside
        # write_synthesis()) as a user interruption.
        overall = incomplete_status
    elif metadata.get("status") == "running":
        # TRN-2018 R4 fix (codex R3 P2): when M1's top-level status is
        # `running`, a partial `results[]` (one provider finished while
        # another is still queued/running) must NOT report `completed`.
        # The live state is authoritative — defer to it until terminal.
        overall = "running"
    elif metadata.get("status") in ("failed", "timed_out", "finished"):
        # M1 terminal: top-level status is authoritative (correctly accounts
        # for failed/timed_out providers via finalize_metadata precedence).
        overall = metadata["status"]
    elif not results:
        # Pre-M1 with no results (or M1 without a top-level status set,
        # which shouldn't happen but is defended).
        overall = "unknown (no results)"
    elif any(r.get("returncode") != 0 for r in results):
        # Pre-M1 path: any non-success rc → partial.
        overall = "partial"
    else:
        # Pre-M1 path: all-zero results → completed.
        overall = "completed"
    print(f"  Status: {overall}")
    return 0


def cmd_status(args):
    # Resolve to git top-level (with non-git fallback) so `trinity status`
    # works from any subdirectory, matching cmd_doctor's behavior. Without
    # this, a user running from `scripts/` would look at
    # `scripts/.trinity/reviews/` instead of the repo-root one where
    # `cmd_review` actually writes artifacts.
    try:
        from . import codex as _codex
    except ImportError:
        import codex as _codex

    root = _codex.resolve_health_root(args.root)
    reviews_dir = root / ".trinity" / "reviews"
    # TRN-2018 M1 behavior change (per CHG L154): missing or empty reviews
    # dir now exits 0 with `no reviews found` on stdout. Previous behavior:
    # exit 1 with `no reviews dir at <path>` or `no reviews under <path>`
    # on stderr. Flagged in CHANGELOG.
    if not reviews_dir.is_dir():
        print("no reviews found")
        return 0

    # Sort key: (timestamp_prefix, mtime). The fixed-width
    # %Y%m%d-%H%M%S prefix gives chronological order across distinct
    # seconds; mtime breaks ties for same-second creates where the
    # slug or numeric collision suffix (`-10` vs `-2`) doesn't preserve
    # creation order. `make_review_dir()` (scripts/codex.py:914) only
    # stamps to seconds and appends `<slug>[-<index>]`, so two reviews
    # made in the same second can have lex order != creation order.
    def _sort_key(d):
        try:
            mtime = d.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (d.name[:15], mtime)

    candidates = sorted(
        [d for d in reviews_dir.iterdir() if d.is_dir()],
        key=_sort_key,
        reverse=True,
    )
    if not candidates:
        print("no reviews found")
        return 0
    return _print_review_summary(candidates[0])

"""Tests for skills/trinity-zc — the ZCode-runtime adaptation of trinity.

trinity-zc dispatches to providers via Bash background processes instead of
Agent sub-agents (the ZCode runtime exposes only the read-only Explore
subagent). These tests guard the contract between SKILL.md's prose and the
reused trinity Python assets so that "SKILL.md says X, runtime does Y"
regressions (the class of bug that produced the setsid + sentinel-printf
defects) are caught automatically.

Three tiers (issue #264 acceptance criteria):

  1. Pure-logic (offline, fast) — sentinel format, state-store flock round-trip,
     config-overlay + dangling-preset detection.
  2. Instruction-fidelity — extract the SKILL.md dispatch step-5 bash block,
     run it literally with a stub provider, assert the output parses through
     the reused synthesis path. This is the test the setsid + printf bugs
     would have failed.
  3. Real-provider doctor — behind a ``slow`` marker, skipped by default.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Reused trinity assets (single source of truth for sentinel, schema, synthesis)
import provider_runtime  # noqa: E402
import review_schema  # noqa: E402
import _review  # noqa: E402

SKILL_MD = ROOT / "skills" / "trinity-zc" / "SKILL.md"
SESSION_PY = ROOT / "scripts" / "session.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_atomic(path: Path, data: dict) -> None:
    """Mirror session.py's flock-protected write for the trinity-zc state file."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            existing = f.read() or "{}"
            data_merged = json.loads(existing)
            data_merged.setdefault("sessions", {}).update(data.get("sessions", {}))
            f.seek(0)
            f.truncate()
            json.dump(data_merged, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _read_sessions(path: Path) -> dict:
    with open(path) as f:
        return json.load(f).get("sessions", {})


def _load_merged_config(
    global_config: dict | None = None, project_overlay: dict | None = None
) -> dict:
    """Merge a global trinity.json config with a project overlay.

    Mirrors trinity-zc's provider-discovery logic (SKILL.md §Provider Discovery).
    Pass ``global_config`` explicitly to keep the offline config-overlay tests
    deterministic and independent of the runner's real ``~/.claude/trinity.json``
    (otherwise a developer/CI image with Trinity already configured could mask or
    pollute the assertions). Pass ``None`` to read the live global config — used
    only by the live integration check.
    """
    if global_config is None:
        global_path = Path.home() / ".claude" / "trinity.json"
        global_config = (
            json.loads(global_path.read_text()) if global_path.exists() else {}
        )

    g = global_config
    proj = project_overlay or {}
    providers = {**g.get("providers", {}), **proj.get("providers", {})}
    presets = {**g.get("presets", {}), **proj.get("presets", {})}
    return {"providers": providers, "presets": presets}


# ---------------------------------------------------------------------------
# Tier 1: Pure-logic (offline, fast)
# ---------------------------------------------------------------------------


class TestSentinelFormat:
    """AC: a dispatch output file with the literal sentinel is splittable by
    parse_structured_review."""

    def test_sentinel_constant_is_the_boundary(self):
        """The reused sentinel must be the single source of truth."""
        sentinel = provider_runtime._STDERR_SENTINEL
        assert "%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%" in sentinel
        assert sentinel.startswith("\n") and sentinel.endswith("\n")

    def test_stdout_stderr_split_round_trips(self, tmp_path):
        """raw_output() output must split back into the original stdout/stderr."""
        stdout = 'review body\n```json\n{"decision":"PASS"}\n```'
        stderr = "some warning"
        raw = (stdout or "") + provider_runtime._STDERR_SENTINEL + (stderr or "")
        parts = raw.split("%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%")
        assert len(parts) == 2
        assert parts[0].strip().endswith(stdout.strip().split("\n")[-1])
        assert parts[1].strip() == stderr

    def test_parse_structured_review_accepts_sentinel_format(self, tmp_path):
        """A full review raw (stdout + sentinel + stderr) parses to PASS."""
        decision_block = textwrap.dedent("""\
            ```json
            {"decision":"PASS","weighted_score":9.6,"blocking":[],"advisories":[]}
            ```
        """)
        raw = "All good.\n" + decision_block + provider_runtime._STDERR_SENTINEL + "\n"
        parsed = review_schema.parse_structured_review(raw)
        # parse_structured_review returns a dict (not an object)
        assert parsed["decision"] == "PASS"
        assert parsed["weighted_score"] == 9.6


class TestStateStore:
    """AC: .claude/trinity-zc.json flock-protected writes round-trip and
    tolerate concurrent multi-instance writes."""

    def test_dispatch_running_then_done_round_trip(self, tmp_path):
        state_file = tmp_path / ".claude" / "trinity-zc.json"
        key = "glm:e2e"

        # dispatch → running
        _write_atomic(
            state_file,
            {
                "sessions": {
                    key: {
                        "provider": "glm",
                        "instance": key,
                        "state": "running",
                        "task": "smoke",
                        "task_type": "general",
                        "output_file": "/tmp/x.out",
                        "cli": "droid exec ...",
                        "start_time": "2026-06-27T21:00:00",
                        "end_time": None,
                        "returncode": None,
                        "last_checked": None,
                        "bytes": 0,
                    }
                }
            },
        )
        sessions = _read_sessions(state_file)
        assert sessions[key]["state"] == "running"

        # completion → done
        sessions[key].update(
            {
                "state": "done",
                "end_time": "2026-06-27T21:00:30",
                "returncode": 0,
                "bytes": 1234,
            }
        )
        _write_atomic(state_file, {"sessions": sessions})
        final = _read_sessions(state_file)
        assert final[key]["state"] == "done"
        assert final[key]["returncode"] == 0
        assert final[key]["bytes"] == 1234

    def test_concurrent_multi_instance_writes_coexist(self, tmp_path):
        """Two instance keys written sequentially must both survive."""
        state_file = tmp_path / ".claude" / "trinity-zc.json"
        _write_atomic(state_file, {"sessions": {"codex:r1": {"state": "running"}}})
        _write_atomic(state_file, {"sessions": {"glm:r2": {"state": "running"}}})
        sessions = _read_sessions(state_file)
        assert "codex:r1" in sessions
        assert "glm:r2" in sessions


class TestConfigOverlay:
    """AC: merged config flags dangling preset references."""

    def test_dangling_preset_reference_detected(self, tmp_path):
        """A preset naming a provider absent from config is flagged."""
        # Isolated global config ({}) so detection is deterministic regardless
        # of the runner's real ~/.claude/trinity.json (P2 test-isolation fix).
        config = _load_merged_config(
            global_config={},
            project_overlay={
                "providers": {"glm": {"cli": "x", "installed": True}},
                "presets": {"bogus": {"providers": ["ghost", "glm"]}},
            },
        )
        provider_names = set(config["providers"])
        dangling = []
        for pname, pcfg in config["presets"].items():
            for ref in pcfg.get("providers", []) + pcfg.get("optional_providers", []):
                if ref not in provider_names:
                    dangling.append((pname, ref))
        assert ("bogus", "ghost") in dangling

    @pytest.mark.integration
    def test_live_global_config_has_no_dangling_refs(self):
        """The real ~/.claude/trinity.json must not reference retired providers.

        Opt-in only (`integration` marker, deselected by default): it reads the
        runner's live home config, so on a machine with unrelated stale preset
        refs it would fail `make test` even though the repo is unchanged. The
        dangling-detection *logic* is covered deterministically by
        test_dangling_preset_reference_detected.
        """
        global_path = Path.home() / ".claude" / "trinity.json"
        if not global_path.exists():
            pytest.skip("no global trinity.json")
        # Live integration check: read the real global config (global_config=None).
        config = _load_merged_config()
        provider_names = set(config["providers"])
        dangling = []
        for pname, pcfg in config["presets"].items():
            for ref in pcfg.get("providers", []) + pcfg.get("optional_providers", []):
                if ref not in provider_names:
                    dangling.append((pname, ref))
        assert dangling == [], f"global config has dangling preset refs: {dangling}"


class TestDispatchInstructionGuards:
    """Static guards for SKILL.md dispatch instructions (Codex-review P2 fixes).

    These pin prose-level contracts that have no executable surface but, if they
    regress, silently break real dispatches.
    """

    def test_run_dir_is_portable(self):
        """Run-dir must use mktemp (uuidgen is absent on minimal Linux/ZCode
        images, where `uuidgen | cut` expands to an empty suffix and parallel
        dispatches collide on one shared dir)."""
        text = SKILL_MD.read_text()
        assert "RUN_DIR=$(mktemp -d" in text, "run-dir allocation must use mktemp -d"
        assert 'RUN_DIR="/tmp/trinity-zc/$(uuidgen' not in text, (
            "run-dir reverted to the non-portable uuidgen code path"
        )

    def test_discovery_carries_preset_aliases(self):
        """The merged-config discovery snippet must carry preset_aliases so
        project-defined aliases resolve (not just hard-coded built-ins)."""
        text = SKILL_MD.read_text()
        assert 'preset_aliases = {**g.get("preset_aliases"' in text, (
            "discovery snippet drops preset_aliases — custom aliases will not resolve"
        )

    def test_discovery_carries_defaults(self):
        """The discovery snippet must carry merged `defaults` so a config-set
        defaults.timeout overrides the built-in table instead of being dropped."""
        text = SKILL_MD.read_text()
        assert 'defaults = {**g.get("defaults"' in text, (
            "discovery snippet drops defaults — config-set timeout overrides ignored"
        )

    def test_timeout_section_honors_config_defaults(self):
        """The §Timeout prose must state the table is a fallback and that a
        merged defaults.timeout override wins for its task_type."""
        text = SKILL_MD.read_text()
        assert "defaults.timeout" in text and "fallback" in text, (
            "§Timeout no longer documents the defaults.timeout override path"
        )

    def test_dispatch_parser_honors_config_aliases(self):
        """Dispatch step 2 must resolve aliases from the merged preset_aliases
        map, not only the hard-coded built-ins (r/fr/dr)."""
        text = SKILL_MD.read_text()
        assert "any key in the merged `preset_aliases` map" in text, (
            "dispatch parser ignores config preset_aliases — custom aliases "
            "report unknown despite being loaded by discovery"
        )

    def test_required_preset_providers_are_not_silently_dropped(self):
        """An unusable REQUIRED preset provider must be surfaced as a failed
        participant, not filtered out — else /trinity-zc review can PASS while
        silently missing a required reviewer (connector P2 'Do not filter
        required preset providers'; mirrors codex.py::resolve_preset_providers,
        which adds every required provider unconditionally)."""
        text = SKILL_MD.read_text()
        assert "filtered out at dispatch" not in text, (
            "Presets prose still says required providers are filtered out — "
            "trinity keeps them and surfaces the absence"
        )
        assert "Do NOT silently drop a required provider" in text, (
            "Presets prose lost the required-provider quorum guarantee"
        )
        assert "failed participant" in text, (
            "synthesis preconditions no longer require recording an undispatched "
            "required provider as a failed participant"
        )

    def test_claude_code_resume_is_honored(self):
        """claude-code has registry supports_resume:true/resume_arg:--resume, so
        the resume matrix must resume it (not bucket it into 'no resume arg')."""
        text = SKILL_MD.read_text()
        assert "deepseek **and** claude-code" in text, (
            "claude-code resume dropped — falls into the no-resume bucket despite "
            "registry supports_resume:true"
        )

    def test_fallback_kill_targets_per_run_marker(self):
        """The timeout/clear/error fallback must grep a per-run KILL_MARKER, never
        a bare '<provider-cli-token>' that could kill another project's job."""
        text = SKILL_MD.read_text()
        assert 'KILL_MARKER="trinity-zc-kill:$(basename "$RUN_DIR")"' in text, (
            "step 5 no longer tags the wrapper with a per-run KILL_MARKER"
        )
        assert "'<provider-cli-token>'" not in text, (
            "a fallback still greps the bare provider CLI token — can kill an "
            "unrelated process sharing that token"
        )
        block = _extract_step5_block()
        assert '\' "$KILL_MARKER" <cli-and-args...>' in block, (
            "the wrapper's $0 is not the KILL_MARKER, so pgrep -f cannot target it"
        )

    def test_step4_appends_task_prompt(self):
        """Step 4 must instruct that the task prompt is the final argument;
        omitting it launches the provider with no task."""
        text = SKILL_MD.read_text()
        assert "is the final argument" in text, (
            "step 4 no longer states the task prompt is the final dispatch arg"
        )

    def test_review_dispatch_appends_schema_addendum(self):
        """Review task_types must append _review_schema_addendum at DISPATCH time
        (step 4), not only as a synthesis precondition — else providers emit
        free-form output and write_synthesis takes the rc-0 legacy PASS path."""
        text = SKILL_MD.read_text()
        assert "review_schema._review_schema_addendum(" in text, (
            "step 4 does not fetch the structured-output addendum at dispatch"
        )
        assert 'PROMPT="$TASK$ADDENDUM"' in text, (
            "step 4 does not build the dispatched prompt from task + addendum"
        )
        # The build must precede the 'final argument' statement (ordering matters:
        # the addendum is useless if appended after providers run).
        assert text.index("review_schema._review_schema_addendum(") < text.index(
            "is the final argument"
        ), "addendum fetch appears after the final-argument step — wrong order"

    def test_review_schema_addendum_helper_is_callable(self):
        """The exact helper the dispatch snippet calls must exist and return the
        structured-output text for 'review' and empty for non-review types."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import review_schema

        assert "Structured Output" in review_schema._review_schema_addendum("review")
        assert review_schema._review_schema_addendum("general") == ""

    def test_required_version_tracks_shipped_scripts(self):
        """The startup REQUIRED_VERSION gate must equal the shipped version
        (rewritten by `make bump`). A stale value would reject the matching
        installed scripts as 'outdated' after the next release."""
        m = re.search(
            r'REQUIRED_VERSION="([0-9]+\.[0-9]+\.[0-9]+)"', SKILL_MD.read_text()
        )
        assert m, "trinity-zc SKILL.md lost its REQUIRED_VERSION gate"
        shipped = (ROOT / "VERSION").read_text().strip()
        assert m.group(1) == shipped, (
            f"trinity-zc REQUIRED_VERSION {m.group(1)} != VERSION {shipped}; "
            "`make bump` must rewrite skills/trinity-zc/SKILL.md too"
        )

    def test_deepseek_resume_passes_session_id(self):
        """The deepseek resume line must carry $SESSION_ID; a bare -r/--resume
        would resume the latest/wrong claude conversation (the wrapper forwards
        args verbatim to claude)."""
        assert '--resume "$SESSION_ID"' in SKILL_MD.read_text(), (
            "deepseek resume must pass the saved $SESSION_ID, not a bare flag"
        )

    def test_release_path_keeps_trinity_zc_in_sync(self):
        """make bump must rewrite, and release-prep must stage, trinity-zc's
        SKILL.md — otherwise a release ships a stale REQUIRED_VERSION gate."""
        makefile = (ROOT / "Makefile").read_text().splitlines()
        bump = [
            ln
            for ln in makefile
            if "REQUIRED_VERSION" in ln and "skills/trinity-zc/SKILL.md" in ln
        ]
        staged = [
            ln
            for ln in makefile
            if "git add" in ln and "skills/trinity-zc/SKILL.md" in ln
        ]
        assert bump, "make bump does not rewrite skills/trinity-zc/SKILL.md"
        assert staged, "release-prep git add does not stage skills/trinity-zc/SKILL.md"

    def test_doctor_reuses_probe_provider(self):
        """doctor must REUSE trinity's `_doctor._probe_provider` (own process
        group + killpg on timeout, rc-based health) rather than a hand-rolled
        bash/perl smoke — connector P2 'Kill doctor probes as a process group'
        and the recurring stdout-vs-JSONL false positives."""
        text = SKILL_MD.read_text()
        doctor = text[text.index("### `doctor`") :]
        doctor = doctor[: doctor.index("### `help`")]
        assert "_doctor._probe_provider(" in doctor, (
            "doctor no longer reuses _probe_provider — a hand-rolled smoke would "
            "reintroduce the process-group/JSONL bugs"
        )
        # The fragile primitives the reuse exists to avoid must be gone.
        assert "perl -e 'alarm" not in doctor, (
            "doctor still uses the perl-alarm wrapper (only signals the exec'd "
            "leader; a forked grandchild holding the pipe hangs the probe)"
        )
        assert 'grep -qi "trinity-ok"' not in doctor, (
            "doctor still greps stdout for a marker — use rc-based _probe_provider"
        )

    def test_doctor_probe_provider_handles_process_group(self):
        """The reused _probe_provider must run the probe in its own session and
        killpg on timeout (the actual mechanism that fixes the hang)."""
        src = (ROOT / "scripts" / "_doctor.py").read_text()
        probe = src[src.index("def _probe_provider(") :]
        probe = probe[: probe.index("\ndef ", 1)]
        assert "start_new_session=True" in probe and "killpg" in probe, (
            "_probe_provider lost its process-group timeout handling"
        )

    def test_heartbeat_fails_fast_on_missing_output(self):
        """A missing output file past the launch grace must surface as a launch
        failure, not be counted as 0 bytes and hidden until max_at."""
        text = SKILL_MD.read_text()
        assert "failed to launch" in text, (
            "heartbeat no longer fails fast on a missing output file"
        )
        assert "running (buffered" not in text, (
            "stale buffered-wrapper heartbeat instruction contradicts the "
            "streaming wrapper — a missing file must fail fast, not report running"
        )

    def test_doctor_sanitizes_env_via_reused_probe(self):
        """doctor must probe with the same sanitized env dispatch uses. Reuse of
        _probe_provider gets this for free: it calls build_provider_env (the
        Python sanitizer), so doctor and dispatch hit the same endpoint."""
        probe_src = (ROOT / "scripts" / "_doctor.py").read_text()
        probe = probe_src[probe_src.index("def _probe_provider(") :]
        probe = probe[: probe.index("\ndef ", 1)]
        assert "build_provider_env()" in probe, (
            "_probe_provider no longer sanitizes via build_provider_env — doctor "
            "would probe a different endpoint than dispatch"
        )

    def test_step5_reuses_sanitized_output_path(self):
        """Step 5 must not recompute OUTPUT_FILE from the raw <instance> (which
        could contain '/'); it reuses step 3's sanitized path."""
        block = _extract_step5_block()
        assert 'OUTPUT_FILE="<run_dir>/<instance>.out"' not in block, (
            "step 5 recomputes OUTPUT_FILE from raw <instance> — loses output "
            "for instances whose key contains '/'"
        )

    def test_dispatch_redirects_stdin(self):
        """The provider invocation must redirect stdin from /dev/null — verified
        live that claude-wrapper providers (deepseek/openrouter/claude-code)
        otherwise block ~3s waiting on stdin and emit a warning."""
        block = _extract_step5_block()
        assert "</dev/null" in block, (
            "step 5 provider invocation does not redirect stdin from /dev/null"
        )

    def test_presets_merge_by_key(self):
        """Discovery prose must say presets merge by key (not wholesale replace),
        matching scripts/config.py::merge_configs."""
        assert "merge by key" in SKILL_MD.read_text(), (
            "discovery prose still says presets replace the whole object"
        )

    def test_synthesis_stages_raw_before_write(self):
        """Review synthesis must copy dispatch output into raw/<provider>.txt
        before write_synthesis (else an rc=0 FIX is rendered as PASS)."""
        text = SKILL_MD.read_text()
        assert 'cp "$OUTPUT_FILE" "$REVIEW_DIR/raw/' in text, (
            "synthesis does not stage the .out into raw/<provider>.txt"
        )

    def test_manifest_ships_review_modules(self):
        """install.sh trees must get the review modules trinity-zc imports for
        `/trinity-zc review`, not just session.py."""
        manifest = json.loads((ROOT / "install-manifest.json").read_text())
        srcs = {e["src"] for e in manifest["files"]}
        for mod in (
            "scripts/_review.py",
            "scripts/review_schema.py",
            "scripts/provider_runtime.py",
            "scripts/_review_metadata.py",
            "scripts/provider_state.py",
        ):
            assert mod in srcs, f"manifest omits {mod} (trinity-zc review needs it)"


# ---------------------------------------------------------------------------
# Tier 2: Instruction fidelity (the regression-catcher)
# ---------------------------------------------------------------------------


def _extract_step5_block() -> str:
    """Extract the bash code block under '## Dispatch Protocol' step 5.

    Uses the same fence-aware reasoning as trinity's parser: find the line
    introducing step 5, then the next ```bash ... ``` fence after it.
    """
    text = SKILL_MD.read_text()
    # Find step 5 heading/prose
    step5_idx = text.find("**5. Spawn via Bash background.**")
    assert step5_idx != -1, "SKILL.md missing step-5 dispatch instruction"
    after = text[step5_idx:]
    # First ```bash fence after step 5
    m = re.search(r"```bash\n(.*?)\n```", after, re.DOTALL)
    assert m, "no bash fence found under step 5"
    return m.group(1)


class TestInstructionFidelity:
    """AC: the SKILL.md step-5 code block, run literally, produces an output
    file that parses cleanly through the reused synthesis path.

    This is the test that would have caught:
      - the setsid bug (setsid missing on macOS → silent no-op)
      - the sentinel printf bug (%%%%...%% → %% instead of % → unsplittable)
    """

    def test_step5_block_executes_and_produces_parseable_output(self, tmp_path):
        block = _extract_step5_block()

        # The block references <run_dir>/<instance>.out and <cli-and-args...>.
        # Substitute a stub provider (printf) so we don't need a real provider.
        output_file = tmp_path / "glm.out"
        run_dir = tmp_path
        instance = "glm"
        # Stub provider: emits a valid TRN-3022 PASS block as stdout
        stub_provider = (
            "printf 'Review OK.\\n\\n```json\\n"
            '{\\"decision\\":\\"PASS\\",\\"weighted_score\\":9.6,'
            '\\"blocking\\":[],\\"advisories\\":[]}\\n```\\n\''
        )

        # Rewrite the block's placeholders: run_dir/instance + cli-and-args
        exec_block = block.replace("<run_dir>", str(run_dir))
        exec_block = exec_block.replace("<instance>", instance)
        exec_block = exec_block.replace("<cli-and-args...>", stub_provider)

        # Run it. The block backgrounds the provider as a child of the wrapper
        # and `wait`s on it under a TERM trap; the harness backgrounds the whole
        # wrapper at a higher level. The wrapper blocks in `wait`, so running it
        # synchronously here still completes when the stub provider exits.
        full = f"set -e\n{exec_block}\n"
        result = subprocess.run(
            ["bash", "-c", full],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "OUTPUT_FILE": str(output_file)},
        )
        assert result.returncode == 0, (
            f"step-5 block failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # The output file must exist and be sentinel-formatted
        assert output_file.exists(), "step-5 block did not create the output file"
        raw = output_file.read_text()

        # The sentinel must split into exactly 2 parts (stdout + stderr)
        parts = raw.split("%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%")
        assert len(parts) == 2, (
            f"sentinel did not split output into 2 parts (got {len(parts)}); "
            f"this is the printf-escaping regression signature"
        )

        # The stdout portion must parse as a TRN-3022 review
        parsed = review_schema.parse_structured_review(raw)
        assert parsed["decision"] == "PASS"
        assert parsed["weighted_score"] == 9.6

    def test_step5_block_writes_rc_file(self, tmp_path):
        """The step-5 block must record the returncode (.rc).

        No .pid is expected: the provider PID is held in the wrapper's `$CHILD`
        shell variable and targeted by the TERM trap; no PID file is written to
        disk, and the wrapper still `wait`s (no double-backgrounding orphan).
        """
        block = _extract_step5_block()
        output_file = tmp_path / "glm.out"
        stub = "printf 'ok\\n'"
        exec_block = block.replace("<run_dir>", str(tmp_path))
        exec_block = exec_block.replace("<instance>", "glm")
        exec_block = exec_block.replace("<cli-and-args...>", stub)
        full = f"set -e\n{exec_block}\n"
        result = subprocess.run(
            ["bash", "-c", full],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "OUTPUT_FILE": str(output_file)},
        )
        assert result.returncode == 0, f"block failed: {result.stderr}"
        assert (tmp_path / "glm.out.rc").exists(), "no .rc file written"
        assert (tmp_path / "glm.out.rc").read_text().strip() == "0"
        # No .pid file should exist (the trap targets the in-shell $CHILD).
        assert not (tmp_path / "glm.out.pid").exists(), (
            "unexpected .pid file (P1 fix regressed)"
        )

    def test_step5_block_traps_term_to_child(self):
        """Static guard: the wrapper must background the provider, capture its
        PID, `wait` on it, and trap TERM/INT to a reap() that TERMs→KILLs the
        child and finishes only once it is dead — otherwise a fallback kill hits
        only the wrapper shell and orphans the provider, or a TERM-ignoring
        provider lingers and keeps writing past the sentinel (connector P2s
        'Kill the provider child...' and 'Reap the provider after forwarding TERM')."""
        block = _extract_step5_block()
        # reap() must escalate TERM -> KILL against the child.
        assert "reap()" in block and "kill -KILL" in block, (
            "step-5 wrapper lost reap()/KILL escalation — a TERM-ignoring "
            "provider would never be force-killed"
        )
        # The trap must invoke reap with $CHILD deferred to fire time (\$CHILD),
        # not bound empty at trap-definition time when CHILD is still unset.
        assert 'trap "reap \\"\\$CHILD\\"" TERM INT' in block, (
            "step-5 wrapper lost its TERM/INT trap (or expands $CHILD too early)"
        )
        assert "CHILD=$!" in block and 'wait "$CHILD"' in block, (
            "step-5 wrapper no longer backgrounds the provider + waits on $CHILD"
        )
        # Must confirm the child is actually gone before writing the sentinel/.rc.
        assert 'while kill -0 "$CHILD"' in block, (
            "step-5 wrapper writes the sentinel without confirming the child died "
            "— a slow/TERM-trapping provider could append after the sentinel"
        )

    def test_step5_trap_reaps_child_on_term(self, tmp_path):
        """Executed end-to-end: TERM to the marker wrapper must reap the provider
        child via the trap, not leave it running. This is the exact regression the
        connector flagged — a foreground child survives a wrapper-only kill."""
        block = _extract_step5_block()
        output_file = tmp_path / "glm.out"
        childpid = tmp_path / "child.pid"
        # Stub provider: record its own PID, then become a long sleep. The pid
        # file lets us detect liveness without pgrep/comm-truncation pitfalls.
        stub = "bash -c 'echo $$ > %s; exec sleep 60'" % childpid
        exec_block = block.replace("<run_dir>", str(tmp_path))
        exec_block = exec_block.replace("<instance>", "glm")
        exec_block = exec_block.replace("<cli-and-args...>", stub)
        # RUN_DIR is set in step 3 (not in the extracted step-5 block); define it
        # so KILL_MARKER is populated (the wrapper $0).
        exec_block = f"RUN_DIR={tmp_path}\n" + exec_block
        proc = subprocess.Popen(
            ["bash", "-c", exec_block],
            cwd=tmp_path,
            env={**os.environ, "OUTPUT_FILE": str(output_file)},
        )

        def child_alive() -> bool:
            if not childpid.exists():
                return False
            pid = childpid.read_text().strip()
            if not pid:
                return False
            return subprocess.run(["kill", "-0", pid]).returncode == 0

        try:
            # The wrapper is the child's PARENT — robust whether or not bash
            # exec-optimizes the final command (which would make the wrapper share
            # the Popen pid). pgrep-by-marker can't tell the wrapper from the outer
            # shell whose argv merely contains the marker literal; ppid can.
            wrapper_pid = None
            for _ in range(150):  # up to ~15s
                if child_alive():
                    cpid = childpid.read_text().strip()
                    ppid = subprocess.run(
                        ["ps", "-o", "ppid=", "-p", cpid],
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if ppid:
                        wrapper_pid = ppid
                        break
                time.sleep(0.1)
            assert wrapper_pid, "provider child never started under a wrapper"

            subprocess.run(["kill", "-TERM", wrapper_pid])

            reaped = False
            for _ in range(150):  # up to ~15s
                if not child_alive():
                    reaped = True
                    break
                time.sleep(0.1)
            assert reaped, (
                "provider child still alive after TERM to the marker wrapper — "
                "the trap did not forward the signal (orphan bug)"
            )
        finally:
            if childpid.exists():
                pid = childpid.read_text().strip()
                if pid:
                    subprocess.run(["kill", "-KILL", pid], capture_output=True)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_step5_reap_escalates_to_kill_on_term_ignoring_provider(self, tmp_path):
        """Executed: a provider that IGNORES TERM must still be force-killed by
        reap()'s KILL escalation and reaped before the wrapper finishes — the
        connector P2 'Reap the provider after forwarding TERM' (a TERM-trapping
        provider would otherwise linger/orphan and write past the sentinel)."""
        block = _extract_step5_block()
        output_file = tmp_path / "glm.out"
        childpid = tmp_path / "child.pid"
        # SIG_IGN survives exec, so this becomes a `sleep` that ignores TERM.
        stub = "bash -c 'trap \"\" TERM; echo $$ > %s; exec sleep 60'" % childpid
        exec_block = block.replace("<run_dir>", str(tmp_path))
        exec_block = exec_block.replace("<instance>", "glm")
        exec_block = exec_block.replace("<cli-and-args...>", stub)
        exec_block = f"RUN_DIR={tmp_path}\n" + exec_block
        proc = subprocess.Popen(
            ["bash", "-c", exec_block],
            cwd=tmp_path,
            env={**os.environ, "OUTPUT_FILE": str(output_file)},
        )

        def child_alive() -> bool:
            if not childpid.exists():
                return False
            pid = childpid.read_text().strip()
            return bool(pid) and subprocess.run(["kill", "-0", pid]).returncode == 0

        try:
            wrapper_pid = None
            for _ in range(150):  # up to ~15s
                if child_alive():
                    cpid = childpid.read_text().strip()
                    ppid = subprocess.run(
                        ["ps", "-o", "ppid=", "-p", cpid],
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if ppid:
                        wrapper_pid = ppid
                        break
                time.sleep(0.1)
            assert wrapper_pid, "provider child never started under a wrapper"

            # Confirm the child really ignores TERM (else the test proves nothing).
            cpid = childpid.read_text().strip()
            subprocess.run(["kill", "-TERM", cpid])
            time.sleep(1)
            assert child_alive(), "stub did not actually ignore TERM; test invalid"

            # Now TERM the wrapper: reap() must escalate to KILL within its grace.
            subprocess.run(["kill", "-TERM", wrapper_pid])
            reaped = False
            for _ in range(200):  # up to ~20s (reap grace is ~5s)
                if not child_alive():
                    reaped = True
                    break
                time.sleep(0.1)
            assert reaped, (
                "TERM-ignoring provider survived — reap() did not escalate to KILL"
            )
        finally:
            if childpid.exists():
                pid = childpid.read_text().strip()
                if pid:
                    subprocess.run(["kill", "-KILL", pid], capture_output=True)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_step5_block_sanitizes_dangerous_env(self, tmp_path):
        """The step-5 block must strip *_BASE_URL before invoking the provider,
        but ONLY the underscore-delimited pattern that provider_runtime strips.

        - OPENAI_BASE_URL / OPENAI2_BASE_URL (incl. digits) must be stripped.
        - DATABASE_URL must be PRESERVED: it ends in 'BASE_URL' but NOT in
          '_BASE_URL', and the Python clearlist (`*_BASE_URL`, fnmatch) keeps it.
          A too-greedy sed (`[A-Za-z0-9_]*BASE_URL`) wrongly strips it — connector
          P2 'Match only underscored endpoint overrides'.
        """
        block = _extract_step5_block()
        output_file = tmp_path / "glm.out"
        stub = (
            'printf "a=%s b=%s db=%s" '
            '"${OPENAI_BASE_URL:-UNSET}" "${OPENAI2_BASE_URL:-UNSET}" '
            '"${DATABASE_URL:-UNSET}"'
        )
        exec_block = block.replace("<run_dir>", str(tmp_path))
        exec_block = exec_block.replace("<instance>", "glm")
        exec_block = exec_block.replace("<cli-and-args...>", stub)
        full = f"set -e\n{exec_block}\n"
        subprocess.run(
            ["bash", "-c", full],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={
                **os.environ,
                "OUTPUT_FILE": str(output_file),
                "OPENAI_BASE_URL": "https://evil.example/v1",
                "OPENAI2_BASE_URL": "https://evil2.example/v1",
                "DATABASE_URL": "postgres://keep.example/db",
            },
            check=True,
        )
        raw = output_file.read_text()
        stdout_part = raw.split("%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%")[0]
        assert "evil.example" not in stdout_part, (
            "OPENAI_BASE_URL leaked to provider — env sanitization regressed"
        )
        assert "evil2.example" not in stdout_part, (
            "OPENAI2_BASE_URL (digit-bearing) leaked — sed sanitizer misses digits"
        )
        assert "keep.example" in stdout_part, (
            "DATABASE_URL was stripped — sed matches 'BASE_URL' without the "
            "required underscore; provider_runtime (*_BASE_URL) keeps it"
        )


class TestDoctorTimeoutDetection:
    """AC: the reused _probe_provider must kill the whole process group on
    timeout, so a provider that forks a child holding the captured pipe cannot
    hang the probe past the timeout (connector P2 'Kill doctor probes as a
    process group')."""

    def test_probe_kills_pipe_holding_grandchild_on_timeout(self, tmp_path):
        """Executed: a provider that forks a child inheriting stdout and then
        sleeps must be force-killed (group) at the timeout — the probe returns
        cause=timeout quickly AND the grandchild is dead, not orphaned."""
        import importlib

        codex = importlib.import_module("codex")
        _doctor = importlib.import_module("_doctor")

        gpid = tmp_path / "grandchild.pid"
        provider = tmp_path / "hangprov"
        # exec sleep so SIG to the group reaches it; record its pid for the orphan
        # check. The leader backgrounds it and waits, holding the pipe open.
        provider.write_text(
            "#!/bin/bash\nbash -c 'echo $$ > \"%s\"; exec sleep 60' &\nwait\n" % gpid
        )
        provider.chmod(0o755)

        prev = codex._LIVE_PROBE_TIMEOUT
        codex._LIVE_PROBE_TIMEOUT = 2
        try:
            start = time.monotonic()
            res = _doctor._probe_provider(
                "hangprov", {"cli": str(provider)}, str(tmp_path)
            )
            elapsed = time.monotonic() - start
        finally:
            codex._LIVE_PROBE_TIMEOUT = prev

        assert res and res.get("cause") == "timeout", f"expected timeout, got {res}"
        assert elapsed < 15, f"probe hung {elapsed:.1f}s past its 2s timeout"

        # The grandchild that held the pipe must be dead (group-killed), not
        # orphaned. On Linux a killpg'd child can briefly remain a ZOMBIE until
        # PID 1 reaps it — `kill -0` still succeeds for a zombie, so treat a Z
        # (or vanished) state as dead (mirrors test_doctor_preflight's check; a
        # zombie runs no provider work).
        def _gone_or_zombie(pid):
            if subprocess.run(["kill", "-0", pid]).returncode != 0:
                return True
            ps = subprocess.run(
                ["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True
            )
            stat = ps.stdout.strip()
            return stat == "" or stat.startswith("Z")

        if gpid.exists():
            pid = gpid.read_text().strip()
            if pid:
                gone = False
                for _ in range(50):
                    if _gone_or_zombie(pid):
                        gone = True
                        break
                    time.sleep(0.1)
                subprocess.run(["kill", "-KILL", pid], capture_output=True)
                assert gone, "pipe-holding grandchild orphaned (group not killed)"


class TestSynthesisReuse:
    """AC: write_synthesis consumes the step-5 output format correctly."""

    def test_write_synthesis_on_step5_format(self, tmp_path):
        """Build a review_dir with the sentinel-format raw and synthesize."""
        review_dir = tmp_path / "review"
        (review_dir / "raw").mkdir(parents=True)
        decision = (
            '```json\n{"decision":"FIX","weighted_score":7.8,'
            '"blocking":[{"title":"x","evidence":"y","fix":"z"}],'
            '"advisories":[]}\n```'
        )
        raw = "Found a bug.\n" + decision + provider_runtime._STDERR_SENTINEL + "\n"
        (review_dir / "raw" / "codex.txt").write_text(raw)

        results = [
            {
                "provider": "codex",
                "returncode": 0,
                "raw": "raw/codex.txt",
                "started_at": "t",
                "finished_at": "t",
            }
        ]
        summary, synth_path = _review.write_synthesis(review_dir, "test", results)
        assert synth_path.exists()
        verdict = summary["verdict"] if isinstance(summary, dict) else str(summary)
        assert verdict == "NEEDS_FIXES", (
            f"expected NEEDS_FIXES (codex FIX), got {verdict}"
        )


# ---------------------------------------------------------------------------
# Tier 3: Real-provider doctor (slow, network)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRealProviderDoctor:
    """AC: real-provider doctor test, marked slow, skipped by default.

    Run with: pytest tests/test_trinity_zc.py -m slow
    Requires droid/codex CLI + network. Smoke-tests each usable provider
    with trinity's own convention (reply 'trinity-ok').
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_droid(self):
        # The GLM smoke runs `droid exec`; skip if droid is absent (codex
        # alone is not sufficient — the test body is GLM/droid-specific).
        if not shutil_which("droid"):
            pytest.skip("droid CLI not available (required for GLM smoke)")

    def test_glm_replies_trinity_ok(self):
        out = subprocess.run(
            [
                "droid",
                "exec",
                "--auto",
                "medium",
                "--model",
                "custom:GLM-5.2",
                "Reply with exactly: trinity-ok",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert "trinity-ok" in out.stdout.lower()


def shutil_which(cmd: str) -> str | None:
    """shutil.which without importing shutil at module top (keeps import lean)."""
    from shutil import which

    return which(cmd)


# ---------------------------------------------------------------------------
# Executed-contract coverage: run the ACTUAL SKILL.md snippets (not a
# reimplementation), plus consistency checks against trinity's source of truth.
# Closes blind spots where a prose/code regression would pass a static grep.
# ---------------------------------------------------------------------------


def _extract_bash_after(anchor: str) -> str:
    text = SKILL_MD.read_text()
    idx = text.find(anchor)
    assert idx != -1, f"anchor not found: {anchor}"
    m = re.search(r"```bash\n(.*?)\n```", text[idx:], re.DOTALL)
    assert m, f"no bash fence after: {anchor}"
    return m.group(1)


def _extract_python_after(anchor: str) -> str:
    text = SKILL_MD.read_text()
    idx = text.find(anchor)
    assert idx != -1, f"anchor not found: {anchor}"
    m = re.search(r"```python\n(.*?)\n```", text[idx:], re.DOTALL)
    assert m, f"no python fence after: {anchor}"
    return m.group(1)


class TestExecutedContracts:
    """Run the real SKILL.md snippets so a logic regression (not just a missing
    phrase) is caught."""

    def test_step3_sanitizes_instance_key_in_path(self, tmp_path):
        """Execute step 3 with an instance key containing ':' and '/'. The
        allocated OUTPUT_FILE basename must be sanitized to '-' and creatable —
        the exact failure the prose warns about (glm:feature/auth)."""
        block = _extract_bash_after("**3. Allocate output file.**")
        cap = tmp_path / "captured"
        script = (
            f'export TMPDIR="{tmp_path}"\n'
            'INSTANCE_KEY="glm:feature/auth"\n'
            f"{block}\n"
            f'printf "%s" "$OUTPUT_FILE" > "{cap}"\n'
            'touch "$OUTPUT_FILE"\n'
        )
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert r.returncode == 0, f"step 3 failed: {r.stderr}"
        out_path = cap.read_text()
        base = out_path.rsplit("/", 1)[-1]
        assert base == "glm-feature-auth.out", f"instance key not sanitized: {base}"
        assert Path(out_path).exists(), "OUTPUT_FILE not creatable (run dir missing)"

    def test_state_store_snippet_round_trips(self, tmp_path):
        """Execute the actual State Store atomic-write python snippet (not the
        test's reimplementation) and read the result back."""
        block = _extract_python_after("**Atomic writes**")
        preamble = 'key = "glm:e2e"\nentry = {"provider": "glm", "state": "running"}\n'
        r = subprocess.run(
            [sys.executable, "-c", preamble + block],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"state-store snippet failed: {r.stderr}"
        data = json.loads((tmp_path / ".claude" / "trinity-zc.json").read_text())
        assert data["sessions"]["glm:e2e"]["state"] == "running"

    def test_discovery_merge_snippet_executes(self, tmp_path):
        """Execute the actual Provider Discovery merge snippet and verify its
        semantics: project providers win, global presets preserved, presets merge
        by key, preset_aliases carried + merged."""
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        proj = tmp_path / "proj"
        (proj / ".claude").mkdir(parents=True)
        (home / ".claude" / "trinity.json").write_text(
            json.dumps(
                {
                    "providers": {"glm": {"cli": "g"}, "codex": {"cli": "c"}},
                    "presets": {"review": {"providers": ["glm"]}},
                    "preset_aliases": {"r": "review"},
                    "defaults": {"timeout": {"review": {"max_at": 999}}, "keep": 1},
                }
            )
        )
        (proj / ".claude" / "trinity.json").write_text(
            json.dumps(
                {
                    "providers": {"glm": {"cli": "PROJ"}},
                    "presets": {"custom": {"providers": ["codex"]}},
                    "preset_aliases": {"c": "custom"},
                    "defaults": {"timeout": {"review": {"max_at": 111}}},
                }
            )
        )
        block = _extract_python_after("Read the merged config with inline Python")
        epilogue = (
            "\nimport json as _j\n"
            'print(_j.dumps({"providers": providers, "presets": presets, '
            '"preset_aliases": preset_aliases, "defaults": defaults}))\n'
        )
        r = subprocess.run(
            [sys.executable, "-c", block + epilogue],
            cwd=proj,
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"discovery snippet failed: {r.stderr}"
        res = json.loads(r.stdout.strip().splitlines()[-1])
        assert res["providers"]["glm"]["cli"] == "PROJ", "project provider must win"
        assert res["providers"]["codex"]["cli"] == "c", "global provider must survive"
        assert "review" in res["presets"] and "custom" in res["presets"], (
            "presets must merge by key, not replace"
        )
        assert res["preset_aliases"] == {"r": "review", "c": "custom"}, (
            "preset_aliases must be carried and merged"
        )
        # defaults shallow-merge: project's defaults.timeout wins; global's other
        # keys survive (shallow merge replaces top-level keys, not deep-merges).
        assert res["defaults"]["timeout"]["review"]["max_at"] == 111, (
            "project defaults.timeout must win over global"
        )

    def test_timeout_table_matches_trinity(self):
        """trinity-zc's timeout table must match trinity's source-of-truth table
        (a silent drift would change kill timing)."""

        def parse(text):
            return {
                m.group(1): (m.group(2).replace(" ", ""), m.group(3).replace(" ", ""))
                for m in re.finditer(
                    r"\|\s*(tdd|review|prp|general)\s*\|\s*(\d+ min)\s*\|\s*(\d+ min)\s*\|",
                    text,
                )
            }

        zc = parse(SKILL_MD.read_text())
        root = parse((ROOT / "SKILL.md").read_text())
        assert zc, "no timeout table parsed from trinity-zc SKILL.md"
        assert zc == root, f"timeout table drifted from trinity: {zc} != {root}"

    def test_task_type_mapping_matches_trinity(self):
        """trinity-zc's task-type keyword mapping must match trinity's (incl. the
        Chinese keywords), or `/trinity-zc review` could infer the wrong type."""
        zc = SKILL_MD.read_text()
        root = (ROOT / "SKILL.md").read_text()
        for kw, typ in [("审查", "review"), ("测试", "tdd"), ("proposal", "prp")]:
            pat = rf"{re.escape(kw)}[`\"]\s*→\s*[`\"]{typ}"
            assert re.search(pat, zc), f"trinity-zc task-type missing {kw}→{typ}"
            assert re.search(pat, root), f"root task-type missing {kw}→{typ}"

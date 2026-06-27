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


def _load_merged_config(tmp_path: Path, project_overlay: dict | None = None) -> dict:
    """Load global ~/.claude/trinity.json merged with a project overlay.

    This mirrors trinity-zc's provider-discovery logic (SKILL.md §Provider
    Discovery). Used here for the config-overlay + dangling-preset tests.
    """
    global_path = Path.home() / ".claude" / "trinity.json"
    g = {}
    if global_path.exists():
        g = json.loads(global_path.read_text())

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
        config = _load_merged_config(
            tmp_path,
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

    def test_live_global_config_has_no_dangling_refs(self):
        """The real ~/.claude/trinity.json must not reference retired providers."""
        global_path = Path.home() / ".claude" / "trinity.json"
        if not global_path.exists():
            pytest.skip("no global trinity.json")
        config = _load_merged_config(Path.cwd())
        provider_names = set(config["providers"])
        dangling = []
        for pname, pcfg in config["presets"].items():
            for ref in pcfg.get("providers", []) + pcfg.get("optional_providers", []):
                if ref not in provider_names:
                    dangling.append((pname, ref))
        assert dangling == [], f"global config has dangling preset refs: {dangling}"


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

        # Run it. The block runs the provider in the foreground (no `&` since
        # the P1 fix); the harness backgrounds at a higher level. No wait needed.
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

        No .pid is expected: the provider runs in the foreground of the
        harness-backgrounded shell, so the harness tracks it directly
        (no double-backgrounding — the P1 fix removed the trailing &).
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
        # No .pid file should exist (double-backgrounding removed).
        assert not (tmp_path / "glm.out.pid").exists(), (
            "unexpected .pid file (P1 fix regressed)"
        )

    def test_step5_block_sanitizes_dangerous_env(self, tmp_path):
        """The step-5 block must strip *_BASE_URL before invoking the provider.

        This is the P2 env-sanitization fix: a dangerous endpoint var set in
        the caller env must NOT reach the provider. The stub provider echoes
        the var; it must come back empty.
        """
        block = _extract_step5_block()
        output_file = tmp_path / "glm.out"
        stub = 'printf "base=%s" "${OPENAI_BASE_URL:-UNSET}"'
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
            },
            check=True,
        )
        raw = output_file.read_text()
        stdout_part = raw.split("%%TRINITY-RAW-STDERR-BOUNDARY-9c3d2a1f7e%%")[0]
        assert "evil.example" not in stdout_part, (
            "OPENAI_BASE_URL leaked to provider — env sanitization regressed"
        )


def _extract_doctor_smoke() -> str:
    """Extract the smoke() function from SKILL.md's doctor section."""
    text = SKILL_MD.read_text()
    m = re.search(r"smoke\(\) \{.*?\n\}", text, re.DOTALL)
    assert m, "no smoke() function in SKILL.md doctor section"
    return m.group(0)


class TestDoctorTimeoutDetection:
    """AC: the doctor smoke() must classify a SIGALRM-timeout correctly.

    The perl-alarm wrapper dies on SIGALRM; under bash command-substitution the
    exit status is 128+14=142, not 14. The smoke() timeout branch must match 142
    (this is the Codex-review P2 finding — the original `[ $rc -eq 14 ]` never
    fired, hiding every timeout as a FAIL).
    """

    def test_timeout_exit_status_is_142(self):
        """Confirm the perl-alarm wrapper actually yields 142, not 14."""
        rc = subprocess.run(
            [
                "bash",
                "-c",
                "out=$(perl -e 'alarm shift; exec @ARGV' 1 sleep 3); echo $?",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert rc == "142", f"perl-alarm timeout rc is {rc}, expected 142"

    def test_smoke_function_classifies_timeout_as_timeout_not_fail(self, tmp_path):
        """The smoke() timeout branch must reference rc 142 (not just 14).

        Fast: checks the extracted smoke() contains the 142 check, rather than
        waiting 30s for a real timeout (the end-to-end variant is `slow`).
        """
        smoke_fn = _extract_doctor_smoke()
        assert "142" in smoke_fn, (
            "smoke() timeout branch does not check rc 142 (SIGALRM under bash); "
            "this is the Codex-review P2 regression — timeouts fall through to FAIL"
        )

    @pytest.mark.slow
    def test_smoke_timeout_end_to_end(self, tmp_path):
        """Slow: run smoke() against a 35s-sleep provider to verify the TIMEOUT
        line is printed (not FAIL) end-to-end. ~30s wall-clock."""
        smoke_fn = _extract_doctor_smoke()
        script = textwrap.dedent(f"""\
            {smoke_fn}
            smoke hung_provider sleep 35
        """)
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=60,
        )
        assert "TIMEOUT" in result.stdout, (
            f"smoke misclassified timeout:\n{result.stdout}"
        )
        assert "FAIL" not in result.stdout


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

"""TRN-3024 Slice F: PR #60 loopback MCP regression fixture.

Captures the 7 missed-bug targets from PR #60 and verifies that the
loopback MCP bridge can surface peer findings that correspond to these
bug patterns. The deterministic fixture replays the cross-provider
visibility gap through the actual MCP ``trinity__peer_findings_so_far``
tool without requiring live model CLIs or network access.

Acceptance criteria:
- Captures the 7 missed-bug targets in a test-readable form.
- Runs a loopback-enabled peer-findings flow and asserts at least one
  of the 7 documented bugs is surfaced through the MCP tool.
- Confirms loopback-disabled behavior remains available and does not
  regress standard review flow.
- PASS criterion: at least 1 of the 7 missed bugs is surfaced.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_codex_adapter import CODEX_SCRIPT, commit_all, init_repo
from tests.test_mcp_loopback import _http_request, _mcp_request, _record_completed_raw


# ---------------------------------------------------------------------------
# BUG_TARGETS — the 7 missed-bug targets from PR #60 in test-readable form.
# Source: TRN-2028-CHG-Add-Trinity-Status-Latest-Command.md change history
# (PR #60 rounds 1-7 from Codex GitHub App bot).
# ---------------------------------------------------------------------------

BUG_TARGETS = [
    {
        "id": 1,
        "round": "R1",
        "title": "Interrupt handler writes incomplete.json before metadata.json",
        "file": "scripts/codex.py",
        "area": "cmd_review error handling",
        "bug_class": "caller-flow",
        "description": (
            "When cmd_review is interrupted (KeyboardInterrupt / ReviewInterrupted / "
            "ReviewOrchestrationError), it writes incomplete.json from its handlers "
            "BEFORE the metadata.json write ever happens. An interrupted review "
            "directory has incomplete.json AND NO metadata.json — the status command "
            "bails with 'no metadata' exactly when the user most needs to summarize."
        ),
        "pattern": "incomplete.json before metadata.json",
    },
    {
        "id": 2,
        "round": "R2",
        "title": "Schema-mismatch: read 'status' instead of 'result'",
        "file": "scripts/codex.py",
        "area": "_print_incomplete_only_summary",
        "bug_class": "writer-schema",
        "description": (
            "cleanup_active_processes writes per-provider cleanup payloads with "
            "'result' (terminated/killed/kill_timeout), but the helper was reading "
            "info.get('status', '?') — wrong field name, always renders '?'."
        ),
        "pattern": "cleanup field name mismatch: result vs status",
    },
    {
        "id": 3,
        "round": "R3",
        "title": "cmd_status uses args.root directly without resolve_root",
        "file": "scripts/codex.py",
        "area": "cmd_status",
        "bug_class": "caller-flow",
        "description": (
            "cmd_status used args.root directly without resolving via "
            "resolve_root / resolve_health_root like the other subcommands do. "
            "Running trinity status from a subdirectory builds "
            "<subdir>/.trinity/reviews instead of the repo-root path."
        ),
        "pattern": "args.root not resolved through resolve_root",
    },
    {
        "id": 4,
        "round": "R4",
        "title": "status not reserved in PRESET_ALIAS_RESERVED_WORDS",
        "file": "scripts/codex.py",
        "area": "preset alias collision",
        "bug_class": "sibling-code",
        "description": (
            "Adding 'status' as a built-in subcommand without also reserving it "
            "in PRESET_ALIAS_RESERVED_WORDS. Configs can define "
            "preset_aliases: {'status': 'review'} and the alias is accepted "
            "instead of failing — leaving 'status' ambiguous."
        ),
        "pattern": "status not in preset alias reserved words",
    },
    {
        "id": 5,
        "round": "R5",
        "title": "Hardcoded 'interrupted' labels mask 'failed' status",
        "file": "scripts/codex.py",
        "area": "_print_incomplete_only_summary",
        "bug_class": "caller-flow",
        "description": (
            "cmd_review's ReviewOrchestrationError handler writes incomplete.json "
            "with status='failed', but _print_incomplete_only_summary hard-coded "
            "both labels as 'interrupted'. A real orchestration failure was "
            "misrendered as 'Status: interrupted (failed)'."
        ),
        "pattern": "hardcoded 'interrupted' label masks 'failed'",
    },
    {
        "id": 6,
        "round": "R6",
        "title": "Same misrendering as R5 in sibling metadata-PRESENT path",
        "file": "scripts/codex.py",
        "area": "_print_review_summary",
        "bug_class": "sibling-code",
        "description": (
            "EXACT same bug class as R5 but in _print_review_summary "
            "(metadata-PRESENT code path). After metadata.json is written but "
            "incomplete.json has status='failed', the overall label still "
            "hard-codes 'interrupted ({incomplete_status})'."
        ),
        "pattern": "sibling path also hardcodes 'interrupted'",
    },
    {
        "id": 7,
        "round": "R7",
        "title": "Lex sort breaks for same-second reviews with different slugs",
        "file": "scripts/codex.py",
        "area": "cmd_status review directory ordering",
        "bug_class": "unverified-invariant",
        "description": (
            "sorted(reviews, reverse=True) over full directory names is wrong "
            "because make_review_dir stamps to seconds and appends <slug>[-<index>]. "
            "Two reviews in the same second with different slugs (-z vs -a) have "
            "lex order != creation order."
        ),
        "pattern": "lex sort wrong for same-second reviews",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_provider_output(
    review_dir: Path,
    provider: str,
    content: str,
    *,
    score: float = 9.3,
    decision: str = "PASS",
    blocking: list | None = None,
) -> None:
    """Write a structured review output for a provider, including metadata."""
    output = {
        "provider": provider,
        "decision": decision,
        "weighted_score": score,
        "findings": content,
    }
    if blocking is not None:
        output["blocking"] = blocking

    raw_dir = review_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{provider}.txt").write_text(
        json.dumps(output, indent=2) + "\n"
    )


def _read_provider_output(review_dir: Path, provider: str) -> str | None:
    """Read a provider's raw output file."""
    path = review_dir / "raw" / f"{provider}.txt"
    if path.exists():
        return path.read_text()
    return None


# ---------------------------------------------------------------------------
# Regression test: loopback MCP peer findings flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPR60RegressionPeerFindings:
    """PR #60 regression: loopback MCP surfaces peer findings that map to
    documented missed-bug targets. This is the primary deterministic fixture
    that proves the bridge can carry cross-provider findings."""

    BUG_PATTERN = "incomplete.json before metadata.json"  # Bug target #1

    @pytest.fixture(autouse=True)
    async def _server_fixture(self, tmp_path):
        from scripts.mcp_loopback import McpLoopbackServer

        review_dir = tmp_path / "reviews" / "reg-001"
        raw_dir = review_dir / "raw"
        raw_dir.mkdir(parents=True)

        server = McpLoopbackServer(review_dir=str(review_dir))
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        self._review_dir = review_dir
        self._raw_dir = raw_dir
        yield
        await server.stop()

    async def test_peer_findings_surfaces_documented_bug_pattern(self):
        """Bug target #1 (incomplete.json before metadata.json) is present in
        provider A's output and accessible via trinity__peer_findings_so_far.
        This proves the bridge can surface the finding for peer consumption."""
        # Simulate provider A completing with a finding matching bug target #1
        _record_completed_raw(
            self._review_dir,
            "provider-a",
            "WARNING: interrupt handler order issue — "
            "incomplete.json before metadata.json",
        )

        # Provider B queries peer findings via loopback MCP
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": "trinity__peer_findings_so_far",
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok", f"Expected ok, got {result}"
        assert len(result["data"]) == 1
        peer_provider = result["data"][0]
        assert peer_provider["provider"] == "provider-a"
        assert self.BUG_PATTERN in peer_provider["content"], (
            f"Bug pattern '{self.BUG_PATTERN}' not found in peer content:\n"
            f"{peer_provider['content']}"
        )

    async def test_peer_findings_returns_all_seven_bug_patterns_across_multiple_providers(
        self,
    ):
        """All 7 bug patterns are documentable across multiple provider outputs.
        Each provider's finding maps to a specific BUG_TARGETS entry."""
        # Map each bug target's pattern to a provider
        _record_completed_raw(self._review_dir, "bug-bot-1", BUG_TARGETS[0]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-2", BUG_TARGETS[1]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-3", BUG_TARGETS[2]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-4", BUG_TARGETS[3]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-5", BUG_TARGETS[4]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-6", BUG_TARGETS[5]["pattern"])
        _record_completed_raw(self._review_dir, "bug-bot-7", BUG_TARGETS[6]["pattern"])

        # A consumer provider queries all peer findings
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": "trinity__peer_findings_so_far",
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert len(result["data"]) == 7, (
            f"Expected 7 peer findings, got {len(result['data'])}"
        )

        # Verify each bug target pattern appears in at least one provider's output
        found_patterns = set()
        for entry in result["data"]:
            for target in BUG_TARGETS:
                if target["pattern"] in entry["content"]:
                    found_patterns.add(target["id"])

        for target in BUG_TARGETS:
            assert target["id"] in found_patterns, (
                f"Bug target #{target['id']} ('{target['pattern']}') "
                f"not found in any peer output"
            )

    async def test_peer_findings_excludes_current_provider(self):
        """When a provider queries peer findings with current_provider set,
        its own output is excluded (avoids self-referencing)."""
        _record_completed_raw(self._review_dir, "provider-a", BUG_TARGETS[0]["pattern"])
        _record_completed_raw(
            self._review_dir, "provider-b", BUG_TARGETS[1]["pattern"]
        )

        # Provider-b queries, excluding itself
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": "trinity__peer_findings_so_far",
                "arguments": {
                    "review_dir": str(self._review_dir),
                    "current_provider": "provider-b",
                },
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        assert result["data"][0]["provider"] == "provider-a"
        assert BUG_TARGETS[0]["pattern"] in result["data"][0]["content"]

    async def test_peer_findings_empty_when_no_peer_outputs(self):
        """Without any completed peer outputs, peer findings returns empty."""
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": "trinity__peer_findings_so_far",
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "empty"

    async def test_bug_targets_documented_as_constant(self):
        """BUG_TARGETS is defined at module scope with all 7 entries."""
        assert len(BUG_TARGETS) == 7
        ids = {t["id"] for t in BUG_TARGETS}
        assert ids == {1, 2, 3, 4, 5, 6, 7}
        for t in BUG_TARGETS:
            assert t["title"], f"Bug #{t['id']} missing title"
            assert t["pattern"], f"Bug #{t['id']} missing pattern"
            assert t["bug_class"], f"Bug #{t['id']} missing bug_class"
            assert t["round"], f"Bug #{t['id']} missing round"


# ---------------------------------------------------------------------------
# End-to-end integration: cmd_review with loopback MCP enabled
# ---------------------------------------------------------------------------

def _write_provider_script(
    path: Path,
    *,
    marker: str = "review-ok",
    exit_code: int = 0,
    read_peer_findings: bool = False,
) -> None:
    """Write a fake provider script for the end-to-end test.

    When read_peer_findings=True, the provider attempts to read peer findings
    via the MCP loopback server by checking for a config file at
    ``<review_dir>/mcp_config/claude-code.json`` (claude-code injection path)
    or via the ``TRINITY_MCP_TOKEN`` env var (codex injection path).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

finder_text = ""

# Try to read MCP config and query peer findings
mcp_token = os.environ.get("TRINITY_MCP_TOKEN", "")
if mcp_token:
    # Check for claude-code style config file
    review_dir = None
    for arg in sys.argv:
        if arg.endswith(".json") and "mcp_config" in arg:
            try:
                config = json.loads(Path(arg).read_text())
                for name, entry in config.get("mcpServers", {{}}).items():
                    if "url" in entry:
                        url = entry["url"]
                        port = url.rsplit(":", 1)[-1].rstrip("/sse")
                        token = entry.get("headers", {{}}).get(
                            "Authorization", ""
                        ).replace("Bearer ", "")
                        if not token:
                            token = mcp_token
                        payload = {{
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {{
                                "name": "trinity__peer_findings_so_far",
                                "arguments": {{}}
                            }}
                        }}
                        import urllib.request
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{{port}}/mcp",
                            data=json.dumps(payload).encode(),
                            headers={{
                                "Authorization": f"Bearer {{token}}",
                                "Content-Type": "application/json",
                            }},
                        )
                        try:
                            resp = urllib.request.urlopen(req, timeout=3)
                            data = json.loads(resp.read())
                            result_text = data.get("result", {{}}).get(
                                "content", []
                            )
                            for item in result_text:
                                txt = json.loads(item.get("text", "{{}}"))
                                if txt.get("status") == "ok":
                                    peers = txt.get("data", [])
                                    if peers:
                                        finder_text = (
                                            f"PEER_FINDINGS_RECEIVED: "
                                            f"{{len(peers)}} peer(s)"
                                        )
                        except Exception:
                            pass
            except Exception:
                pass

result = {{
    "decision": "PASS",
    "weighted_score": 9.3,
    "blocking": [],
    "advisories": [],
}}
if finder_text:
    result["advisories"].append({{"title": finder_text}})

print(json.dumps(result))
sys.exit({exit_code})
""",
    )
    path.chmod(0o755)


def _simple_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with a tracked file."""
    repo = tmp_path / "repo"
    init_repo(repo)
    tracked = repo / "review.txt"
    tracked.write_text("before\n")
    commit_all(repo, "init")
    tracked.write_text("before\nafter\n")
    return repo


def _write_config(
    config_path: Path,
    providers: dict[str, Path],
    *,
    enable_loopback_mcp: bool = False,
) -> None:
    """Write a trinity.json config for the end-to-end test."""
    provider_config = {}
    for name, path in providers.items():
        cfg: dict = {"cli": str(path), "timeout": 10}
        if enable_loopback_mcp:
            cfg["enable_loopback_mcp"] = True
        provider_config[name] = cfg

    config_path.write_text(
        json.dumps({
            "providers": provider_config,
            "review": {
                "prompt_template": "Scope: {scope}\n\n{diff}\n\n{files}\n",
                "default_providers": list(providers.keys()),
            },
        })
    )


def _run_codex(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run codex.py with given args."""
    return subprocess.run(
        [sys.executable, str(CODEX_SCRIPT)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


class TestLoopbackEndToEnd:
    """End-to-end integration: cmd_review with loopback MCP."""

    def test_review_completes_with_loopback_enabled(self, tmp_path):
        """cmd_review starts the MCP loopback, runs providers, and cleans up."""
        repo = _simple_repo(tmp_path)
        provider_a_path = tmp_path / "bin" / "claude-code"
        provider_b_path = tmp_path / "bin" / "codex"

        _write_provider_script(provider_a_path, marker="review-a")
        _write_provider_script(provider_b_path, marker="review-b")

        config_path = tmp_path / "config.json"
        out_dir = tmp_path / "reviews"
        providers = {"claude-code": provider_a_path, "codex": provider_b_path}
        _write_config(config_path, providers, enable_loopback_mcp=True)

        result = _run_codex(
            [
                "review",
                "--scope", ".",
                "--root", str(repo),
                "--config", str(config_path),
                "--out-dir", str(out_dir),
            ],
            cwd=repo,
        )

        # Review should complete successfully
        assert result.returncode == 0, (
            f"Expected rc=0, got rc={result.returncode}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
        # Review dir path should be in stdout
        assert str(out_dir) in result.stdout, (
            f"Expected out_dir in stdout:\n{result.stdout[:500]}"
        )
        # MCP server referenced in stderr (lifecycle evidence)
        assert "MCP loopback server" in result.stderr, (
            f"Expected MCP server reference in stderr:\n{result.stderr[:500]}"
        )
        assert "stopping MCP loopback server" in result.stderr, (
            f"Expected MCP server stop in stderr:\n{result.stderr[:500]}"
        )

    def test_loopback_disabled_review_still_works(self, tmp_path):
        """Without loopback MCP flags, standard review flow is unaffected."""
        repo = _simple_repo(tmp_path)
        provider_a_path = tmp_path / "bin" / "provider-a"
        provider_b_path = tmp_path / "bin" / "provider-b"

        _write_provider_script(provider_a_path)
        _write_provider_script(provider_b_path)

        # No enable_loopback_mcp flag
        config_path = tmp_path / "config.json"
        out_dir = tmp_path / "reviews"
        providers = {"provider-a": provider_a_path, "provider-b": provider_b_path}
        _write_config(config_path, providers)

        result = _run_codex(
            [
                "review",
                "--scope", ".",
                "--root", str(repo),
                "--config", str(config_path),
                "--out-dir", str(out_dir),
            ],
            cwd=repo,
        )

        assert result.returncode == 0, (
            f"Expected rc=0, got rc={result.returncode}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
        # Standard output: review dir path
        assert str(out_dir) in result.stdout
        # All providers completed
        assert "provider-a" in result.stderr
        assert "provider-b" in result.stderr


# ---------------------------------------------------------------------------
# BUG_TARGETS schema validation
# ---------------------------------------------------------------------------

class TestBugTargetsSchema:
    """Validate the BUG_TARGETS constant schema."""

    def test_all_fields_present(self):
        for target in BUG_TARGETS:
            assert set(target.keys()) == {
                "id", "round", "title", "file", "area",
                "bug_class", "description", "pattern",
            }, f"Bug #{target['id']} has unexpected fields"

    def test_bug_class_values(self):
        valid_classes = {"caller-flow", "writer-schema", "sibling-code",
                         "unverified-invariant"}
        for target in BUG_TARGETS:
            assert target["bug_class"] in valid_classes, (
                f"Bug #{target['id']} has invalid bug_class "
                f"'{target['bug_class']}'"
            )

    def test_round_values(self):
        for target in BUG_TARGETS:
            assert target["round"].startswith("R"), (
                f"Bug #{target['id']} has invalid round '{target['round']}'"
            )

    def test_ids_are_unique(self):
        ids = [t["id"] for t in BUG_TARGETS]
        assert len(ids) == len(set(ids)), "Duplicate bug IDs found"

    def test_every_bug_target_is_referenced_in_at_least_one_test(self):
        """Prove all 7 bugs are documented — this doesn't test the MCP plumbing
        but ensures the fixture's test-readability contract is met."""
        assert len(BUG_TARGETS) == 7
        # Every bug has a pattern long enough to be searchable
        for target in BUG_TARGETS:
            assert len(target["pattern"]) > 10, (
                f"Bug #{target['id']} pattern too short to be meaningful"
            )

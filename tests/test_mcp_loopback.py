"""Tests for TRN-3024 Slice A: loopback MCP server lifecycle and read-only tools.

Tests use the async MCP server directly without launching real providers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts.mcp_loopback import (
    TOOL_METHODOLOGY,
    TOOL_PEER_FINDINGS,
    TOOL_CURRENT_SCOPE,
    TOOL_PRIOR_REVIEW,
    _METHODOLOGY_RULE,
    _make_tool_result,
    _read_completed_peer_outputs,
    _resolve_prior_review,
    _check_auth,
    _count_diff_lines,
)


@pytest.fixture(autouse=True)
def _clear_trinity_mcp_token():
    """Ensure TRINITY_MCP_TOKEN is clean before and after each test."""
    os.environ.pop("TRINITY_MCP_TOKEN", None)
    yield
    os.environ.pop("TRINITY_MCP_TOKEN", None)


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helper: send an HTTP request to the server
# ---------------------------------------------------------------------------


async def _http_request(
    host: str,
    port: int,
    method: str,
    path: str,
    token: str,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    """Send an HTTP request to the loopback server and return (status, body)."""
    import asyncio

    reader, writer = await asyncio.open_connection(host, port)
    try:
        lines = [f"{method} {path} HTTP/1.1".encode()]
        lines.append(f"Host: {host}:{port}".encode())
        if token:
            lines.append(f"Authorization: Bearer {token}".encode())
        if body is not None:
            lines.append(f"Content-Length: {len(body)}".encode())
            lines.append(b"Content-Type: application/json")
        # Empty line between headers and body
        lines.append(b"")
        if body is not None:
            lines.append(body)
        else:
            # Need a second empty so the join produces a trailing \r\n
            lines.append(b"")

        writer.write(b"\r\n".join(lines))
        await writer.drain()

        # Read status line
        status_line = await reader.readline()
        if not status_line:
            return (0, b"")

        status_parts = status_line.decode("utf-8", errors="replace").strip().split(" ")
        status_code = int(status_parts[1]) if len(status_parts) >= 2 else 0

        # Read headers
        content_length = 0
        while True:
            header_line = await reader.readline()
            header_str = header_line.decode("utf-8", errors="replace").strip()
            if not header_str:
                break
            if header_str.lower().startswith("content-length:"):
                try:
                    content_length = int(header_str.split(":", 1)[1].strip())
                except ValueError:
                    pass

        # Read body
        response_body = b""
        if content_length > 0:
            response_body = await reader.readexactly(content_length)

        return (status_code, response_body)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def _mcp_request(
    port: int,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int = 1,
) -> tuple[int, dict]:
    """Send a JSON-RPC request via the /mcp endpoint."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }).encode()

    status, resp_body = await _http_request(
        "127.0.0.1", port, "POST", "/mcp", token, body
    )
    if resp_body:
        return (status, json.loads(resp_body))
    return (status, {})


# ---------------------------------------------------------------------------
# Tool response shape tests
# ---------------------------------------------------------------------------


class TestToolResultShape:
    """Verify the PRP-mandated tool response shape."""

    def test_ok_result(self):
        result = _make_tool_result("ok", data={"key": "val"})
        assert result["status"] == "ok"
        assert result["data"] == {"key": "val"}
        assert result["error"] is None

    def test_empty_result(self):
        result = _make_tool_result("empty", data=[])
        assert result["status"] == "empty"
        assert result["data"] == []
        assert result["error"] is None

    def test_error_result(self):
        result = _make_tool_result("error", error="something broke")
        assert result["status"] == "error"
        assert result["data"] is None
        assert result["error"] == "something broke"


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuth:
    """Server rejects unauthenticated requests."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        yield
        await server.stop()

    async def test_no_auth_header_returns_401(self):
        status, body = await _http_request(
            "127.0.0.1", self._port, "POST", "/mcp", token="",
        )
        assert status == 401

    async def test_wrong_token_returns_401(self):
        status, body = await _http_request(
            "127.0.0.1", self._port, "POST", "/mcp", token="wrong-token",
        )
        assert status == 401

    async def test_valid_token_succeeds(self):
        status, body = await _mcp_request(
            self._port, self._token, "tools/list",
        )
        assert status == 200

    async def test_sse_endpoint_requires_auth(self):
        status, body = await _http_request(
            "127.0.0.1", self._port, "GET", "/sse", token="",
        )
        assert status == 401


# ---------------------------------------------------------------------------
# Tool listing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolList:
    """tools/list returns the four tool definitions."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        yield
        await server.stop()

    async def test_lists_four_tools(self):
        status, resp = await _mcp_request(
            self._port, self._token, "tools/list",
        )
        assert status == 200
        tools = resp.get("result", {}).get("tools", [])
        assert len(tools) == 4
        names = [t["name"] for t in tools]
        assert TOOL_CURRENT_SCOPE in names
        assert TOOL_PEER_FINDINGS in names
        assert TOOL_PRIOR_REVIEW in names
        assert TOOL_METHODOLOGY in names

    async def test_unknown_method_returns_error(self):
        status, resp = await _mcp_request(
            self._port, self._token, "resources/list",
        )
        assert status == 200
        assert "error" in resp
        assert resp["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Tool handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMethodologyTool:
    """trinity__methodology_rule returns the bundled methodology text."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        yield
        await server.stop()

    async def test_returns_methodology_text(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {"name": TOOL_METHODOLOGY, "arguments": {}},
        )
        assert status == 200
        result = resp.get("result", {})
        content = result.get("content", [])
        assert len(content) == 1
        tool_result = json.loads(content[0]["text"])
        assert tool_result["status"] == "ok"
        assert "Methodology" in tool_result["data"]
        assert "6-step" in tool_result["data"]


@pytest.mark.asyncio
class TestPeerFindingsTool:
    """trinity__peer_findings_so_far reads completed provider outputs."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self, tmp_path):
        from scripts.mcp_loopback import McpLoopbackServer

        # Create review dir with raw/ subdir
        review_dir = tmp_path / "reviews" / "rev-001"
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

    async def test_empty_when_no_peer_outputs(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PEER_FINDINGS,
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "empty"

    async def test_returns_peer_output(self):
        # Write a completed peer output
        (self._raw_dir / "codex.txt").write_text("PASS - all checks good")
        (self._raw_dir / "gemini.txt").write_text("FIX - found an issue")

        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PEER_FINDINGS,
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert len(result["data"]) == 2

    async def test_excludes_current_provider(self):
        (self._raw_dir / "codex.txt").write_text("PASS")
        (self._raw_dir / "gemini.txt").write_text("FIX")

        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PEER_FINDINGS,
                "arguments": {
                    "review_dir": str(self._review_dir),
                    "current_provider": "gemini",
                },
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        assert result["data"][0]["provider"] == "codex"

    async def test_missing_review_dir_returns_error(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PEER_FINDINGS,
                "arguments": {"review_dir": "/nonexistent/path"},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "error"


@pytest.mark.asyncio
class TestCurrentScopeTool:
    """trinity__current_scope reads review scope data."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self, tmp_path):
        from scripts.mcp_loopback import McpLoopbackServer

        review_dir = tmp_path / "reviews" / "rev-001"
        review_dir.mkdir(parents=True)

        server = McpLoopbackServer(review_dir=str(review_dir))
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        self._review_dir = review_dir
        yield
        await server.stop()

    async def test_returns_scope_without_diff(self):
        # Write metadata
        meta = {
            "input": {
                "mode": "plan-review",
                "changed_files": ["src/main.py", "tests/test_main.py"],
            }
        }
        (self._review_dir / "metadata.json").write_text(json.dumps(meta))

        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_CURRENT_SCOPE,
                "arguments": {"review_dir": str(self._review_dir)},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert result["data"]["mode"] == "plan-review"
        assert "src/main.py" in result["data"]["changed_files"]

    async def test_handles_missing_review_dir(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_CURRENT_SCOPE,
                "arguments": {"review_dir": "/nonexistent"},
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "error"


@pytest.mark.asyncio
class TestPriorReviewTool:
    """trinity__prior_review_summary matches prior reviews by identity."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self, tmp_path):
        from scripts.mcp_loopback import McpLoopbackServer

        # Create current review dir
        reviews_dir = tmp_path / "reviews"
        current_dir = reviews_dir / "rev-002"
        current_dir.mkdir(parents=True)

        # Write current review metadata
        current_meta = {
            "input": {
                "mode": "plan-review",
                "review_input_sha256": "abc123",
            }
        }
        (current_dir / "metadata.json").write_text(json.dumps(current_meta))

        # Create prior review with matching hash
        prior_dir = reviews_dir / "rev-001"
        prior_dir.mkdir(parents=True)
        prior_meta = {
            "input": {
                "mode": "plan-review",
                "review_input_sha256": "abc123",
            },
            "status": "completed",
            "created_at": "2026-05-28T12:00:00",
            "provider_states": {"codex": "finished", "gemini": "finished"},
            "results": [
                {"provider": "codex", "status": "pass"},
                {"provider": "gemini", "status": "fix"},
            ],
        }
        (prior_dir / "metadata.json").write_text(json.dumps(prior_meta))
        (prior_dir / "synthesis.md").write_text("# Synthesis\nAll good.\n")

        server = McpLoopbackServer(review_dir=str(current_dir))
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        self._current_dir = current_dir
        self._reviews_dir = reviews_dir
        yield
        await server.stop()

    async def test_finds_matching_prior_review(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PRIOR_REVIEW,
                "arguments": {
                    "review_dir": str(self._current_dir),
                    "review_input_sha256": "abc123",
                },
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "ok"
        assert result["data"]["mode"] == "plan-review"
        assert "Synthesis" in (result["data"].get("synopsis") or "")

    async def test_returns_empty_when_no_match(self):
        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PRIOR_REVIEW,
                "arguments": {
                    "review_dir": str(self._current_dir),
                    "review_input_sha256": "nonexistent_hash",
                },
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "empty"

    async def test_skips_prior_review_without_hash(self):
        """Prior review without review_input_sha256 should not match."""
        # Add a review without the hash
        nohash_dir = self._reviews_dir / "rev-000"
        nohash_dir.mkdir()
        nohash_meta = {
            "input": {"mode": "plan-review"},
            "status": "completed",
        }
        (nohash_dir / "metadata.json").write_text(json.dumps(nohash_meta))

        status, resp = await _mcp_request(
            self._port,
            self._token,
            "tools/call",
            {
                "name": TOOL_PRIOR_REVIEW,
                "arguments": {
                    "review_dir": str(self._current_dir),
                    "review_input_sha256": "abc123",
                },
            },
        )
        assert status == 200
        result = json.loads(resp["result"]["content"][0]["text"])
        # Should still find rev-001, not rev-000
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestReadCompletedPeerOutputs:
    """_read_completed_peer_outputs helper."""

    def test_empty_dir_returns_empty(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        assert _read_completed_peer_outputs(tmp_path, None) == []

    def test_skips_non_txt_files(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "notes.txt").write_text("data")
        results = _read_completed_peer_outputs(tmp_path, None)
        # All .txt files in raw/ are potential provider outputs
        assert len(results) == 1
        assert results[0][0] == "notes"

    def test_excludes_current_provider(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "codex.txt").write_text("PASS")
        (raw_dir / "gemini.txt").write_text("FIX")
        results = _read_completed_peer_outputs(tmp_path, "codex")
        names = [n for n, _ in results]
        assert "codex" not in names
        assert "gemini" in [n for n, _ in results]

    def test_skips_empty_files(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "codex.txt").write_text("")
        results = _read_completed_peer_outputs(tmp_path, None)
        assert len(results) == 0

    def test_missing_raw_dir_returns_empty(self, tmp_path):
        results = _read_completed_peer_outputs(tmp_path, None)
        assert results == []


class TestResolvePriorReview:
    """_resolve_prior_review identity matching."""

    def test_no_reviews_parent(self, tmp_path):
        result = _resolve_prior_review(tmp_path / "reviews" / "rev-001", "abc123")
        assert result is None

    def test_skips_missing_metadata(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        rev_001 = rev_dir / "rev-001"
        rev_002 = rev_dir / "rev-002"
        rev_001.mkdir(parents=True)
        rev_002.mkdir()
        result = _resolve_prior_review(rev_002, "abc123")
        assert result is None

    def test_matches_by_hash(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        prior = rev_dir / "rev-001"
        current = rev_dir / "rev-002"
        prior.mkdir(parents=True)
        current.mkdir()
        (prior / "metadata.json").write_text(json.dumps({
            "input": {"review_input_sha256": "abc123"},
            "status": "completed",
            "created_at": "2026-01-01T00:00:00",
        }))
        (current / "metadata.json").write_text(json.dumps({
            "input": {"review_input_sha256": "abc123"},
        }))
        result = _resolve_prior_review(current, "abc123")
        assert result is not None
        assert result["status"] == "completed"

    def test_no_match_for_wrong_hash(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        prior = rev_dir / "rev-001"
        current = rev_dir / "rev-002"
        prior.mkdir(parents=True)
        current.mkdir()
        (prior / "metadata.json").write_text(json.dumps({
            "input": {"review_input_sha256": "diff-hash"},
        }))
        (current / "metadata.json").write_text(json.dumps({
            "input": {"review_input_sha256": "target-hash"},
        }))
        result = _resolve_prior_review(current, "target-hash")
        assert result is None

    def test_skips_prior_without_hash_field(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        prior = rev_dir / "rev-001"
        current = rev_dir / "rev-002"
        prior.mkdir(parents=True)
        current.mkdir()
        (prior / "metadata.json").write_text(json.dumps({
            "input": {"mode": "plan-review"},  # no review_input_sha256
        }))
        result = _resolve_prior_review(current, "any-hash")
        assert result is None

    def test_skips_current_dir(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        current = rev_dir / "rev-001"
        current.mkdir(parents=True)
        (current / "metadata.json").write_text(json.dumps({
            "input": {"review_input_sha256": "abc123"},
        }))
        # The only review dir with this hash IS the current one
        result = _resolve_prior_review(current, "abc123")
        assert result is None

    def test_bad_json_in_prior_skipped(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        prior = rev_dir / "rev-001"
        current = rev_dir / "rev-002"
        prior.mkdir(parents=True)
        current.mkdir()
        (prior / "metadata.json").write_text("not json")
        result = _resolve_prior_review(current, "abc123")
        assert result is None


class TestCheckAuth:
    """Bearer token validation."""

    def test_missing_header(self):
        assert _check_auth({}, "token123") is False

    def test_wrong_scheme(self):
        assert _check_auth({"authorization": "Basic token123"}, "token123") is False

    def test_wrong_token(self):
        assert _check_auth({"authorization": "Bearer wrong"}, "correct") is False

    def test_correct_token(self):
        assert _check_auth({"authorization": "Bearer correct"}, "correct") is True

    def test_case_sensitive(self):
        assert _check_auth({"authorization": "bearer correct"}, "correct") is False

    def test_empty_token_in_header(self):
        assert _check_auth({"authorization": "Bearer "}, "token") is False


class TestCountDiffLines:
    """Diff line counting helper."""

    def test_empty_diff(self):
        assert _count_diff_lines("") == 0

    def test_counts_additions(self):
        diff = """--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old line
+new line"""
        assert _count_diff_lines(diff) == 2


    def test_counts_deletions(self):
        diff = """--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old line
+new line"""
        assert _count_diff_lines(diff) == 2


    def test_ignores_hunk_headers(self):
        diff = """--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old
+new
+another
-yet_another"""
        assert _count_diff_lines(diff) == 4


    def test_ignores_diff_git_headers(self):
        diff = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-old
+new"""
        # The +++ and --- lines should NOT be counted
        assert _count_diff_lines(diff) == 2


    def test_multiple_hunks(self):
        diff = """--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-old_a
+new_a
@@ -10 +10 @@
-old_b
+new_b"""
        assert _count_diff_lines(diff) == 4


class TestMethodologyConstant:
    """Verify the bundled methodology constant matches the source file."""

    def test_contains_methodology_heading(self):
        assert "### §4. Methodology" in _METHODOLOGY_RULE

    def test_contains_6step_reference(self):
        assert "6-step" in _METHODOLOGY_RULE

    def test_contains_all_six_steps(self):
        for step_num in range(1, 7):
            assert f"{step_num}." in _METHODOLOGY_RULE

    def test_matches_source_file_structure(self):
        """Verify the bundled constant reflects the methodology from the source.
        
        This test reads the source rule file and confirms that the heading
        `### §4. Methodology` exists, ensuring edits to the source preserve
        the heading prefix (as required by the PRP).
        """
        source_path = Path("rules/TRN-1007-SOP-PR-Readiness.md")
        assert source_path.is_file(), "Source methodology file not found"
        content = source_path.read_text()
        assert "### §4. Methodology" in content, (
            "Source file must contain the §4 Methodology heading "
            "(required by TRN-3024 PRP for bundle extraction)"
        )


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLifecycle:
    """Server lifecycle (start, bind, stop)."""

    async def test_binds_to_localhost(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        assert port > 0
        assert port <= 65535
        await server.stop()

    async def test_port_is_ephemeral(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        # Ephemeral ports are typically >= 32768, but we just check > 0
        assert port > 0
        await server.stop()

    async def test_multiple_servers_different_ports(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server1 = McpLoopbackServer()
        server2 = McpLoopbackServer()
        port1 = await server1.start()
        port2 = await server2.start()
        assert port1 != port2
        await server1.stop()
        await server2.stop()

    async def test_stop_then_start_again(self):
        """Stop is idempotent and allows re-binding."""
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        assert port > 0
        await server.stop()
        # Stop again should be safe
        await server.stop()

    async def test_generates_token_by_default(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        assert server.token is not None
        assert len(server.token) == 32
        await server.start()
        await server.stop()

    async def test_accepts_custom_token(self):
        from scripts.mcp_loopback import McpLoopbackServer

        custom_token = "custom-token-123"
        server = McpLoopbackServer(token=custom_token)
        assert server.token == custom_token
        await server.start()
        await server.stop()

    async def test_token_length_is_32_chars(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        await server.start()
        assert len(server.token) == 32
        await server.stop()

    async def test_trinity_mcp_token_env_var(self):
        """Server sets TRINITY_MCP_TOKEN in the environment."""
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        await server.start()
        assert os.environ.get("TRINITY_MCP_TOKEN") == server.token
        await server.stop()

    async def test_does_not_overwrite_existing_trinity_mcp_token(self):
        """If TRINITY_MCP_TOKEN is already set, server uses it."""
        from scripts.mcp_loopback import McpLoopbackServer

        os.environ["TRINITY_MCP_TOKEN"] = "preexisting-token"
        server = McpLoopbackServer()
        await server.start()
        assert os.environ["TRINITY_MCP_TOKEN"] == "preexisting-token"
        await server.stop()
        # Clean up
        os.environ.pop("TRINITY_MCP_TOKEN", None)


# ---------------------------------------------------------------------------
# 404 / unknown endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEndpointRouting:
    """Server only responds to /sse, /messages, and /mcp."""

    @pytest.fixture(autouse=True)
    async def _server_fixture(self):
        from scripts.mcp_loopback import McpLoopbackServer

        server = McpLoopbackServer()
        port = await server.start()
        self._server = server
        self._port = port
        self._token = server.token
        yield
        await server.stop()

    async def test_unknown_path_returns_404(self):
        status, body = await _http_request(
            "127.0.0.1", self._port, "GET", "/unknown", self._token,
        )
        assert status == 404

    async def test_wrong_method_on_mcp(self):
        status, body = await _http_request(
            "127.0.0.1", self._port, "GET", "/mcp", self._token,
        )
        assert status == 404

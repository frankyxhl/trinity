"""TRN-3024 Slice A: loopback MCP server lifecycle and read-only tools.

Exposes a read-only MCP (Model Context Protocol) server on 127.0.0.1 with
bearer-token authentication and four read-only tool handlers. No provider
is wired in this slice; provider injection happens in Slices B and C
(issues #139 and #140).

Tool contracts (per TRN-3024 PRP):
  trinity__current_scope       — re-read of files/diff hunks under review
  trinity__peer_findings_so_far — completed raw/<other-provider>.txt outputs
  trinity__prior_review_summary — synthesis.md + metadata.json from prior review
  trinity__methodology_rule     — TRN-1007 §4 methodology rule text

Transport:
  /sse   — MCP over HTTP SSE (GET long-lived stream, POST /messages)
  /mcp   — MCP streamable HTTP (POST request/response)

Security:
  - Binds to 127.0.0.1 only (loopback)
  - OS-allocated ephemeral port
  - Bearer token (32-char hex, from os.urandom(16).hex())
  - Unauthenticated requests → HTTP 401 with no JSON-RPC body
  - No TLS (loopback-only threat model)

Lifecycle:
  - SIGTERM handler responds 503 to in-flight requests and exits
  - Normal stop via asyncio event loop shutdown
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import signal
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcp_loopback")

# ---------------------------------------------------------------------------
# Methodology rule — bundled runtime copy of TRN-1007 §4.
# Source: rules/TRN-1007-SOP-PR-Readiness.md line starting with "### §4."
# Keep in sync when the source file changes.
# ---------------------------------------------------------------------------
_METHODOLOGY_RULE = """### §4. Methodology (PR #60 / #61 / #64-derived 6-step rule)

For new code surfaces, verify each step in the CHG body OR a PR-body checklist. Each item is "verified" when the named artifact below exists / passes:

1. **Trace caller flows** of any function the diff consumes data from
   - *Verify*: name at least one concrete caller function and the data it passes; cite file:line.
2. **Read writer schemas** of any data the diff parses
   - *Verify*: cite the writer's file:line and the field shape (or stdlib doc if external); show a test asserting the contract.
3. **Compare to sibling registration sites** for any new subcommand / feature / config key
   - *Verify*: list the sibling sites and confirm they're either updated or explicitly out-of-scope (e.g., reserved-words sets, config validators, help text registries).
4. **When fixing value-handling in helper X**, grep for the same hard-code/pattern in sibling helpers consuming the same data source
   - *Verify*: paste the `grep` command run; cite each hit either fixed or noted N/A.
5. **Comments asserting invariants** are paired with tests
   - *Verify*: each invariant docstring cites its corresponding test by name.
6. **Backwards-compat against older-tag matrix** verified — especially install / runtime spawn flows (PR #64 R1 lesson: piping `main`'s `install.sh` with `TRINITY_VERSION=<older-tag>` must still produce a clean failure or workaround)
   - *Verify*: state which version-pin / older-tag scenarios were checked and the expected behavior in each."""

# MCP protocol constants
MCP_PROTOCOL_VERSION_SSE = "2024-11-05"
MCP_PROTOCOL_VERSION_STREAMABLE = "2025-03-26"
MCP_JSONRPC_VERSION = "2.0"

# Tool names
TOOL_CURRENT_SCOPE = "trinity__current_scope"
TOOL_PEER_FINDINGS = "trinity__peer_findings_so_far"
TOOL_PRIOR_REVIEW = "trinity__prior_review_summary"
TOOL_METHODOLOGY = "trinity__methodology_rule"

# ---------------------------------------------------------------------------
# Server state / data objects
# ---------------------------------------------------------------------------


@dataclass
class SseSession:
    """An active SSE connection with its pending-response queue."""

    session_id: str
    messages: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    _closed: bool = False

    async def send_event(self, event: str, data: str) -> None:
        if self._closed:
            return
        payload = f"event: {event}\ndata: {data}\n\n"
        await self.messages.put(payload)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.messages.put_nowait("")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


# Tool schema descriptors for tools/list
_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": TOOL_CURRENT_SCOPE,
        "description": "Re-read of files/diff hunks under review, including diff --git output and changed-file list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_dir": {"type": "string", "description": "Path to the review directory"},
            },
            "required": ["review_dir"],
        },
    },
    {
        "name": TOOL_PEER_FINDINGS,
        "description": "Concatenation of completed raw/<other-provider>.txt outputs for providers that have already finished.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_dir": {"type": "string", "description": "Path to the review directory"},
                "current_provider": {
                    "type": "string",
                    "description": "Name of the calling provider (excluded from peer results)",
                },
            },
            "required": ["review_dir"],
        },
    },
    {
        "name": TOOL_PRIOR_REVIEW,
        "description": "Structured summary from the immediately prior review on the same review input, if one exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_dir": {"type": "string", "description": "Path to the current review directory"},
                "review_input_sha256": {
                    "type": "string",
                    "description": "Optional SHA-256 override for identity matching; defaults to metadata.json input.review_input_sha256",
                },
            },
            "required": ["review_dir"],
        },
    },
    {
        "name": TOOL_METHODOLOGY,
        "description": "The current TRN-1007 §4 Methodology rule text (6-step rule).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _make_tool_result(status: str, data: Any = None, error: str | None = None) -> dict:
    """Build a standard tool response per the PRP contract."""
    result: dict[str, Any] = {"status": status}
    if data is not None:
        result["data"] = data
    else:
        result["data"] = None
    result["error"] = error
    return result


def _read_completed_peer_outputs(review_dir: Path, current_provider: str | None) -> list[tuple[str, str]]:
    """Read completed raw/<provider>.txt files, excluding current_provider.

    Only reads raw artifacts recorded in metadata.results. The provider runner
    appends a result only after composing the raw file, so this avoids treating
    an in-progress raw write as authoritative peer findings.
    """
    metadata = _read_review_metadata(review_dir)
    result_entries = metadata.get("results", [])
    if not isinstance(result_entries, list):
        return []

    review_root = review_dir.resolve()
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in result_entries:
        if not isinstance(entry, dict):
            continue
        raw_rel = entry.get("raw")
        if not isinstance(raw_rel, str) or not raw_rel:
            continue
        name_value = entry.get("provider")
        name = name_value if isinstance(name_value, str) and name_value else Path(raw_rel).stem
        if current_provider and name == current_provider:
            continue
        if name in seen:
            continue

        try:
            fpath = (review_dir / raw_rel).resolve()
            fpath.relative_to(review_root)
        except (OSError, ValueError):
            continue
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text()
        except (OSError, PermissionError):
            continue
        if not content.strip():
            continue
        results.append((name, content))
        seen.add(name)

    return results


def _read_review_metadata(review_dir: Path) -> dict[str, Any]:
    """Read metadata.json from a review directory."""
    meta_path = review_dir / "metadata.json"
    try:
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text())
            if isinstance(meta, dict):
                return meta
    except (json.JSONDecodeError, OSError, PermissionError):
        pass
    return {}


def _metadata_input(meta: dict[str, Any]) -> dict[str, Any]:
    input_info = meta.get("input", {})
    return input_info if isinstance(input_info, dict) else {}


def _review_identity(
    input_info: dict[str, Any],
    review_input_sha256: str | None = None,
) -> tuple[tuple[str, Any], ...] | None:
    """Return the stable review identity used to reuse prior summaries."""
    input_hash = input_info.get("review_input_sha256") or review_input_sha256
    mode = input_info.get("mode")
    if not input_hash or not mode:
        return None

    fields: list[tuple[str, Any]] = [
        ("mode", mode),
        ("scope", input_info.get("scope") or "."),
        ("review_input_sha256", input_hash),
    ]

    if mode == "pr":
        if input_info.get("pr") is None:
            return None
        fields.append(("pr", input_info.get("pr")))
    elif mode == "base-head":
        if not input_info.get("base") or not input_info.get("head"):
            return None
        fields.extend([
            ("base", input_info.get("base")),
            ("head", input_info.get("head")),
        ])
    elif mode == "working-tree":
        fields.extend([
            ("base", input_info.get("base") or "HEAD"),
            ("head", input_info.get("head") or "working-tree"),
        ])
    else:
        for key in ("pr", "base", "head"):
            if key in input_info:
                fields.append((key, input_info.get(key)))

    return tuple(fields)


def _resolve_prior_review(
    current_review_dir: Path,
    review_input_sha256: str,
) -> dict | None:
    """Find the immediately prior review matching the same input identity.

    Looks in the parent reviews directory for the most recent review
    matching the current mode/scope/review identity plus input hash.
    """
    reviews_parent = current_review_dir.parent
    if not reviews_parent.is_dir():
        return None

    current_identity = _review_identity(
        _metadata_input(_read_review_metadata(current_review_dir)),
        review_input_sha256,
    )
    if current_identity is None:
        return None

    candidates: list[Path] = []
    try:
        for entry in reviews_parent.iterdir():
            if not entry.is_dir() or entry.resolve() == current_review_dir.resolve():
                continue
            meta_path = entry / "metadata.json"
            if not meta_path.is_file():
                continue
            meta = _read_review_metadata(entry)
            candidate_input = _metadata_input(meta)
            if candidate_input.get("review_input_sha256") != review_input_sha256:
                continue
            if _review_identity(candidate_input) == current_identity:
                candidates.append(entry)
    except (OSError, PermissionError):
        return None

    if not candidates:
        return None

    # Pick the most recent by review timestamp, tiebroken by mtime.
    def _sort_key(p: Path) -> tuple[str, float]:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (p.name[:15], mtime)

    candidates.sort(key=_sort_key, reverse=True)
    best = candidates[0]

    # Build the summary response
    best_meta = {}
    synopsis = None
    try:
        meta_path = best / "metadata.json"
        if meta_path.is_file():
            best_meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError, PermissionError):
        pass

    try:
        syn_path = best / "synthesis.md"
        if syn_path.is_file():
            synopsis = syn_path.read_text()
    except OSError:
        pass

    return {
        "review_dir": str(best),
        "timestamp": best_meta.get("created_at") or best_meta.get("started_at") or "",
        "mode": best_meta.get("input", {}).get("mode", ""),
        "status": best_meta.get("status", ""),
        "provider_count": len(best_meta.get("provider_states", {})),
        "result_count": len(best_meta.get("results", [])),
        "synopsis": synopsis,
    }


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


async def handle_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict:
    """Dispatch a tool call to the appropriate handler.

    Returns a JSON-RPC result-shaped dict with a ``content`` list containing
    the tool response as a text content item.
    """
    try:
        raw_result = await _dispatch_tool_inner(tool_name, arguments)
    except Exception as exc:
        logger.exception("Tool %s failed", tool_name)
        raw_result = _make_tool_result("error", error=str(exc))

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(raw_result),
            }
        ],
        "isError": raw_result.get("status") == "error",
    }


async def _dispatch_tool_inner(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Inner dispatch — returns the raw tool result dict."""
    if tool_name == TOOL_METHODOLOGY:
        return _handle_methodology()
    elif tool_name == TOOL_PEER_FINDINGS:
        return _handle_peer_findings(arguments)
    elif tool_name == TOOL_PRIOR_REVIEW:
        return _handle_prior_review(arguments)
    elif tool_name == TOOL_CURRENT_SCOPE:
        return _handle_current_scope(arguments)
    else:
        return _make_tool_result("error", error=f"Unknown tool: {tool_name}")


def _handle_methodology() -> dict:
    """Return the bundled methodology rule text."""
    return _make_tool_result("ok", data=_METHODOLOGY_RULE)


def _handle_peer_findings(arguments: dict[str, Any]) -> dict:
    """Return concatenated completed peer outputs."""
    review_dir_str = arguments.get("review_dir", "")
    if not review_dir_str:
        return _make_tool_result("error", error="review_dir is required")
    review_dir = Path(review_dir_str)
    if not review_dir.is_dir():
        return _make_tool_result("error", error=f"review_dir not found: {review_dir_str}")

    current_provider = arguments.get("current_provider")
    peers = _read_completed_peer_outputs(review_dir, current_provider)
    if not peers:
        return _make_tool_result("empty", data=[])

    data = [{"provider": name, "content": content} for name, content in peers]
    return _make_tool_result("ok", data=data)


def _handle_prior_review(arguments: dict[str, Any]) -> dict:
    """Return prior review summary matching the input identity."""
    review_dir_str = arguments.get("review_dir", "")
    if not review_dir_str:
        return _make_tool_result("error", error="review_dir is required")

    current_dir = Path(review_dir_str)
    if not current_dir.is_dir():
        return _make_tool_result("error", error=f"review_dir not found: {review_dir_str}")

    current_input = _metadata_input(_read_review_metadata(current_dir))
    review_input_sha256 = (
        arguments.get("review_input_sha256")
        or current_input.get("review_input_sha256")
        or ""
    )
    if not review_input_sha256:
        return _make_tool_result("empty", data=None)

    prior = _resolve_prior_review(current_dir, review_input_sha256)
    if prior is None:
        return _make_tool_result("empty", data=None)

    return _make_tool_result("ok", data=prior)


def _handle_current_scope(arguments: dict[str, Any]) -> dict:
    """Re-read scope data from the review directory."""
    review_dir_str = arguments.get("review_dir", "")
    if not review_dir_str:
        return _make_tool_result("error", error="review_dir is required")

    review_dir = Path(review_dir_str)
    if not review_dir.is_dir():
        return _make_tool_result("error", error=f"review_dir not found: {review_dir_str}")

    scope_info = _metadata_input(_read_review_metadata(review_dir))
    diff_content = _read_review_diff(review_dir)

    # Cap response size to protect provider context windows
    MAX_SCOPE_BYTES = 512 * 1024  # 512 KiB
    if diff_content and len(diff_content) > MAX_SCOPE_BYTES:
        return _make_tool_result(
            "error",
            error=f"Scope exceeds {MAX_SCOPE_BYTES}-byte ceiling; resolve a narrower scope first",
        )

    changed_files = scope_info.get("changed_paths") or scope_info.get("changed_files", [])
    if diff_content:
        changed_lines = _count_diff_lines(diff_content)
    else:
        changed_lines = 0

    data: dict[str, Any] = {
        "changed_files": changed_files,
        "changed_lines": changed_lines,
        "mode": scope_info.get("mode", ""),
        "diff": diff_content,
        "metadata": scope_info,
    }
    return _make_tool_result("ok", data=data)


def _read_review_diff(review_dir: Path) -> str | None:
    """Read the diff from cmd_review artifacts, with legacy diff.patch fallback."""
    prompt_path = review_dir / "prompt.md"
    try:
        if prompt_path.is_file():
            diff_content = _extract_prompt_diff(prompt_path.read_text())
            if diff_content:
                return diff_content
    except (OSError, PermissionError):
        pass

    diff_path = review_dir / "diff.patch"
    try:
        if diff_path.is_file():
            return diff_path.read_text()
    except (OSError, PermissionError):
        pass
    return None


def _extract_prompt_diff(prompt_text: str) -> str | None:
    """Extract the rendered review diff from prompt.md."""
    search_from = prompt_text.find("## Git Diff")
    if search_from < 0:
        search_from = 0

    fence_start = prompt_text.find("```diff", search_from)
    if fence_start >= 0:
        body_start = prompt_text.find("\n", fence_start)
        if body_start >= 0:
            body_start += 1
            body_end = prompt_text.find("\n```", body_start)
            if body_end < 0:
                return prompt_text[body_start:].rstrip()
            return prompt_text[body_start:body_end].rstrip()

    raw_start = prompt_text.find("diff --git ", search_from)
    if raw_start < 0:
        return None
    raw_end = len(prompt_text)
    for marker in ("\n### ", "\n## Review Schema", "\n## Structured Output"):
        marker_pos = prompt_text.find(marker, raw_start)
        if marker_pos >= 0:
            raw_end = min(raw_end, marker_pos)
    return prompt_text[raw_start:raw_end].rstrip()


def _count_diff_lines(diff: str) -> int:
    """Count lines changed in a unified diff (additions + deletions)."""
    count = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++ "):
            count += 1
        elif line.startswith("-") and not line.startswith("--- "):
            count += 1
    return count


# ---------------------------------------------------------------------------
# HTTP request / response helpers
# ---------------------------------------------------------------------------


def _build_http_response(
    status_code: int,
    status_text: str,
    body: bytes = b"",
    content_type: str = "application/json",
    extra_headers: list[tuple[str, str]] | None = None,
) -> bytes:
    """Build an HTTP/1.1 response byte string."""
    lines = [f"HTTP/1.1 {status_code} {status_text}".encode()]
    lines.append(f"Content-Type: {content_type}".encode())
    lines.append(f"Content-Length: {len(body)}".encode())
    if extra_headers:
        for k, v in extra_headers:
            lines.append(f"{k}: {v}".encode())
    lines.append(b"Connection: close")
    lines.append(b"")
    lines.append(body)
    return b"\r\n".join(lines)


def _build_sse_headers() -> list[tuple[str, str]]:
    """Return SSE endpoint response headers."""
    return [
        ("Content-Type", "text/event-stream"),
        ("Cache-Control", "no-cache"),
        ("Connection", "keep-alive"),
        ("Access-Control-Allow-Origin", "*"),
    ]


async def _read_http_request(
    reader: asyncio.StreamReader,
) -> tuple[str, str, dict[str, str], bytes] | None:
    """Read and parse one HTTP request.

    Returns (method, path, headers, body) or None on connection close.
    """
    try:
        request_line = await reader.readline()
        if not request_line:
            return None
        request_str = request_line.decode("utf-8", errors="replace").strip()
        parts = request_str.split(" ")
        if len(parts) < 2:
            return None
        method = parts[0]
        path = parts[1]

        headers: dict[str, str] = {}
        content_length = 0
        while True:
            header_line = await reader.readline()
            header_str = header_line.decode("utf-8", errors="replace").strip()
            if not header_str:
                break
            if ":" in header_str:
                key, _, value = header_str.partition(":")
                headers[key.strip().lower()] = value.strip()
                if key.strip().lower() == "content-length":
                    try:
                        content_length = int(value.strip())
                    except ValueError:
                        pass

        body = b""
        if content_length > 0:
            body = await reader.readexactly(content_length)
        return (method, path, headers, body)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        return None


def _check_auth(headers: dict[str, str], expected_token: str) -> bool:
    """Validate Bearer token from Authorization header."""
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[len("Bearer "):]
    return token == expected_token


# ---------------------------------------------------------------------------
# MCP JSON-RPC helpers
# ---------------------------------------------------------------------------


def _make_jsonrpc_response(
    request_id: Any,
    result: dict | None = None,
    error: dict | None = None,
) -> dict:
    """Build a JSON-RPC 2.0 response dict."""
    resp: dict[str, Any] = {"jsonrpc": MCP_JSONRPC_VERSION}
    if request_id is not None:
        resp["id"] = request_id
    else:
        resp["id"] = None
    if error:
        resp["error"] = error
    elif result is not None:
        resp["result"] = result
    return resp


def _make_jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return _make_jsonrpc_response(request_id, error={"code": code, "message": message})


def _make_tools_list_response(request_id: Any) -> dict:
    """Build tools/list response."""
    return _make_jsonrpc_response(
        request_id,
        result={"tools": _TOOL_DEFINITIONS},
    )


def _make_initialize_response(request_id: Any, params: dict[str, Any]) -> dict:
    """Build the MCP initialize response required before tool discovery."""
    protocol_version = params.get("protocolVersion") or MCP_PROTOCOL_VERSION_STREAMABLE
    return _make_jsonrpc_response(
        request_id,
        result={
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "trinity-loopback", "version": "0.1.0"},
        },
    )


async def _make_tool_call_response(request_id: Any, tool_name: str, arguments: dict) -> dict:
    """Build tools/call response by dispatching to the handler."""
    tool_result = await handle_tool_call(tool_name, arguments)
    return _make_jsonrpc_response(request_id, result=tool_result)


def _bind_review_dir_argument(
    tool_name: str,
    arguments: dict[str, Any],
    server_review_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if tool_name not in {TOOL_CURRENT_SCOPE, TOOL_PEER_FINDINGS, TOOL_PRIOR_REVIEW}:
        return arguments, None
    if not server_review_dir:
        return arguments, None

    expected = Path(server_review_dir).expanduser().resolve()
    requested = arguments.get("review_dir") or server_review_dir
    requested_path = Path(str(requested)).expanduser().resolve()
    if requested_path != expected:
        return None, "review_dir must match the loopback server review_dir"

    bound = dict(arguments)
    bound["review_dir"] = str(expected)
    return bound, None


async def _dispatch_mcp_request(
    request: dict[str, Any],
    server_review_dir: str = "",
) -> dict | None:
    """Dispatch one MCP JSON-RPC request. Returns None for notifications."""
    request_id = request.get("id")
    method_name = request.get("method", "")
    params = request.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if method_name == "initialize":
        return _make_initialize_response(request_id, params)
    if method_name == "notifications/initialized":
        return None
    if method_name == "tools/list":
        return _make_tools_list_response(request_id)
    if method_name == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        arguments, bind_error = _bind_review_dir_argument(
            tool_name,
            arguments,
            server_review_dir,
        )
        if bind_error:
            raw_result = _make_tool_result("error", error=bind_error)
            return _make_jsonrpc_response(
                request_id,
                result={
                    "content": [{"type": "text", "text": json.dumps(raw_result)}],
                    "isError": True,
                },
            )
        return await _make_tool_call_response(request_id, tool_name, arguments)
    return _make_jsonrpc_error(request_id, -32601, f"Method not found: {method_name}")


# ---------------------------------------------------------------------------
# MCP Loopback Server
# ---------------------------------------------------------------------------


class McpLoopbackServer:
    """Loopback MCP server with auth, SSE, and streamable HTTP transports.

    Usage:
        server = McpLoopbackServer(review_dir="/path/to/review")
        port = await server.start()
        # ... use the server ...
        await server.stop()
    """

    def __init__(
        self,
        review_dir: str = "",
        token: str | None = None,
    ) -> None:
        self._review_dir = review_dir
        env_token = os.environ.get("TRINITY_MCP_TOKEN")
        self._token = token or env_token or secrets.token_hex(16)  # 32-char hex
        self._server: asyncio.AbstractServer | None = None
        self._port: int = 0
        self._sse_sessions: dict[str, SseSession] = {}
        self._sse_sessions_lock = asyncio.Lock()
        self._stopped = False
        self._blocking_loop: asyncio.AbstractEventLoop | None = None

        # Ensure TRINITY_MCP_TOKEN is set for child processes
        if token is not None or "TRINITY_MCP_TOKEN" not in os.environ:
            os.environ["TRINITY_MCP_TOKEN"] = self._token

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    async def start(self) -> int:
        """Start the server, bind to 127.0.0.1 with an ephemeral port.

        Returns the assigned port number.
        """
        self._server = await asyncio.start_server(
            self._handle_connection,
            host="127.0.0.1",
            port=0,
        )
        for sock in self._server.sockets:
            if sock.family == socket.AF_INET:
                self._port = sock.getsockname()[1]
                break

        logger.info("MCP loopback server started on 127.0.0.1:%d", self._port)
        return self._port

    async def stop(self) -> None:
        """Gracefully stop the server and close all SSE sessions."""
        blocking_loop = self._blocking_loop
        running_loop = asyncio.get_running_loop()
        try:
            if (
                blocking_loop is not None
                and blocking_loop.is_running()
                and blocking_loop is not running_loop
            ):
                future = asyncio.run_coroutine_threadsafe(
                    self._stop_in_current_loop(),
                    blocking_loop,
                )
                await asyncio.wrap_future(future)
                blocking_loop.call_soon_threadsafe(blocking_loop.stop)
                return

            await self._stop_in_current_loop()
            if blocking_loop is running_loop:
                blocking_loop.call_soon(blocking_loop.stop)
        finally:
            self._clear_token_env()

    def _clear_token_env(self) -> None:
        if os.environ.get("TRINITY_MCP_TOKEN") == self._token:
            os.environ.pop("TRINITY_MCP_TOKEN", None)

    async def _stop_in_current_loop(self) -> None:
        """Stop server resources on the loop that owns them."""
        self._stopped = True
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        async with self._sse_sessions_lock:
            for session in self._sse_sessions.values():
                session.close()
            self._sse_sessions.clear()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming TCP connection."""
        try:
            parsed = await _read_http_request(reader)
            if parsed is None:
                return
            method, path, headers, body = parsed

            # Auth check for all paths (including SSE endpoint)
            if not _check_auth(headers, self._token):
                resp = _build_http_response(401, "Unauthorized", b'{"error":"unauthorized"}')
                await self._write_response(writer, resp)
                return

            if path == "/sse" and method == "GET":
                await self._handle_sse(reader, writer, headers)
            elif path.startswith("/messages") and method == "POST":
                await self._handle_messages(writer, headers, body, path)
            elif path == "/mcp" and method == "POST":
                await self._handle_mcp_endpoint(writer, headers, body)
            else:
                resp = _build_http_response(404, "Not Found")
                await self._write_response(writer, resp)
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _write_response(
        self, writer: asyncio.StreamWriter, data: bytes
    ) -> None:
        try:
            writer.write(data)
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    # -- SSE endpoint -------------------------------------------------------

    async def _handle_sse(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        """Handle a GET /sse connection — SSE stream."""
        session_id = secrets.token_urlsafe(16)
        session = SseSession(session_id=session_id)

        async with self._sse_sessions_lock:
            self._sse_sessions[session_id] = session

        # Build SSE response headers
        resp_headers = _build_sse_headers()
        resp_lines = [b"HTTP/1.1 200 OK"]
        for k, v in resp_headers:
            resp_lines.append(f"{k}: {v}".encode())
        writer.write(b"\r\n".join(resp_lines) + b"\r\n\r\n")
        await writer.drain()

        disconnect_task = asyncio.create_task(reader.read())
        try:
            # Send the endpoint event with session info
            endpoint_url = f"/messages?sessionId={session_id}"
            await session.send_event("endpoint", endpoint_url)

            # Stream events from the queue
            while not self._stopped and not session._closed:
                message_task = asyncio.create_task(session.messages.get())
                try:
                    done, _ = await asyncio.wait(
                        {message_task, disconnect_task},
                        timeout=30.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if disconnect_task in done:
                        with contextlib.suppress(ConnectionError, OSError):
                            await disconnect_task
                        message_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await message_task
                        break
                    if message_task not in done:
                        message_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await message_task
                        try:
                            writer.write(b": keepalive\n\n")
                            await writer.drain()
                        except (ConnectionError, OSError):
                            break
                        continue
                    payload = message_task.result()
                    if not payload:
                        continue
                    writer.write(payload.encode())
                    await writer.drain()
                except asyncio.CancelledError:
                    message_task.cancel()
                    raise
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass
        finally:
            disconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionError, OSError):
                await disconnect_task
            session.close()
            async with self._sse_sessions_lock:
                self._sse_sessions.pop(session_id, None)

    # -- Messages endpoint (SSE backchannel) --------------------------------

    async def _handle_messages(
        self,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        body: bytes,
        path: str,
    ) -> None:
        """Handle a POST /messages?sessionId=XXX request."""
        # Parse session ID from query
        session_id = ""
        if "?" in path:
            query = path.split("?", 1)[1]
            for part in query.split("&"):
                if part.startswith("sessionId="):
                    session_id = part[len("sessionId="):]
                    break

        if not session_id:
            resp = _build_http_response(400, "Bad Request", b'{"error":"sessionId required"}')
            await self._write_response(writer, resp)
            return

        async with self._sse_sessions_lock:
            session = self._sse_sessions.get(session_id)

        if session is None or session._closed:
            resp = _build_http_response(404, "Not Found", b'{"error":"session not found"}')
            await self._write_response(writer, resp)
            return

        # Parse JSON-RPC request
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            resp = _build_http_response(400, "Bad Request", b'{"error":"invalid JSON"}')
            await self._write_response(writer, resp)
            return

        # Process the request and send responses via SSE; notifications are ACK-only.
        response = await _dispatch_mcp_request(request, self._review_dir)
        if response is not None:
            await session.send_event("message", json.dumps(response))

        # ACK the POST
        ack = _build_http_response(202, "Accepted", b"{}")
        await self._write_response(writer, ack)

    # -- Streamable HTTP endpoint (/mcp) ------------------------------------

    async def _handle_mcp_endpoint(
        self,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Handle a POST /mcp request (streamable HTTP transport)."""
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            resp = _build_http_response(400, "Bad Request", b'{"error":"invalid JSON"}')
            await self._write_response(writer, resp)
            return

        response = await _dispatch_mcp_request(request, self._review_dir)
        if response is None:
            http_resp = _build_http_response(202, "Accepted", b"{}")
        else:
            body_bytes = json.dumps(response).encode()
            http_resp = _build_http_response(200, "OK", body_bytes)
        await self._write_response(writer, http_resp)


# ---------------------------------------------------------------------------
# Top-level lifecycle helpers
# ---------------------------------------------------------------------------


async def _run_server_and_wait(
    server: McpLoopbackServer,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the server until shutdown_event is set."""
    await server.start()
    print(f"MCP server started on 127.0.0.1:{server.port}", flush=True)
    await shutdown_event.wait()


def _handle_sigterm(server: McpLoopbackServer, loop: asyncio.AbstractEventLoop) -> None:
    """Signal handler for SIGTERM — schedule server stop."""
    logger.info("Received SIGTERM, shutting down MCP server")
    loop.call_soon_threadsafe(asyncio.create_task, server.stop())


def _try_add_signal_handler(
    loop: asyncio.AbstractEventLoop,
    sig: signal.Signals,
    callback: Any,
    *args: Any,
) -> bool:
    """Register a signal handler when the current loop/platform supports it."""
    try:
        loop.add_signal_handler(sig, callback, *args)
        return True
    except (NotImplementedError, ValueError, RuntimeError):
        return False


def start_server_blocking(
    review_dir: str = "",
    token: str | None = None,
    timeout: float = 30.0,
) -> tuple[McpLoopbackServer, int]:
    """Start the MCP server synchronously (for use from sync code).

    Returns (server, port). The caller must call stop() when done.
    Runs the asyncio event loop in a background thread.
    """
    import threading

    server = McpLoopbackServer(review_dir=review_dir, token=token)
    port_future: list[int] = []
    error_future: list[Exception | None] = [None]

    def _run() -> None:
        loop = asyncio.new_event_loop()
        server._blocking_loop = loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.start())
            port_future.append(server.port)

            _try_add_signal_handler(loop, signal.SIGTERM, _handle_sigterm, server, loop)

            loop.run_forever()
        except Exception as exc:
            error_future[0] = exc
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait for the port
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if error_future[0] is not None:
            server._clear_token_env()
            raise error_future[0]
        if port_future:
            return server, port_future[0]
        time.sleep(0.05)

    server._clear_token_env()
    raise TimeoutError("MCP server did not start within timeout")

    return server, server.port


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _async_main() -> None:
    """Async main: start server on 127.0.0.1:<ephemeral-port> and wait for signal."""
    review_dir = os.environ.get("TRINITY_REVIEW_DIR", "")
    token = os.environ.get("TRINITY_MCP_TOKEN")

    server = McpLoopbackServer(review_dir=review_dir, token=token)
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    _try_add_signal_handler(loop, signal.SIGTERM, _signal_handler)
    _try_add_signal_handler(loop, signal.SIGINT, _signal_handler)

    try:
        await _run_server_and_wait(server, shutdown_event)
    finally:
        await server.stop()
        # Clean up env
        os.environ.pop("TRINITY_MCP_TOKEN", None)


def main() -> None:
    """Synchronous entry point for direct invocation."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Standard MCP stdio dispatcher for the inert KAI mailbox adapter.

This file only supplies protocol plumbing.  A trusted runtime must inject a
``MailboxTools`` instance; the command-line entrypoint intentionally has no
credentials or authorizer and therefore cannot access the mailbox.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, TextIO

try:
    from .mailbox_tools import MailboxToolError, MailboxTools
except ImportError:  # direct ``python server.py`` invocation
    from mailbox_tools import MailboxToolError, MailboxTools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "kai-mailbox", "version": "0.1.0"}
TOOL_NAMES = set(MailboxTools.TOOLS)


def _catalog() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[4] / "docs" / "reference" / "external-assistant-tools.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        tools = value.get("tools") if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        tools = None
    if not isinstance(tools, list) or {item.get("name") for item in tools if isinstance(item, dict)} != TOOL_NAMES:
        raise RuntimeError("mailbox tool catalog unavailable or incomplete")
    return tools


TOOL_CATALOG = _catalog()


def _error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data is not None:
        result["error"]["data"] = data
    return result


class MCPServer:
    def __init__(self, tools: MailboxTools | None = None):
        self.tools = tools

    def handle(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return _error(None, -32600, "Invalid Request")
        req_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return _error(req_id, -32600, "Invalid Request")
        if method.startswith("notifications/"):
            return None
        params = request.get("params", {})
        if not isinstance(params, dict):
            return _error(req_id, -32602, "Invalid params")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            }}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_CATALOG}}
        if method != "tools/call":
            return _error(req_id, -32601, "Method not found")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in TOOL_NAMES or not isinstance(arguments, dict):
            return _error(req_id, -32602, "Invalid tool name or arguments")
        if self.tools is None:
            exc = MailboxToolError("identity_rejected", "trusted conversation authorizer required")
        else:
            try:
                result = self.tools.dispatch(name, arguments)
            except MailboxToolError as caught:
                exc = caught
            else:
                return {"jsonrpc": "2.0", "id": req_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}],
                    "structuredContent": result,
                }}
        structured = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, sort_keys=True)}],
            "structuredContent": structured,
            "isError": True,
        }}


def run_stdio(server: MCPServer, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    for line in stdin:
        try:
            request = json.loads(line)
        except (ValueError, TypeError):
            response = _error(None, -32700, "Parse error")
        else:
            response = server.handle(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    # No default MailboxTools construction: the CLI remains inert until a
    # trusted runtime explicitly injects an authenticated instance.
    return run_stdio(MCPServer())


if __name__ == "__main__":
    raise SystemExit(main())

"""Standard MCP stdio dispatcher for the inert KAI mailbox adapter.

This file only supplies protocol plumbing.  A trusted runtime must inject a
``MailboxTools`` instance; the command-line entrypoint intentionally has no
credentials or authorizer and therefore cannot access the mailbox.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, TextIO

try:
    from .mailbox_tools import MailboxToolError, MailboxTools
except ImportError:  # direct ``python server.py`` invocation
    from mailbox_tools import MailboxToolError, MailboxTools

PROTOCOL_VERSION = "2024-11-05"
EVENTS_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = (EVENTS_PROTOCOL_VERSION, PROTOCOL_VERSION)
SERVER_INFO = {"name": "kai-mailbox", "version": "0.1.0"}
TOOL_NAMES = set(MailboxTools.TOOLS)


def _catalog() -> list[dict[str, Any]]:
    paths = [Path(__file__).resolve().parents[4] / "docs" / "reference" / "external-assistant-tools.json",
             Path(__file__).with_name("external-assistant-tools.json")]
    tools = None
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            tools = value.get("tools") if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(tools, list):
            break
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
    def __init__(self, tools: MailboxTools | None = None, events: Any = None):
        self.tools = tools
        self.events = events

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
            requested = params.get("protocolVersion")
            if self.events is not None:
                if requested not in (None, EVENTS_PROTOCOL_VERSION):
                    return _error(req_id, -32602, "events require protocol 2026-07-28")
                selected_version = EVENTS_PROTOCOL_VERSION
            else:
                selected_version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            capabilities = {"tools": {"listChanged": False}}
            if self.events is not None:
                capabilities["events"] = {}
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": selected_version,
                "capabilities": capabilities,
                "serverInfo": SERVER_INFO,
            }}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "server/discover":
            capabilities = {"tools": {}}
            if self.events is not None:
                capabilities["events"] = {}
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "resultType": "complete",
                "supportedVersions": [EVENTS_PROTOCOL_VERSION] if self.events is not None else list(SUPPORTED_PROTOCOL_VERSIONS),
                "capabilities": capabilities,
            }}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_CATALOG}}
        if method in ("events/list", "events/subscribe", "events/unsubscribe"):
            if self.events is None:
                return _error(req_id, -32601, "Method not found")
            try:
                if method == "events/list" and hasattr(self.events, "definition"):
                    if params.get("cursor") not in (None, ""):
                        return {"jsonrpc": "2.0", "id": req_id, "result": {"events": [], "nextCursor": None}}
                    result = {"events": [self.events.definition()], "nextCursor": None}
                elif method == "events/subscribe" and hasattr(self.events, "subscribe"):
                    if params.get("name") != getattr(self.events, "definition")().get("name") or params.get("arguments", {}) != {}:
                        return _error(req_id, -32602, "Invalid event arguments")
                    delivery = params.get("delivery") if isinstance(params.get("delivery"), dict) else params
                    if not isinstance(delivery, dict) or delivery.get("mode") != "webhook":
                        return _error(req_id, -32602, "Invalid webhook delivery")
                    result = self.events.subscribe(delivery.get("url"), delivery.get("secret"), params.get("ttlMs", 86400000))
                elif method == "events/unsubscribe" and hasattr(self.events, "unsubscribe"):
                    if params.get("name") != getattr(self.events, "definition")().get("name"):
                        return _error(req_id, -32602, "Invalid unsubscribe request")
                    delivery = params.get("delivery")
                    if not isinstance(delivery, dict) or not isinstance(delivery.get("url"), str):
                        return _error(req_id, -32602, "Invalid unsubscribe request")
                    result = self.events.unsubscribe(delivery.get("url"))
                elif hasattr(self.events, "handle"):
                    result = self.events.handle(method, params)
                else:
                    handler = getattr(self.events, method.split("/", 1)[1])
                    result = handler(params)
            except MailboxToolError as exc:
                return _error(req_id, -32000, exc.message, {"code": exc.code})
            except (AttributeError, TypeError, ValueError) as exc:
                return _error(req_id, -32602, "Invalid event arguments")
            except Exception:
                return _error(req_id, -32000, "Event operation rejected")
            if isinstance(result, dict) and result.get("jsonrpc") == "2.0":
                return dict(result, id=req_id)
            return {"jsonrpc": "2.0", "id": req_id, "result": result if result is not None else {}}
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
    stop = threading.Event()
    pump = getattr(server.events, "pump_once", None) if server.events is not None else None

    def deliver() -> None:
        while not stop.wait(1.0):
            try:
                if callable(pump):
                    pump()
            except Exception:
                # Delivery state is durable and the next tick revalidates the
                # binding; MCP request handling must remain available.
                continue

    worker = threading.Thread(target=deliver, name="kai-event-pump", daemon=True)
    if callable(pump):
        worker.start()
    try:
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
    finally:
        stop.set()
        if worker.is_alive():
            worker.join(timeout=2)
    return 0


def main() -> int:
    # No default MailboxTools construction: the CLI remains inert until a
    # trusted runtime explicitly injects an authenticated instance.
    return run_stdio(MCPServer())


if __name__ == "__main__":
    raise SystemExit(main())

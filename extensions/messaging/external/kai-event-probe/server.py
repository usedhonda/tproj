#!/usr/bin/env python3
"""Connection-only MCP Events probe for the KAI Dots conversation.

This process deliberately has no mailbox adapter. It implements only the MCP
2.0 discovery/events surface and an operator-triggered synthetic event.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROTOCOL_VERSION = "2026-07-28"
EVENT_NAME = "kai.connection.probe"
DEFAULT_TTL_MS = 24 * 60 * 60 * 1000
MAX_BODY = 256 * 1024


def state_path() -> Path:
    path = Path(os.environ.get("KAI_EVENT_PROBE_STATE", "~/.local/share/tproj/kai-event-probe/subscriptions.json")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    return path


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"subscriptions": {}}
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) and isinstance(value.get("subscriptions"), dict) else {"subscriptions": {}}
    except (OSError, ValueError):
        return {"subscriptions": {}}


def save_state(state: dict) -> None:
    path = state_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def rpc_error(req_id: object, code: int, message: str, reason: str | None = None) -> dict:
    error = {"code": code, "message": message}
    if reason:
        error["data"] = {"reason": reason}
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def public_https(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        return False
    if not addresses:
        return False
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified:
            return False
    return True


def secret_bytes(value: object) -> bytes | None:
    if not isinstance(value, str) or not value.startswith("whsec_"):
        return None
    try:
        decoded = base64.b64decode(value[6:], validate=True)
    except (ValueError, TypeError):
        return None
    return decoded if 24 <= len(decoded) <= 64 else None


def sign(secret: bytes, webhook_id: str, timestamp: int, body: bytes) -> str:
    message = f"{webhook_id}.{timestamp}.".encode() + body
    digest = base64.b64encode(hmac.new(secret, message, hashlib.sha256).digest()).decode()
    return f"v1,{digest}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """MCP Events requires callback requests to fail closed on redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirect)


def event_definition() -> dict:
    return {
        "name": EVENT_NAME,
        "description": "Synthetic connection-only probe event; it never reads mailbox data.",
        "delivery": ["webhook"],
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "payloadSchema": {
            "type": "object",
            "properties": {"probe": {"type": "string"}, "sentAt": {"type": "string"}},
            "required": ["probe", "sentAt"],
            "additionalProperties": False,
        },
    }


def subscription_identity(arguments: object, delivery: dict) -> str:
    material = canonical({"owner": "connection-only", "url": delivery["url"], "name": EVENT_NAME, "arguments": arguments})
    return "sub_" + hashlib.sha256(material.encode()).hexdigest()[:32]


class Probe:
    def __init__(self) -> None:
        self.state = load_state()

    def handle(self, req: dict) -> dict | None:
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "server/discover":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resultType": "complete", "supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}, "events": {}}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": "connection_status", "description": "Report connection-only probe state; no mailbox data is accessed.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}}
        if method == "tools/call":
            if params.get("name") != "connection_status":
                return rpc_error(req_id, -32602, "Unknown tool")
            content = {"mode": "connection-only", "mailboxConnected": False, "eventName": EVENT_NAME, "subscriptionCount": len(self.state["subscriptions"])}
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(content, sort_keys=True)}], "structuredContent": content}}
        if method == "events/list":
            if params.get("cursor") not in (None, ""):
                return {"jsonrpc": "2.0", "id": req_id, "result": {"events": [], "nextCursor": None}}
            return {"jsonrpc": "2.0", "id": req_id, "result": {"events": [event_definition()], "nextCursor": None}}
        if method == "events/subscribe":
            return self.subscribe(req_id, params)
        if method == "events/unsubscribe":
            return self.unsubscribe(req_id, params)
        return rpc_error(req_id, -32601, "Method not found")

    def subscribe(self, req_id: object, params: dict) -> dict:
        if params.get("name") != EVENT_NAME or params.get("arguments", {}) != {}:
            return rpc_error(req_id, -32602, "Invalid event arguments")
        delivery = params.get("delivery")
        if not isinstance(delivery, dict) or delivery.get("mode") != "webhook" or not public_https(delivery.get("url", "")):
            return rpc_error(req_id, -32015, "Callback endpoint rejected", "invalid_callback_url")
        secret_value = delivery.get("secret")
        raw_secret = secret_bytes(secret_value)
        if raw_secret is None:
            return rpc_error(req_id, -32602, "Invalid webhook secret")
        sub_id = subscription_identity({}, delivery)
        existing = self.state["subscriptions"].get(sub_id)
        refresh = params.get("ttlMs", DEFAULT_TTL_MS)
        if refresh is None:
            expiry = None
        else:
            try:
                expiry = time.time() + max(60_000, min(int(refresh), 30 * 24 * 60 * 60 * 1000)) / 1000
            except (TypeError, ValueError):
                return rpc_error(req_id, -32602, "Invalid ttlMs")
        # Verification is intentionally performed before persistence. Redirects are refused.
        challenge = secrets.token_urlsafe(32)
        verification = {"type": "verification", "challenge": challenge}
        result = self.post(delivery["url"], sub_id, raw_secret, verification, "msg_verification_" + uuid.uuid4().hex)
        echoed = result[1].get("challenge")
        if not result[0] or not isinstance(echoed, str) or not hmac.compare_digest(echoed, challenge):
            return rpc_error(req_id, -32015, "Callback verification failed", result[2])
        self.state["subscriptions"][sub_id] = {"id": sub_id, "name": EVENT_NAME, "arguments": {}, "url": delivery["url"], "secret": secret_value, "expiresAt": expiry}
        save_state(self.state)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"id": sub_id, "refreshBefore": datetime.fromtimestamp(expiry, timezone.utc).isoformat().replace("+00:00", "Z") if expiry else None, "cursor": None, "truncated": False}}

    def unsubscribe(self, req_id: object, params: dict) -> dict:
        delivery = params.get("delivery") or {}
        if params.get("name") != EVENT_NAME or not isinstance(delivery, dict):
            return rpc_error(req_id, -32602, "Invalid unsubscribe request")
        sub_id = subscription_identity({}, delivery)
        self.state["subscriptions"].pop(sub_id, None)
        save_state(self.state)
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    def post(self, url: str, sub_id: str, raw_secret: bytes, payload: dict, webhook_id: str) -> tuple[bool, dict, str]:
        if not public_https(url):
            return False, {}, "invalid_callback_url"
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > MAX_BODY:
            return False, {}, "payload_too_large"
        timestamp = int(time.time())
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "webhook-id": webhook_id, "webhook-timestamp": str(timestamp), "webhook-signature": sign(raw_secret, webhook_id, timestamp, body), "X-MCP-Subscription-Id": sub_id})
        try:
            with NO_REDIRECT_OPENER.open(request, timeout=10) as response:
                if not 200 <= response.status < 300:
                    return False, {}, f"http_{response.status}"
                try:
                    value = json.loads(response.read())
                except (ValueError, TypeError):
                    value = {}
                return True, value if isinstance(value, dict) else {}, "ok"
        except (urllib.error.URLError, TimeoutError, OSError):
            return False, {}, "request_failed"

    def send_one(self, subscription_id: str, probe: str) -> tuple[bool, str]:
        sub = self.state["subscriptions"].get(subscription_id)
        if not sub:
            return False, "unknown_subscription"
        secret_value = secret_bytes(sub.get("secret"))
        if not secret_value or not public_https(sub.get("url", "")):
            return False, "invalid_subscription"
        payload = {"eventId": "evt_" + uuid.uuid4().hex, "name": EVENT_NAME, "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "data": {"probe": probe, "sentAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}, "cursor": None}
        ok, _, reason = self.post(sub["url"], subscription_id, secret_value, payload, payload["eventId"])
        return ok, reason


def run_stdio(probe: Probe) -> int:
    for line in sys.stdin:
        try:
            req = json.loads(line)
            response = probe.handle(req)
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        except (ValueError, TypeError):
            print(json.dumps(rpc_error(None, -32700, "Parse error"), separators=(",", ":")), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Connection-only KAI MCP Events probe")
    parser.add_argument("--send-event", metavar="SUBSCRIPTION_ID", help="send one synthetic probe event to an existing subscription")
    parser.add_argument("--probe", default="operator-one-event", help="synthetic probe label (no mailbox data)")
    args = parser.parse_args()
    probe = Probe()
    if args.send_event:
        ok, reason = probe.send_one(args.send_event, args.probe)
        print(json.dumps({"sent": ok, "reason": reason, "subscription": args.send_event}, sort_keys=True))
        return 0 if ok else 1
    return run_stdio(probe)


if __name__ == "__main__":
    raise SystemExit(main())

"""Authenticated, durable MCP mailbox events; no default authorizer."""
from __future__ import annotations

import base64
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import hmac
import importlib.util
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import time
from typing import Any

PROBE = Path(__file__).parents[1] / "kai-event-probe" / "server.py"
SPEC = importlib.util.spec_from_file_location("kai_probe_secure", PROBE)
_secure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_secure)
EVENT_NAME = "kai.mailbox.message"
MAX_ATTEMPTS = 3
MAX_BATCH = 100
DEFAULT_TTL_MS = 86400000
CANCELLED_STATES = frozenset(("cancelled", "canceled", "expired", "terminal", "rejected", "stale_session"))
POST_ERROR_CLASSES = frozenset((
    "http_error", "timeout", "tls", "network", "target_unavailable",
    "oversized_request", "oversized_response", "invalid_response",
))


def _payload_bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _payload_hash(payload):
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class TrustedBinding:
    binding_id: str
    incarnation: str
    reader: Any


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class KAIEventDelivery:
    def __init__(self, authorizer: Any, state_path: str | Path):
        self.authorizer = authorizer
        self.path = Path(state_path).expanduser()
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise RuntimeError("unsafe state path")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

    def _binding(self):
        authorize = getattr(self.authorizer, "authorize", None)
        if not callable(authorize):
            raise RuntimeError("trusted authorizer unavailable")
        value = authorize()
        if not isinstance(value, TrustedBinding) or not value.binding_id or not value.incarnation or not callable(value.reader):
            raise RuntimeError("authorizer rejected")
        return value

    @contextlib.contextmanager
    def _lock(self):
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self):
        if self.path.is_symlink():
            raise RuntimeError("unsafe state path")
        if not self.path.exists():
            return {"subscriptions": {}, "outbox": {}, "cursor": {}}
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict) or any(not isinstance(value.get(k), dict) for k in ("subscriptions", "outbox", "cursor")):
            raise RuntimeError("invalid state schema")
        return value

    def _save(self, value):
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def definition(self):
        return {
            "name": EVENT_NAME,
            "description": "A durable mailbox message is available; fetch and acknowledge with the authorized MSG tools.",
            "delivery": ["webhook"],
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "payloadSchema": {
                "type": "object",
                "properties": {"messageId": {"type": "string"}},
                "required": ["messageId"],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _sid(url, binding):
        material = json.dumps([EVENT_NAME, url, binding.binding_id], separators=(",", ":"))
        return "sub_" + hashlib.sha256(material.encode()).hexdigest()[:32]

    @staticmethod
    def _owned(sub, binding):
        # Enrollment generation is the durable owner. Endpoint incarnation is
        # refreshed after a verified service restart, never used to bind a
        # second callback or principal.
        return sub.get("binding") == binding.binding_id

    @classmethod
    def _active(cls, sub, binding, now):
        expiry = sub.get("expiresAt")
        return cls._owned(sub, binding) and (expiry is None or now < expiry)

    def subscribe(self, url, secret, ttl_ms=DEFAULT_TTL_MS):
        binding = self._binding()
        raw = _secure.secret_bytes(secret)
        if not isinstance(url, str) or raw is None or not _secure.public_https(url):
            raise RuntimeError("invalid callback or secret")
        if ttl_ms is not None and (isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or not 60000 <= ttl_ms <= 30 * DEFAULT_TTL_MS):
            raise RuntimeError("invalid subscription expiry")
        sid = self._sid(url, binding)
        challenge = secrets.token_urlsafe(32)
        with self._lock():
            state = self._load()
            existing = state["subscriptions"].get(sid)
            if existing and not self._owned(existing, binding):
                raise RuntimeError("subscription ownership mismatch")
            for other_sid, other in state["subscriptions"].items():
                if other_sid != sid and self._active(other, binding, time.time()):
                    raise RuntimeError("subscription already bound to another callback")
            result = self._post(url, sid, raw, {"type": "verification", "challenge": challenge}, sid)
            ok, echoed = result[0], result[1]
            if not ok or not isinstance(echoed.get("challenge"), str) or not hmac.compare_digest(echoed["challenge"], challenge):
                raise RuntimeError("callback verification failed")
            current = self._binding()
            if current.binding_id != binding.binding_id:
                raise RuntimeError("binding changed during verification")
            expiry = None if ttl_ms is None else time.time() + ttl_ms / 1000
            state["subscriptions"][sid] = {
                "id": sid, "url": url, "secret": secret, "binding": binding.binding_id,
                "incarnation": binding.incarnation, "expiresAt": expiry,
            }
            self._save(state)
        return {"id": sid, "refreshBefore": _iso(expiry) if expiry is not None else None, "cursor": None, "truncated": False}

    def unsubscribe(self, sid):
        binding = self._binding()
        if not isinstance(sid, str):
            raise RuntimeError("invalid subscription")
        if sid.startswith("https://"):
            sid = self._sid(sid, binding)
        with self._lock():
            state = self._load()
            sub = state["subscriptions"].get(sid)
            if sub and not self._owned(sub, binding):
                raise RuntimeError("subscription ownership mismatch")
            state["subscriptions"].pop(sid, None)
            for item in state["outbox"].values():
                if item["subscription"] == sid and item.get("status") != "sent":
                    item["status"] = "revoked"
            self._save(state)

    def pump_once(self, limit=MAX_BATCH):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BATCH:
            raise RuntimeError("invalid batch limit")
        binding = self._binding()
        queued = 0
        with self._lock():
            state = self._load()
            now = time.time()
            for sid, sub in state["subscriptions"].items():
                if queued >= limit or not self._active(sub, binding, now):
                    continue
                if sub.get("incarnation") != binding.incarnation:
                    sub["incarnation"] = binding.incarnation
                    for item in state["outbox"].values():
                        if item["subscription"] == sid and item.get("status") not in ("sent", "terminal", "revoked"):
                            item["status"] = "revoked"
                    self._save(state)
                cursor = state["cursor"].get(sid, 0)
                page = binding.reader(cursor)
                if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
                    raise RuntimeError("invalid mailbox page")
                next_cursor = page.get("next_cursor")
                messages = page["messages"]
                if isinstance(next_cursor, bool) or not isinstance(next_cursor, int) or next_cursor < cursor or len(messages) > limit - queued:
                    raise RuntimeError("invalid mailbox cursor or batch")
                for message in messages:
                    mid = message.get("message_id") if isinstance(message, dict) else None
                    if not isinstance(mid, str) or not mid:
                        raise RuntimeError("invalid mailbox message")
                    if message.get("state") in CANCELLED_STATES:
                        continue
                    eid = "evt_" + hashlib.sha256((sid + "\0" + mid).encode()).hexdigest()[:32]
                    if eid not in state["outbox"]:
                        payload = {"eventId": eid, "name": EVENT_NAME, "timestamp": _iso(now), "data": {"messageId": mid}, "cursor": None}
                        state["outbox"][eid] = {
                            "subscription": sid,
                            "payload": payload,
                            "payload_hash": _payload_hash(payload),
                            "attempts": 0, "nextAt": now, "status": "pending",
                        }
                        queued += 1
                state["cursor"][sid] = next_cursor
            # Durable exact payload and cursor precede every external side effect.
            self._save(state)
            posts = 0
            for eid, item in state["outbox"].items():
                if posts >= limit or item.get("status") in ("sent", "terminal", "revoked") or item.get("nextAt", 0) > time.time():
                    continue
                current = self._binding()
                sub = state["subscriptions"].get(item["subscription"])
                if not sub or not self._active(sub, current, time.time()):
                    item["status"] = "revoked"
                    self._save(state)
                    continue
                raw = _secure.secret_bytes(sub["secret"])
                if raw is None:
                    raise RuntimeError("invalid persisted secret")
                if item["attempts"] >= MAX_ATTEMPTS:
                    item["status"] = "terminal"
                    self._save(state)
                    continue
                item["attempts"] += 1
                item["status"] = "unknown"
                item["nextAt"] = time.time() + min(300, 2 ** item["attempts"])
                # Clear diagnostics before the side effect so a crash cannot
                # leave a prior attempt looking like the current one.
                item["last_http_status"] = None
                item["last_error_class"] = None
                self._save(state)
                result = self._post(sub["url"], eid, raw, item["payload"], item["subscription"])
                ok = result[0]
                status = result[2] if len(result) > 2 and isinstance(result[2], int) and not isinstance(result[2], bool) else None
                error_class = result[3] if len(result) > 3 and result[3] in POST_ERROR_CLASSES else None
                item["last_http_status"] = status
                item["last_error_class"] = error_class
                posts += 1
                item["status"] = "sent" if ok else ("terminal" if status in (410, 413) or item["attempts"] >= MAX_ATTEMPTS else "unknown")
                self._save(state)
        return queued

    def retry_once(self, message_id, *, actor_endpoint):
        """Manually retry one stored terminal event exactly once.

        The caller must have already authenticated the original message and
        current KAI recipient.  This method only enforces the enrolled event
        binding, callback subscription, and durable event record invariants.
        """
        if not isinstance(message_id, str) or not message_id:
            raise RuntimeError("invalid message id")
        if not isinstance(actor_endpoint, str) or not actor_endpoint:
            raise RuntimeError("invalid actor endpoint")
        with self._lock():
            binding = self._binding()
            state = self._load()
            matches = []
            for eid, item in state["outbox"].items():
                payload = item.get("payload") if isinstance(item, dict) else None
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict) and data.get("messageId") == message_id:
                    matches.append((eid, item))
            if len(matches) != 1:
                raise RuntimeError("event message id is ambiguous" if len(matches) > 1 else "event not found")
            eid, item = matches[0]
            if item.get("status") != "terminal":
                raise RuntimeError("event is not terminal")
            sid = item.get("subscription")
            sub = state["subscriptions"].get(sid)
            now = time.time()
            if not isinstance(sub, dict) or not self._owned(sub, binding):
                raise RuntimeError("subscription binding mismatch")
            if sub.get("incarnation") != binding.incarnation:
                raise RuntimeError("subscription incarnation mismatch")
            if not self._active(sub, binding, now):
                raise RuntimeError("subscription expired")
            if sub.get("id") != sid or not isinstance(sub.get("url"), str) or not _secure.public_https(sub["url"]):
                raise RuntimeError("invalid subscription")
            if self._sid(sub["url"], binding) != sid:
                raise RuntimeError("subscription id mismatch")
            claim = item.get("manual_retry")
            if isinstance(claim, dict):
                return self._retry_result(message_id, eid, item, claim)
            if item.get("last_http_status") in (410, 413):
                raise RuntimeError("event delivery is not retryable")
            payload = item.get("payload")
            data = payload.get("data") if isinstance(payload, dict) else None
            if (not isinstance(payload, dict) or set(payload) != {"eventId", "name", "timestamp", "data", "cursor"}
                    or payload.get("eventId") != eid or payload.get("name") != EVENT_NAME
                    or not isinstance(payload.get("timestamp"), str) or not isinstance(data, dict)
                    or set(data) != {"messageId"} or data.get("messageId") != message_id
                    or payload.get("cursor") is not None):
                raise RuntimeError("invalid stored event payload")
            expected_eid = "evt_" + hashlib.sha256((sid + "\0" + message_id).encode()).hexdigest()[:32]
            if eid != expected_eid:
                raise RuntimeError("event id mismatch")
            digest = _payload_hash(payload)
            stored_hash = item.get("payload_hash")
            if stored_hash is not None and (not isinstance(stored_hash, str) or not hmac.compare_digest(stored_hash, digest)):
                raise RuntimeError("payload hash mismatch")
            raw = _secure.secret_bytes(sub.get("secret"))
            if raw is None:
                raise RuntimeError("invalid persisted secret")
            # Claim and count are durable before the external side effect.  A
            # historical record without payload_hash is pinned only in claim.
            claim = {"status": "unknown", "attempts": 1, "payload_hash": digest,
                     "http_status": None, "error_class": None, "actor_endpoint": actor_endpoint}
            item["manual_retry"] = claim
            item["attempts"] = item.get("attempts", 0) + 1
            item["last_http_status"] = None
            item["last_error_class"] = None
            self._save(state)
            if not hmac.compare_digest(claim["payload_hash"], _payload_hash(item["payload"])):
                return self._retry_result(message_id, eid, item, claim)
            result = self._post(sub["url"], eid, raw, item["payload"], sid)
            ok = result[0]
            status = result[2] if len(result) > 2 and isinstance(result[2], int) and not isinstance(result[2], bool) else None
            error_class = result[3] if len(result) > 3 and result[3] in POST_ERROR_CLASSES else None
            claim["status"] = "sent" if ok else "failed"
            claim["http_status"] = status
            claim["error_class"] = error_class
            item["last_http_status"] = status
            item["last_error_class"] = error_class
            # Keep the outbox terminal; manual result is separate from pump state.
            self._save(state)
            return self._retry_result(message_id, eid, item, claim)

    @staticmethod
    def _retry_result(message_id, eid, item, claim):
        status = claim.get("status") if claim.get("status") in ("unknown", "sent", "failed") else "unknown"
        code = claim.get("http_status")
        if isinstance(code, bool) or not isinstance(code, int):
            code = None
        error = claim.get("error_class") if claim.get("error_class") in POST_ERROR_CLASSES else None
        attempts = claim.get("attempts") if isinstance(claim.get("attempts"), int) and not isinstance(claim.get("attempts"), bool) else None
        total = item.get("attempts") if isinstance(item.get("attempts"), int) and not isinstance(item.get("attempts"), bool) else None
        return {"message_id": message_id, "event_id": eid, "status": status,
                "attempts": attempts, "total_attempts": total,
                "status_code": code, "error_class": error}

    def _post(self, url, webhook_id, secret, payload, subscription_id=None):
        target = _secure.validated_address(url)
        if target is None:
            return False, {}, None, "target_unavailable"
        parsed, ip = target
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > _secure.MAX_BODY:
            return False, {}, None, "oversized_request"
        stamp = int(time.time())
        headers = {
            "Content-Type": "application/json", "Host": parsed.netloc,
            "webhook-id": webhook_id, "webhook-timestamp": str(stamp),
            "webhook-signature": _secure.sign(secret, webhook_id, stamp, body),
            "X-MCP-Subscription-Id": subscription_id or webhook_id,
        }
        connection = _secure.PinnedHTTPSConnection(parsed.hostname, ip, parsed.port or 443, ssl.create_default_context(), 10)
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            status = response.status if isinstance(response.status, int) and not isinstance(response.status, bool) else None
            try:
                raw = response.read(_secure.MAX_BODY + 1)
            except TimeoutError:
                return False, {}, status, "timeout"
            except ssl.SSLError:
                return False, {}, status, "tls"
            except http.client.HTTPException:
                return False, {}, status, "network"
            except OSError:
                return False, {}, status, "network"
            if status is None:
                return False, {}, None, "network"
            if len(raw) > _secure.MAX_BODY:
                return False, {}, status, "oversized_response"
            if not 200 <= status < 300:
                return False, {}, status, "http_error"
            try:
                value = json.loads(raw) if raw else {}
            except ValueError:
                return True, {}, status, "invalid_response"
            if not isinstance(value, dict):
                return True, {}, status, "invalid_response"
            return True, value, status, None
        except TimeoutError:
            return False, {}, None, "timeout"
        except ssl.SSLError:
            return False, {}, None, "tls"
        except http.client.HTTPException:
            return False, {}, None, "network"
        except OSError:
            return False, {}, None, "network"
        finally:
            connection.close()

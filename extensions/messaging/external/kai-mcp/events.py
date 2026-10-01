"""Fail-closed, durable mailbox event delivery for an authenticated KAI service."""
from __future__ import annotations
import base64, hashlib, hmac, importlib.util, json, os, secrets, time, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROBE = Path(__file__).parents[1] / "kai-event-probe" / "server.py"
SPEC = importlib.util.spec_from_file_location("kai_probe_secure", PROBE)
_secure = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(_secure)
EVENT_NAME = "kai.mailbox.message"

@dataclass(frozen=True)
class TrustedBinding:
    binding_id: str
    incarnation: str
    reader: Any

def _safe_state(path: Path) -> Path:
    if path.is_symlink(): raise RuntimeError("unsafe state path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink(): raise RuntimeError("unsafe state directory")
    os.chmod(path.parent, 0o700); return path

class KAIEventDelivery:
    def __init__(self, authorizer: Any, state_path: str | Path):
        self.authorizer = authorizer; self.path = _safe_state(Path(state_path).expanduser())

    def _binding(self) -> TrustedBinding:
        if self.authorizer is None or not callable(getattr(self.authorizer, "authorize", None)):
            raise RuntimeError("trusted authorizer unavailable")
        value = self.authorizer.authorize()
        if not isinstance(value, TrustedBinding) or not value.binding_id or not value.incarnation or not callable(value.reader):
            raise RuntimeError("authorizer rejected")
        return value

    def _load(self):
        if not self.path.exists(): return {"subscriptions": {}, "outbox": {}, "cursor": {}}
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict): raise RuntimeError("invalid state")
        return value

    def _save(self, value):
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"))); os.chmod(tmp, 0o600); tmp.replace(self.path); os.chmod(self.path, 0o600)

    def definition(self):
        return {"name": EVENT_NAME, "delivery": ["webhook"], "inputSchema": {"type": "object", "additionalProperties": False}, "payloadSchema": {"type": "object", "properties": {"eventId": {"type": "string"}, "messageId": {"type": "string"}, "binding": {"type": "string"}}, "required": ["eventId", "messageId", "binding"], "additionalProperties": False}}

    def subscribe(self, url: str, secret: str, ttl_ms: int | None = None) -> dict:
        binding = self._binding()
        raw = _secure.secret_bytes(secret)
        if raw is None or not _secure.public_https(url): raise RuntimeError("invalid callback or secret")
        challenge = secrets.token_urlsafe(32); sid = "sub_" + hashlib.sha256((url + binding.binding_id).encode()).hexdigest()[:32]
        ok, echoed = self._post(url, sid, raw, {"type": "verification", "challenge": challenge})
        if not ok or echoed.get("challenge") != challenge: raise RuntimeError("callback verification failed")
        state = self._load(); state.setdefault("subscriptions", {})[sid] = {"id": sid, "url": url, "secret": secret, "binding": binding.binding_id, "incarnation": binding.incarnation, "expiresAt": time.time() + (ttl_ms or 86400000) / 1000}; self._save(state)
        return {"id": sid, "refreshBefore": state["subscriptions"][sid]["expiresAt"]}

    def unsubscribe(self, sid: str) -> None:
        self._binding(); state = self._load(); state.setdefault("subscriptions", {}).pop(sid, None); self._save(state)

    def pump_once(self, limit: int = 100) -> int:
        binding = self._binding(); state = self._load(); now = time.time(); queued = 0
        for sid, sub in list(state.get("subscriptions", {}).items()):
            if sub.get("binding") != binding.binding_id or sub.get("incarnation") != binding.incarnation or now >= sub.get("expiresAt", 0): continue
            for message in binding.reader(state.get("cursor", {}).get(sid)):
                mid = message.get("id") if isinstance(message, dict) else None
                if not isinstance(mid, str) or not mid: continue
                eid = "evt_" + hashlib.sha256((sid + "\0" + mid).encode()).hexdigest()[:32]
                if eid in state.setdefault("outbox", {}): continue
                state["outbox"][eid] = {"subscription": sid, "payload": {"eventId": eid, "messageId": mid, "binding": binding.binding_id}, "attempts": 0, "nextAt": now}
                state.setdefault("cursor", {})[sid] = mid; queued += 1
                if queued >= limit: break
        for eid, item in state.get("outbox", {}).items():
            if item.get("nextAt", 0) > now or item.get("status") == "sent": continue
            sub = state["subscriptions"].get(item["subscription"]); raw = _secure.secret_bytes(sub.get("secret", "")) if sub else None
            if not sub or raw is None: item["status"] = "revoked"; continue
            ok, _ = self._post(sub["url"], eid, raw, item["payload"]); item["attempts"] += 1; item["status"] = "sent" if ok else "unknown"; item["nextAt"] = now + min(300, 2 ** item["attempts"])
        self._save(state); return queued

    def _post(self, url, sid, secret, payload):
        # Verification and delivery share the probe's validated HTTPS boundary.
        target = _secure.validated_address(url)
        if target is None: return False, {}
        parsed, ip = target; body = json.dumps(payload, separators=(",", ":")).encode(); stamp = str(int(time.time())); headers = {"Content-Type": "application/json", "Host": parsed.netloc, "webhook-id": sid, "webhook-timestamp": stamp, "webhook-signature": _secure.sign(secret, sid, int(stamp), body)}
        try:
            conn = _secure.PinnedHTTPSConnection(parsed.hostname, ip, parsed.port or 443, __import__("ssl").create_default_context(), 10); conn.request("POST", parsed.path or "/", body, headers); response = conn.getresponse(); data = response.read(); return (200 <= response.status < 300), json.loads(data) if data else {}
        except Exception: return False, {}

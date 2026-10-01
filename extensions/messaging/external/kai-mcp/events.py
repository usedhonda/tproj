"""Fail-closed, durable mailbox event delivery for an authenticated KAI service."""
from __future__ import annotations
import base64, hashlib, hmac, importlib.util, json, os, secrets, time, urllib.request
import fcntl, tempfile, ssl
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
        for key in ("subscriptions", "outbox", "cursor"):
            if not isinstance(value.get(key), dict): raise RuntimeError("invalid state schema")
        return value

    def _save(self, value):
        lock = self.path.with_suffix(".lock"); fd=os.open(lock, os.O_CREAT|os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX); fd2,tmp=tempfile.mkstemp(prefix=self.path.name+".",dir=self.path.parent); os.write(fd2,json.dumps(value,sort_keys=True,separators=(",",":")).encode()); os.fsync(fd2); os.close(fd2); os.chmod(tmp,0o600); os.replace(tmp,self.path); os.chmod(self.path,0o600)
        finally: fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

    def definition(self):
        return {"name": EVENT_NAME, "delivery": ["webhook"], "inputSchema": {"type": "object", "additionalProperties": False}, "payloadSchema": {"type": "object", "properties": {"eventId": {"type": "string"}, "messageId": {"type": "string"}, "binding": {"type": "string"}}, "required": ["eventId", "messageId", "binding"], "additionalProperties": False}}

    def subscribe(self, url: str, secret: str, ttl_ms: int | None = None) -> dict:
        binding = self._binding()
        raw = _secure.secret_bytes(secret)
        if raw is None or not _secure.public_https(url): raise RuntimeError("invalid callback or secret")
        challenge = secrets.token_urlsafe(32); sid = "sub_" + hashlib.sha256((url + binding.binding_id).encode()).hexdigest()[:32]
        ok, echoed = self._post(url, sid, raw, {"type": "verification", "challenge": challenge})
        if not ok or echoed.get("challenge") != challenge: raise RuntimeError("callback verification failed")
        state = self._load(); expiry=time.time() + (ttl_ms or 86400000) / 1000; state.setdefault("subscriptions", {})[sid] = {"id": sid, "url": url, "secret": secret, "binding": binding.binding_id, "incarnation": binding.incarnation, "expiresAt": expiry}; self._save(state)
        return {"id": sid, "refreshBefore": expiry}

    def unsubscribe(self, sid: str) -> None:
        binding=self._binding(); state = self._load(); sub=state.setdefault("subscriptions", {}).get(sid)
        if sub and (sub.get("binding") != binding.binding_id or sub.get("incarnation") != binding.incarnation): raise RuntimeError("subscription ownership mismatch")
        state["subscriptions"].pop(sid, None); self._save(state)

    def pump_once(self, limit: int = 100) -> int:
        binding = self._binding(); state = self._load(); now = time.time(); queued = 0
        for sid, sub in list(state.get("subscriptions", {}).items()):
            if sub.get("binding") != binding.binding_id or sub.get("incarnation") != binding.incarnation or now >= sub.get("expiresAt", 0): continue
            result=binding.reader(state.get("cursor", {}).get(sid)); messages=result.get("messages",[]) if isinstance(result,dict) else result
            for message in messages:
                mid = message.get("id") if isinstance(message, dict) else None
                if not isinstance(mid, str) or not mid: continue
                eid = "evt_" + hashlib.sha256((sid + "\0" + mid).encode()).hexdigest()[:32]
                if eid in state.setdefault("outbox", {}): continue
                state["outbox"][eid] = {"subscription": sid, "payload": {"eventId": eid, "name": EVENT_NAME, "timestamp": time.time(), "data": {"messageId": mid}, "cursor": None}, "attempts": 0, "nextAt": now}
                state.setdefault("cursor", {})[sid] = message.get("cursor",mid) if isinstance(message,dict) else mid; queued += 1
                if queued >= limit: break
        for eid, item in state.get("outbox", {}).items():
            if item.get("nextAt", 0) > now or item.get("status") in ("sent","terminal"): continue
            sub = state["subscriptions"].get(item["subscription"]); raw = _secure.secret_bytes(sub.get("secret", "")) if sub else None
            if not sub or raw is None or sub.get("binding") != binding.binding_id or sub.get("incarnation") != binding.incarnation or now >= sub.get("expiresAt",0): item["status"] = "revoked"; continue
            if item.get("attempts",0) >= 3: item["status"] = "terminal"; continue
            ok, _ = self._post(sub["url"], eid, raw, item["payload"]); item["attempts"] += 1; item["status"] = "sent" if ok else ("terminal" if item["attempts"]>=3 else "unknown"); item["nextAt"] = now + min(300, 2 ** item["attempts"])
        self._save(state); return queued

    def _post(self, url, sid, secret, payload):
        # Verification and delivery share the probe's validated HTTPS boundary.
        target = _secure.validated_address(url)
        if target is None: return False, {}
        parsed, ip = target; body = json.dumps(payload, separators=(",", ":")).encode(); stamp = str(int(time.time())); headers = {"Content-Type": "application/json", "Host": parsed.netloc, "webhook-id": sid, "webhook-timestamp": stamp, "webhook-signature": _secure.sign(secret, sid, int(stamp), body)}
        try:
            conn = _secure.PinnedHTTPSConnection(parsed.hostname, ip, parsed.port or 443, ssl.create_default_context(), 10); path=parsed.path or "/"; path += ("?"+parsed.query) if parsed.query else ""; headers["X-MCP-Subscription-Id"]=sid; conn.request("POST", path, body, headers); response = conn.getresponse(); data = response.read(256*1024+1); conn.close(); return (200 <= response.status < 300), json.loads(data) if data and len(data)<=256*1024 else {}
        except Exception: return False, {}

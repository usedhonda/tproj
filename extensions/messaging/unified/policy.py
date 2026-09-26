"""Pure, fail-closed policy checks for unified message submission."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

try:
    from .protocol import HubError
except ImportError:
    from protocol import HubError

TTL = 600
RECOVERY_TTL = 86400


def _normal(body: str) -> str:
    return " ".join(body.split())


def _family(address: str) -> str:
    role = address.rsplit(".", 1)[-1].lower()
    if role in ("cc", "claude") or role.startswith("claude-p"):
        return "cc"
    if role in ("cdx", "codex") or role.startswith("codex-p"):
        return "cdx"
    return ""


def _recovery_fingerprint(sender: str, target: str, body: str) -> str:
    normalized = _normal(body)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}T[^ ]+", "TIMESTAMP", normalized)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "DATE", normalized)
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "TIME", normalized)
    normalized = re.sub(r"(?i)pid[=: ]+\d+", "pid=PID", normalized)
    normalized = re.sub(r"(?i)commit[=: ]+[0-9a-f]{7,40}", "commit=HASH", normalized)
    normalized = re.sub(r"https?://[^ ]+", "URL", normalized)
    return hashlib.sha1(f"{sender}|{target}|{normalized}".encode()).hexdigest()


def _blocked_body(body: str) -> str | None:
    if re.match(r"^[ \t]*\[from:[^\]]+\]", body):
        return "relay_like"
    if re.search(r"\[(?:Control|ACK):[^\]]+\]", body):
        return "control_or_ack"
    if re.search(r"\[Persona[ \t]+(?:Sync|Check)\]", body, re.I):
        return "persona_control"
    if re.match(r"^[ \t]*\[(?:Task|Role-Handoff):", body):
        return "control_marker_in_chat"
    return None


def check_policy(db: sqlite3.Connection, sender_endpoint: str, target_address: str,
                 body: str, now: float, in_reply_to: str | None = None) -> None:
    """Raise :class:`HubError` for forbidden or duplicate unified sends."""
    lower = target_address.lower()
    if lower in {"all", "*", "broadcast", "everyone"}:
        raise HubError("policy_blocked", "broadcast-like target is forbidden")
    reason = _blocked_body(body)
    if reason:
        raise HubError("policy_blocked", reason)
    if in_reply_to:
        return
    family = _family(target_address)
    if family:
        rows = db.execute(
            "SELECT target_address, body, created_at FROM messages "
            "WHERE sender_endpoint=? AND created_at>=? ORDER BY created_at DESC",
            (sender_endpoint, float(now) - TTL),
        )
        normalized = _normal(body)
        for row in rows:
            if _family(row[0]) == family and row[0] != target_address and _normal(row[1]) == normalized:
                raise HubError("policy_blocked", "potential fan-out")
    # Recovery replay is intentionally independent of target family and has no
    # bypass flag in the unified API. Only recovery-shaped gate sends qualify.
    if lower == "gate" or lower.startswith("gate:"):
        recovery = re.search(r"未達|読み落とし|復元|再投入|過去の指示|過去依頼|\bskip(?:ping)?\b", body, re.I)
        context = re.search(r"ご主人様|ユーザー|LINE|id[ \t]+\d+|作業依頼|指示|URLだして|日報", body, re.I)
        if recovery and context:
            fp = _recovery_fingerprint(sender_endpoint, target_address, body)
            rows = db.execute("SELECT body, target_address, created_at FROM messages WHERE sender_endpoint=? AND created_at>=?", (sender_endpoint, float(now) - RECOVERY_TTL))
            for old_body, old_target, _created in rows:
                if _recovery_fingerprint(sender_endpoint, old_target, old_body) == fp:
                    raise HubError("policy_blocked", "repeated recovery dispatch")

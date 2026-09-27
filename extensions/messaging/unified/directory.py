"""Transactional directory rename helpers for federated messaging.

The manager calls :func:`manager_update`; owner hubs expose the three
``peer_directory_*`` functions through their federation dispatch.  A change
is identified by ``change_id`` and may be retried safely.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from protocol import HubError


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS directory_changes (
      change_id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
      error TEXT
    );
    CREATE TABLE IF NOT EXISTS directory_transactions (
      change_id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
      created_at REAL NOT NULL, updated_at REAL NOT NULL
    );
    """)


def _payload(req: dict[str, Any]) -> dict[str, Any]:
    payload = req.get("payload")
    if not isinstance(payload, dict) or not req.get("change_id"):
        raise HubError("invalid_directory", "change_id and payload required")
    return payload


def prepare(hub: Any, req: dict[str, Any]) -> dict[str, Any]:
    """Stage an owner-local payload without changing authoritative rows."""
    ensure_schema(hub.db)
    payload = _payload(req); change_id = str(req["change_id"])
    existing = hub._row("SELECT payload,state FROM directory_changes WHERE change_id=?", (change_id,))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if existing:
        if existing["payload"] != encoded:
            raise HubError("id_conflict", "change ID has different payload")
        return {"change_id": change_id, "state": existing["state"]}
    projects = payload.get("projects", [])
    local_id = hub.local_id if hasattr(hub, "local_id") else hub.config.get("host_id")
    if any(not isinstance(p, dict) or p.get("host_id") != local_id for p in projects):
        raise HubError("identity_rejected", "owner may stage only local projects")
    expected = payload.get("expected_revision")
    current = int(hub._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])
    if expected is not None and int(expected) != current:
        raise HubError("revision_conflict", "directory revision changed")
    hub.db.execute("INSERT INTO directory_changes(change_id,payload,state,error) VALUES(?,?,?,NULL)", (change_id, encoded, "prepared"))
    return {"change_id": change_id, "state": "prepared", "revision": current}


def commit(hub: Any, req: dict[str, Any]) -> dict[str, Any]:
    """Apply one prepared owner-local change atomically and idempotently."""
    ensure_schema(hub.db)
    change_id = str(req.get("change_id") or "")
    row = hub._row("SELECT payload,state FROM directory_changes WHERE change_id=?", (change_id,))
    if not row: raise HubError("not_found", "directory change is not prepared")
    if row["state"] == "committed": return {"change_id": change_id, "state": "committed"}
    payload = json.loads(row["payload"])
    local_id = hub.local_id if hasattr(hub, "local_id") else hub.config.get("host_id")
    projects = payload.get("projects", [])
    if any(p.get("host_id") != local_id for p in projects):
        raise HubError("identity_rejected", "owner may commit only local projects")
    hub._tx()
    try:
        for p in projects:
            old = hub._row("SELECT alias FROM projects WHERE project_id=?", (p["project_id"],))
            if old and old[0] != p["alias"]:
                hub.db.execute("INSERT OR IGNORE INTO alias_history(alias) VALUES(?)", (old[0],))
                hub.db.execute("UPDATE participants SET address=? WHERE project_id=? AND kind='cc'", (p["alias"] + ".cc", p["project_id"]))
                hub.db.execute("UPDATE participants SET address=? WHERE project_id=? AND kind='cdx'", (p["alias"] + ".cdx", p["project_id"]))
            conflict = hub._row("SELECT project_id FROM projects WHERE alias=? AND project_id<>?", (p["alias"], p["project_id"]))
            if conflict: raise HubError("directory_conflict", "alias already assigned")
            hub.db.execute("UPDATE projects SET alias=?,path=? WHERE project_id=? AND host_id=?", (p["alias"], p["path"], p["project_id"], local_id))
        rev = int(hub._row("SELECT value FROM metadata WHERE key='directory_revision'")[0]) + 1
        hub.db.execute("UPDATE metadata SET value=? WHERE key='directory_revision'", (str(rev),))
        hub.db.execute("UPDATE directory_changes SET state='committed',error=NULL WHERE change_id=?", (change_id,))
        hub._commit()
    except Exception:
        hub._rollback(); raise
    return {"change_id": change_id, "state": "committed", "revision": rev}


def status(hub: Any, req: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(hub.db)
    row = hub._row("SELECT change_id,state,error FROM directory_changes WHERE change_id=?", (req.get("change_id"),))
    return dict(row) if row else {"change_id": req.get("change_id"), "state": "unknown"}


def manager_update(hub: Any, req: dict[str, Any], peer_call: Callable[[str, str, dict[str, Any]], dict[str, Any]], peer_ids: list[str]) -> dict[str, Any]:
    """Two-phase manager orchestration; no commit is attempted after prepare failure."""
    ensure_schema(hub.db)
    change_id = str(req.get("change_id") or "")
    payload = _payload(req)
    if not change_id: raise HubError("invalid_directory", "change_id required")
    owners = {str(p.get("host_id")) for p in payload.get("projects", [])}
    owners.discard(str(getattr(hub, "local_id", hub.config.get("host_id"))))
    if any(pid not in peer_ids for pid in owners): raise HubError("host_unavailable", "directory owner is not enrolled")
    prepared: list[str] = []
    for owner in sorted(owners):
        peer_call(owner, "directory_prepare", {"change_id": change_id, "payload": payload})
        prepared.append(owner)
    local_projects = [p for p in payload.get("projects", []) if p.get("host_id") == getattr(hub, "local_id", hub.config.get("host_id"))]
    if local_projects:
        prepare(hub, {"change_id": change_id, "payload": {**payload, "projects": local_projects}})
    for owner in prepared: peer_call(owner, "directory_commit", {"change_id": change_id})
    if local_projects: commit(hub, {"change_id": change_id})
    return {"change_id": change_id, "state": "committed"}

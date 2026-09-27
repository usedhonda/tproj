"""Transactional directory rename helpers for federated messaging.

The manager calls :func:`manager_update`; owner hubs expose the three
``peer_directory_*`` functions through their federation dispatch.  A change
is identified by ``change_id`` and may be retried safely.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

try:
    from .protocol import HubError
except ImportError:
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
    try: db.execute("ALTER TABLE directory_changes ADD COLUMN error TEXT")
    except sqlite3.OperationalError: pass


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
    if any(not isinstance(p, dict) or not all(p.get(k) for k in ("project_id", "alias", "host_id", "path")) or p.get("host_id") != local_id for p in projects):
        raise HubError("identity_rejected", "owner may stage only local projects")
    expected = payload.get("expected_revision")
    current = int(hub._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])
    if expected is not None and int(expected) != current:
        raise HubError("revision_conflict", "directory revision changed")
    aliases = [p["alias"] for p in projects]
    if len(aliases) != len(set(aliases)) or any(hub._row("SELECT 1 FROM alias_history WHERE alias=?", (a,)) for a in aliases):
        raise HubError("directory_conflict", "alias is duplicate or historical")
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
            if old:
                hub.db.execute("UPDATE projects SET alias=?,path=? WHERE project_id=? AND host_id=?", (p["alias"], p["path"], p["project_id"], local_id))
            else:
                hub.db.execute("INSERT INTO projects(project_id,alias,host_id,path) VALUES(?,?,?,?)", (p["project_id"],p["alias"],local_id,p["path"]))
                for kind in ("cc", "cdx"):
                    hub.db.execute("INSERT OR IGNORE INTO participants(participant_id,project_id,address,host_id,kind) VALUES(?,?,?,?,?)", (f"{p['project_id']}:{kind}",p["project_id"],f"{p['alias']}.{kind}",local_id,kind))
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
    payload = req.get("payload") or {"expected_revision": req.get("expected_revision"), "projects": req.get("projects", [])}
    if not change_id: raise HubError("invalid_directory", "change_id required")
    local_id = str(getattr(hub, "local_id", hub.config.get("host_id")))
    owners = {str(p.get("host_id")) for p in payload.get("projects", [])}
    owners.discard(local_id)
    if any(pid not in peer_ids for pid in owners): raise HubError("host_unavailable", "directory owner is not enrolled")
    ensure_schema(hub.db)
    existing = hub._row("SELECT state,payload FROM directory_transactions WHERE change_id=?", (change_id,))
    if existing and existing["state"] == "decided":
        # Recovery path: redo only idempotent commits.
        for owner in sorted(owners): peer_call(owner, "directory_commit", {"change_id": change_id})
        local_projects = [p for p in payload.get("projects", []) if p.get("host_id") == local_id]
        if local_projects: commit(hub, {"change_id": change_id})
        return {"change_id": change_id, "state": "committed", "revision": int(hub._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])}
    # A durable decision is written before any commit; prepare failures leave no decision.
    owners_payload = {owner: [p for p in payload.get("projects", []) if str(p.get("host_id")) == owner] for owner in owners}
    local_projects = [p for p in payload.get("projects", []) if str(p.get("host_id")) == local_id]
    for owner in sorted(owners):
        peer_call(owner, "directory_prepare", {"change_id": change_id, "payload": {**payload, "projects": owners_payload[owner]}})
    if local_projects: prepare(hub, {"change_id": change_id, "payload": {**payload, "projects": local_projects}})
    now = hub._now(); encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    hub.db.execute("INSERT OR REPLACE INTO directory_transactions(change_id,payload,state,created_at,updated_at) VALUES(?,?,?,?,?)", (change_id, encoded, "decided", now, now))
    for owner in sorted(owners): peer_call(owner, "directory_commit", {"change_id": change_id})
    if local_projects: commit(hub, {"change_id": change_id})
    hub.db.execute("UPDATE directory_transactions SET state='committed',updated_at=? WHERE change_id=?", (hub._now(), change_id))
    return {"change_id": change_id, "state": "committed", "revision": int(hub._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])}

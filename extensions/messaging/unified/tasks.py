"""Authoritative, durable task lifecycle for the unified messaging hub.

The authority is deliberately small and host-facing: callers pass an already
authenticated endpoint tuple, while host integration remains responsible for
attesting direct-user approval evidence.  All state transitions are durable in
the same SQLite database as the mailbox and are fenced by endpoint incarnation
and epoch values.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import os
import uuid
from typing import Any, Mapping


class TaskAuthorityError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


SCHEMA = """
CREATE TABLE IF NOT EXISTS task_approvals (
 approval_id TEXT PRIMARY KEY, intent_hash TEXT NOT NULL, scope_hash TEXT NOT NULL,
 evidence_hash TEXT NOT NULL, source_endpoint TEXT NOT NULL, source_incarnation TEXT,
 host_id TEXT NOT NULL, created_at REAL NOT NULL)
;
CREATE TABLE IF NOT EXISTS tasks (
 task_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, intent_hash TEXT NOT NULL,
 scope_hash TEXT NOT NULL, approval_id TEXT NOT NULL, owner_endpoint TEXT NOT NULL,
 owner_incarnation TEXT NOT NULL, owner_host_id TEXT NOT NULL, owner_project_id TEXT NOT NULL,
 executor_endpoint TEXT NOT NULL, executor_incarnation TEXT NOT NULL, executor_host_id TEXT NOT NULL,
 status TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, FOREIGN KEY(approval_id) REFERENCES task_approvals(approval_id))
;
CREATE TABLE IF NOT EXISTS task_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, kind TEXT NOT NULL,
 actor_endpoint TEXT NOT NULL, actor_incarnation TEXT NOT NULL, epoch INTEGER NOT NULL,
 data TEXT NOT NULL, at REAL NOT NULL)
;
CREATE TABLE IF NOT EXISTS task_operations (
 token TEXT PRIMARY KEY, task_id TEXT NOT NULL, endpoint TEXT NOT NULL, incarnation TEXT NOT NULL,
 epoch INTEGER NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL)
;
CREATE TABLE IF NOT EXISTS task_handoffs (
 task_id TEXT PRIMARY KEY, expected_epoch INTEGER NOT NULL, target_endpoint TEXT NOT NULL,
 target_incarnation TEXT NOT NULL, target_host_id TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL)
;
CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id,event_id);
CREATE INDEX IF NOT EXISTS task_ops_task ON task_operations(task_id,state);
"""


_STATUSES = {"submitted", "accepted", "in_progress", "done", "blocked", "verified", "reported", "cancelled", "frozen"}
_MUTATING = {"ack", "progress", "done", "block", "verify", "report"}


def _hash(value: Any) -> str:
    if isinstance(value, str) and len(value) == 64:
        return value
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class TaskAuthority:
    """SQLite-backed task authority.  ``db`` may be a path or sqlite connection."""

    def __init__(self, db: str | os.PathLike | sqlite3.Connection):
        self.db = sqlite3.connect(str(db), isolation_level=None, check_same_thread=False) if isinstance(db, (str, os.PathLike)) else db
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @staticmethod
    def _actor(actor: Mapping[str, Any]) -> dict[str, str]:
        keys = ("endpoint_id", "incarnation", "host_id", "project_id")
        if not all(str(actor.get(k, "")) for k in keys):
            raise TaskAuthorityError("identity_rejected", "trusted endpoint identity is incomplete")
        return {k: str(actor[k]) for k in keys}

    def _task(self, task_id: str):
        row = self.db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise TaskAuthorityError("not_found", "task does not exist")
        return row

    def _event(self, task_id, kind, actor, epoch, data=None):
        self.db.execute("INSERT INTO task_events(task_id,kind,actor_endpoint,actor_incarnation,epoch,data,at) VALUES(?,?,?,?,?,?,?)",
                        (task_id, kind, actor["endpoint_id"], actor["incarnation"], epoch,
                         json.dumps(data or {}, sort_keys=True), time.time()))

    def _owner(self, row, actor):
        if row["owner_endpoint"] != actor["endpoint_id"] or row["owner_incarnation"] != actor["incarnation"]:
            raise TaskAuthorityError("not_owner", "only current owner may perform this operation")

    def _executor(self, row, actor):
        if row["executor_endpoint"] != actor["endpoint_id"] or row["executor_incarnation"] != actor["incarnation"]:
            raise TaskAuthorityError("stale_executor", "executor incarnation is fenced")

    def _epoch(self, req, row):
        if req.get("expected_epoch") is not None and int(req["expected_epoch"]) != row["epoch"]:
            raise TaskAuthorityError("epoch_conflict", "task epoch changed")

    def _view(self, row):
        d = dict(row); d["payload"] = json.loads(d["payload"]); return d

    def dispatch(self, req: Mapping[str, Any], actor: Mapping[str, Any]):
        actor = self._actor(actor); op = str(req.get("op", ""))
        if op.startswith("task_"): op = op[5:]
        if op.startswith("handoff_"): op = op[8:]
        fn = getattr(self, f"_op_{op}", None)
        if not fn: raise TaskAuthorityError("unsupported", "unsupported task operation")
        return fn(dict(req), actor)

    def _op_approval(self, req, actor):
        # Host integration must set this only after direct-user evidence was
        # authenticated; the task authority never accepts selector-only proof.
        if not req.get("host_attested") or req.get("source_endpoint") != actor["endpoint_id"]:
            raise TaskAuthorityError("approval_unattested", "approval requires host-attested direct-user evidence")
        required = ("approval_id", "intent_hash", "scope_hash", "evidence_hash")
        if not all(req.get(k) for k in required): raise TaskAuthorityError("invalid_approval", "approval fields required")
        aid = str(req["approval_id"]); existing = self.db.execute("SELECT * FROM task_approvals WHERE approval_id=?", (aid,)).fetchone()
        if existing:
            if any(existing[k] != str(req[k]) for k in ("intent_hash", "scope_hash", "evidence_hash")):
                raise TaskAuthorityError("id_conflict", "approval ID has different evidence")
            return {"approval_id": aid, "duplicate": True}
        self.db.execute("INSERT INTO task_approvals VALUES(?,?,?,?,?,?,?,?)", (aid, str(req["intent_hash"]), str(req["scope_hash"]), str(req["evidence_hash"]), actor["endpoint_id"], actor["incarnation"], actor["host_id"], time.time()))
        return {"approval_id": aid, "created": True}

    def _op_submit(self, req, actor):
        aid = str(req.get("approval_id", "")); approval = self.db.execute("SELECT * FROM task_approvals WHERE approval_id=?", (aid,)).fetchone()
        if not approval: raise TaskAuthorityError("approval_missing", "approval reference is unknown")
        if approval["source_endpoint"] != actor["endpoint_id"] or approval["source_incarnation"] != actor["incarnation"]:
            raise TaskAuthorityError("approval_owner", "approval source is fenced to its registering endpoint")
        for k in ("intent_hash", "scope_hash"):
            if str(req.get(k, "")) != approval[k]: raise TaskAuthorityError("approval_mismatch", f"{k} does not match approval")
        if req.get("owner_endpoint") and str(req["owner_endpoint"]) != actor["endpoint_id"]: raise TaskAuthorityError("not_owner", "submitter must be owner")
        key = str(req.get("idempotency_key") or "");
        if not key: raise TaskAuthorityError("invalid_task", "idempotency_key required")
        old = self.db.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
        if old:
            if old["intent_hash"] != str(req["intent_hash"]) or old["scope_hash"] != str(req["scope_hash"]): raise TaskAuthorityError("id_conflict", "idempotency key conflicts")
            return {"task": self._view(old), "duplicate": True}
        executor = req.get("executor") or {}; executor_endpoint = str(executor.get("endpoint_id") or req.get("executor_endpoint") or actor["endpoint_id"]); executor_inc = str(executor.get("incarnation") or req.get("executor_incarnation") or actor["incarnation"]); executor_host = str(executor.get("host_id") or req.get("executor_host_id") or actor["host_id"])
        now = time.time(); tid = str(req.get("task_id") or uuid.uuid4()); payload = req.get("payload") or {}
        self.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (tid,key,str(req["intent_hash"]),str(req["scope_hash"]),aid,actor["endpoint_id"],actor["incarnation"],actor["host_id"],actor["project_id"],executor_endpoint,executor_inc,executor_host,"submitted",0,json.dumps(payload,sort_keys=True),now,now))
        self._event(tid, "submit", actor, 0); return {"task": self._view(self._task(tid))}

    def _visible(self, row, actor):
        return row["owner_endpoint"] == actor["endpoint_id"] or row["executor_endpoint"] == actor["endpoint_id"] or (row["executor_incarnation"] == actor["incarnation"] and row["executor_host_id"] == actor["host_id"])
    def _op_status(self, req, actor):
        row=self._task(str(req.get("task_id"))); 
        if not self._visible(row,actor): raise TaskAuthorityError("not_visible","task is not assigned to actor")
        return {"task": self._view(row)}
    def _op_list(self, req, actor):
        rows = self.db.execute("SELECT * FROM tasks WHERE owner_endpoint=? OR executor_endpoint=? ORDER BY created_at",(actor["endpoint_id"],actor["endpoint_id"])).fetchall(); return {"tasks": [self._view(r) for r in rows]}

    def _op_active(self, req, actor):
        rows = self.db.execute("SELECT * FROM tasks WHERE (owner_endpoint=? OR executor_endpoint=?) AND status NOT IN ('reported','cancelled') ORDER BY created_at",(actor["endpoint_id"],actor["endpoint_id"])).fetchall(); return {"tasks": [self._view(r) for r in rows]}

    def _transition(self, req, actor, target, kind):
        row = self._task(str(req.get("task_id"))); self._epoch(req, row); self._executor(row, actor)
        if req.get("expected_epoch") is None: raise TaskAuthorityError("epoch_required", "expected_epoch is required")
        allowed={"submitted":{"accepted","blocked"},"accepted":{"in_progress","blocked"},"in_progress":{"done","blocked"},"done":{"verified","blocked"},"blocked":{"in_progress","done","verified"},"verified":{"reported"},"reported":set(),"cancelled":set(),"frozen":set()}
        if target not in allowed.get(row["status"], set()):
            raise TaskAuthorityError("stale_task", "task cannot be resurrected")
        self.db.execute("UPDATE tasks SET status=?,updated_at=? WHERE task_id=? AND epoch=?", (target,time.time(),row["task_id"],row["epoch"]))
        self._event(row["task_id"], kind, actor, row["epoch"], req.get("data")); return {"task": self._view(self._task(row["task_id"]))}

    def _op_ack(self, req, actor): return self._transition(req, actor, "accepted", "ack")
    def _op_progress(self, req, actor): return self._transition(req, actor, "in_progress", "progress")
    def _op_done(self, req, actor): return self._transition(req, actor, "done", "done")
    def _op_block(self, req, actor): return self._transition(req, actor, "blocked", "block")
    def _op_verify(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row); return self._owner_transition(row,actor,"verified","verify",req)
    def _op_report(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row); return self._owner_transition(row,actor,"reported","report",req)
    def _owner_transition(self,row,actor,target,kind,req):
        if target not in ({"verified"} if row["status"]=="done" else {"reported"} if row["status"]=="verified" else set()): raise TaskAuthorityError("invalid_transition","invalid task transition")
        self.db.execute("UPDATE tasks SET status=?,updated_at=? WHERE task_id=? AND epoch=?",(target,time.time(),row["task_id"],row["epoch"])); self._event(row["task_id"],kind,actor,row["epoch"],req.get("data")); return {"task":self._view(self._task(row["task_id"]))}

    def _op_cancel(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row)
        self.db.execute("UPDATE tasks SET status='cancelled',updated_at=? WHERE task_id=? AND epoch=?",(time.time(),row["task_id"],row["epoch"])); self._event(row["task_id"],"cancel",actor,row["epoch"]); return {"task":self._view(self._task(row["task_id"]))}

    def _op_freeze(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row)
        self.db.execute("UPDATE tasks SET status='frozen',updated_at=? WHERE task_id=? AND epoch=?",(time.time(),row["task_id"],row["epoch"])); self._event(row["task_id"],"freeze",actor,row["epoch"]); return {"task":self._view(self._task(row["task_id"]))}

    def _op_begin_operation(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._epoch(req,row); self._executor(row,actor)
        if req.get("expected_epoch") is None: raise TaskAuthorityError("epoch_required","expected_epoch is required")
        h=self.db.execute("SELECT state,target_endpoint,target_incarnation FROM task_handoffs WHERE task_id=?",(row["task_id"],)).fetchone()
        if h and h["state"] in ("prepared","released","accepted") and (h["target_endpoint"] != actor["endpoint_id"] or h["target_incarnation"] != actor["incarnation"]): raise TaskAuthorityError("handoff_pending","task is quiescing for handoff")
        kind = str(req.get("tool_use_id") or req.get("kind","mutation"))
        existing=self.db.execute("SELECT * FROM task_operations WHERE task_id=? AND endpoint=? AND incarnation=? AND kind=? AND state='open'",(row["task_id"],actor["endpoint_id"],actor["incarnation"],kind)).fetchone()
        if existing: return {"token":existing["token"],"epoch":row["epoch"],"duplicate":True}
        token=str(uuid.uuid4()); self.db.execute("INSERT INTO task_operations VALUES(?,?,?,?,?,?,?)",(token,row["task_id"],actor["endpoint_id"],actor["incarnation"],row["epoch"],kind,"open",time.time())); return {"token":token,"epoch":row["epoch"]}

    def _op_end_operation(self, req, actor):
        token=str(req.get("token","")); op=self.db.execute("SELECT * FROM task_operations WHERE token=?",(token,)).fetchone()
        if not op and req.get("tool_use_id"):
            op=self.db.execute("SELECT * FROM task_operations WHERE kind=? ORDER BY created_at DESC LIMIT 1",(str(req["tool_use_id"]),)).fetchone(); token=op["token"] if op else token
        if not op: raise TaskAuthorityError("not_found","operation token unknown")
        if op["endpoint"] != actor["endpoint_id"] or op["incarnation"] != actor["incarnation"]: raise TaskAuthorityError("stale_executor","operation owner is fenced")
        if op["state"] != "open": return {"token":token,"duplicate":True}
        self.db.execute("UPDATE task_operations SET state='closed' WHERE token=?",(token,)); return {"token":token,"closed":True}

    def _op_prepare_handoff(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row)
        if self.db.execute("SELECT 1 FROM task_operations WHERE task_id=? AND state='open'",(row["task_id"],)).fetchone(): raise TaskAuthorityError("operations_open","handoff requires quiescence")
        target=req.get("target") or {}; required=("endpoint_id","incarnation","host_id")
        if not all(target.get(k) for k in required): raise TaskAuthorityError("invalid_handoff","target identity required")
        prior=self.db.execute("SELECT state FROM task_handoffs WHERE task_id=?",(row["task_id"],)).fetchone()
        if prior and prior["state"] in ("released","accepted"): raise TaskAuthorityError("handoff_in_progress","handoff already advanced")
        self.db.execute("INSERT INTO task_handoffs VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET expected_epoch=excluded.expected_epoch,target_endpoint=excluded.target_endpoint,target_incarnation=excluded.target_incarnation,target_host_id=excluded.target_host_id,state='prepared',created_at=excluded.created_at",(row["task_id"],row["epoch"],str(target["endpoint_id"]),str(target["incarnation"]),str(target["host_id"]),"prepared",time.time()))
        return {"handoff":{"task_id":row["task_id"],"from_endpoint":row["executor_endpoint"],"from_incarnation":row["executor_incarnation"],"target":dict(target),"expected_epoch":row["epoch"]}}

    def _op_release_handoff(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._executor(row,actor); self._epoch(req,row)
        if self.db.execute("SELECT 1 FROM task_operations WHERE task_id=? AND state='open'",(row["task_id"],)).fetchone(): raise TaskAuthorityError("operations_open","release requires quiescence")
        h=self.db.execute("SELECT * FROM task_handoffs WHERE task_id=? AND expected_epoch=?",(row["task_id"],row["epoch"])).fetchone()
        if not h: raise TaskAuthorityError("handoff_missing","handoff is not prepared")
        self.db.execute("UPDATE task_handoffs SET state='released' WHERE task_id=?",(row["task_id"],)); return {"task_id":row["task_id"],"released":True}

    def _op_accept_handoff(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._epoch(req,row)
        h=self.db.execute("SELECT * FROM task_handoffs WHERE task_id=?",(row["task_id"],)).fetchone()
        if not h or h["state"] != "released": raise TaskAuthorityError("handoff_not_released","old executor must release first")
        if h["target_endpoint"] != actor["endpoint_id"] or h["target_incarnation"] != actor["incarnation"]: raise TaskAuthorityError("stale_executor","handoff target identity mismatch")
        self.db.execute("UPDATE task_handoffs SET state='accepted' WHERE task_id=?",(row["task_id"],)); return {"task_id":row["task_id"],"accepted":True}

    def _op_commit_handoff(self, req, actor):
        row=self._task(str(req.get("task_id"))); self._owner(row,actor); self._epoch(req,row)
        if self.db.execute("SELECT 1 FROM task_operations WHERE task_id=? AND state='open'",(row["task_id"],)).fetchone(): raise TaskAuthorityError("operations_open","handoff requires quiescence")
        target=req.get("target") or {}; required=("endpoint_id","incarnation","host_id")
        if not all(target.get(k) for k in required): raise TaskAuthorityError("invalid_handoff","target identity required")
        h=self.db.execute("SELECT * FROM task_handoffs WHERE task_id=?",(row["task_id"],)).fetchone()
        if not h or h["state"] != "accepted" or h["target_endpoint"] != str(target["endpoint_id"]) or h["target_incarnation"] != str(target["incarnation"]) or h["target_host_id"] != str(target["host_id"]): raise TaskAuthorityError("handoff_not_accepted","target must accept before commit")
        epoch=row["epoch"]+1; self.db.execute("UPDATE tasks SET executor_endpoint=?,executor_incarnation=?,executor_host_id=?,epoch=?,updated_at=? WHERE task_id=? AND epoch=?",(str(target["endpoint_id"]),str(target["incarnation"]),str(target["host_id"]),epoch,time.time(),row["task_id"],row["epoch"]))
        self.db.execute("UPDATE task_handoffs SET state='committed' WHERE task_id=?",(row["task_id"],)); self._event(row["task_id"],"handoff_commit",actor,epoch,{"target":target}); return {"task":self._view(self._task(row["task_id"]))}

"""Durable SQLite mailbox hub for the unified agent messaging contract."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import stat
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from .protocol import HubError, MAX_BODY, MAX_TTL, serve_socket
    from .policy import check_policy
except ImportError:  # allow the installed single-file entrypoint to be invoked directly
    from protocol import HubError, MAX_BODY, MAX_TTL, serve_socket
    from policy import check_policy


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, alias TEXT NOT NULL UNIQUE, host_id TEXT NOT NULL, path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alias_history (alias TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS participants (participant_id TEXT PRIMARY KEY, project_id TEXT, address TEXT NOT NULL UNIQUE, host_id TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS endpoints (endpoint_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, host_id TEXT NOT NULL, session TEXT, pane TEXT, pid INTEGER, pid_start TEXT, runtime_id TEXT, platform TEXT, incarnation TEXT NOT NULL, last_heartbeat REAL NOT NULL, retired INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(participant_id) REFERENCES participants(participant_id));
CREATE TABLE IF NOT EXISTS messages (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, in_reply_to TEXT, sender_endpoint TEXT NOT NULL, target_address TEXT NOT NULL, recipient_endpoint TEXT, body TEXT NOT NULL, kind TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, payload_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'accepted', adapter_received_at REAL, UNIQUE(message_id));
CREATE TABLE IF NOT EXISTS receipts (message_id TEXT PRIMARY KEY, state TEXT NOT NULL, evidence TEXT, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS message_recipient ON messages(recipient_endpoint, state, expires_at);
"""


class Hub:
    def __init__(self, db_path: str | os.PathLike, config: dict | str | os.PathLike | None = None):
        self.db_path = str(db_path)
        self.config = self._load_config(config)
        self.host_tokens = self.config.get("hosts", {})
        self.admin_token = self.config.get("admin_token")
        self.db = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('directory_revision','0')")
        self.db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('maintenance','open')")

    @staticmethod
    def _load_config(config):
        if config is None: return {}
        if isinstance(config, dict): return config
        with open(config, encoding="utf-8") as f: return json.load(f)

    def close(self): self.db.close()
    def _now(self): return time.time()
    def _row(self, q, args=()): return self.db.execute(q, args).fetchone()
    def _auth(self, req, admin=False):
        token = req.get("admin_token") if admin else req.get("host_token")
        ident = "admin" if admin else req.get("host_id")
        expected = self.admin_token if admin else self.host_tokens.get(ident)
        if not expected or not secrets.compare_digest(str(token or ""), str(expected)):
            raise HubError("unauthorized", "invalid credentials")
        return ident
    def _maintenance(self): return self._row("SELECT value FROM metadata WHERE key='maintenance'")[0]
    def _project(self, address):
        base, dot, role = address.rpartition(".")
        if not dot or role not in ("cc", "cdx"): raise HubError("unknown_target", "address must be project.cc or project.cdx")
        p = self._row("SELECT * FROM projects WHERE alias=?", (base,))
        if not p: raise HubError("unknown_target", "unknown project")
        return p, role
    def _address(self, target, sender_endpoint):
        ep = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (sender_endpoint,))
        if not ep: raise HubError("identity_rejected", "unknown sender endpoint")
        if target in ("cc", "cdx"): target = (self._project_for_participant(ep["participant_id"]) or "") + "." + target
        return target
    def _project_for_participant(self, participant_id):
        r = self._row("SELECT p.alias FROM projects p JOIN participants x ON x.project_id=p.project_id WHERE x.participant_id=?", (participant_id,))
        return r[0] if r else None
    def _participant(self, address):
        service = self._row("SELECT * FROM participants WHERE address=? AND project_id IS NULL", (address,))
        if service: return service
        p, role = self._project(address)
        r = self._row("SELECT * FROM participants WHERE address=?", (address,))
        if not r:
            r = self._row("SELECT * FROM participants WHERE project_id=? AND kind=?", (p["project_id"], role))
        if not r: raise HubError("unknown_target", "unknown participant")
        return r
    def _endpoint_for_send(self, participant):
        rows = self.db.execute("SELECT * FROM endpoints WHERE participant_id=? AND retired=0 ORDER BY endpoint_id", (participant["participant_id"],)).fetchall()
        if len(rows) != 1: raise HubError("ambiguous_target" if rows else "no_recipient", "ambiguous target" if rows else "target has no current endpoint")
        return rows[0]
    def _host_endpoint(self, host, endpoint_id):
        e = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (endpoint_id,))
        if not e or e["host_id"] != host: raise HubError("identity_rejected", "endpoint is not owned by host")
        if e["retired"]: raise HubError("stale_session", "endpoint is retired")
        return e
    def _tx(self): self.db.execute("BEGIN IMMEDIATE")
    def _commit(self): self.db.execute("COMMIT")
    def _rollback(self):
        if self.db.in_transaction: self.db.execute("ROLLBACK")

    # Public convenience methods mirror dispatch operations for embedders/tests.
    def ping(self):
        return {"maintenance": self._maintenance(), "revision": int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])}
    def directory_list(self):
        now=self._now(); participants=[]
        for x in self.db.execute("SELECT * FROM participants"):
            d=dict(x); eps=[dict(e) for e in self.db.execute("SELECT endpoint_id,host_id,incarnation,last_heartbeat,retired FROM endpoints WHERE participant_id=?",(x["participant_id"],))]; d["endpoints"]=eps; d["online"]=any(not e["retired"] and now-e["last_heartbeat"] <= 30 for e in eps); participants.append(d)
        return {"revision": int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0]), "projects": [dict(x) for x in self.db.execute("SELECT * FROM projects")], "participants": participants, "services": [x for x in participants if x["project_id"] is None]}
    def resolve(self, address):
        return dict(self._participant(address))
    def endpoints_list(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM endpoints")]

    def directory_import(self, req):
        self._auth(req, True); projects, services = req.get("projects", []), req.get("services", [])
        expected = req.get("expected_revision")
        self._tx()
        try:
            rev = int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])
            if expected is not None and int(expected) != rev: raise HubError("revision_conflict", "directory revision changed")
            seen = set()
            for x in projects:
                if not all(x.get(k) for k in ("project_id", "alias", "host_id", "path")): raise HubError("invalid_directory", "project fields required")
                if x["alias"] in seen: raise HubError("directory_conflict", "duplicate alias")
                seen.add(x["alias"])
                old = self._row("SELECT * FROM projects WHERE project_id=?", (x["project_id"],))
                if old and old["alias"] != x["alias"]:
                    self.db.execute("UPDATE participants SET address=? WHERE project_id=? AND kind='cc'", (f"{x['alias']}.cc", x["project_id"]))
                    self.db.execute("UPDATE participants SET address=? WHERE project_id=? AND kind='cdx'", (f"{x['alias']}.cdx", x["project_id"]))
                other = self._row("SELECT project_id FROM projects WHERE alias=?", (x["alias"],))
                if other and other[0] != x["project_id"]: raise HubError("directory_conflict", "alias already assigned")
                if not old and self._row("SELECT 1 FROM alias_history WHERE alias=?", (x["alias"],)): raise HubError("directory_conflict", "historical alias cannot be reused")
                if old and old["alias"] != x["alias"]: self.db.execute("INSERT OR IGNORE INTO alias_history(alias) VALUES(?)", (old["alias"],))
                self.db.execute("INSERT INTO projects(project_id,alias,host_id,path) VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET alias=excluded.alias,host_id=excluded.host_id,path=excluded.path", (x["project_id"],x["alias"],x["host_id"],x["path"]))
                for kind in ("cc", "cdx"):
                    aid = f"{x['project_id']}:{kind}"
                    self.db.execute("INSERT OR IGNORE INTO participants(participant_id,project_id,address,host_id,kind) VALUES(?,?,?,?,?)", (aid,x["project_id"],f"{x['alias']}.{kind}",x["host_id"],kind))
            for x in services:
                if not all(x.get(k) for k in ("participant_id","address","host_id","kind")): raise HubError("invalid_directory", "service fields required")
                old = self._row("SELECT * FROM participants WHERE participant_id=?", (x["participant_id"],))
                if old and old["address"] != x["address"]: raise HubError("directory_conflict", "participant address reassignment forbidden")
                self.db.execute("INSERT INTO participants(participant_id,address,host_id,kind) VALUES(?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET host_id=excluded.host_id", (x["participant_id"],x["address"],x["host_id"],x["kind"]))
            rev += 1; self.db.execute("UPDATE metadata SET value=? WHERE key='directory_revision'", (str(rev),)); self._commit()
            return {"revision": rev}
        except Exception: self._rollback(); raise

    def register(self, req):
        host = self._auth(req); required = ("endpoint_id","participant_id","host_id","session","pane","pid","pid_start","runtime_id","platform")
        if req.get("host_id") != host or not all(k in req for k in required): raise HubError("invalid_endpoint", "endpoint fields required")
        p = self._row("SELECT * FROM participants WHERE participant_id=?", (req["participant_id"],))
        if not p or p["host_id"] != host: raise HubError("identity_rejected", "participant is not owned by host")
        old = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (req["endpoint_id"],)); now = self._now()
        if old and old["retired"]: raise HubError("stale_session", "retired endpoint cannot be revived")
        if old and any(str(old[k]) != str(req[k]) for k in ("host_id","participant_id","session","pane","pid","pid_start","runtime_id","platform")): raise HubError("identity_rejected", "endpoint identity is immutable")
        inc = old["incarnation"] if old and old["pid_start"] == str(req["pid_start"]) and old["runtime_id"] == req["runtime_id"] else str(uuid.uuid4())
        self.db.execute("INSERT INTO endpoints(endpoint_id,participant_id,host_id,session,pane,pid,pid_start,runtime_id,platform,incarnation,last_heartbeat,retired) VALUES(?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(endpoint_id) DO UPDATE SET participant_id=excluded.participant_id,session=excluded.session,pane=excluded.pane,pid=excluded.pid,pid_start=excluded.pid_start,runtime_id=excluded.runtime_id,platform=excluded.platform,incarnation=excluded.incarnation,last_heartbeat=excluded.last_heartbeat,retired=0", (req["endpoint_id"],req["participant_id"],host,req["session"],req["pane"],req["pid"],str(req["pid_start"]),req["runtime_id"],req["platform"],inc,now))
        return {"endpoint_id": req["endpoint_id"], "incarnation": inc}

    def submit(self, req):
        host = self._auth(req); msg = req.get("message") or {}; sender = self._host_endpoint(host, msg.get("sender_endpoint"))
        mode = self._maintenance()
        if mode == "stopped": raise HubError("maintenance", "hub delivery is paused")
        body = msg.get("body", "")
        if not isinstance(body, str) or len(body.encode()) > MAX_BODY: raise HubError("invalid_message", "body exceeds 64 KiB")
        if any(ord(c) < 32 and c not in "\n\t" for c in body) or "\x7f" in body:
            raise HubError("invalid_message", "terminal control characters are forbidden")
        ttl = int(msg.get("ttl_sec", MAX_TTL));
        if ttl < 1 or ttl > MAX_TTL: raise HubError("invalid_message", "ttl exceeds 24 hours")
        mid, target = msg.get("message_id"), msg.get("target")
        if not mid or (not target and not msg.get("in_reply_to")): raise HubError("invalid_message", "message_id and target required")
        if mode == "probe" and mid not in set(self.config.get("probe_message_ids", [])): raise HubError("maintenance", "only configured probe messages are allowed")
        canonical = json.dumps({k: msg.get(k) for k in ("thread_id","in_reply_to","sender_endpoint","target","body","kind","ttl_sec")}, sort_keys=True, separators=(",",":"))
        ph = hashlib.sha256(canonical.encode()).hexdigest(); existing = self._row("SELECT * FROM messages WHERE message_id=?", (mid,))
        if existing:
            if existing["payload_hash"] != ph: raise HubError("id_conflict", "message ID has different payload")
            return {"message_id": mid, "state": existing["state"], "duplicate": True}
        if msg.get("sender_endpoint") != sender["endpoint_id"]: raise HubError("identity_rejected", "sender endpoint mismatch")
        if msg.get("in_reply_to"):
            original = self._row("SELECT * FROM messages WHERE message_id=?", (msg["in_reply_to"],))
            if not original or original["recipient_endpoint"] != sender["endpoint_id"]:
                raise HubError("identity_rejected", "reply sender is not original recipient")
            recipient = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (original["sender_endpoint"],))
            if recipient and recipient["retired"]:
                participant = self._row("SELECT * FROM participants WHERE participant_id=?", (recipient["participant_id"],))
                if participant and participant["project_id"] is None and participant["kind"] == "openclaw":
                    recipient = self._endpoint_for_send(participant)
            if not recipient or recipient["retired"]:
                raise HubError("no_recipient", "original sender endpoint is unavailable")
            target = self._row("SELECT address FROM participants WHERE participant_id=?", (recipient["participant_id"],))[0]
            if msg.get("thread_id") and msg["thread_id"] != original["thread_id"]:
                raise HubError("invalid_message", "reply thread must match original")
            msg = dict(msg, thread_id=original["thread_id"])
        else:
            target = self._address(target, sender["endpoint_id"])
            recipient = self._endpoint_for_send(self._participant(target))
        check_policy(self.db, sender["endpoint_id"], target, body, self._now(), msg.get("in_reply_to"))
        created = self._now(); expires = created + ttl
        self.db.execute("INSERT INTO messages(message_id,thread_id,in_reply_to,sender_endpoint,target_address,recipient_endpoint,body,kind,created_at,expires_at,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (mid,msg.get("thread_id") or mid,msg.get("in_reply_to"),sender["endpoint_id"],target,recipient["endpoint_id"],body,msg.get("kind","chat"),created,expires,ph))
        return {"message_id": mid, "state": "queued"}

    def inbox(self, req):
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        cursor = int(req.get("cursor") or 0)
        limit = min(max(int(req.get("limit", 100)), 1), 100)
        rows = self.db.execute("SELECT rowid AS sequence,* FROM messages WHERE recipient_endpoint=? AND rowid>? ORDER BY rowid LIMIT ?", (ep["endpoint_id"], cursor, limit)).fetchall()
        out = self.message_views(rows)
        return {"messages":out,"next_cursor":out[-1]["sequence"] if out else cursor}

    def message_views(self, rows):
        out = []
        size = 0
        for row in rows:
            item = dict(row)
            q = self._row("SELECT p.address FROM participants p JOIN endpoints e ON e.participant_id=p.participant_id WHERE e.endpoint_id=?", (item["sender_endpoint"],))
            item["sender_address"] = q[0] if q else None
            encoded = len(json.dumps(item, ensure_ascii=False).encode())
            if size + encoded > 200000: break
            out.append(item); size += encoded
        return out

    def claim(self, req):
        host=self._auth(req)
        if self._maintenance() == "stopped": raise HubError("maintenance", "hub delivery is paused")
        ep=self._host_endpoint(host,req.get("endpoint_id")); now=self._now()
        self._tx()
        try:
            limit=min(max(int(req.get("limit",100)),1),1000)
            rows=self.db.execute("SELECT * FROM messages WHERE recipient_endpoint=? AND expires_at>? AND state IN ('accepted','queued','adapter_received') ORDER BY created_at,message_id LIMIT ?",(ep["endpoint_id"],now,limit)).fetchall()
            if self._maintenance() == "probe": rows=[r for r in rows if r["message_id"] in set(self.config.get("probe_message_ids", []))]
            rows=self.message_views(rows)
            for r in rows: self.db.execute("UPDATE messages SET state='adapter_received',adapter_received_at=? WHERE message_id=?",(now,r["message_id"]))
            self._commit()
        except Exception:
            self._rollback(); raise
        return {"messages":rows}

    def receipt(self, req):
        host=self._auth(req); msg=self._row("SELECT * FROM messages WHERE message_id=?",(req.get("message_id"),));
        if not msg: raise HubError("not_found","message not found")
        ep=self._host_endpoint(host, req.get("endpoint_id"));
        if msg["recipient_endpoint"] != ep["endpoint_id"]: raise HubError("unauthorized","only recipient may receipt")
        state=req.get("state");
        if state not in ("presented","uncertain","stale_session","rejected"): raise HubError("invalid_receipt","invalid receipt state")
        current = msg["state"]
        if current == "presented" and state != "presented": raise HubError("invalid_receipt", "receipt state cannot move backwards")
        self._tx()
        try:
            self.db.execute("INSERT OR REPLACE INTO receipts(message_id,state,evidence,at) VALUES(?,?,?,?)",(msg["message_id"],state,req.get("evidence"),self._now())); self.db.execute("UPDATE messages SET state=? WHERE message_id=?",(state,msg["message_id"])); self._commit()
        except Exception: self._rollback(); raise
        return {"message_id":msg["message_id"],"state":state}

    def dispatch(self, req):
        op=req.get("op")
        if op == "directory_update":
            self._auth(req)
            if "expected_revision" not in req:
                raise HubError("revision_conflict", "expected revision required")
            return self.directory_import(dict(req, admin_token=self.admin_token))
        if op=="ping": return {"maintenance":self._maintenance(),"revision":int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])}
        if op=="directory_import": return self.directory_import(req)
        if op=="directory_list": self._auth(req); return self.directory_list()
        if op=="directory_resolve": self._auth(req); p=self._participant(req["address"]); return dict(p)
        if op=="endpoint_register": return self.register(req)
        if op=="endpoint_retire":
            host=self._auth(req); self._host_endpoint(host,req["endpoint_id"]); self.db.execute("UPDATE endpoints SET retired=1 WHERE endpoint_id=?",(req["endpoint_id"],)); self.db.execute("UPDATE messages SET state='stale_session' WHERE recipient_endpoint=? AND state IN ('accepted','queued','adapter_received')",(req["endpoint_id"],)); return {"retired":req["endpoint_id"]}
        if op=="endpoints_list": self._auth(req); return {"endpoints":[dict(x) for x in self.db.execute("SELECT * FROM endpoints WHERE host_id=?", (req.get("host_id"),))]}
        if op=="submit": return self.submit(req)
        if op=="inbox": return self.inbox(req)
        if op=="claim": return self.claim(req)
        if op=="receipt": return self.receipt(req)
        if op=="query":
            host=self._auth(req); m=self._row("SELECT * FROM messages WHERE message_id=?",(req.get("message_id"),));
            if not m: raise HubError("not_found","message not found")
            if m["expires_at"] <= self._now() and m["state"] in ("accepted","queued","adapter_received"):
                self.db.execute("UPDATE messages SET state='expired' WHERE message_id=?", (m["message_id"],)); m=self._row("SELECT * FROM messages WHERE message_id=?",(req.get("message_id"),))
            ep=self._host_endpoint(host,req.get("endpoint_id"));
            if ep["endpoint_id"] not in (m["sender_endpoint"],m["recipient_endpoint"]): raise HubError("unauthorized","not party to message")
            return dict(m)
        if op=="maintenance":
            self._auth(req,True); mode=req.get("mode");
            if mode not in ("stopped","probe","open"): raise HubError("invalid_maintenance","invalid mode")
            self.db.execute("UPDATE metadata SET value=? WHERE key='maintenance'",(mode,)); return {"maintenance":mode}
        raise HubError("unknown_op", "unknown operation")


def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--socket",required=True); ap.add_argument("--db",required=True); ap.add_argument("--config",required=True); args=ap.parse_args(argv)
    os.umask(0o077)
    lock = open(args.socket+".lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    Path(args.socket).parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try: os.unlink(args.socket)
    except FileNotFoundError: pass
    config = Hub._load_config(args.config)
    factory = Hub
    if config.get('host_id'):
        from federation import FederatedHub
        factory = FederatedHub
    s=socket.socket(socket.AF_UNIX); s.bind(args.socket); s.listen(16); os.chmod(args.socket,0o600)
    if factory is Hub:
        hub=Hub(args.db,config)
        try: serve_socket(s,hub.dispatch)
        finally: hub.close(); s.close()
    else:
        import threading
        def dispatch(req):
            instance=factory(args.db,args.config)
            try: return instance.dispatch(req)
            finally: instance.close()
        def retry_loop():
            while True:
                instance=None
                try:
                    instance=factory(args.db,args.config)
                    instance.tick()
                except (OSError, HubError, sqlite3.Error): pass
                finally:
                    if instance: instance.close()
                time.sleep(2)
        threading.Thread(target=retry_loop,daemon=True).start()
        try: serve_socket(s,dispatch,concurrent=True)
        finally: s.close()

if __name__ == "__main__": main()

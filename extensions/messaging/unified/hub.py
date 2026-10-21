"""Durable SQLite mailbox hub for the unified agent messaging contract."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import os
import secrets
import socket
import sqlite3
import stat
import time
from urllib.parse import quote
import uuid
from pathlib import Path
from typing import Any

try:
    from .protocol import HubError, MAX_REQUEST, MAX_TTL, serve_socket, success, resource_error
    from .policy import check_policy
    from .native_notice import content_digest
except ImportError:  # allow the installed single-file entrypoint to be invoked directly
    from protocol import HubError, MAX_REQUEST, MAX_TTL, serve_socket, success, resource_error
    from policy import check_policy
    from native_notice import content_digest


HUB_NATIVE_VERSION = 2

WAIT_REASONS = ('waiting_input', 'busy', 'draft_protected', 'endpoint_unavailable', 'adapter_error', 'auth_required',
                'native_queue_accepted', 'native_queue_pending', 'native_publication_unknown', 'native_retry_pending')
DIAGNOSTIC_REASONS = WAIT_REASONS + ('receipt_timeout', 'dispatch_error', 'adapter_interrupted')


def _receipt_reason(receipt):
    if not receipt: return None
    try: reason = json.loads(receipt['evidence']).get('delivery_reason')
    except (ValueError, TypeError, AttributeError): return None
    return reason if reason in DIAGNOSTIC_REASONS else None


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, alias TEXT NOT NULL UNIQUE, host_id TEXT NOT NULL, path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alias_history (alias TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS alias_redirect (alias TEXT PRIMARY KEY, successor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participants (participant_id TEXT PRIMARY KEY, project_id TEXT, address TEXT NOT NULL UNIQUE, host_id TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS endpoints (endpoint_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, host_id TEXT NOT NULL, session TEXT, pane TEXT, pid INTEGER, pid_start TEXT, runtime_id TEXT, platform TEXT, incarnation TEXT NOT NULL, last_heartbeat REAL NOT NULL, retired INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(participant_id) REFERENCES participants(participant_id));
CREATE TABLE IF NOT EXISTS endpoint_native (endpoint_id TEXT PRIMARY KEY, native_kind TEXT NOT NULL, native_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, in_reply_to TEXT, sender_endpoint TEXT NOT NULL, target_address TEXT NOT NULL, recipient_endpoint TEXT, body TEXT NOT NULL, kind TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, payload_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'accepted', adapter_received_at REAL, UNIQUE(message_id));
CREATE TABLE IF NOT EXISTS receipts (message_id TEXT PRIMARY KEY, state TEXT NOT NULL, evidence TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS native_delivery_owners (message_id TEXT PRIMARY KEY REFERENCES messages(message_id), original_recipient TEXT NOT NULL, actor_endpoint TEXT NOT NULL, actor_incarnation TEXT NOT NULL, content_hash TEXT NOT NULL, generation INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS message_recipient ON messages(recipient_endpoint, state, expires_at);
"""


class Hub:
    def __init__(self, db_path: str | os.PathLike, config: dict | str | os.PathLike | None = None,
                 read_only: bool = False):
        self.db_path = str(db_path)
        self.read_only = bool(read_only)
        self.config = self._load_config(config)
        self.host_tokens = self.config.get("hosts", {})
        self.admin_token = self.config.get("admin_token")
        try:
            if self.read_only:
                self.db = sqlite3.connect('file:' + quote(self.db_path, safe='/') + '?mode=ro', uri=True,
                                          isolation_level=None, check_same_thread=False)
            else:
                self.db = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        except (OSError, sqlite3.Error) as exc:
            classified = resource_error(exc, 'authority_persistence')
            if classified:
                raise classified from None
            raise HubError('unavailable', 'local messaging storage is unavailable') from None
        self.db.row_factory = sqlite3.Row
        if not self.read_only:
            try:
                self.db.executescript(SCHEMA)
                self.db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('directory_revision','0')")
                self.db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('maintenance','open')")
            except (OSError, sqlite3.Error) as exc:
                classified = resource_error(exc, 'authority_persistence')
                if classified:
                    raise classified from None
                raise HubError('unavailable', 'local messaging storage is unavailable') from None

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
        if not p or self._row("SELECT 1 FROM alias_redirect WHERE alias=?", (base,)): raise HubError("unknown_target", "unknown project")
        return p, role
    def _redirect_target(self, target):
        """Map a retired project alias to the alias that replaced it (one hop), or None."""
        base, dot, role = target.rpartition(".")
        if not dot or role not in ("cc", "cdx"): return None
        r = self._row("SELECT successor FROM alias_redirect WHERE alias=?", (base,))
        return r[0] + "." + role if r else None
    def _submit_redirected(self, req):
        msg = req.get("message") or {}; target = msg.get("target")
        new = self._redirect_target(target) if isinstance(target, str) and target else None
        if not new: return self.submit(req)
        # Rewrite before hashing so a retry of the same ID with the old name stays the same message.
        out = self.submit(dict(req, message=dict(msg, target=new)))
        return dict(out, renamed_from=target, renamed_to=new) if isinstance(out, dict) else out
    def directory_retire(self, req):
        """Owner-side retirement of a local project alias that now lives elsewhere under `successor`."""
        self._auth(req, True); alias, successor = str(req.get("alias") or ""), str(req.get("successor") or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", successor) or successor == alias: raise HubError("invalid_request", "valid successor alias required")
        p = self._row("SELECT * FROM projects WHERE alias=?", (alias,))
        if not p or p["host_id"] != self.config.get("host_id"): raise HubError("unknown_target", "alias is not a local project")
        if self._row("SELECT 1 FROM alias_redirect WHERE alias=? OR alias=?", (alias, successor)): raise HubError("directory_conflict", "alias already retired or successor is retired")
        now = self._now()
        if self._row("SELECT 1 FROM endpoints e JOIN participants x ON x.participant_id=e.participant_id WHERE x.project_id=? AND e.retired=0 AND ?-e.last_heartbeat<=30", (p["project_id"], now)):
            raise HubError("project_in_use", "project has a live endpoint")
        self._tx()
        try:
            self.db.execute("INSERT OR IGNORE INTO alias_history(alias) VALUES(?)", (alias,))
            self.db.execute("INSERT INTO alias_redirect(alias,successor) VALUES(?,?)", (alias, successor))
            self.db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='directory_revision'")
            self._commit()
        except Exception: self._rollback(); raise
        return {"retired": alias, "successor": successor}
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
        if self._now() - rows[0]["last_heartbeat"] > 30:
            # A missed heartbeat is not proof of death. Refuse new delivery until
            # the owner refreshes evidence; do not retire an otherwise live agent.
            raise HubError("endpoint_unavailable", "target liveness needs owner refresh")
        return rows[0]
    def _host_endpoint(self, host, endpoint_id):
        e = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (endpoint_id,))
        if not e or e["host_id"] != host: raise HubError("identity_rejected", "endpoint is not owned by host")
        if e["retired"]: raise HubError("stale_session", "endpoint is retired")
        return e
    def attest_native(self, req):
        """Persist only owner-host authenticated native conversation evidence."""
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        kind, native = req.get("native_kind"), req.get("native_id")
        if ep["platform"] not in ("cc", "cdx") or kind not in ("thread_id", "session_id") or not isinstance(native, str) or not native:
            raise HubError("identity_rejected", "authenticated native identity required")
        old = self._row("SELECT * FROM endpoint_native WHERE endpoint_id=?", (ep["endpoint_id"],))
        if old and (old["native_kind"] != kind or old["native_id"] != native):
            raise HubError("identity_rejected", "endpoint native identity is immutable")
        self.db.execute("INSERT OR IGNORE INTO endpoint_native VALUES(?,?,?)", (ep["endpoint_id"], kind, native))
        return {"endpoint_id": ep["endpoint_id"]}

    def _handoff_native_delivery(self, req, *, dead_owner):
        """Private transaction core; NOT exposed by dispatch or called by Host.

        dead_owner must come from the trusted owner Host's independent PID/start
        observation, never a peer body/public caller flag. Caller integration is
        deliberately withheld until that proof and local consumer fencing exist.
        Original message rows, notice tokens and content digests stay immutable.
        """
        host = self._auth(req)
        self._tx()
        try:
            old = self._row('SELECT * FROM endpoints WHERE endpoint_id=?', (req.get('old_endpoint'),))
            new = self._host_endpoint(host, req.get('new_endpoint'))
            if (not old or old['host_id'] != host or old['endpoint_id'] == new['endpoint_id']
                    or any(old[k] != new[k] for k in ('participant_id', 'platform'))
                    or new['platform'] != 'cdx' or self._now() - new['last_heartbeat'] > 30
                    or req.get('old_incarnation') != old['incarnation']
                    or req.get('new_incarnation') != new['incarnation']):
                raise HubError('identity_rejected', 'handoff endpoint continuity mismatch')
            markers = [self._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (ep['endpoint_id'],))
                       for ep in (old, new)]
            if (not all(markers) or any(markers[0][k] != markers[1][k] for k in ('native_kind', 'native_id'))
                    or any(req.get(k) != markers[1][k] for k in ('native_kind', 'native_id'))):
                raise HubError('identity_rejected', 'handoff requires independent matching native attestations')
            identity = {key: req.get(key) for key in ('old_endpoint', 'new_endpoint', 'old_incarnation',
                                                       'new_incarnation', 'native_kind', 'native_id')}
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            key = 'native_handoff:' + hashlib.sha256(json.dumps([old['endpoint_id'], old['incarnation']]).encode()).hexdigest()
            prior = self._row('SELECT value FROM metadata WHERE key=?', (key,))
            if prior:
                saved = json.loads(prior[0])
                if saved['digest'] != digest:
                    raise HubError('handoff_conflict', 'old incarnation already handed off elsewhere')
                self._commit()
                return dict(saved['result'], duplicate=True)
            if old['retired']:
                raise HubError('stale_session', 'historical retired originals cannot be revived')
            if (not isinstance(dead_owner, dict)
                    or any(str(dead_owner.get(k)) != str(old[k]) for k in ('endpoint_id', 'incarnation', 'pid', 'pid_start'))
                    or dead_owner.get('reason') not in ('pid_absent', 'pid_start_changed')
                    or (dead_owner['reason'] == 'pid_start_changed'
                        and (dead_owner.get('observed_pid_start') is None
                             or str(dead_owner['observed_pid_start']) == str(old['pid_start'])))):
                raise HubError('identity_rejected', 'independent dead-owner incarnation evidence required')
            others = self._row('SELECT 1 FROM endpoints WHERE participant_id=? AND retired=0 AND endpoint_id NOT IN (?,?) LIMIT 1',
                               (old['participant_id'], old['endpoint_id'], new['endpoint_id']))
            if others:
                raise HubError('ambiguous_target', 'another live owner prevents handoff')
            # Read the effective current actor, never rewrite original recipient.
            rows = self.db.execute("SELECT m.*,o.generation AS owner_generation FROM messages m LEFT JOIN native_delivery_owners o ON o.message_id=m.message_id WHERE COALESCE(o.actor_endpoint,m.recipient_endpoint)=? AND (o.message_id IS NULL OR o.actor_incarnation=?) AND m.state IN ('accepted','queued','adapter_received') AND m.expires_at>? AND NOT EXISTS (SELECT 1 FROM messages r JOIN endpoints re ON re.endpoint_id=r.sender_endpoint JOIN endpoint_native rn ON rn.endpoint_id=re.endpoint_id WHERE r.in_reply_to=m.message_id AND r.thread_id=m.thread_id AND (r.sender_endpoint=m.recipient_endpoint OR (re.participant_id=? AND re.host_id=? AND re.platform='cdx' AND rn.native_kind=? AND rn.native_id=?)))",
                                   (old['endpoint_id'], old['incarnation'], self._now(), old['participant_id'], host,
                                    markers[1]['native_kind'], markers[1]['native_id']))
            # Finish reading the actor join before changing it. Retain only
            # bounded-per-row metadata, not another copy of every message body.
            grants = [(row['message_id'], row['recipient_endpoint'], new['endpoint_id'], new['incarnation'],
                       content_digest(dict(row)), (row['owner_generation'] or 0) + 1) for row in rows]
            for grant in grants:
                self.db.execute('INSERT INTO native_delivery_owners VALUES(?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET actor_endpoint=excluded.actor_endpoint,actor_incarnation=excluded.actor_incarnation,generation=excluded.generation', grant)
            count = len(grants)
            # Late old native_begin_present/receipt recheck retirement while
            # holding this same SQLite write lock, so cannot use an old claim.
            self.db.execute('UPDATE endpoints SET retired=1 WHERE endpoint_id=? AND incarnation=?',
                            (old['endpoint_id'], old['incarnation']))
            result = dict(transferred=count, old_endpoint=old['endpoint_id'], new_endpoint=new['endpoint_id'])
            self.db.execute('INSERT INTO metadata(key,value) VALUES(?,?)',
                            (key, json.dumps(dict(digest=digest, result=result), sort_keys=True)))
            self._commit()
            return result
        except Exception:
            self._rollback()
            raise

    def _same_native_party(self, current, historical_id):
        if current["endpoint_id"] == historical_id:
            return True
        old = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (historical_id,))
        if not old or not old["retired"] or any(old[k] != current[k] for k in ("host_id", "participant_id", "platform")):
            return False
        native = self._row("SELECT * FROM endpoint_native WHERE endpoint_id=?", (historical_id,))
        other = self._row("SELECT * FROM endpoint_native WHERE endpoint_id=?", (current["endpoint_id"],))
        if not native or not other or any(native[k] != other[k] for k in ("native_kind", "native_id")):
            return False
        participant = self._row("SELECT * FROM participants WHERE participant_id=?", (current["participant_id"],))
        try:
            return self._endpoint_for_send(participant)["endpoint_id"] == current["endpoint_id"]
        except HubError:
            return False

    def _reply_endpoint(self, historical_id):
        old = self._row("SELECT * FROM endpoints WHERE endpoint_id=?", (historical_id,))
        if not old or not old["retired"]:
            return old
        participant = self._row("SELECT * FROM participants WHERE participant_id=?", (old["participant_id"],))
        if not participant:
            return None
        if participant["project_id"] is None and participant["kind"] == "openclaw":
            return self._endpoint_for_send(participant)
        current = self._endpoint_for_send(participant)
        return current if self._same_native_party(current, historical_id) else None

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
            d=dict(x); eps=[dict(e) for e in self.db.execute("SELECT endpoint_id,host_id,incarnation,last_heartbeat,retired FROM endpoints WHERE participant_id=? AND retired=0",(x["participant_id"],))]; d["endpoints"]=eps; d["online"]=any(not e["retired"] and now-e["last_heartbeat"] <= 30 for e in eps); participants.append(d)
        retired = {r[0] for r in self.db.execute("SELECT alias FROM alias_redirect")}
        projects = [dict(x) for x in self.db.execute("SELECT * FROM projects") if x["alias"] not in retired]
        live = {x["project_id"] for x in projects}; participants = [x for x in participants if x["project_id"] is None or x["project_id"] in live]
        return {"revision": int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0]), "projects": projects, "participants": participants, "services": [x for x in participants if x["project_id"] is None]}
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
        if not isinstance(body, str): raise HubError("invalid_message", "body must be text")
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
            if not original or not self._same_native_party(sender, original["recipient_endpoint"]):
                raise HubError("identity_rejected", "reply sender is not original recipient")
            recipient = self._reply_endpoint(original["sender_endpoint"])
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
        out = self.message_views(rows, response_kind="inbox")
        result = {"messages":out,"next_cursor":out[-1]["sequence"] if out else cursor}
        self._check_message_response(result)
        return result

    def inbox_notice(self, req):
        """Read-only metadata for a native PostToolUse inbox notice.

        This deliberately does not claim, consume, present, or acknowledge any
        message.  The caller's endpoint is authenticated by the host and only
        the canonical sender address plus a bounded set of message IDs leave
        the hub.
        """
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        limit = min(max(int(req.get("limit", 3)), 1), 3)
        try:
            cursor = int(req.get("cursor") or 0)
        except (TypeError, ValueError):
            cursor = 0
        cursor = max(cursor, 0)
        rows = self.db.execute(
            "SELECT m.rowid AS sequence, m.message_id, m.state, m.kind, m.created_at, "
            "p.address AS sender_address "
            "FROM messages m JOIN endpoints e ON e.endpoint_id=m.sender_endpoint "
            "JOIN participants p ON p.participant_id=e.participant_id "
            "WHERE m.recipient_endpoint=? AND m.rowid>? "
            "AND m.state IN ('accepted','queued','adapter_received','dispatching','uncertain') "
            "AND NOT EXISTS (SELECT 1 FROM messages reply "
            "WHERE reply.in_reply_to=m.message_id "
            "AND reply.sender_endpoint=m.recipient_endpoint "
            "AND reply.recipient_endpoint=m.sender_endpoint) "
            "AND m.expires_at>? ORDER BY m.rowid LIMIT ?",
            (ep["endpoint_id"], cursor, self._now(), limit),
        ).fetchall()
        return {"messages": [dict(row) for row in rows],
                "next_cursor": rows[-1]["sequence"] if rows else cursor}

    def outbox(self, req):
        """Messages this participant sent that have not reached a final state.

        Metadata only (no body). Covers every endpoint incarnation of the sender so a
        restart does not hide earlier sends. The state shown is this hub's copy: for a
        recipient on another host the owning host holds the truth.
        """
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        now = self._now(); limit = min(max(int(req.get("limit", 200)), 1), 500)
        rows = self.db.execute(
            "SELECT m.message_id, m.target_address, m.state, m.created_at, m.expires_at, "
            "e.host_id AS recipient_host_id, p.kind AS recipient_kind "
            "FROM messages m "
            "LEFT JOIN endpoints e ON e.endpoint_id=m.recipient_endpoint "
            "LEFT JOIN participants p ON p.participant_id=e.participant_id "
            "WHERE m.sender_endpoint IN (SELECT endpoint_id FROM endpoints WHERE participant_id=?) "
            "AND m.expires_at>? AND m.created_at>? "
            "AND m.state IN ('accepted','queued','adapter_received','dispatching','uncertain') "
            "ORDER BY m.created_at LIMIT ?",
            (ep["participant_id"], now, now - 7 * 86400, limit)).fetchall()
        return {"messages": [dict(r) for r in rows], "now": now}

    def _check_message_response(self, result):
        # The host uses default JSON separators; this also bounds the smaller
        # compact hub frame. Include the success envelope and trailing newline.
        if len((json.dumps(success(result), ensure_ascii=False) + "\n").encode()) > MAX_REQUEST:
            raise HubError("response_too_large", "message response exceeds wire limit")

    def message_views(self, rows, response_kind="messages"):
        out = []
        size = 0
        for row in rows:
            item = dict(row)
            owner = self._row('SELECT o.*,n.native_kind,n.native_id FROM native_delivery_owners o JOIN endpoint_native n ON n.endpoint_id=o.actor_endpoint WHERE o.message_id=?', (item['message_id'],))
            if owner:
                item['delivery_actor'] = dict(endpoint_id=owner['actor_endpoint'], incarnation=owner['actor_incarnation'],
                    native_kind=owner['native_kind'], native_id=owner['native_id'], generation=owner['generation'],
                    original_recipient=owner['original_recipient'], content_hash=owner['content_hash'])
            q = self._row("SELECT p.address FROM participants p JOIN endpoints e ON e.participant_id=p.participant_id WHERE e.endpoint_id=?", (item["sender_endpoint"],))
            item["sender_address"] = q[0] if q else None
            encoded = len(json.dumps(item, ensure_ascii=False).encode())
            if size + encoded > 200000:
                if out: break
                result = item if response_kind == "query" else {"messages": [item]}
                if response_kind == "inbox": result["next_cursor"] = item["sequence"]
                self._check_message_response(result)
                out.append(item)
                break
            out.append(item); size += encoded
        return out

    def _delivery_actor(self, msg, ep, *, native=False):
        """Validate current delivery right without changing immutable origin."""
        owner = self._row('SELECT * FROM native_delivery_owners WHERE message_id=?', (msg['message_id'],))
        if owner:
            if (owner['original_recipient'] != msg['recipient_endpoint']
                    or owner['actor_endpoint'] != ep['endpoint_id']
                    or owner['actor_incarnation'] != ep['incarnation']
                    or owner['content_hash'] != content_digest(dict(msg))):
                raise HubError('identity_rejected', 'current native delivery owner mismatch')
            if not native:
                raise HubError('identity_rejected', 'transferred originals require native presentation')
        elif msg['recipient_endpoint'] != ep['endpoint_id']:
            raise HubError('unauthorized', 'only current recipient may present')
        return owner

    def _actor_reservation(self, msg, ep, owner, req):
        marker = self._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (ep['endpoint_id'],))
        if (not marker or ep['platform'] != 'cdx'
                or req.get('incarnation') != ep['incarnation']
                or any(req.get(k) != marker[k] for k in ('native_kind', 'native_id'))):
            raise HubError('identity_rejected', 'transferred receipt requires current native binding')
        value = dict(endpoint_id=ep['endpoint_id'], incarnation=ep['incarnation'],
                     native_kind=marker['native_kind'], native_id=marker['native_id'],
                     content_hash=owner['content_hash'], generation=owner['generation'])
        key = 'native_actor_reserved:' + hashlib.sha256(msg['message_id'].encode()).hexdigest()
        return key, json.dumps(value, sort_keys=True)

    def native_pending(self, req, *, drain=False):
        """Coalesced wake generation derived atomically from existing mailbox rows.

        No second queue: insertion rowid is the pending sequence. A drain is
        notification bookkeeping, never body consumption or work completion.
        """
        host = self._auth(req)
        expected = req.get('generation')
        if drain and (type(expected) is not int or not 0 <= expected <= 9223372036854775807):
            raise HubError('invalid_request', 'invalid pending generation')
        self._tx()
        try:
            ep = self._host_endpoint(host, req.get('endpoint_id'))
            marker = self._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (ep['endpoint_id'],))
            if (not marker or ep['platform'] not in ('cdx', 'cc')
                    or req.get('incarnation') != ep['incarnation']
                    or req.get('native_kind') != marker['native_kind']
                    or req.get('native_id') != marker['native_id']):
                raise HubError('identity_rejected', 'pending native binding mismatch')
            generation = self._row('SELECT COALESCE(MAX(m.rowid),0) FROM messages m LEFT JOIN native_delivery_owners o ON o.message_id=m.message_id WHERE COALESCE(o.actor_endpoint,m.recipient_endpoint)=? AND (o.message_id IS NULL OR o.actor_incarnation=?)',
                                   (ep['endpoint_id'], ep['incarnation']))[0]
            now = self._now()
            oldest = self._row("SELECT MIN(m.created_at) FROM messages m LEFT JOIN native_delivery_owners o ON o.message_id=m.message_id WHERE COALESCE(o.actor_endpoint,m.recipient_endpoint)=? AND (o.message_id IS NULL OR o.actor_incarnation=?) AND expires_at>? AND state IN ('accepted','queued','adapter_received') AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.in_reply_to=m.message_id AND r.sender_endpoint=COALESCE(o.actor_endpoint,m.recipient_endpoint))",
                               (ep['endpoint_id'], ep['incarnation'], now))[0]
            pending = oldest is not None
            key = 'native_drained:' + ep['endpoint_id']
            saved = self._row('SELECT value FROM metadata WHERE key=?', (key,))
            drained_generation = int(saved[0]) if saved else 0
            cleared = False
            # BEGIN IMMEDIATE serializes this comparison with insert. New arrival
            # after the empty snapshot cannot be cleared by the older generation.
            if drain and expected == generation and not pending:
                self.db.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                (key, str(generation)))
                drained_generation = generation
                cleared = True
            result = dict(generation=generation, drained_generation=drained_generation,
                          pending=pending, wake_needed=pending,
                          oldest_pending_age_seconds=max(0.0, now - oldest) if pending else None)
            if drain: result['cleared'] = cleared
            self._commit()
            return result
        except Exception:
            self._rollback()
            raise

    def claim(self, req):
        host=self._auth(req)
        if self._maintenance() == "stopped": raise HubError("maintenance", "hub delivery is paused")
        now=self._now()
        after = req.get('after_sequence')
        if after is not None and (type(after) is not int or after < 0 or after > 9223372036854775807):
            raise HubError('invalid_request', 'invalid claim sequence')
        self._tx()
        try:
            ep=self._host_endpoint(host,req.get("endpoint_id"))
            limit=min(max(int(req.get("limit",100)),1),1000)
            # Optional keyset scan on the existing immutable insertion sequence.
            # Default callers retain their historical created-at ordering.
            boundary = ' AND m.rowid>?' if after is not None else ''
            order = 'm.rowid' if after is not None else 'm.created_at,m.message_id'
            params = (ep['endpoint_id'], ep['incarnation'], now) + ((after,) if after is not None else ()) + (limit,)
            rows=self.db.execute("SELECT m.rowid AS sequence,m.* FROM messages m LEFT JOIN native_delivery_owners o ON o.message_id=m.message_id WHERE COALESCE(o.actor_endpoint,m.recipient_endpoint)=? AND (o.message_id IS NULL OR o.actor_incarnation=?) AND m.expires_at>? AND m.state IN ('accepted','queued','adapter_received') AND NOT EXISTS (SELECT 1 FROM messages reply WHERE reply.in_reply_to=m.message_id AND reply.sender_endpoint=COALESCE(o.actor_endpoint,m.recipient_endpoint))" + boundary + " ORDER BY " + order + " LIMIT ?", params).fetchall()
            scanned_sequence = rows[-1]['sequence'] if rows else 0
            if self._maintenance() == "probe": rows=[r for r in rows if r["message_id"] in set(self.config.get("probe_message_ids", []))]
            rows=self.message_views(rows)
            for r in rows: self.db.execute("UPDATE messages SET state='adapter_received',adapter_received_at=? WHERE message_id=?",(now,r["message_id"]))
            self._commit()
        except Exception:
            self._rollback(); raise
        result = {"messages": rows}
        if after is not None:
            result['next_sequence'] = rows[-1]['sequence'] if rows else scanned_sequence
        return result

    def receipt(self, req):
        """Serialize receipt state and owner validation with cancel/retirement."""
        host = self._auth(req)
        state = req.get("state")
        if state not in ("presented", "uncertain", "stale_session", "rejected"):
            raise HubError("invalid_receipt", "invalid receipt state")
        self._tx()
        try:
            msg = self._row("SELECT * FROM messages WHERE message_id=?", (req.get("message_id"),))
            if not msg:
                raise HubError("not_found", "message not found")
            ep = self._host_endpoint(host, req.get("endpoint_id"))
            owner = self._delivery_actor(msg, ep, native=True)
            if owner:
                key, expected = self._actor_reservation(msg, ep, owner, req)
                saved = self._row('SELECT value FROM metadata WHERE key=?', (key,))
                if state == 'presented' and (not saved or saved[0] != expected):
                    raise HubError('invalid_receipt', 'transferred presentation requires native reservation')
            current = msg["state"]
            if current in ("cancelled", "expired", "stale_session", "rejected"):
                if state != current:
                    raise HubError("terminal_message", "terminal message cannot be presented")
                self._commit()
                return {"message_id": msg["message_id"], "state": current}
            if current == "presented" and state != "presented":
                raise HubError("invalid_receipt", "receipt state cannot move backwards")
            self.db.execute("INSERT OR REPLACE INTO receipts(message_id,state,evidence,at) VALUES(?,?,?,?)",
                            (msg["message_id"], state, req.get("evidence"), self._now()))
            self.db.execute("UPDATE messages SET state=? WHERE message_id=?", (state, msg["message_id"]))
            self._commit()
            return {"message_id": msg["message_id"], "state": state}
        except Exception:
            self._rollback()
            raise

    def begin_present(self, req, *, native=False):
        """Serialize irreversible adapter presentation against sender cancellation."""
        host = self._auth(req)
        self._tx()
        try:
            ep = self._host_endpoint(host, req.get("endpoint_id"))
            msg = self._row("SELECT * FROM messages WHERE message_id=?", (req.get("message_id"),))
            if not msg: raise HubError("not_found", "message not found")
            owner = self._delivery_actor(msg, ep, native=native)
            if native:
                marker = self._row("SELECT * FROM endpoint_native WHERE endpoint_id=?", (ep["endpoint_id"],))
                if (ep["platform"] != "cdx" or not marker
                        or any(not isinstance(req.get(k), str) or not req[k]
                               for k in ("incarnation", "native_kind", "native_id", "content_hash"))
                        or req["incarnation"] != ep["incarnation"]
                        or req["native_kind"] != marker["native_kind"]
                        or req["native_id"] != marker["native_id"]
                        or req["content_hash"] != content_digest(dict(msg))):
                    raise HubError("identity_rejected", "native presentation binding or content mismatch")
                mode = self._maintenance()
                if mode == "stopped" or (mode == "probe" and msg["message_id"] not in set(self.config.get("probe_message_ids", []))):
                    raise HubError("maintenance", "native presentation is paused")
            if msg["state"] not in ("accepted", "queued", "adapter_received"):
                raise HubError("presentation_unavailable", "message is terminal or presentation has already begun")
            if msg["expires_at"] <= self._now():
                raise HubError("expired", "message expired before presentation")
            if self._row("SELECT 1 FROM messages WHERE in_reply_to=? AND sender_endpoint IN (?,?) LIMIT 1", (msg["message_id"], msg["recipient_endpoint"], ep["endpoint_id"])):
                raise HubError("presentation_unavailable", "recipient already replied to message")
            self.db.execute("UPDATE messages SET state='dispatching' WHERE message_id=?", (msg["message_id"],))
            if native and owner:
                key, value = self._actor_reservation(msg, ep, owner, req)
                self.db.execute('INSERT INTO metadata(key,value) VALUES(?,?)', (key, value))
            self._commit()
            result = {"message_id": msg["message_id"], "state": "dispatching"}
            if native:
                result.update(content_hash=req["content_hash"], endpoint_id=ep["endpoint_id"],
                              incarnation=ep["incarnation"], native_kind=marker["native_kind"], native_id=marker["native_id"])
            return result
        except Exception:
            self._rollback(); raise

    def cancel(self, req):
        """Cancel only before presentation starts; cancellation never stops a task."""
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        self._tx()
        try:
            msg = self._row("SELECT * FROM messages WHERE message_id=?", (req.get("message_id"),))
            if not msg: raise HubError("not_found", "message not found")
            if msg["sender_endpoint"] != ep["endpoint_id"]:
                raise HubError("unauthorized", "only original sender may cancel")
            if msg["state"] not in ("accepted", "queued", "adapter_received", "cancelled"):
                raise HubError("too_late", "presentation started or message is terminal; execution is not cancelled")
            self.db.execute("UPDATE messages SET state='cancelled' WHERE message_id=?", (msg["message_id"],))
            self._commit()
            return {"message_id": msg["message_id"], "state": "cancelled"}
        except Exception:
            self._rollback(); raise

    def delivery_status(self, req):
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get("endpoint_id"))
        msg = self._row("SELECT * FROM messages WHERE message_id=?", (req.get("message_id"),))
        if not msg: raise HubError("not_found", "message not found")
        if msg["recipient_endpoint"] != ep["endpoint_id"]:
            raise HubError("unauthorized", "only recipient may report delivery status")
        reason = req.get("reason")
        if reason not in WAIT_REASONS:
            raise HubError("invalid_status", "invalid delivery reason")
        if msg["state"] not in ("accepted", "queued", "adapter_received"):
            return {"message_id": msg["message_id"], "state": msg["state"]}
        evidence = dict(delivery_reason=reason, endpoint_id=ep['endpoint_id'], incarnation=ep['incarnation'])
        native = req.get('native_observation')
        if reason.startswith('native_'):
            marker = self._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (ep['endpoint_id'],))
            if (not isinstance(native, dict) or not marker
                    or native.get('incarnation') != ep['incarnation']
                    or any(native.get(k) != marker[k] for k in ('native_kind', 'native_id'))
                    or any(not isinstance(native.get(k), str) or not 1 <= len(native[k]) <= 128
                           for k in ('attempt', 'generation'))):
                raise HubError('identity_rejected', 'native diagnostic binding mismatch')
            evidence['native_observation'] = {k: native[k] for k in
                ('incarnation', 'native_kind', 'native_id', 'attempt', 'generation')}
        self.db.execute("INSERT OR REPLACE INTO receipts(message_id,state,evidence,at) VALUES(?,?,?,?)",
                        (msg["message_id"], msg["state"], json.dumps(evidence), self._now()))
        return {"message_id": msg["message_id"], "state": msg["state"], "delivery_reason": reason}

    def response_evidence(self, message):
        # A linked row alone is not proof of a response by the pinned recipient.
        args = (message['message_id'], message['recipient_endpoint'],
                message['sender_endpoint'], message['thread_id'])
        where = 'in_reply_to=? AND sender_endpoint=? AND recipient_endpoint=? AND thread_id=?'
        count = self._row('SELECT COUNT(*) AS n FROM messages WHERE ' + where, args)['n']
        ids = [row['message_id'] for row in self.db.execute(
            'SELECT message_id FROM messages WHERE ' + where + ' ORDER BY created_at,message_id LIMIT 20', args)]
        return {'recipient_reply_count': count, 'recipient_reply_message_ids': ids,
                'response_state': 'recipient_replied' if count else 'unconfirmed'}

    def delivery_summary(self, message, response):
        """Read-only lifecycle projection; never rewrite uncertain delivery effects."""
        state = message['state']
        now = self._now()
        elapsed = message['expires_at'] <= now
        receipt = self._row('SELECT state,evidence,at FROM receipts WHERE message_id=?', (message['message_id'],))
        endpoint = self._row('SELECT retired,incarnation FROM endpoints WHERE endpoint_id=?', (message['recipient_endpoint'],))
        presented = state == 'presented' or bool(receipt and receipt['state'] == 'presented')
        replied = response['response_state'] == 'recipient_replied'
        terminal = state in ('cancelled', 'expired', 'rejected', 'stale_session')
        lifecycle = state if terminal else ('ttl_elapsed' if elapsed else 'active')
        eligible = bool(endpoint and not endpoint['retired'] and not elapsed
                        and state in ('accepted', 'queued', 'adapter_received')
                        and not presented and not replied)
        if terminal:
            status, reason = 'action_required', state + ('_with_reply' if replied else '')
        elif replied:
            status, reason = 'recipient_replied', 'ttl_elapsed_with_reply' if elapsed else 'recipient_replied'
        elif presented:
            status, reason = 'presentation_confirmed', 'receipt_confirmed'
        elif elapsed:
            status = 'action_required'
            reason = ('ttl_elapsed_outcome_unknown' if state in ('dispatching', 'uncertain')
                      else 'ttl_elapsed_before_presentation')
        elif not endpoint or endpoint['retired']:
            status, reason = 'action_required', 'pinned_recipient_unavailable'
        elif state == 'uncertain':
            status, reason = 'action_required', 'presentation_outcome_unknown'
        else:
            status, reason = 'waiting', 'presentation_in_progress' if state == 'dispatching' else 'pending'
        observed_at = None
        if status == 'waiting' and receipt and receipt['state'] == state and receipt['at'] <= now:
            observed = _receipt_reason(receipt)
            try: evidence = json.loads(receipt['evidence'])
            except (ValueError, TypeError): evidence = {}
            bound = (isinstance(evidence, dict) and endpoint
                     and evidence.get('endpoint_id') == message['recipient_endpoint']
                     and evidence.get('incarnation') == endpoint['incarnation'])
            if bound and observed and observed.startswith('native_'):
                marker = self._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (message['recipient_endpoint'],))
                native = evidence.get('native_observation')
                bound = bool(marker and isinstance(native, dict)
                             and native.get('incarnation') == endpoint['incarnation']
                             and all(native.get(k) == marker[k] for k in ('native_kind', 'native_id')))
            if bound and observed in WAIT_REASONS:
                reason, observed_at = observed, receipt['at']
        return {'status': status, 'lifecycle': lifecycle, 'reason': reason,
                'pending_age_seconds': max(0.0, now - message['created_at']) if status == 'waiting' else None,
                'reason_observed_at': observed_at,
                'ttl_elapsed': elapsed, 'presentation_confirmed': presented,
                'new_presentation_eligible': eligible}

    def diagnose(self, req, authenticated_party=None):
        host=self._auth(req)
        try:
            message=self._row('SELECT rowid AS sequence,message_id,thread_id,state,sender_endpoint,recipient_endpoint,created_at,expires_at,adapter_received_at FROM messages WHERE message_id=?',(req.get('message_id'),))
        except (OSError, sqlite3.Error) as exc:
            classified = resource_error(exc, 'outcome_query')
            if classified: raise classified from None
            raise HubError('unavailable', 'delivery metadata unavailable') from None
        if not message:raise HubError('not_found','message not found')
        operator=req.get('operator_diagnostic') is True and host in self.config.get('diagnostic_hosts',[])
        if authenticated_party is not None:
            if (authenticated_party['host_id'] != host or authenticated_party['endpoint_id'] not in
                    (message['sender_endpoint'], message['recipient_endpoint'])):
                raise HubError('unauthorized', 'diagnostic proof is not a pinned party')
        elif not operator:
            ep=self._host_endpoint(host,req.get('endpoint_id'))
            if not any(self._same_native_party(ep, party) for party in (message['sender_endpoint'], message['recipient_endpoint'])):
                raise HubError('unauthorized','delivery metadata requires party or configured operator permission')
        result=dict(message)
        response = self.response_evidence(message)
        result.update(response)
        result['delivery_summary'] = self.delivery_summary(message, response)
        result['diagnostic_host_id']=self.config.get('host_id',host)
        receipt=self._row('SELECT state,evidence,at FROM receipts WHERE message_id=?',(message['message_id'],))
        result['presentation_confirmed']=message['state']=='presented' or bool(receipt and receipt['state']=='presented')
        result['receipt_at']=receipt['at'] if receipt else None
        result['receipt_state']=receipt['state'] if receipt else None
        result['reply_count']=self._row('SELECT COUNT(*) AS n FROM messages WHERE in_reply_to=?', (message['message_id'],))['n']
        result['reply_message_ids']=[row['message_id'] for row in self.db.execute(
            'SELECT message_id FROM messages WHERE in_reply_to=? ORDER BY created_at,message_id LIMIT 20',
            (message['message_id'],))]
        result['delivery_reason'] = _receipt_reason(receipt)
        if result['delivery_reason'] is not None:
            result['delivery_checked_at'] = receipt['at']
        endpoint=self._row('SELECT host_id,retired,last_heartbeat FROM endpoints WHERE endpoint_id=?',(message['recipient_endpoint'],))
        result['recipient_host_id']=endpoint['host_id'] if endpoint else None
        result['recipient_retired']=bool(endpoint['retired']) if endpoint else None
        result['recipient_online']=bool(endpoint and not endpoint['retired'] and self._now()-endpoint['last_heartbeat']<=30)
        return result

    def diagnostic_identity(self, req):
        """Read-only host-owned endpoint/native evidence for process continuity checks."""
        host = self._auth(req)
        active_only = req.get('active_only') is True
        ids = req.get('endpoint_ids')
        if ids is not None and (not isinstance(ids, list) or not 1 <= len(ids) <= 32
                                or any(not isinstance(x, str) or not x or len(x) > 128 for x in ids)):
            raise HubError('invalid_request', 'endpoint_ids requires 1 to 32 bounded endpoint IDs')
        active_filter = ' AND retired=0' if active_only else ''
        native_filter = ' AND e.retired=0' if active_only else ''
        args = (host,)
        if ids is not None:
            placeholders = ','.join('?' for _ in ids)
            active_filter += ' AND endpoint_id IN (' + placeholders + ')'
            native_filter += ' AND e.endpoint_id IN (' + placeholders + ')'
            args += tuple(ids)
        try:
            endpoints = [dict(row) for row in self.db.execute(
                'SELECT endpoint_id,participant_id,host_id,session,pane,pid,pid_start,runtime_id,platform,incarnation,last_heartbeat,retired '
                'FROM endpoints WHERE host_id=?' + active_filter + ' ORDER BY endpoint_id', args)]
            native = [dict(row) for row in self.db.execute(
                'SELECT n.endpoint_id,n.native_kind,n.native_id FROM endpoint_native n '
                'JOIN endpoints e ON e.endpoint_id=n.endpoint_id WHERE e.host_id=?' + native_filter + ' ORDER BY n.endpoint_id', args)]
            projects = [dict(row) for row in self.db.execute(
                'SELECT project_id,alias,host_id,path FROM projects WHERE host_id=? ORDER BY project_id', (host,))]
        except (OSError, sqlite3.Error) as exc:
            classified = resource_error(exc, 'outcome_query')
            if classified: raise classified from None
            raise HubError('unavailable', 'diagnostic identity unavailable') from None
        return {'host_id': host, 'endpoints': endpoints, 'endpoint_native': native, 'projects': projects}

    def messaging_capabilities(self, req):
        self._auth(req)
        return {'capabilities': ['native_attest', 'native_continuity',
                                'read_only_diagnose', 'diagnostic_identity', 'resource_exhausted',
                                'native_begin_present', 'native_pending', 'native_drain'],
                'native_runtime': {'hub_version': HUB_NATIVE_VERSION}, 'peers': {}}

    def dispatch(self, req):
        op=req.get("op")
        if op in ('messaging_capabilities', 'peer_messaging_capabilities'):
            return self.messaging_capabilities(req)
        if op == 'diagnostic_identity': return self.diagnostic_identity(req)
        if op == "task_capabilities":
            self._auth(req)
            from tasks import task_capabilities
            return {"capabilities": task_capabilities()}
        if op == "directory_update":
            self._auth(req)
            if "expected_revision" not in req:
                raise HubError("revision_conflict", "expected revision required")
            return self.directory_import(dict(req, admin_token=self.admin_token))
        if op=="ping": return {"maintenance":self._maintenance(),"revision":int(self._row("SELECT value FROM metadata WHERE key='directory_revision'")[0])}
        if op=="directory_import": return self.directory_import(req)
        if op=="directory_list": self._auth(req); return self.directory_list()
        if op=="directory_resolve": self._auth(req); p=self._participant(req["address"]); return dict(p)
        if op=="native_attest": return self.attest_native(req)
        if op=="endpoint_register": return self.register(req)
        if op=="endpoint_retire":
            host=self._auth(req); self._host_endpoint(host,req["endpoint_id"]); self.db.execute("UPDATE endpoints SET retired=1 WHERE endpoint_id=?",(req["endpoint_id"],)); self.db.execute("UPDATE messages SET state='stale_session' WHERE recipient_endpoint=? AND state IN ('accepted','queued','adapter_received')",(req["endpoint_id"],)); return {"retired":req["endpoint_id"]}
        if op == "endpoints_list":
            host = self._auth(req)
            sql = "SELECT * FROM endpoints WHERE host_id=?"
            if req.get("active_only") is True:
                sql += " AND retired=0"
            return {"endpoints": [dict(x) for x in self.db.execute(sql, (host,))]}
        if op=="directory_retire": return self.directory_retire(req)
        if op=="submit": return self._submit_redirected(req)
        if op=="inbox": return self.inbox(req)
        if op=="inbox_notice": return self.inbox_notice(req)
        if op=="native_pending": return self.native_pending(req)
        if op=="native_drain": return self.native_pending(req, drain=True)
        if op=="claim": return self.claim(req)
        if op=="receipt": return self.receipt(req)
        if op=="begin_present": return self.begin_present(req)
        if op=="native_begin_present": return self.begin_present(req, native=True)
        if op=="cancel": return self.cancel(req)
        if op=="delivery_status": return self.delivery_status(req)
        if op=="diagnose": return self.diagnose(req)
        if op=="outbox": return self.outbox(req)
        if op=="query":
            host=self._auth(req); m=self._row("SELECT * FROM messages WHERE message_id=?",(req.get("message_id"),));
            if not m: raise HubError("not_found","message not found")
            # Read expiry through delivery_summary; never mutate before or after
            # party authorization in a query (including rejected queries).
            ep=self._host_endpoint(host,req.get("endpoint_id"));
            if not any(self._same_native_party(ep, party) for party in (m["sender_endpoint"], m["recipient_endpoint"])): raise HubError("unauthorized","not party to message")
            # Same resolved sender the inbox and claim views carry: a reader that fetches
            # one message by ID must not have to trust the name written in its body.
            result = self.message_views([m], response_kind="query")[0]
            response = self.response_evidence(m)
            result.update(response)
            result['delivery_summary'] = self.delivery_summary(m, response)
            result["reader_is_recipient"] = self._same_native_party(ep, m["recipient_endpoint"])
            receipt = self._row("SELECT evidence,at FROM receipts WHERE message_id=?", (m["message_id"],))
            if receipt and m["state"] in ("accepted", "queued", "adapter_received", "uncertain"):
                reason = _receipt_reason(receipt)
                if reason: result.update(delivery_reason=reason, delivery_checked_at=receipt['at'])
            self._check_message_response(result)
            return result
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
        import threading
        def dispatch(req):
            ro = req.get('op') in ('diagnose', 'peer_diagnose', 'diagnostic_identity', 'messaging_capabilities', 'peer_messaging_capabilities')
            instance=factory(args.db,args.config, read_only=ro)
            try: return instance.dispatch(req)
            finally: instance.close()
        try: serve_socket(s,dispatch)
        finally: s.close()
    else:
        import threading
        def dispatch(req):
            ro = req.get('op') in ('diagnose', 'peer_diagnose', 'diagnostic_identity', 'messaging_capabilities', 'peer_messaging_capabilities')
            instance=factory(args.db,args.config, read_only=ro)
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

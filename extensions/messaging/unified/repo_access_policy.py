"""Owner-local grant ledger and audit for the read-only repo read service.

State lives in one ignored sqlite file on the owning host. Only the operator CLI
(`tproj-repo-access`) mutates grants; nothing here is reachable through messaging.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_OPS = ("list", "tree", "read", "search")
VALID_OPS = frozenset(("list", "tree", "read", "search", "log", "diff", "write"))
AUDIT_KEYS = ("ts", "reader", "project_id", "op", "path_or_hash", "allowed", "reason", "bytes", "truncated", "revision")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reader TEXT NOT NULL,
  generation TEXT NOT NULL DEFAULT '',
  project_id TEXT NOT NULL,
  root TEXT NOT NULL,
  ops TEXT NOT NULL,
  path_scope TEXT,
  expires_at REAL,
  granted_at REAL NOT NULL,
  UNIQUE (reader, project_id)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta (key, value) VALUES ('revision', 0);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  reader TEXT NOT NULL,
  project_id TEXT NOT NULL,
  op TEXT NOT NULL,
  path_or_hash TEXT NOT NULL,
  allowed INTEGER NOT NULL,
  reason TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  truncated INTEGER NOT NULL,
  revision INTEGER NOT NULL
);
"""


def default_path() -> str:
    env = os.environ.get("TPROJ_REPO_ACCESS_DB")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".local", "state", "tproj", "repo-access.sqlite")


def _norm_ops(ops) -> str:
    if isinstance(ops, str):
        ops = [o for o in ops.split(",") if o]
    ops = sorted(set(str(o).strip() for o in ops))
    if not ops:
        raise ValueError("at least one operation is required")
    unknown = [o for o in ops if o not in VALID_OPS]
    if unknown:
        raise ValueError("unknown operation: %s" % ",".join(unknown))
    return ",".join(ops)


def _norm_scope(scope):
    if scope is None:
        return None
    text = str(scope).strip().strip("/")
    if not text:
        return None
    parts = text.split("/")
    if any(p in ("", ".", "..") for p in parts) or text.startswith("/"):
        raise ValueError("invalid path scope")
    return "/".join(parts)


def _in_scope(scope, rel_path) -> bool:
    if scope is None:
        return True
    rel = str(rel_path).replace("\\", "/")
    if rel.startswith("/"):
        return False
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if ".." in parts:
        return False
    sparts = scope.split("/")
    return parts[: len(sparts)] == sparts


class RepoPolicy:
    def __init__(self, path=None):
        self.path = str(path) if path else default_path()
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, mode=0o700, exist_ok=True)
        if not os.path.exists(self.path):
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=2.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _revision(conn) -> int:
        return int(conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])

    @staticmethod
    def _bump(conn) -> None:
        conn.execute("UPDATE meta SET value = value + 1 WHERE key='revision'")

    def revision(self) -> int:
        conn = self._connect()
        try:
            return self._revision(conn)
        finally:
            conn.close()

    def grant(self, reader, project_id, root, ops=DEFAULT_OPS, path_scope=None, expires_at=None, generation="") -> int:
        if not reader or not project_id or not root:
            raise ValueError("reader, project_id and root are required")
        ops_text = _norm_ops(ops)
        scope = _norm_scope(path_scope)
        if expires_at is not None:
            expires_at = float(expires_at)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM grants WHERE reader=? AND project_id=?", (str(reader), str(project_id)))
            cur = conn.execute(
                "INSERT INTO grants (reader, generation, project_id, root, ops, path_scope, expires_at, granted_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (str(reader), str(generation or ""), str(project_id), str(root), ops_text, scope, expires_at, time.time()),
            )
            self._bump(conn)
            conn.execute("COMMIT")
            return int(cur.lastrowid)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def revoke(self, reader=None, project_id=None, grant_id=None) -> int:
        clauses, params = [], []
        if reader is not None:
            clauses.append("reader=?")
            params.append(str(reader))
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(str(project_id))
        if grant_id is not None:
            clauses.append("id=?")
            params.append(int(grant_id))
        if not clauses:
            raise ValueError("revoke needs at least one selector")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM grants WHERE " + " AND ".join(clauses), params)
            removed = cur.rowcount
            if removed > 0:
                self._bump(conn)
            conn.execute("COMMIT")
            return removed
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _row(row) -> dict:
        return {
            "id": row["id"],
            "reader": row["reader"],
            "generation": row["generation"],
            "project_id": row["project_id"],
            "root": row["root"],
            "ops": row["ops"].split(",") if row["ops"] else [],
            "path_scope": row["path_scope"],
            "expires_at": row["expires_at"],
            "granted_at": row["granted_at"],
        }

    def list(self, reader=None, project_id=None) -> list:
        clauses, params = [], []
        if reader is not None:
            clauses.append("reader=?")
            params.append(str(reader))
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(str(project_id))
        sql = "SELECT * FROM grants" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id"
        conn = self._connect()
        try:
            return [self._row(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def granted_projects(self, reader, generation="") -> list:
        now = time.time()
        conn = self._connect()
        try:
            rev = self._revision(conn)
            rows = conn.execute("SELECT * FROM grants WHERE reader=? ORDER BY id", (str(reader),)).fetchall()
        finally:
            conn.close()
        out = []
        for row in rows:
            if row["expires_at"] is not None and row["expires_at"] <= now:
                continue
            if row["generation"] and row["generation"] != (generation or ""):
                continue
            out.append({
                "project_id": row["project_id"],
                "root": row["root"],
                "ops": row["ops"].split(","),
                "path_scope": row["path_scope"],
                "revision": rev,
            })
        return out

    def check(self, reader, project_id, root, op, rel_path=None, generation="") -> dict:
        conn = self._connect()
        try:
            rev = self._revision(conn)
            row = conn.execute(
                "SELECT * FROM grants WHERE reader=? AND project_id=?", (str(reader), str(project_id))
            ).fetchone()
        finally:
            conn.close()

        def result(allowed, reason, scope=None):
            return {"allowed": allowed, "reason": reason, "revision": rev, "path_scope": scope}

        if row is None:
            return result(False, "not_granted")
        if row["generation"] and row["generation"] != (generation or ""):
            return result(False, "generation_mismatch")
        if row["expires_at"] is not None and row["expires_at"] <= time.time():
            return result(False, "expired")
        if row["root"] != root:
            return result(False, "root_changed")
        if op not in row["ops"].split(","):
            return result(False, "op_not_granted")
        scope = row["path_scope"]
        if rel_path is not None and not _in_scope(scope, rel_path):
            return result(False, "path_out_of_scope", scope)
        return result(True, "ok", scope)

    def audit(self, record: dict) -> None:
        rec = {k: record[k] for k in AUDIT_KEYS if k in record}
        path = str(rec.get("path_or_hash") or "")
        if path.startswith("/") or ".." in path:
            path = hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:16]
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO audit (ts, reader, project_id, op, path_or_hash, allowed, reason, bytes, truncated, revision)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    float(rec.get("ts") or time.time()),
                    str(rec.get("reader") or ""),
                    str(rec.get("project_id") or ""),
                    str(rec.get("op") or ""),
                    path,
                    1 if rec.get("allowed") else 0,
                    str(rec.get("reason") or ""),
                    int(rec.get("bytes") or 0),
                    1 if rec.get("truncated") else 0,
                    int(rec["revision"]) if rec.get("revision") is not None else self._revision(conn),
                ),
            )
        finally:
            conn.close()

    def audit_list(self, limit=50, reader=None, project_id=None) -> list:
        clauses, params = [], []
        if reader is not None:
            clauses.append("reader=?")
            params.append(str(reader))
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(str(project_id))
        sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [
            {
                "ts": r["ts"], "reader": r["reader"], "project_id": r["project_id"], "op": r["op"],
                "path_or_hash": r["path_or_hash"], "allowed": bool(r["allowed"]), "reason": r["reason"],
                "bytes": r["bytes"], "truncated": bool(r["truncated"]), "revision": r["revision"],
            }
            for r in rows
        ]

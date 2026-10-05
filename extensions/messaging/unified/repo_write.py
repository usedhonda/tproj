"""Writes to a granted project's working tree (repo_write, repo_revert).

Specification: docs/reference/repo-write-service.md.  A writer submits whole-file
changes; this host validates them against the owner's grants and the current tree and
applies them in the same call.  Nothing is ever executed, staged, committed or pushed.

Safety model in short: all-or-nothing; every path is opened relative to a directory file
descriptor with no-follow; files are written to a temporary name in the same directory
and renamed into place; a path the owner has uncommitted changes in is refused unless
the last writer was a previous patch of this service; credentials in content are refused.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
from typing import Any, Dict, List, Tuple

from repo_access import (CREDENTIAL_RE, RepoError, Snapshot, _open_beneath, _tracked_files, check_relative,
                         name_denied, SNIFF_BYTES)

MAX_FILES = 20
MAX_FILE_BYTES = 128 * 1024
MAX_TOTAL_BYTES = 192 * 1024         # a request travels in one 256 KiB host frame
MAX_NEW_DIR_DEPTH = 3
PATCH_TTL_SECONDS = 7 * 24 * 3600
PATCH_ID_RE = re.compile(r"^[0-9a-fA-F-]{16,64}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(root: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(root, threading.Lock())


def state_dir() -> str:
    return os.environ.get("TPROJ_REPO_PATCH_DIR") or os.path.expanduser("~/.local/state/tproj/repo-patches")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def written_sha(project_id: str, rel: str):
    """SHA-256 this service last wrote to `rel`, or None. Read-only: never creates state."""
    path = os.path.join(state_dir(), re.sub(r"[^A-Za-z0-9_.-]", "_", project_id), "index.json")
    try:
        with open(path) as fh:
            value = json.load(fh).get(rel)
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and SHA_RE.match(value) else None


class _Store:
    """Owner-local record of applied patches (previous contents for revert). Never returned."""

    def __init__(self, project_id: str):
        self.dir = os.path.join(state_dir(), re.sub(r"[^A-Za-z0-9_.-]", "_", project_id))
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self.index_path = os.path.join(self.dir, "index.json")

    def _patch_path(self, patch_id: str) -> str:
        return os.path.join(self.dir, patch_id + ".json")

    def load(self, patch_id: str):
        try:
            with open(self._patch_path(patch_id)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def save(self, patch_id: str, record: dict) -> None:
        self._atomic(self._patch_path(patch_id), record)

    def index(self) -> Dict[str, str]:
        try:
            with open(self.index_path) as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_index(self, index: Dict[str, str]) -> None:
        self._atomic(self.index_path, index)

    def prune(self) -> None:
        cutoff = time.time() - PATCH_TTL_SECONDS
        for name in os.listdir(self.dir):
            full = os.path.join(self.dir, name)
            if name.endswith(".json") and name != "index.json" and os.path.getmtime(full) < cutoff:
                os.unlink(full)

    def _atomic(self, path: str, obj: Any) -> None:
        tmp = "%s.%s.tmp" % (path, secrets.token_hex(4))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


def _read_regular(dir_fd: int, name: str) -> Tuple[bytes, int]:
    """Read one regular file by name relative to dir_fd, no-follow. Returns (data, mode)."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        raise RepoError("path_not_found")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise RepoError("path_denied")
        if st.st_size > 1024 * 1024:
            raise RepoError("too_large")
        with os.fdopen(os.dup(fd), "rb") as fh:
            return fh.read(), st.st_mode
    finally:
        os.close(fd)


def _validate(req: dict) -> Tuple[str, List[dict], bool]:
    patch_id = req.get("patch_id")
    changes = req.get("changes")
    if not isinstance(patch_id, str) or not PATCH_ID_RE.match(patch_id):
        raise RepoError("invalid_request")
    if not isinstance(changes, list) or not changes or len(changes) > MAX_FILES:
        raise RepoError("invalid_request")
    total, seen, clean = 0, set(), []
    for item in changes:
        if not isinstance(item, dict):
            raise RepoError("invalid_request")
        action, content, path = item.get("action"), item.get("content"), item.get("path")
        if action not in ("create", "modify") or not isinstance(content, str) or "\0" in content:
            raise RepoError("invalid_request")
        base = item.get("base_sha256")
        if (action == "modify") != (base is not None) or (base is not None and not (isinstance(base, str) and SHA_RE.match(base))):
            raise RepoError("invalid_request")
        parts = check_relative(path)
        if not parts:
            raise RepoError("invalid_request")
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise RepoError("too_large")
        total += len(data)
        if CREDENTIAL_RE.search(content):
            raise RepoError("content_withheld")
        rel = "/".join(parts)
        if rel in seen:
            raise RepoError("invalid_request")
        seen.add(rel)
        clean.append({"path": rel, "parts": parts, "action": action, "data": data, "base_sha256": base})
    if total > MAX_TOTAL_BYTES:
        raise RepoError("too_large")
    return patch_id, clean, bool(req.get("dry_run"))


def _digest(changes: List[dict]) -> str:
    h = hashlib.sha256()
    for c in sorted(changes, key=lambda c: c["path"]):
        h.update(("%s\0%s\0%s\0%s\0" % (c["path"], c["action"], c["base_sha256"], _sha(c["data"]))).encode())
    return h.hexdigest()


def _ensure_parent(root: str, parts: List[str], prefix_depth: int) -> int:
    """Open the parent directory of parts, creating at most MAX_NEW_DIR_DEPTH missing levels."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(root, flags)
    except OSError:
        raise RepoError("project_offline")
    created = 0
    try:
        for part in parts[:-1]:
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                created += 1
                if created > MAX_NEW_DIR_DEPTH:
                    raise RepoError("scope_denied")
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                    nxt = os.open(part, flags, dir_fd=fd)
                except OSError:
                    raise RepoError("path_denied")
            except OSError:
                raise RepoError("path_denied")
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def write(access: Any, reader: dict, req: dict) -> dict:
    return _run(access, reader, "write", req)


def revert(access: Any, reader: dict, req: dict) -> dict:
    return _run(access, reader, "revert", req)


def _run(access: Any, reader: dict, op: str, req: dict) -> dict:
    repo_id = req.get("repo_id")
    if not isinstance(repo_id, str) or not repo_id:
        raise RepoError("invalid_request")
    project, grant = access._resolve(reader, repo_id)
    pid = project["project_id"]
    patch_id, changes, dry = None, [], False
    try:
        if op == "write":
            patch_id, changes, dry = _validate(req)
        else:
            patch_id = req.get("patch_id")
            if not isinstance(patch_id, str) or not PATCH_ID_RE.match(patch_id):
                raise RepoError("invalid_request")
        verdict_paths = [c["path"] for c in changes] or [None]
        for rel in verdict_paths:
            verdict = access.policy.check(reader["participant_id"], pid, grant["root"], "write", rel, reader.get("generation", ""))
            if not verdict["allowed"]:
                raise RepoError("not_granted" if verdict["reason"] in ("not_granted", "expired", "generation_mismatch", "op_not_granted")
                                else "scope_denied")
        access._rate(reader, pid)
        with _lock_for(grant["root"]):
            result = _write_locked(grant, pid, reader, patch_id, changes, dry) if op == "write" else _revert_locked(grant, pid, reader, patch_id)
    except RepoError as exc:
        access._audit(reader, pid, op, patch_id or "", False, exc.code, 0, False)
        raise
    nbytes = sum(len(c["data"]) for c in changes)
    access._audit(reader, pid, op, patch_id or "", True, "dry_run" if dry else "ok", nbytes, False)
    return result


def _write_locked(grant: dict, project_id: str, reader: dict, patch_id: str, changes: List[dict], dry: bool) -> dict:
    root = grant["root"]
    store = _Store(project_id)
    digest = _digest(changes)
    prior = store.load(patch_id)
    if prior is not None:
        if prior.get("digest") != digest or prior.get("writer") != reader["participant_id"]:
            raise RepoError("conflict")
        return dict(prior["result"], duplicate=True)
    snap = Snapshot(root)
    index = store.index()
    tracked = set(p for p in _tracked_files(root))
    dirty = set(snap.dirty_paths)
    plan = []
    for c in changes:
        rel = c["path"]
        exists = True
        parent_fd = None
        try:
            try:
                parent_fd = _open_beneath(root, c["parts"][:-1], True) if len(c["parts"]) > 1 else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            except RepoError:
                parent_fd, exists = None, False
                present = 0
                for n in range(len(c["parts"]) - 1, 0, -1):     # how many parent levels already exist
                    try:
                        os.close(_open_beneath(root, c["parts"][:n], True)); present = n; break
                    except RepoError:
                        continue
                if len(c["parts"]) - 1 - present > MAX_NEW_DIR_DEPTH:
                    raise RepoError("scope_denied")
            old, mode = b"", 0o644
            if exists and parent_fd is not None:
                try:
                    old, mode = _read_regular(parent_fd, c["parts"][-1])
                except RepoError as exc:
                    if exc.code != "path_not_found":
                        raise
                    exists = False
            if c["action"] == "create":
                if exists or rel in tracked:
                    raise RepoError("exists")
            else:
                if not exists or rel not in tracked:
                    raise RepoError("path_not_found")
                if mode & 0o111 or b"\0" in old[:SNIFF_BYTES]:
                    raise RepoError("path_denied")
                if _sha(old) != c["base_sha256"]:
                    raise RepoError("conflict")
                if rel in dirty and index.get(rel) != _sha(old):
                    raise RepoError("dirty_path")
            plan.append(dict(c, old=old, mode=mode & 0o777 if exists else 0o644, existed=exists))
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
    files = [{"path": p["path"], "action": p["action"], "status": "ok", "file_sha256": _sha(p["data"])} for p in plan]
    if dry:
        return {"patch_id": patch_id, "applied": False, "dry_run": True, "files": files, "head": snap.head, "dirty": snap.dirty}
    done = []
    try:
        for p in plan:
            parent_fd = _ensure_parent(root, p["parts"], 0)
            try:
                tmp = ".tproj-write-" + secrets.token_hex(6)
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, p["mode"], dir_fd=parent_fd)
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(p["data"]); fh.flush(); os.fsync(fh.fileno())
                except BaseException:
                    os.unlink(tmp, dir_fd=parent_fd); raise
                os.rename(tmp, p["parts"][-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
            done.append(p)
    except BaseException as exc:
        for p in reversed(done):   # all or nothing
            try:
                _restore(root, p)
            except Exception:
                pass
        raise exc if isinstance(exc, RepoError) else RepoError("path_denied")
    for p in plan:
        index[p["path"]] = _sha(p["data"])
    store.save_index(index)
    after = Snapshot(root)
    result = {"patch_id": patch_id, "applied": True, "files": files, "head": after.head, "dirty": after.dirty}
    store.save(patch_id, {"digest": digest, "writer": reader["participant_id"], "result": result, "reverted": False, "files": [
        {"path": p["path"], "action": p["action"], "new_sha256": _sha(p["data"]),
         "prev_b64": base64.b64encode(p["old"]).decode() if p["existed"] else None, "mode": p["mode"]} for p in plan]})
    store.prune()
    return result


def _restore(root: str, p: dict) -> None:
    parent_fd = _open_beneath(root, p["parts"][:-1], True) if len(p["parts"]) > 1 else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if p["existed"]:
            tmp = ".tproj-write-" + secrets.token_hex(6)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, p["mode"], dir_fd=parent_fd)
            with os.fdopen(fd, "wb") as fh:
                fh.write(p["old"])
            os.rename(tmp, p["parts"][-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        else:
            os.unlink(p["parts"][-1], dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _revert_locked(grant: dict, project_id: str, reader: dict, patch_id: str) -> dict:
    root = grant["root"]
    store = _Store(project_id)
    record = store.load(patch_id)
    if record is None or record.get("writer") != reader["participant_id"]:
        raise RepoError("path_not_found")
    if record.get("reverted"):
        raise RepoError("conflict")
    entries = record["files"]
    for e in entries:      # verify first so a revert is all or nothing too
        parts = check_relative(e["path"])
        parent_fd = _open_beneath(root, parts[:-1], True) if len(parts) > 1 else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            current, _ = _read_regular(parent_fd, parts[-1])
        finally:
            os.close(parent_fd)
        if _sha(current) != e["new_sha256"]:
            raise RepoError("conflict")
    index = store.index()
    for e in reversed(entries):
        parts = check_relative(e["path"])
        prev = base64.b64decode(e["prev_b64"]) if e["prev_b64"] is not None else None
        _restore(root, {"parts": parts, "existed": prev is not None, "old": prev or b"", "mode": e.get("mode", 0o644)})
        if prev is None:
            index.pop(e["path"], None)
        else:
            index[e["path"]] = _sha(prev)
    store.save_index(index)
    record["reverted"] = True
    store.save(patch_id, record)
    snap = Snapshot(root)
    return {"patch_id": patch_id, "reverted": True, "files": [{"path": e["path"], "status": "restored"} for e in entries],
            "head": snap.head, "dirty": snap.dirty}

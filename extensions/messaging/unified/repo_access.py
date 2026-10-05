"""Read-only access to a granted project's tracked source (list, tree, read, search).

Specification: docs/reference/repo-read-service.md.  This module performs the safe
read and applies one filter to every path.  It never writes, builds or runs anything,
and it decides nothing about who may read: that is `repo_access_policy`.

Safety model in short: the root is opened as a directory file descriptor and every
path component is opened relative to it with no-follow, so a symlink swapped in after
a check cannot redirect the read; only regular files are opened; only tracked files
are served; git is invoked with a fixed argv and no repository-supplied helper; and
repository content is returned as untrusted data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

READ_DEFAULT_LINES = 200
READ_MAX_LINES = 1000
READ_DEFAULT_BYTES = 32 * 1024
READ_MAX_BYTES = 128 * 1024
PAGE_DEFAULT = 100
PAGE_MAX = 200
TREE_MAX_DEPTH = 3
SEARCH_SECONDS = 2.0
SEARCH_BUDGET = 150_000      # result bytes; keeps a response far below the 256 KiB host wire limit
MAX_LINE_CHARS = 4000        # a longer line is reported as truncated, never cut silently
SEARCH_LINE_CHARS = 2000     # lines longer than this are skipped by search (bounds regex time)
MAX_PATTERN_CHARS = 200
SNIFF_BYTES = 8192
FULL_HASH_MAX_BYTES = 1024 * 1024   # a whole-file SHA-256 (the base for a later write) is reported up to this size
GIT_OUTPUT_CAP = 8 * 1024 * 1024
RATE_CALLS_PER_MIN = 120
RATE_BYTES_PER_HOUR = 8 * 1024 * 1024

ALWAYS_DENIED_DIRS = frozenset((".git", ".local", ".svn", ".hg", ".ssh", ".gnupg", ".aws"))
DENIED_NAME_RE = re.compile(
    r"(^\.env($|[.\-_])|\.(pem|key|p12|pfx|mobileprovision|keychain|keychain-db|jks|kdbx)$"
    r"|^id_(rsa|dsa|ecdsa|ed25519)|^credentials?(\.|$)|^secrets?(\.|$)|\.secret$|^\.netrc$|^\.npmrc$)",
    re.IGNORECASE)
DENIED_EXT = frozenset((
    "wav mp3 m4a aif aiff flac caf ogg opus mp4 mov m4v avi mkv webm zip gz tgz bz2 xz 7z rar dmg iso "
    "app ipa pkg exe dll dylib so a o class jar sqlite sqlite3 db").split())
CREDENTIAL_RE = re.compile(
    r"(npm_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9\-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{30,}|(?i:(?:api[_-]?key|secret|passwd|password|token))\s*[:=]\s*[\"']?[A-Za-z0-9+/_\-]{24,})")
# A quantified group, a back-reference, or many unbounded quantifiers can make Python's
# backtracking engine take exponential or high-polynomial time on one line; none of
# that is needed for code search, so such patterns are refused up front.
NESTED_QUANTIFIER_RE = re.compile(r"\)\s*[+*{]|\\[1-9]|(?:[+*][^+*]*){5,}")
SAFE_ENV = {
    "PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
    "LC_ALL": "C", "LANG": "C",
    "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_EXTERNAL_DIFF": "", "HOME": os.devnull,
}
GIT_BASE = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.untrackedCache=false", "-c", "diff.external="]
FIXED_MESSAGES = {
    "not_granted": "this reader has no grant for that project",
    "scope_denied": "that path or operation is outside the grant",
    "project_offline": "the project is not available on its owning host",
    "host_unavailable": "the owning host could not be reached",
    "path_not_found": "no such readable path",
    "path_denied": "that path is never served",
    "snapshot_expired": "the working tree changed since that snapshot",
    "too_large": "the request exceeds a size limit",
    "rate_limited": "too many reads; retry later",
    "content_withheld": "content was withheld by the credential screen",
    "invalid_request": "invalid request",
    "conflict": "the file changed since it was read, or the patch id was reused with different content",
    "dirty_path": "the owner has uncommitted changes in that path",
    "exists": "that path already exists",
}


class RepoError(Exception):
    """A rejection carrying only a fixed code and a fixed, content-free message."""

    def __init__(self, code: str, retry_after: Optional[int] = None):
        super().__init__(FIXED_MESSAGES.get(code, "request rejected"))
        self.code = code
        self.retry_after = retry_after


# ---------------------------------------------------------------- git (fixed argv)

def _git(root: str, *args: str, timeout: float = 3.0) -> bytes:
    proc = subprocess.run(GIT_BASE + ["-C", root] + list(args), env=SAFE_ENV, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RepoError("project_offline")
    return proc.stdout[:GIT_OUTPUT_CAP]


def _tracked_files(root: str) -> List[str]:
    raw = _git(root, "ls-files", "-z", timeout=5.0)
    return sorted(p for p in raw.decode("utf-8", "surrogateescape").split("\0") if p)


class Snapshot:
    """HEAD, branch, dirty tracked files and a fingerprint of the working tree."""

    def __init__(self, root: str):
        self.root = root
        self.head = _git(root, "rev-parse", "HEAD").decode().strip()
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
        self.branch = branch
        status = _git(root, "status", "--porcelain=v1", "-z", "-uno", "--no-renames", timeout=5.0)
        entries = [e for e in status.decode("utf-8", "surrogateescape").split("\0") if e]
        self.dirty_paths = sorted(e[3:] for e in entries if len(e) > 3)
        digest = hashlib.sha256()
        digest.update(self.head.encode())
        for rel in self.dirty_paths:
            try:
                st = os.lstat(os.path.join(root, rel))
                digest.update(("%s\0%d\0%d\0" % (rel, st.st_size, st.st_mtime_ns)).encode("utf-8", "surrogateescape"))
            except OSError:
                digest.update(("%s\0gone\0" % rel).encode("utf-8", "surrogateescape"))
        self.id = digest.hexdigest()[:16]

    @property
    def dirty(self) -> int:
        return len(self.dirty_paths)

    def state(self) -> Tuple[str, str, str]:
        return (self.head, self.branch, self.id)


# ---------------------------------------------------------------- path policy

def check_relative(path: str) -> List[str]:
    """Split a repo-relative path, rejecting anything that could leave the root."""
    if not isinstance(path, str) or len(path) > 1024 or "\0" in path:
        raise RepoError("invalid_request")
    if path in ("", "."):
        return []
    if path.startswith("/") or "\\" in path:
        raise RepoError("path_denied")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise RepoError("path_denied")
    for p in parts:
        if name_denied(p):
            raise RepoError("path_denied")
    return parts


def name_denied(name: str) -> bool:
    if name in ALWAYS_DENIED_DIRS or DENIED_NAME_RE.search(name):
        return True
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in DENIED_EXT


def _open_beneath(root: str, parts: List[str], want_dir: bool) -> int:
    """Open `parts` under `root` one component at a time, never following a symlink."""
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(root, flags_dir)
    except OSError:
        raise RepoError("project_offline")
    try:
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if last and not want_dir:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            else:
                flags = flags_dir
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except OSError:
                raise RepoError("path_not_found")
            os.close(fd)
            fd = nxt
        mode = os.fstat(fd).st_mode
        if want_dir and not stat.S_ISDIR(mode):
            raise RepoError("path_not_found")
        if not want_dir and not stat.S_ISREG(mode):
            raise RepoError("path_denied")
        return fd
    except BaseException:
        os.close(fd)
        raise


# ---------------------------------------------------------------- service

class RepoAccess:
    """list / tree / read / search for one host's projects.

    `policy`   a `RepoPolicy`.
    `projects` callable returning this host's projects as dicts with
               project_id, alias, path (and host_id when available).
    """

    def __init__(self, policy: Any, projects: Callable[[], Iterable[dict]], clock: Callable[[], float] = time.time):
        self.policy = policy
        self.projects = projects
        self.clock = clock
        self._calls: Dict[Tuple[str, str], deque] = {}
        self._bytes: Dict[Tuple[str, str], deque] = {}
        self._tracked_cache: Dict[Tuple[str, str], Tuple[set, set]] = {}

    # --- entry points -----------------------------------------------------

    def list_repos(self, reader: dict) -> dict:
        local = {p["project_id"]: p for p in self.projects()}
        repos = []
        for grant in self.policy.granted_projects(reader["participant_id"], reader.get("generation", "")):
            project = local.get(grant["project_id"])
            if not project or os.path.realpath(project["path"]) != grant["root"]:
                continue
            ops = [op for op in grant["ops"] if op in ("list", "tree", "read", "search", "write")]
            entry = {"repo_id": grant["project_id"], "name": project.get("alias") or os.path.basename(grant["root"]),
                     "ops": ops, "path_scope": grant["path_scope"], "state": "online"}
            try:
                snap = Snapshot(grant["root"])
                entry.update(branch=snap.branch, head=snap.head, dirty=snap.dirty)
            except (RepoError, subprocess.SubprocessError, OSError):
                entry["state"] = "offline"
            repos.append(entry)
        self._audit(reader, "", "list", "", True, "ok", 0, False)
        return {"repos": repos, "read_at": self._now()}

    def handle(self, op: str, reader: dict, req: dict) -> dict:
        """Run one op for an already-authenticated reader."""
        if op == "list":
            return self.list_repos(reader)
        if op in ("write", "revert"):
            import repo_write
            return getattr(repo_write, op)(self, reader, req)
        if op not in ("tree", "read", "search"):
            raise RepoError("invalid_request")
        repo_id = req.get("repo_id")
        if not isinstance(repo_id, str) or not repo_id:
            raise RepoError("invalid_request")
        rel = req.get("path") or ""
        parts = []
        denied = None
        try:
            parts = check_relative(rel)
        except RepoError as exc:
            denied = exc
        project, grant = self._resolve(reader, repo_id)
        rel_norm = "/".join(parts)
        verdict = self.policy.check(reader["participant_id"], project["project_id"], grant["root"], op,
                                    rel_norm if parts else None, reader.get("generation", ""))
        if not verdict["allowed"]:
            self._audit(reader, project["project_id"], op, rel_norm, False, verdict["reason"], 0, False)
            raise RepoError("not_granted" if verdict["reason"] in ("not_granted", "expired", "generation_mismatch")
                            else "scope_denied")
        if denied is not None:
            self._audit(reader, project["project_id"], op, rel_norm, False, denied.code, 0, False)
            raise denied
        self._rate(reader, project["project_id"])
        try:
            result = {"tree": self._tree, "read": self._read, "search": self._search}[op](grant, project, parts, req)
        except RepoError as exc:
            self._audit(reader, project["project_id"], op, rel_norm, False, exc.code, 0, False)
            raise
        size = len(json.dumps(result, ensure_ascii=False).encode())
        self._rate_bytes(reader, project["project_id"], size)
        self._audit(reader, project["project_id"], op, rel_norm, True, "ok", size, bool(result.get("truncated")))
        return result

    # --- resolution, limits, audit ---------------------------------------

    def _resolve(self, reader: dict, repo_id: str) -> Tuple[dict, dict]:
        local = {p["project_id"]: p for p in self.projects()}
        grants = self.policy.granted_projects(reader["participant_id"], reader.get("generation", ""))
        by_alias = [g for g in grants if (local.get(g["project_id"]) or {}).get("alias") == repo_id]
        pick = [g for g in grants if g["project_id"] == repo_id] or (by_alias if len(by_alias) == 1 else [])
        if not pick:
            raise RepoError("not_granted")
        grant = pick[0]
        project = local.get(grant["project_id"])
        if not project:
            raise RepoError("project_offline")
        if os.path.realpath(project["path"]) != grant["root"]:
            raise RepoError("scope_denied")
        return project, grant

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.clock()))

    def _rate(self, reader: dict, project_id: str) -> None:
        key = (reader["participant_id"], project_id)
        now = self.clock()
        calls = self._calls.setdefault(key, deque())
        while calls and calls[0] < now - 60:
            calls.popleft()
        if len(calls) >= RATE_CALLS_PER_MIN:
            raise RepoError("rate_limited", retry_after=int(calls[0] + 60 - now) + 1)
        used = self._bytes.setdefault(key, deque())
        while used and used[0][0] < now - 3600:
            used.popleft()
        if sum(b for _, b in used) >= RATE_BYTES_PER_HOUR:
            raise RepoError("rate_limited", retry_after=int(used[0][0] + 3600 - now) + 1)
        calls.append(now)

    def _rate_bytes(self, reader: dict, project_id: str, size: int) -> None:
        self._bytes.setdefault((reader["participant_id"], project_id), deque()).append((self.clock(), size))

    def _audit(self, reader: dict, project_id: str, op: str, path: str, allowed: bool, reason: str,
               nbytes: int, truncated: bool) -> None:
        try:
            self.policy.audit({"reader": reader.get("participant_id", ""), "project_id": project_id, "op": op,
                               "path_or_hash": path, "allowed": allowed, "reason": reason, "bytes": nbytes,
                               "truncated": truncated, "revision": self.policy.revision()})
        except Exception:
            pass  # an audit failure must not turn a refusal into a read, nor leak anything

    # --- tracked set ------------------------------------------------------

    def _tracked(self, root: str, snap: Snapshot) -> Tuple[set, set]:
        key = (root, snap.head)
        cached = self._tracked_cache.get(key)
        if cached is None:
            files = set(p for p in _tracked_files(root) if not any(name_denied(x) for x in p.split("/")))
            dirs = set()
            for f in files:
                parts = f.split("/")
                for i in range(1, len(parts)):
                    dirs.add("/".join(parts[:i]))
            self._tracked_cache = {key: (files, dirs)}
            cached = (files, dirs)
        return cached

    # --- envelope ----------------------------------------------------------

    def _envelope(self, project: dict, before: Snapshot, after: Optional[Snapshot], **extra: Any) -> dict:
        consistent = after is not None and after.state() == before.state()
        out = {"repo_id": project["project_id"], "branch": before.branch, "head": before.head,
               "dirty": before.dirty, "untracked_included": False, "read_at": self._now(),
               "snapshot_id": before.id, "consistent": consistent,
               "untrusted_content": True}
        out.update(extra)
        return out

    def _check_snapshot(self, req: dict, snap: Snapshot) -> None:
        wanted = req.get("snapshot_id")
        if wanted is not None and wanted != snap.id:
            raise RepoError("snapshot_expired")

    # --- tree --------------------------------------------------------------

    def _tree(self, grant: dict, project: dict, parts: List[str], req: dict) -> dict:
        root = grant["root"]
        before = Snapshot(root)
        self._check_snapshot(req, before)
        depth = req.get("depth", 1)
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1 or depth > TREE_MAX_DEPTH:
            raise RepoError("invalid_request")
        limit = self._page(req)
        files, dirs = self._tracked(root, before)
        base = "/".join(parts)
        fd = _open_beneath(root, parts, want_dir=True)
        os.close(fd)
        entries: List[dict] = []
        self._walk(root, parts, depth, files, dirs, entries)
        entries.sort(key=lambda e: e["path"])
        offset = self._cursor_offset(req, "tree", [base, depth], before.id)
        page = entries[offset:offset + limit]
        nxt = self._cursor_make("tree", [base, depth], before.id, offset + limit) if offset + limit < len(entries) else None
        after = Snapshot(root)
        return self._envelope(project, before, after, path=base, entries=page, truncated=nxt is not None,
                              returned_range=[offset, offset + len(page)], next_cursor=nxt)

    def _walk(self, root: str, parts: List[str], depth: int, files: set, dirs: set, out: List[dict]) -> None:
        fd = _open_beneath(root, parts, want_dir=True)
        found: List[Tuple[str, str, int]] = []
        try:
            with os.scandir(fd) as it:
                for entry in it:   # read everything while the directory descriptor is still open
                    if name_denied(entry.name) or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        found.append((entry.name, "dir", 0))
                    elif entry.is_file(follow_symlinks=False):
                        found.append((entry.name, "file", entry.stat(follow_symlinks=False).st_size))
        finally:
            os.close(fd)
        for name, kind, size in sorted(found):
            rel = "/".join(parts + [name])
            if kind == "dir":
                if rel not in dirs:
                    continue
                out.append({"path": rel, "kind": "dir"})
                if depth > 1:
                    self._walk(root, parts + [name], depth - 1, files, dirs, out)
            elif rel in files:
                out.append({"path": rel, "kind": "file", "size": size})

    # --- read --------------------------------------------------------------

    def _read(self, grant: dict, project: dict, parts: List[str], req: dict) -> dict:
        if not parts:
            raise RepoError("invalid_request")
        root = grant["root"]
        before = Snapshot(root)
        self._check_snapshot(req, before)
        rel = "/".join(parts)
        files, _ = self._tracked(root, before)
        # A file this service created is untracked until the owner commits it; it stays readable
        # (so its writer can verify it) only while it still has exactly what the service wrote.
        import repo_write
        written = None if rel in files else repo_write.written_sha(project["project_id"], rel)
        if rel not in files and written is None:
            raise RepoError("path_not_found")
        start = self._int(req.get("start", 1), 1, 10 ** 9)
        end = self._int(req["end"], start, 10 ** 9) if "end" in req else start + READ_DEFAULT_LINES - 1
        if end - start + 1 > READ_MAX_LINES:
            raise RepoError("too_large")
        byte_cap = self._int(req["max_bytes"], 1, READ_MAX_BYTES) if "max_bytes" in req else READ_DEFAULT_BYTES
        fd = _open_beneath(root, parts, want_dir=False)
        size = os.fstat(fd).st_size
        with os.fdopen(fd, "rb") as handle:
            full = hashlib.sha256()
            if size <= FULL_HASH_MAX_BYTES:
                for block in iter(lambda: handle.read(65536), b""):
                    full.update(block)
                handle.seek(0)
            if written is not None and (size > FULL_HASH_MAX_BYTES or full.hexdigest() != written):
                raise RepoError("path_not_found")
            if b"\0" in handle.read(SNIFF_BYTES):
                return self._envelope(project, before, Snapshot(root), path=rel, kind="binary", size=size,
                                      truncated=False, returned_range=None, next_cursor=None, lines=[])
            handle.seek(0)
            lines: List[dict] = []
            total_bytes = 0
            truncated = False
            long_line = False
            lineno = 0
            digest = hashlib.sha256()
            chunk = MAX_LINE_CHARS * 4
            while True:
                raw = handle.readline(chunk + 1)
                if not raw:
                    break
                digest.update(raw)
                over = len(raw) > chunk
                while over and not raw.endswith(b"\n"):
                    # swallow the rest of an over-long line so numbering stays right
                    more = handle.readline(chunk)
                    if not more:
                        break
                    digest.update(more)
                    raw = more
                lineno += 1
                if lineno < start:
                    continue
                if lineno > end:
                    truncated = True
                    break
                text = raw.decode("utf-8", "replace").rstrip("\r\n") if not over else ""
                if over:
                    text = ""  # the line is longer than we serve; say so rather than cut it silently
                    long_line = True
                elif len(text) > MAX_LINE_CHARS:
                    text = text[:MAX_LINE_CHARS]
                    long_line = True
                total_bytes += len(text.encode("utf-8")) + 1
                if total_bytes > byte_cap and lines:
                    truncated = True
                    break
                lines.append({"n": lineno, "text": text, **({"line_truncated": True} if over or len(text) == MAX_LINE_CHARS else {})})
        if CREDENTIAL_RE.search("\n".join(item["text"] for item in lines)):
            raise RepoError("content_withheld")
        after = Snapshot(root)
        last = lines[-1]["n"] if lines else start - 1
        nxt = {"start": last + 1} if truncated else None
        cite_range = "L%d-L%d" % (lines[0]["n"], last) if lines else "L%d" % start
        tag = before.head if before.dirty == 0 else "%s+%s" % (before.head, before.id)
        return self._envelope(project, before, after, path=rel, kind="text", size=size, lines=lines,
                              truncated=truncated, line_truncated=long_line,
                              returned_range=[lines[0]["n"], last] if lines else None,
                              next_cursor=nxt, file_sha256_prefix=digest.hexdigest()[:16] if not truncated else None,
                              file_sha256=full.hexdigest() if size <= FULL_HASH_MAX_BYTES else None,
                              cite="%s@%s:%s:%s" % (project.get("alias") or project["project_id"], tag, rel, cite_range))

    # --- search ------------------------------------------------------------

    def _search(self, grant: dict, project: dict, parts: List[str], req: dict) -> dict:
        root = grant["root"]
        before = Snapshot(root)
        self._check_snapshot(req, before)
        pattern = req.get("pattern")
        if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
            raise RepoError("invalid_request")
        mode = req.get("mode", "literal")
        if mode not in ("literal", "regex"):
            raise RepoError("invalid_request")
        case = bool(req.get("case_sensitive", False))
        if mode == "regex":
            if NESTED_QUANTIFIER_RE.search(pattern):
                raise RepoError("invalid_request")
            try:
                rx = re.compile(pattern, 0 if case else re.IGNORECASE)
            except re.error:
                raise RepoError("invalid_request")
        else:
            rx = re.compile(re.escape(pattern), 0 if case else re.IGNORECASE)
        context = self._int(req.get("context", 2), 0, 20)
        limit = self._page(req)
        include = self._globs(req.get("glob_include"))
        exclude = self._globs(req.get("glob_exclude"))
        files, _ = self._tracked(root, before)
        base = "/".join(parts)
        qkey = [base, pattern, mode, case, context, include, exclude]
        cursor = self._cursor_load(req, "search", qkey, before.id)
        start_file, start_line = (cursor or [0, 0])
        candidates = [f for f in sorted(files)
                      if (not base or f == base or f.startswith(base + "/"))
                      and (not include or any(self._glob(f, g) for g in include))
                      and not any(self._glob(f, g) for g in exclude)]
        deadline = time.monotonic() + SEARCH_SECONDS
        used = 0
        matches: List[dict] = []
        timed_out = False
        withheld = 0
        next_cursor = None
        for fi in range(start_file, len(candidates)):
            rel = candidates[fi]
            try:
                fd = _open_beneath(root, rel.split("/"), want_dir=False)
            except RepoError:
                continue
            with os.fdopen(fd, "rb") as handle:
                if b"\0" in handle.read(SNIFF_BYTES):
                    continue
                handle.seek(0)
                window: deque = deque(maxlen=context)
                pending: List[dict] = []
                lineno = 0
                for raw in handle:
                    lineno += 1
                    if len(raw) > SEARCH_LINE_CHARS * 4:
                        continue
                    text = raw.decode("utf-8", "replace").rstrip("\r\n")
                    for item in pending:
                        if item["after_left"] > 0:
                            item["context_after"].append({"n": lineno, "text": text})
                            item["after_left"] -= 1
                            used += len(text)
                    if fi == start_file and lineno <= start_line:
                        window.append({"n": lineno, "text": text}); continue
                    if len(text) <= SEARCH_LINE_CHARS and rx.search(text):
                        if CREDENTIAL_RE.search(text):
                            withheld += 1
                        else:
                            hit = {"path": rel, "n": lineno, "text": text, "context_before": list(window),
                                   "context_after": [], "after_left": context}
                            hit["cite"] = "%s@%s:%s:L%d" % (project.get("alias") or project["project_id"],
                                                             before.head, rel, lineno)
                            matches.append(hit); pending.append(hit)
                            used += len(text) + sum(len(c["text"]) for c in hit["context_before"]) + 80
                            if len(matches) >= limit or used >= SEARCH_BUDGET:
                                next_cursor = self._cursor_make("search", qkey, before.id, [fi, lineno])
                                break
                    window.append({"n": lineno, "text": text})
                    if time.monotonic() > deadline:
                        timed_out = True
                        next_cursor = self._cursor_make("search", qkey, before.id, [fi, lineno])
                        break
            if next_cursor:
                break
        for hit in matches:
            hit.pop("after_left", None)
            hit["context_before"] = [c for c in hit["context_before"] if not CREDENTIAL_RE.search(c["text"])]
            hit["context_after"] = [c for c in hit["context_after"] if not CREDENTIAL_RE.search(c["text"])]
        after = Snapshot(root)
        return self._envelope(project, before, after, matches=matches, match_count=len(matches),
                              no_match=(not matches and not timed_out), timed_out=timed_out,
                              withheld_matches=withheld, truncated=next_cursor is not None,
                              returned_range=None, next_cursor=next_cursor)

    # --- small helpers -----------------------------------------------------

    @staticmethod
    def _int(value: Any, low: int, high: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < low or value > high:
            raise RepoError("invalid_request")
        return value

    @classmethod
    def _page(cls, req: dict) -> int:
        return cls._int(req.get("limit", PAGE_DEFAULT), 1, PAGE_MAX)

    @staticmethod
    def _globs(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or len(value) > 8 or not all(isinstance(g, str) and 0 < len(g) <= 100 for g in value):
            raise RepoError("invalid_request")
        return list(value)

    @staticmethod
    def _glob(path: str, pattern: str) -> bool:
        import fnmatch
        return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pattern)

    @staticmethod
    def _qhash(kind: str, query: Any) -> str:
        return hashlib.sha256(json.dumps([kind, query], sort_keys=True).encode()).hexdigest()[:12]

    def _cursor_make(self, kind: str, query: Any, snap: str, position: Any) -> str:
        blob = json.dumps({"k": kind, "q": self._qhash(kind, query), "s": snap, "p": position}).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=")

    def _cursor_load(self, req: dict, kind: str, query: Any, snap: str) -> Any:
        cursor = req.get("cursor")
        if cursor is None:
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(str(cursor) + "=" * (-len(str(cursor)) % 4)))
        except (ValueError, TypeError):
            raise RepoError("invalid_request")
        if not isinstance(data, dict) or data.get("k") != kind or data.get("q") != self._qhash(kind, query):
            raise RepoError("invalid_request")
        if data.get("s") != snap:
            raise RepoError("snapshot_expired")
        return data.get("p")

    def _cursor_offset(self, req: dict, kind: str, query: Any, snap: str) -> int:
        position = self._cursor_load(req, kind, query, snap)
        if position is None:
            return 0
        if not isinstance(position, int) or position < 0:
            raise RepoError("invalid_request")
        return position

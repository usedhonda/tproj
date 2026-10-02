"""Authenticated discovery and binding for the unified local host agent.

The registry is evidence, not an identity claim: a record is usable only when
its process is still alive, has the recorded start time, and is an actual CC
or Codex process.  Callers may select an endpoint, but selectors never grant
authority by themselves.
"""
from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import re
import shlex
import sqlite3
import socket
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Iterable, Mapping


class IdentityError(ValueError):
    """Raised when local endpoint identity cannot be authenticated."""


_ALIAS = re.compile(r"^[A-Za-z0-9_-]+\.(cc|cdx)$")
_PLATFORMS = {"cc", "cdx"}
# Registry observations expire after 48h.  This is deliberately a bounded
# registration freshness window, not a process lifetime limit: long-lived
# sessions must renew their registry record to remain discoverable.
_MAX_RECORD_AGE = 172800
_ENDPOINT_NAMESPACE = uuid.UUID("2e529d9e-6ab4-4f8a-b94d-b54f6123b5ac")


def peer_credentials(sock: socket.socket) -> tuple[int, int]:
    """Return the kernel-observed (pid, uid) for a local Unix peer."""
    try:
        if sys.platform == "darwin":
            # macOS exposes LOCAL_PEERPID and getpeereid on different releases.
            level = getattr(socket, "SOL_LOCAL", 0)
            option = getattr(socket, "LOCAL_PEERPID", 2)
            raw = sock.getsockopt(level, option, 4)
            pid = int.from_bytes(raw, sys.byteorder, signed=True)
            if pid <= 1:
                raise IdentityError("invalid peer PID")
            if not hasattr(sock, "getpeereid"):
                try:
                    uid = ctypes.c_uint()
                    gid = ctypes.c_uint()
                    fn = ctypes.CDLL(None).getpeereid
                    fn.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
                    fn.restype = ctypes.c_int
                    if fn(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
                        return pid, int(uid.value)
                except (AttributeError, OSError):
                    pass
                # Python on newer macOS builds omits getpeereid but exposes
                # LOCAL_PEERCRED (xucred: version, uid, groups...).
                option = getattr(socket, "LOCAL_PEERCRED", None)
                if option is None:
                    raise IdentityError("getpeereid unavailable")
                cred = sock.getsockopt(getattr(socket, "SOL_SOCKET", 0), option, 12)
                if len(cred) < 8:
                    raise IdentityError("invalid peer credentials")
                uid = int.from_bytes(cred[4:8], sys.byteorder, signed=False)
            else:
                uid, _gid = sock.getpeereid()
            return pid, int(uid)
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        pid = int.from_bytes(raw[0:4], sys.byteorder, signed=True)
        uid = int.from_bytes(raw[4:8], sys.byteorder, signed=False)
        if pid <= 1:
            raise IdentityError("invalid peer PID")
        return pid, uid
    except (AttributeError, OSError, ValueError) as exc:
        raise IdentityError("local peer credentials unavailable") from exc


def _process_info(pid: int) -> dict[str, Any]:
    """Obtain process evidence; this small function is injectable in tests."""
    if pid <= 1:
        raise IdentityError("invalid process PID")
    if sys.platform.startswith("linux") and Path(f"/proc/{pid}/stat").exists():
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        # Linux starttime is stable within a boot; use it as the pid incarnation.
        ppid = int(stat[3])
        start = int(stat[21])
        uid = os.stat(f"/proc/{pid}").st_uid
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        cwd = str(Path(f"/proc/{pid}/cwd").resolve())
        return {"ppid": ppid, "pid_start": start, "uid": uid, "command": cmd, "cwd": cwd}
    result = subprocess.run(["ps", "-p", str(pid), "-o", "ppid=,lstart=,uid=,command="],
                            capture_output=True, text=True, check=False)
    fields = result.stdout.strip().split(None, 7)
    if result.returncode or len(fields) < 8:
        raise IdentityError("process unavailable")
    try:
        started = int(time.mktime(time.strptime(" ".join(fields[1:6]), "%a %b %d %H:%M:%S %Y")))
        uid = int(fields[6])
        cwd = ""  # Caller binding needs PID/start/UID/argv, not an lsof subprocess.
        return {"ppid": int(fields[0]), "pid_start": started, "uid": uid,
                "command": fields[7], "cwd": cwd}
    except (ValueError, OSError, IndexError) as exc:
        raise IdentityError("invalid process record") from exc


def _records(root: Path) -> Iterable[dict[str, Any]]:
    try:
        paths = root.glob("**/*.json")
    except OSError:
        return ()
    result = []
    for path in paths:
        if path.is_symlink():
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def _canonical(path: Any) -> str:
    return str(Path(str(path)).expanduser().resolve(strict=False))


def _platform(record: Mapping[str, Any]) -> str | None:
    alias = str(record.get("alias", ""))
    platform = str(record.get("platform", "")).lower()
    if platform not in _PLATFORMS and _ALIAS.fullmatch(alias):
        platform = alias.rsplit(".", 1)[1]
    return platform if platform in _PLATFORMS else None


def _runtime(record: Mapping[str, Any], session: str) -> str:
    return str(record.get("runtime_id") or record.get("conversation_id") or record.get("session_id") or session)


def native_conversation_context(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the native Codex conversation binding supplied to a tool caller.

    Shared app-servers multiplex conversations, so process ancestry alone is
    insufficient.  At least one native ID is required; when both are present
    they must agree with the same host-owned record.  Callers cannot invent a
    selector-only identity.  The values are deliberately opaque strings and
    are cross-checked against the host-owned registry by ``bind_caller``.
    """
    env = os.environ if env is None else env
    thread = str(env.get("CODEX_THREAD_ID", "")).strip()
    session = str(env.get("CODEX_SESSION_ID", "")).strip()
    if not thread and not session:
        return {}
    result = {}
    if thread:
        result["thread_id"] = thread
    if session:
        result["session_id"] = session
    # CODEX_* native context is only emitted by Codex callers; make that
    # platform binding explicit so a shared project with a live CC pane cannot
    # become an ambiguous adoption candidate.
    result["platform"] = "cdx"
    for key in ("CODEX_PROJECT_ID", "CODEX_PROJECT", "CODEX_PLATFORM"):
        value = str(env.get(key, "")).strip()
        if value:
            result[key.removeprefix("CODEX_").lower()] = value
    return result


def _conversation_matches(endpoint: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    """Match native IDs, requiring every supplied native field to agree."""
    if not context or not (context.get("thread_id") or context.get("session_id")):
        return False
    thread_values = {str(endpoint.get(key, "")) for key in ("thread_id", "conversation_id") if endpoint.get(key)}
    session_values = {str(endpoint.get(key, "")) for key in ("session_id", "session", "runtime_id") if endpoint.get(key)}
    if context.get("thread_id") and thread_values and str(context["thread_id"]) not in thread_values:
        return False
    if context.get("session_id") and session_values and str(context["session_id"]) not in session_values:
        return False
    if not ((context.get("thread_id") and str(context["thread_id"]) in thread_values)
            or (context.get("session_id") and str(context["session_id"]) in session_values)):
        return False
    project = context.get("project_id") or context.get("project")
    if project and str(endpoint.get("project_id", "")) != str(project) and str(endpoint.get("participant_id", "")).split(":", 1)[0] != str(project):
        return False
    platform = context.get("platform")
    return not platform or str(endpoint.get("platform", "")) == str(platform)


_NATIVE_THREAD_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _native_rollout_metadata(thread_id: str, sessions_root: Path) -> list[dict[str, Any]]:
    """Read one exact Codex TUI session header as bounded local evidence."""
    if not _NATIVE_THREAD_ID.fullmatch(thread_id) or not sessions_root.is_dir():
        return []
    pattern = f"rollout-*-{thread_id}.jsonl"
    found: list[dict[str, Any]] = []
    try:
        paths = sessions_root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/" + pattern)
    except OSError:
        return []
    for path in paths:
        try:
            relative = path.relative_to(sessions_root)
        except ValueError:
            continue
        if (path.is_symlink() or any((sessions_root / part).is_symlink() for part in relative.parts)
                or not path.is_file() or not path.name.lower().endswith(f"-{thread_id.lower()}.jsonl")):
            continue
        try:
            with path.open(encoding="utf-8") as stream:
                header = json.loads(stream.readline())
        except (OSError, UnicodeError, ValueError):
            continue
        payload = header.get("payload") if isinstance(header, dict) else None
        if not isinstance(header, dict) or header.get("type") != "session_meta" or not isinstance(payload, dict):
            continue
        if str(payload.get("id", "")) != thread_id:
            continue
        if payload.get("session_id") and str(payload["session_id"]) != thread_id:
            continue
        if str(payload.get("originator", "")) != "codex-tui" or str(payload.get("source", "")) != "vscode":
            continue
        cwd = payload.get("cwd")
        if not cwd:
            continue
        found.append({"host_id": "local", "thread_id": thread_id, "session_id": thread_id,
                      "cwd": cwd, "source_kind": "vscode-rollout", "source": "vscode",
                      "originator": "codex-tui", "metadata_path": str(path)})
    return found if len(found) == 1 else []


def native_thread_metadata(thread_id: str, db_path: str | os.PathLike | None = None,
                           sessions_root: str | os.PathLike | None = None) -> list[dict[str, Any]]:
    """Read host-local Codex thread metadata without opening a writer."""
    thread_id = str(thread_id or "").strip()
    if not thread_id:
        return []
    path = Path(db_path or (Path.home() / ".codex/sqlite/codex-dev.db"))
    catalog: list[dict[str, Any]] = []
    try:
        if path.is_file():
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                columns = {row[1] for row in db.execute("PRAGMA table_info(local_thread_catalog)")}
                session_column = ",session_id" if "session_id" in columns else ""
                rows = db.execute(
                    f"SELECT host_id,thread_id,cwd,source_kind,source_updated_at{session_column} FROM local_thread_catalog WHERE thread_id=?",
                    (thread_id,),
                ).fetchall()
            catalog = [dict(row) for row in rows
                       if row["host_id"] in (None, "local") and row["cwd"]
                       and str(row["source_kind"] or "cli") == "cli"]
    except (OSError, sqlite3.Error):
        catalog = []
    if catalog:
        return catalog
    root = Path(sessions_root) if sessions_root is not None else Path.home() / ".codex/sessions"
    return _native_rollout_metadata(thread_id, root)


def adopt_native_conversation(endpoints: Iterable[Mapping[str, Any]], context: Mapping[str, Any],
                              metadata: Iterable[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Annotate a unique live tmux endpoint from native thread catalog evidence."""
    endpoint_list = [dict(endpoint) for endpoint in endpoints]
    thread = str(context.get("thread_id", "")).strip()
    if not thread:
        return endpoint_list
    records = list(metadata) if metadata is not None else native_thread_metadata(thread)
    records = [row for row in records if str(row.get("source_kind") or "cli") in {"cli", "vscode-rollout"}]
    projects = {_canonical(row.get("cwd")) for row in records if row.get("cwd")}
    if len(projects) != 1:
        return endpoint_list
    proven_sessions = {str(row.get("session_id")) for row in records if row.get("session_id")}
    # The current catalog schema has no session column.  In that case a pair
    # of distinct caller IDs cannot be correlated safely; only the observed
    # equal-ID form is admissible without an explicit catalog mapping.
    if context.get("session_id") and not proven_sessions and str(context["session_id"]) != thread:
        return endpoint_list
    candidates = []
    for endpoint in endpoint_list:
        platform = str(endpoint.get("platform", ""))
        if platform != str(context.get("platform") or "cdx"):
            continue
        project_path = endpoint.get("project_path") or endpoint.get("path")
        if endpoint.get("thread_id") and str(endpoint.get("thread_id")) != thread:
            continue
        if context.get("session_id") and endpoint.get("session_id") and str(endpoint.get("session_id")) != str(context["session_id"]):
            continue
        if context.get("session_id") and proven_sessions and str(context["session_id"]) not in proven_sessions:
            continue
        if project_path and _canonical(project_path) == next(iter(projects)):
            candidates.append(endpoint)
    if len(candidates) != 1:
        return endpoint_list
    adopted = endpoint_list
    selected = candidates[0]
    for endpoint in adopted:
        if endpoint.get("endpoint_id") == selected.get("endpoint_id"):
            endpoint["thread_id"] = thread
            if context.get("session_id") and (proven_sessions or str(context["session_id"]) == thread):
                endpoint["session_id"] = str(context["session_id"])
            break
    return adopted


def _endpoint_id(host: str, runtime: str, session: str, pid_start: int) -> str:
    return str(uuid.uuid5(_ENDPOINT_NAMESPACE, "\x1f".join((host, runtime, session, str(pid_start)))))


def discover_endpoints(registry_root: str | os.PathLike[str], host_id: str,
                       projects: Iterable[Mapping[str, Any]], *, now: int | None = None,
                       inspect_process: Callable[[int], Mapping[str, Any]] = _process_info) -> list[dict[str, Any]]:
    """Discover only live, non-stale local CC/Codex endpoint incarnations."""
    now = int(time.time() if now is None else now)
    project_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        if str(project.get("host_id", "")) != host_id or not project.get("path"):
            continue
        project_map[(host_id, _canonical(project["path"]))] = project
    found: list[dict[str, Any]] = []
    for record in _records(Path(registry_root)):
        alias = str(record.get("alias", ""))
        platform = _platform(record)
        pid, start, observed = record.get("pid"), record.get("pid_start"), record.get("observed_at")
        session = str(record.get("session") or record.get("session_id") or "")
        path = record.get("project") or record.get("path") or record.get("cwd")
        if not (_ALIAS.fullmatch(alias) and platform and session and isinstance(pid, int) and pid > 1
                and isinstance(start, int) and start > 0 and isinstance(observed, (int, float))
                and observed <= now and now - observed <= _MAX_RECORD_AGE and path):
            continue
        project = project_map.get((host_id, _canonical(path)))
        if not project:
            continue
        try:
            live = dict(inspect_process(pid))
        except (IdentityError, OSError, ValueError, KeyError):
            continue
        command = str(live.get("command", "")).lower()
        actual_start = live.get("pid_start")
        if actual_start != start or live.get("uid") != os.getuid():
            continue
        # Require process evidence, not merely a stale pane/model tag.
        needles = ("claude", "anthropic") if platform == "cc" else ("codex", "openai")
        if not any(token in command for token in needles):
            continue
        runtime = _runtime(record, session)
        found.append({
            "endpoint_id": _endpoint_id(host_id, runtime, session, start),
            "participant_id": f"{project.get('project_id')}:{platform}",
            "project_id": str(project.get("project_id")), "host_id": host_id,
            "address": f"{project.get('alias')}.{platform}", "session": session,
            "pane": record.get("pane") or record.get("pane_id") or record.get("tmux_pane"),
            "pid": pid, "pid_start": start, "runtime_id": runtime, "platform": platform,
            "project_path": _canonical(path),
            "thread_id": record.get("thread_id") or record.get("conversation_id"),
            "session_id": record.get("session_id") or record.get("codex_session_id"),
        })
    return sorted(found, key=lambda item: item["endpoint_id"])


def _tmux_rows() -> list[dict[str, str]]:
    """Read tproj pane tags without treating tags as process identity."""
    fmt = "#{session_name}\t#{pane_id}\t#{pane_pid}\t#{pane_current_path}\t#{@project}\t#{@alias}\t#{@role}"
    result = subprocess.run(["tmux", "list-panes", "-a", "-F", fmt],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        return []
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        session, pane, pane_pid, current_path, project, alias, role = fields
        if pane_pid.isdigit():
            rows.append({"session": session, "pane": pane, "pane_pid": pane_pid,
                         "current_path": current_path, "project": project,
                         "alias": alias, "role": role})
    return rows


def _process_descendants(root_pid: int) -> list[int]:
    """Return process descendants of a tmux shell, excluding the shell itself."""
    result = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, check=False)
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and all(item.isdigit() for item in fields):
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found: list[int] = []
    queue = list(children.get(root_pid, []))
    while queue:
        pid = queue.pop(0)
        found.append(pid)
        queue.extend(children.get(pid, []))
    return found


def discover_tmux_endpoints(host_id: str, projects: Iterable[Mapping[str, Any]],
                            existing: Iterable[Mapping[str, Any]] = (), *,
                            panes: Callable[[], Iterable[Mapping[str, Any]]] = _tmux_rows,
                            descendants: Callable[[int], Iterable[int]] = _process_descendants,
                            inspect_process: Callable[[int], Mapping[str, Any]] = _process_info) -> list[dict[str, Any]]:
    """Discover unmatched local agents from authenticated tproj tmux panes.

    Pane metadata selects candidates only. A live same-UID Claude/Codex process
    descendant, with its PID incarnation, is required before an endpoint is
    emitted. Existing registry participants win and are never duplicated.
    """
    project_by_path = {}
    project_by_alias = {}
    for project in projects:
        if not isinstance(project, Mapping) or str(project.get("host_id", "")) != host_id:
            continue
        if project.get("path"):
            project_by_path[_canonical(project["path"])] = project
        if project.get("alias"):
            project_by_alias[str(project["alias"])] = project
    occupied = {str(item.get("participant_id")) for item in existing if item.get("participant_id")}
    found = []
    for pane in panes():
        role = str(pane.get("role", "")).lower()
        platform = "cc" if role.startswith("claude-") else "cdx" if role.startswith("codex-") else None
        if not platform:
            continue
        raw_project = str(pane.get("project") or pane.get("current_path") or "")
        if raw_project.startswith("ssh://"):
            continue
        project = project_by_path.get(_canonical(raw_project)) or project_by_alias.get(str(pane.get("alias", "")))
        if not project:
            continue
        participant_id = f"{project.get('project_id')}:{platform}"
        # Registry-backed participants are authoritative.  For an unmatched
        # standalone participant, however, retain every live candidate from a
        # distinct pane: downstream binding/target resolution must reject an
        # ambiguous identity instead of silently choosing the first pane.
        if participant_id in occupied:
            continue
        try:
            root_pid = int(pane.get("pane_pid", 0))
        except (TypeError, ValueError):
            continue
        for pid in descendants(root_pid):
            try:
                info = dict(inspect_process(int(pid)))
            except (IdentityError, OSError, ValueError, KeyError):
                continue
            command = str(info.get("command", "")).lower()
            if info.get("uid") != os.getuid() or any(token in command for token in ("ssh ", "ssh-", "proxycommand")):
                continue
            needles = ("claude", "anthropic") if platform == "cc" else ("codex", "openai")
            start = info.get("pid_start")
            if not isinstance(start, int) or start <= 0 or not any(token in command for token in needles):
                continue
            session = str(pane.get("session", ""))
            pane_id = str(pane.get("pane", ""))
            runtime = f"tmux:{session}:{pane_id}:{start}"
            found.append({
                "endpoint_id": _endpoint_id(host_id, runtime, session, start),
                "participant_id": participant_id, "project_id": str(project.get("project_id")),
                "host_id": host_id, "address": f"{project.get('alias')}.{platform}",
                "session": session, "pane": pane_id, "pid": int(pid), "pid_start": start,
                "runtime_id": runtime, "platform": platform,
                "project_path": _canonical(raw_project),
                "thread_id": pane.get("thread_id") or pane.get("conversation_id"),
                "session_id": pane.get("session_id") or pane.get("codex_session_id"),
            })
            break
    return sorted(found, key=lambda item: item["endpoint_id"])


def bind_caller(pid: int, uid: int, endpoints: Iterable[Mapping[str, Any]], *, session: str | None = None,
                claimed_alias: str | None = None, conversation: Mapping[str, Any] | None = None,
                inspect_process: Callable[[int], Mapping[str, Any]] = _process_info) -> dict[str, Any]:
    """Bind a socket peer to exactly one endpoint through live PID ancestry."""
    if pid <= 1 or uid < 0:
        raise IdentityError("invalid caller credentials")
    candidates = [dict(endpoint) for endpoint in endpoints
                  if (session is None or endpoint.get("session") == session)
                  and (claimed_alias is None or endpoint.get("address") == claimed_alias)]
    if not candidates:
        raise IdentityError("no endpoint matches selectors")
    seen: set[int] = set()
    current = pid
    matches: list[dict[str, Any]] = []
    app_server_seen = False
    app_server_pids: set[int] = set()
    for _ in range(64):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        try:
            info = dict(inspect_process(current))
        except (IdentityError, OSError, ValueError, KeyError):
            break
        if info.get("uid") != uid:
            raise IdentityError("caller UID mismatch")
        command = str(info.get("command", "")).lower()
        # An app-server may execute tools for unrelated conversations. Its
        # launcher ancestry proves process ownership, not conversation identity.
        # Reject before matching this process or walking to its launcher, even
        # when selectors or a descendant endpoint appear to disambiguate it.
        try:
            argv = shlex.split(command)
        except ValueError:
            # ps output is not guaranteed to preserve shell quoting. A malformed
            # later argument must not conceal a plain executable/subcommand pair.
            argv = command.split()
        if argv and Path(argv[0]).name in {"node", "node.exe"}:
            argv = argv[1:]
        if (len(argv) >= 2 and any(Path(token).name in {"codex", "codex.exe", "codex.js"} for token in argv[:2])
                and "app-server" in argv[1:]):
            app_server_seen = True
            app_server_pids.add(current)
        for endpoint in candidates:
            if endpoint.get("pid") == current and endpoint.get("pid_start") == info.get("pid_start"):
                platform = endpoint.get("platform")
                needles = ("claude", "anthropic") if platform == "cc" else ("codex", "openai")
                if not any(token in command for token in needles):
                    raise IdentityError("caller is not an agent process")
                matches.append(endpoint)
        parent = info.get("ppid")
        if not isinstance(parent, int) or parent == current:
            break
        current = parent
    if app_server_seen:
        if not conversation:
            raise IdentityError("shared Codex app-server ancestry cannot authenticate caller without native conversation context")
        # Native IDs select among endpoint records, but cannot bypass the
        # same live process ancestry proof established above.
        matches = []
        for item in candidates:
            if not _conversation_matches(item, conversation):
                continue
            try:
                live = dict(inspect_process(int(item["pid"])))
            except (IdentityError, OSError, ValueError, KeyError, TypeError):
                continue
            if live.get("pid_start") != item.get("pid_start") or live.get("uid") != uid:
                continue
            command = str(live.get("command", "")).lower()
            if item.get("pid") not in app_server_pids and not any(token in command for token in ("codex", "openai")):
                continue
            matches.append(item)
    unique = {item["endpoint_id"]: item for item in matches}
    if len(unique) != 1:
        raise IdentityError("endpoint binding is ambiguous" if len(unique) > 1 else "agent ancestor absent")
    return next(iter(unique.values()))


def same_live_process_family(existing: Mapping[str, Any], candidate: Mapping[str, Any], *,
                             inspect_process: Callable[[int], Mapping[str, Any]] = _process_info) -> bool:
    """Return whether two endpoint observations bind to one live process tree.

    This is intentionally stricter than matching an alias or runtime label.  Both
    recorded PID incarnations must still verify, and the candidate must be an
    ancestor/descendant of the existing process (or vice versa) while all
    participant location attributes remain unchanged.
    """
    keys = ("participant_id", "host_id", "session", "pane", "platform")
    if any(str(existing.get(key, "")) != str(candidate.get(key, "")) for key in keys):
        return False
    try:
        old_pid, new_pid = int(existing["pid"]), int(candidate["pid"])
        old_start, new_start = int(existing["pid_start"]), int(candidate["pid_start"])
    except (KeyError, TypeError, ValueError):
        return False
    if old_pid <= 1 or new_pid <= 1:
        return False
    try:
        old_info = dict(inspect_process(old_pid))
        new_info = dict(inspect_process(new_pid))
    except (IdentityError, OSError, ValueError, KeyError):
        return False
    if (old_info.get("pid_start") != old_start or new_info.get("pid_start") != new_start
            or old_info.get("uid") != os.getuid() or new_info.get("uid") != os.getuid()):
        return False
    if old_pid == new_pid:
        return old_start == new_start
    if old_info.get("uid") != new_info.get("uid"):
        return False

    def is_ancestor(ancestor_pid: int, descendant_pid: int) -> bool:
        seen: set[int] = set()
        current = descendant_pid
        for _ in range(64):
            if current <= 1 or current in seen:
                return False
            if current == ancestor_pid:
                return True
            seen.add(current)
            try:
                info = dict(inspect_process(current))
            except (IdentityError, OSError, ValueError, KeyError):
                return False
            if info.get("uid") != os.getuid():
                return False
            parent = info.get("ppid")
            if not isinstance(parent, int) or parent == current:
                return False
            current = parent
        return False

    return is_ancestor(old_pid, new_pid) or is_ancestor(new_pid, old_pid)

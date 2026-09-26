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
        })
    return sorted(found, key=lambda item: item["endpoint_id"])


def bind_caller(pid: int, uid: int, endpoints: Iterable[Mapping[str, Any]], *, session: str | None = None,
                claimed_alias: str | None = None, inspect_process: Callable[[int], Mapping[str, Any]] = _process_info) -> dict[str, Any]:
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
        for endpoint in candidates:
            if endpoint.get("pid") == current and endpoint.get("pid_start") == info.get("pid_start"):
                command = str(info.get("command", "")).lower()
                platform = endpoint.get("platform")
                needles = ("claude", "anthropic") if platform == "cc" else ("codex", "openai")
                if not any(token in command for token in needles):
                    raise IdentityError("caller is not an agent process")
                matches.append(endpoint)
        parent = info.get("ppid")
        if not isinstance(parent, int) or parent == current:
            break
        current = parent
    unique = {item["endpoint_id"]: item for item in matches}
    if len(unique) != 1:
        raise IdentityError("endpoint binding is ambiguous" if len(unique) > 1 else "agent ancestor absent")
    return next(iter(unique.values()))

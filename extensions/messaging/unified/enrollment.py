"""Explicit, transactional SSH enrollment for the unified mailbox mesh.

Enrollment is deliberately separate from runtime startup.  It exchanges host
identity over an authenticated SSH stdin channel, admits only a complete
online mesh, stages every member before committing any topology, and never
touches tmux/agent processes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import uuid
from typing import Any, Callable, Iterable, Mapping

MAX_HOSTS = 32
SSH_TIMEOUT = 8


class EnrollmentError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.chmod(raw, 0o600); os.replace(raw, path)
    finally:
        if os.path.exists(raw): os.unlink(raw)


def _rpc(socket_path: str, request: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(SSH_TIMEOUT)
        sock.connect(socket_path)
        sock.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
        raw = sock.makefile("rb").readline(262145)
    if not raw.endswith(b"\n"):
        raise EnrollmentError("local messaging service returned an invalid response")
    response = json.loads(raw)
    if not response.get("ok"):
        raise EnrollmentError(str(response.get("error", {}).get("message", "local messaging unavailable")))
    return response.get("result") or {}


def _ssh_aliases(path: Path | None = None) -> list[str]:
    """Read explicit SSH Host aliases only; never mutate SSH configuration."""
    path = path or (Path.home() / ".ssh/config")
    aliases: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.strip().split()
            if len(fields) >= 2 and fields[0].lower() == "host":
                for alias in fields[1:]:
                    if alias and not any(ch in alias for ch in "*?!") and alias not in aliases:
                        aliases.append(alias)
    except OSError:
        pass
    return aliases


def _remote(alias: str, request: dict[str, Any], runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> dict[str, Any]:
    if not alias or any(ch in alias for ch in "\r\n;|&"):
        raise EnrollmentError("invalid SSH alias")
    run = runner or subprocess.run
    command = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_TIMEOUT}", "-T", "--", alias,
               'python3 "$HOME/lib/tproj-msg-unified/enrollment.py" --control']
    try:
        result = run(command, input=json.dumps(request), capture_output=True, text=True,
                     timeout=SSH_TIMEOUT + 2, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnrollmentError(f"host {alias} is unreachable") from exc
    if result.returncode:
        raise EnrollmentError(f"host {alias} rejected enrollment control")
    try:
        response = json.loads(result.stdout)
    except ValueError as exc:
        raise EnrollmentError(f"host {alias} returned invalid enrollment response") from exc
    if not response.get("ok"):
        raise EnrollmentError(str(response.get("error", "remote enrollment rejected")))
    return response.get("result") or {}


def local_description(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home(); config_dir = home / ".config/tproj"
    host = _read_json(config_dir / "msg-host.json")
    hub = _read_json(config_dir / "msg-hub.json")
    host_id, token, socket_path = host.get("host_id"), host.get("host_token"), host.get("hub_socket") or hub.get("socket")
    if not isinstance(host_id, str) or not host_id or not isinstance(token, str) or not token or not isinstance(socket_path, str):
        raise EnrollmentError("local messaging runtime is not initialized; run tproj-msg-unified setup")
    directory = _rpc(socket_path, {"op": "directory_list", "host_id": host_id, "host_token": token})
    projects = [{k: p.get(k) for k in ("project_id", "alias", "host_id", "path")} for p in directory.get("projects", [])]
    return {"host_id": host_id, "host_token": token, "projects": projects,
            "aliases": sorted(str(p["alias"]) for p in projects if p.get("alias"))}


def admit(descriptions: Iterable[Mapping[str, Any]], management_host_id: str) -> list[dict[str, Any]]:
    hosts = [dict(item) for item in descriptions]
    if not hosts or len(hosts) > MAX_HOSTS:
        raise EnrollmentError("enrollment requires one to 32 initialized hosts")
    ids = [str(item.get("host_id", "")) for item in hosts]
    if any(not ident for ident in ids) or len(set(ids)) != len(ids):
        raise EnrollmentError("host identity is missing or duplicated")
    if management_host_id not in ids:
        raise EnrollmentError("management host is not in the admitted mesh")
    aliases: set[str] = set(); owners: dict[str, str] = {}
    for item in hosts:
        for alias in item.get("aliases", []):
            alias = str(alias)
            if not alias or alias in aliases:
                raise EnrollmentError(f"project alias is duplicated: {alias}")
            aliases.add(alias); owners[alias] = str(item["host_id"])
        if item.get("online") is False:
            raise EnrollmentError(f"host {item['host_id']} is offline")
    return hosts


def topology(descriptions: Iterable[Mapping[str, Any]], management_host_id: str, aliases: Mapping[str, str]) -> dict[str, Any]:
    hosts = admit(descriptions, management_host_id)
    return {"version": 1, "mode": "multi", "management_host_id": management_host_id,
            "local": {"id": management_host_id},
            "hosts": [{"id": str(h["host_id"]), "ssh_alias": str(h.get("ssh_alias", h["host_id"])),
                       "display_name": str(h.get("display_name", h["host_id"])),
                       "kind": str(h.get("kind", "mac"))} for h in hosts],
            "projects": dict(aliases)}


def _control(home: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    action = request.get("action")
    if action == "describe":
        return local_description(home)
    config_dir = home / ".config/tproj"; txn = str(request.get("txn", ""))
    if not txn or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in txn):
        raise EnrollmentError("invalid enrollment transaction")
    pending = config_dir / f"enrollment.{txn}.pending.json"
    if action == "prepare":
        payload = dict(request.get("topology") or {})
        host_config = _read_json(config_dir / "msg-host.json")
        if host_config.get("host_id"):
            payload["local"] = {"id": str(host_config["host_id"])}
        _atomic_json(pending, {"txn": txn, "topology": payload, "hosts": request.get("hosts", {})})
        return {"prepared": True, "txn": txn}
    if action == "commit":
        committed = config_dir / f"enrollment.{txn}.committed.json"
        if committed.exists(): return {"committed": True, "txn": txn, "retry": True}
        saved = _read_json(pending)
        if saved.get("txn") != txn: raise EnrollmentError("enrollment prepare record is missing")
        _atomic_json(config_dir / "topology.json", saved["topology"])
        hub = _read_json(config_dir / "msg-hub.json"); host = _read_json(config_dir / "msg-host.json")
        hub["hosts"] = dict(saved.get("hosts") or {}); hub["topology_path"] = str(config_dir / "topology.json")
        _atomic_json(config_dir / "msg-hub.json", hub)
        _atomic_json(committed, {"txn": txn})
        pending.unlink(missing_ok=True)
        return {"committed": True, "txn": txn}
    if action in ("abort", "recover"):
        if (config_dir / f"enrollment.{txn}.committed.json").exists():
            return {"committed": True, "txn": txn, "retry": True}
        pending.unlink(missing_ok=True); return {"aborted": True, "txn": txn}
    raise EnrollmentError("unsupported enrollment control action")


def enroll(alias: str, *, home: Path | None = None, return_host: bool = False,
           remote: Callable[[str, dict[str, Any]], dict[str, Any]] = _remote) -> dict[str, Any]:
    local = local_description(home)
    cfg_dir = (home or Path.home()) / ".config/tproj"
    prior = _read_json(cfg_dir / "topology.json")
    prior_hosts = prior.get("hosts", []) if isinstance(prior.get("hosts"), list) else []
    peers = [alias] + [str(item.get("ssh_alias")) for item in prior_hosts
                       if item.get("ssh_alias") and item.get("ssh_alias") != alias]
    expected_ids = {str(item.get("id")) for item in prior_hosts if item.get("id")}
    descriptions = [dict(local, online=True, ssh_alias="local", display_name=local["host_id"], kind="local")]
    for candidate in peers[:MAX_HOSTS - 1]:
        try:
            item = remote(candidate, {"action": "describe"})
        except EnrollmentError:
            if candidate == alias: raise
            continue
        if expected_ids and str(item.get("host_id")) not in expected_ids and candidate != alias:
            continue
        item.update(online=True, ssh_alias=candidate)
        descriptions.append(item)
    if len(descriptions) < 2:
        raise EnrollmentError("no initialized peer host was admitted")
    aliases: dict[str, str] = {}
    for item in descriptions:
        for project in item.get("projects", []): aliases[str(project["alias"])] = str(item["host_id"])
    manager = str(prior.get("management_host_id") or local["host_id"])
    top = topology(descriptions, manager, aliases)
    tokens = {str(item["host_id"]): str(item["host_token"]) for item in descriptions}
    txn = uuid.uuid4().hex
    prepared: list[str] = []
    try:
        for item in descriptions:
            req = {"action": "prepare", "txn": txn, "topology": top, "hosts": tokens}
            if item["host_id"] == local["host_id"]: _control(home or Path.home(), req)
            else: remote(str(item["ssh_alias"]), req)
            prepared.append(str(item["host_id"]))
        for item in descriptions:
            req = {"action": "commit", "txn": txn}
            if item["host_id"] == local["host_id"]: _control(home or Path.home(), req)
            else: remote(str(item["ssh_alias"]), req)
    except EnrollmentError:
        for item in descriptions:
            if str(item["host_id"]) in prepared and str(item["host_id"]) != local["host_id"]:
                try: remote(str(item["ssh_alias"]), {"action": "recover", "txn": txn})
                except EnrollmentError: pass
        raise
    return {"enrolled": True, "host_count": len(descriptions), "management_host_id": local["host_id"],
            **({"return_host": alias} if return_host else {})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("alias", nargs="?"); parser.add_argument("--control", action="store_true"); parser.add_argument("--return-host", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.control:
            request = json.load(__import__("sys").stdin); result = _control(Path.home(), request); print(json.dumps({"ok": True, "result": result}))
        else:
            if not args.alias: raise EnrollmentError("SSH alias is required")
            result = enroll(args.alias, return_host=args.return_host); print(json.dumps(result, sort_keys=True))
        return 0
    except EnrollmentError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=__import__("sys").stderr); return 2


if __name__ == "__main__": raise SystemExit(main())

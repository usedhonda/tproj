"""Provision the local standalone unified messaging runtime.

This module only writes local configuration and LaunchAgent manifests. It never
stops or restarts a service (or any tproj/agent session); launchctl is left to
the caller after reviewing the generated files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid
from typing import Any


def _atomic_json(path: Path, value: dict[str, Any], dry_run: bool) -> bool:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if path.exists() and path.read_bytes() == data:
        return False
    if dry_run:
        print(f"WOULD WRITE {path}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(raw, 0o600); os.replace(raw, path)
    finally:
        if os.path.exists(raw): os.unlink(raw)
    return True


def _atomic_text(path: Path, data: str, mode: int, dry_run: bool) -> bool:
    encoded = data.encode()
    if path.exists() and path.read_bytes() == encoded and (path.stat().st_mode & 0o777) == mode:
        return False
    if dry_run:
        print(f"WOULD WRITE {path}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.chmod(raw, mode); os.replace(raw, path)
    finally:
        if os.path.exists(raw): os.unlink(raw)
    return True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _local_id(config_dir: Path, topology_path: Path) -> str:
    topology = _read_json(topology_path)
    local = topology.get("local") if isinstance(topology.get("local"), dict) else {}
    if local.get("id"):
        return str(local["id"])
    old = _read_json(config_dir / "msg-host.json")
    if old.get("host_id"):
        return str(old["host_id"])
    return str(uuid.uuid4())


def _remote_enrollment_detected(config_dir: Path) -> bool:
    client = _read_json(config_dir / "msg-client.json")
    if client.get("active") is True or (config_dir / "msg-client.enrolled").exists():
        return True
    hub = _read_json(config_dir / "msg-hub.json")
    hosts = hub.get("hosts")
    federation = hub.get("federation")
    return (isinstance(hosts, dict) and len(hosts) > 1) or bool(federation and federation.get("peers"))


def _projects(home: Path, host_id: str) -> list[dict[str, str]]:
    workspace = home / ".config/tproj/workspace.yaml"
    if not workspace.exists():
        return []
    try:
        proc = subprocess.run(["yq", "-o=json", str(workspace)], capture_output=True, text=True, check=True)
        payload = json.loads(proc.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        return []
    result = []
    for item in payload.get("projects", []) if isinstance(payload, dict) else []:
        if isinstance(item, str): item = {"path": item}
        if not isinstance(item, dict) or item.get("type", "local") != "local":
            continue
        path = os.path.abspath(os.path.expanduser(str(item.get("path", ""))))
        if not path.startswith("/"): continue
        alias = str(item.get("alias") or Path(path).name)
        project_id = str(item.get("project_id") or ("p-" + hashlib.sha256(f"{host_id}\0{path}".encode()).hexdigest()[:24]))
        result.append({"project_id": project_id, "alias": alias, "host_id": host_id, "path": path})
    return result


def _plist(label: str, script: Path, config: Path) -> str:
    return """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>{python}</string><string>{script}</string><string>--config</string><string>{config}</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
""".format(label=label, python=sys.executable, script=script, config=config)


def setup(home: Path | None = None, refresh: bool = False, dry_run: bool = False, migrate: bool = False) -> dict[str, Any]:
    home = home or Path.home(); config_dir = home / ".config/tproj"; state = home / ".local/share/tproj-msg-unified"
    topology_path = config_dir / "topology.json"
    if _remote_enrollment_detected(config_dir) and not migrate:
        raise RuntimeError("existing remote-central enrollment detected; rerun with --migrate to preserve and adapt it")
    host_id = _local_id(config_dir, topology_path)
    old_host = _read_json(config_dir / "msg-host.json")
    token = str(old_host.get("host_token") or secrets.token_urlsafe(32))
    old_hub = _read_json(config_dir / "msg-hub.json")
    admin = str(old_hub.get("admin_token") or secrets.token_urlsafe(32))
    socket = state / "hub.sock"; journal = state / "host.db"; hub_db = state / "hub.db"
    hub = dict(old_hub); hub.update({"host_id": host_id, "hosts": dict(old_hub.get("hosts") or {}, **{host_id: token}), "admin_token": admin, "topology_path": str(topology_path), "socket": str(socket), "db": str(hub_db)})
    host = dict(old_host); host.update({"host_id": host_id, "host_token": token, "hub_socket": str(socket), "journal": str(journal), "registry": str(home / ".cache/tproj-model-role")})
    client = _read_json(config_dir / "msg-client.json"); client.update({"host_id": host_id, "host_token": token, "hub_socket": str(socket), "active": bool(client.get("active", False))})
    changed = [_atomic_json(config_dir / "msg-hub.json", hub, dry_run), _atomic_json(config_dir / "msg-host.json", host, dry_run), _atomic_json(config_dir / "msg-client.json", client, dry_run)]
    projects = _projects(home, host_id)
    if projects:
        hub["projects"] = projects
    lib = home / "lib/tproj-msg-unified"; hub_script = lib / "hub.py"; host_script = lib / "host.py"
    agents = home / "Library/LaunchAgents"
    changed += [_atomic_text(agents / "local.tproj.msg-unified-hub.plist", _plist("local.tproj.msg-unified-hub", hub_script, config_dir / "msg-hub.json"), 0o644, dry_run), _atomic_text(agents / "local.tproj.msg-unified-host.plist", _plist("local.tproj.msg-unified-host", host_script, config_dir / "msg-host.json"), 0o644, dry_run)]
    if projects and not dry_run:
        try:
            from hub import Hub
            mailbox = Hub(str(hub_db), hub)
            revision = mailbox.directory_list()["revision"]
            mailbox.directory_import({"admin_token": admin, "projects": projects, "services": [], "expected_revision": revision})
            mailbox.close()
        except (ImportError, OSError, ValueError):
            # The runtime remains usable; the host will reconcile its directory
            # on first refresh once the installed hub is available.
            pass
    return {"host_id": host_id, "changed": sum(changed), "projects": len(projects), "socket": str(socket), "dry_run": dry_run}


def status(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home(); config_dir = home / ".config/tproj"
    hub = _read_json(config_dir / "msg-hub.json"); host = _read_json(config_dir / "msg-host.json")
    return {"configured": bool(hub and host), "host_id": host.get("host_id"), "socket": host.get("hub_socket"), "remote_enrollment": _remote_enrollment_detected(config_dir), "hub_config": str(config_dir / "msg-hub.json"), "host_config": str(config_dir / "msg-host.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup"); p.add_argument("--refresh", action="store_true"); p.add_argument("--migrate", action="store_true"); p.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true")
    d = sub.add_parser("dry-run"); d.add_argument("--refresh", action="store_true")
    sub.add_parser("enroll").add_argument("alias")
    args = parser.parse_args(argv)
    if args.command == "status": print(json.dumps(status(), sort_keys=True)); return 0
    if args.command == "enroll":
        try:
            from . import enrollment  # parent-owned implementation
        except ImportError:
            import enrollment  # type: ignore
        return enrollment.main([args.alias])
    try: result = setup(refresh=getattr(args, "refresh", False), dry_run=args.command == "dry-run" or getattr(args, "dry_run", False), migrate=getattr(args, "migrate", False))
    except RuntimeError as exc: print(str(exc), file=sys.stderr); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())

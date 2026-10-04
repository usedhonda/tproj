"""Provision and activate the local standalone unified messaging runtime.

This module writes local configuration and LaunchAgent manifests and may
activate the two local messaging labels through launchctl. It never stops or
restarts a tproj/agent session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import plistlib
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


def _remote_enrollment_detected(config_dir: Path, expected_socket: Path | None = None) -> bool:
    client = _read_json(config_dir / "msg-client.json")
    if client.get("active") is True or (config_dir / "msg-client.enrolled").exists():
        if expected_socket is None or client.get("hub_socket") != str(expected_socket):
            return True
    hub = _read_json(config_dir / "msg-hub.json")
    hosts = hub.get("hosts")
    federation = hub.get("federation")
    # A local federated hub is valid standalone state once it has an owner
    # host_id. Only the legacy ownerless/central shape requires migration.
    return (not hub.get("host_id")) and ((isinstance(hosts, dict) and len(hosts) > 1) or bool(federation and federation.get("peers")))


def _legacy_migration_ready(state: Path, host_id: str) -> bool:
    """Return true only for a pre-split DB explicitly owned by this host.

    Open the database read-only: a missing or malformed marker must not cause
    SQLite to create a file before the migration guard has passed.
    """
    database = state / "hub.db"
    if not database.is_file():
        return False
    try:
        uri = f"file:{database}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='owner_host_id'"
            ).fetchone()
        return row is not None and str(row[0]) == host_id
    except (OSError, sqlite3.Error):
        return False


def _workspace_payload(home: Path) -> dict | None:
    workspace = home / ".config/tproj/workspace.yaml"
    if not workspace.exists():
        return None
    for command in (["yq", "-o=json", ".", str(workspace)], ["yq", ".", str(workspace)]):
        try:
            proc = subprocess.run(command, capture_output=True, text=True, check=True)
            return json.loads(proc.stdout)
        except (OSError, subprocess.CalledProcessError, ValueError): pass
    raise RuntimeError('Cannot read workspace.yaml; install yq and check the YAML syntax')


def _projects(home: Path, host_id: str) -> list[dict[str, str]]:
    payload = _workspace_payload(home)
    if payload is None:
        return []
    existing_by_path = {}
    database = home / '.local/share/tproj-msg-unified/hub.db'
    if database.exists():
        import sqlite3
        with sqlite3.connect(str(database)) as conn:
            try: existing_by_path = {r[0]:r[1] for r in conn.execute('SELECT path,project_id FROM projects WHERE host_id=?',(host_id,))}
            except sqlite3.OperationalError: pass
    result = []
    for item in payload.get("projects", []) if isinstance(payload, dict) else []:
        if isinstance(item, str): item = {"path": item}
        if not isinstance(item, dict) or item.get("type", "local") != "local":
            continue
        if not item.get('path'): continue
        path = os.path.abspath(os.path.expanduser(str(item["path"])))
        if not path.startswith("/"): continue
        alias = str(item.get("alias") or Path(path).name)
        project_id = str(item.get("project_id") or existing_by_path.get(path) or ("p-" + hashlib.sha256(f"{host_id}\0{path}".encode()).hexdigest()[:24]))
        result.append({"project_id": project_id, "alias": alias, "host_id": host_id, "path": path})
    return result


def _plist(label: str, script: Path, config: Path, extra: list[str] | None = None) -> str:
    args = [sys.executable, str(script), "--config", str(config)] + (extra or [])
    return plistlib.dumps({"Label": label, "ProgramArguments": args, "RunAtLoad": True, "KeepAlive": True,
                          "EnvironmentVariables": {"PATH": str(Path.home()/"bin")+":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
                          "StandardErrorPath": str(config.parent/(label+".err"))}, fmt=plistlib.FMT_XML).decode()


def _activate(home: Path, manifests: list[Path], changed: bool, no_start: bool, dry_run: bool) -> list[str]:
    if no_start or dry_run:
        return ["skipped"]
    uid = str(os.getuid()); results = []
    for manifest, label in zip(manifests, ("local.tproj.msg-unified-hub", "local.tproj.msg-unified-host")):
        try:
            listed = subprocess.run(["/bin/launchctl", "print", f"gui/{uid}/{label}"], capture_output=True)
        except OSError:
            results.append(f"unavailable:{label}"); continue
        if listed.returncode == 0:
            if changed:
                subprocess.run(["/bin/launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                results.append(f"reloaded:{label}")
            else:
                results.append(f"running:{label}")
            continue
        try:
            boot = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(manifest)], capture_output=True, text=True)
        except OSError:
            results.append(f"unavailable:{label}"); continue
        if boot.returncode:
            results.append(f"unavailable:{label}")
        else:
            results.append(f"started:{label}")
    return results


def setup(home: Path | None = None, refresh: bool = False, dry_run: bool = False, migrate: bool = False, no_start: bool = False) -> dict[str, Any]:
    home = home or Path.home(); config_dir = home / ".config/tproj"; state = home / ".local/share/tproj-msg-unified"
    topology_path = config_dir / "topology.json"
    expected_socket = home / ".local/share/tproj-msg-unified/hub.sock"
    legacy_enrollment = _remote_enrollment_detected(config_dir, expected_socket)
    if legacy_enrollment and not migrate:
        raise RuntimeError("existing remote-central enrollment requires a prepared owner-local migration; rerun with --migrate after preparing the owner-local DB")
    host_id = _local_id(config_dir, topology_path)
    if legacy_enrollment and migrate and not _legacy_migration_ready(state, host_id):
        raise RuntimeError("legacy central enrollment requires a pre-split owner-local DB marker (metadata.owner_host_id must match configured host identity)")
    old_host = _read_json(config_dir / "msg-host.json")
    token = str(old_host.get("host_token") or secrets.token_urlsafe(32))
    old_hub = _read_json(config_dir / "msg-hub.json")
    admin = str(old_hub.get("admin_token") or secrets.token_urlsafe(32))
    if not dry_run: state.mkdir(parents=True, exist_ok=True, mode=0o700)
    socket = state / "hub.sock"; host_socket = state / "host.sock"; journal = state / "host.db"; hub_db = state / "hub.db"
    hub = dict(old_hub); hub.update({"host_id": host_id, "hosts": dict(old_hub.get("hosts") or {}, **{host_id: token}), "admin_token": admin, "topology_path": str(topology_path), "socket": str(socket), "db": str(hub_db)})
    host = dict(old_host); host.update({"host_id": host_id, "host_token": token, "hub_socket": str(socket), "socket": str(host_socket), "journal": str(journal), "registry": str(home / ".cache/tproj-model-role"), "federated": True})
    host.setdefault("delivery_enabled", True)
    client = _read_json(config_dir / "msg-client.json"); client.update({"host_id": host_id, "socket": str(host_socket), "hub_socket": str(socket), "active": True})
    topology = _read_json(topology_path); topology.setdefault("version", 1); topology["mode"] = topology.get("mode", "standalone"); topology.setdefault("mode_explicit", True); topology.setdefault("local", {"id": host_id, "display_name": os.uname().nodename.split(".", 1)[0], "ssh_alias": None}); topology["local"].setdefault("id", host_id)
    changed_flags = [_atomic_json(topology_path, topology, dry_run)]
    launcher = '#!/bin/sh\nexec python3 "$HOME/lib/tproj-msg-unified/cli.py" "$@"\n'
    changed_flags.append(_atomic_text(home/'bin/tproj-msg-unified', launcher, 0o755, dry_run))
    if not (home/'bin/tproj-msg').exists():
        changed_flags.append(_atomic_text(home/'bin/tproj-msg', launcher, 0o755, dry_run))
    changed_flags += [_atomic_json(config_dir / "msg-hub.json", hub, dry_run), _atomic_json(config_dir / "msg-host.json", host, dry_run), _atomic_json(config_dir / "msg-client.json", client, dry_run)]
    projects = _projects(home, host_id)
    if projects:
        hub["projects"] = projects
    lib = home / "lib/tproj-msg-unified"; hub_script = lib / "hub.py"; host_script = lib / "host.py"
    agents = home / "Library/LaunchAgents"
    manifests = [agents / "local.tproj.msg-unified-hub.plist", agents / "local.tproj.msg-unified-host.plist"]
    changed_flags += [_atomic_text(manifests[0], _plist("local.tproj.msg-unified-hub", hub_script, config_dir / "msg-hub.json", ["--socket", str(socket), "--db", str(hub_db)]), 0o644, dry_run), _atomic_text(manifests[1], _plist("local.tproj.msg-unified-host", host_script, config_dir / "msg-host.json"), 0o644, dry_run)]
    if projects and not dry_run and not migrate:
        try:
            from hub import Hub
            mailbox = Hub(str(hub_db), hub)
            revision = mailbox.directory_list()["revision"]
            existing = mailbox.directory_list()["projects"]
            by_id = {item["project_id"]: item for item in existing}
            additions = [] if existing else projects
            if additions:
                topology = _read_json(topology_path)
                if topology.get('mode') == 'multi':
                    raise RuntimeError('Register new projects through the shared directory while in multi-host mode')
                mailbox.directory_import({"admin_token": admin, "projects": additions, "services": [], "expected_revision": revision})
            mailbox.close()
        except (ImportError, OSError, ValueError) as exc:
            raise RuntimeError(f"directory seed failed: {type(exc).__name__}") from exc
    if not dry_run:
        _atomic_text(config_dir / "msg-client.enrolled", "active\n", 0o600, False)
    activation = _activate(home, manifests, any(changed_flags), no_start, dry_run)
    if any(item.startswith('unavailable:') for item in activation):
        raise RuntimeError('Local messaging service could not start; inspect the user LaunchAgent logs')
    return {"host_id": host_id, "changed": sum(changed_flags), "projects": len(projects), "socket": str(socket), "dry_run": dry_run, "activation": activation}


def _admin_hub(home: Path):
    from hub import Hub
    hub_cfg = _read_json(home / ".config/tproj/msg-hub.json")
    return Hub(str(home / ".local/share/tproj-msg-unified/hub.db"), hub_cfg), str(hub_cfg.get("admin_token") or "")


def retire_alias(home: Path, alias: str, successor: str) -> dict[str, Any]:
    """Retire a local project alias that now lives elsewhere; messages to the old name reach `successor`."""
    hub, admin = _admin_hub(home)
    try: return hub.directory_retire({"admin_token": admin, "alias": alias, "successor": successor})
    finally: hub.close()


def reconcile(home: Path, apply: bool = False) -> list[dict[str, str]]:
    """Local hub projects whose path the workspace now lists as a remote project are retired to that alias."""
    payload = _workspace_payload(home) or {}
    remote = {os.path.abspath(os.path.expanduser(str(i.get("path")))): str(i.get("alias") or Path(str(i["path"])).name)
              for i in payload.get("projects", []) if isinstance(i, dict) and i.get("type") == "remote" and i.get("path")}
    hub, admin = _admin_hub(home); found = []
    try:
        redirected = {r[0] for r in hub.db.execute("SELECT alias FROM alias_redirect")}
        for p in hub.directory_list()["projects"]:
            successor = remote.get(os.path.abspath(p["path"]))
            if successor and p["alias"] != successor and p["alias"] not in redirected:
                item = {"alias": p["alias"], "successor": successor, "status": "pending"}
                if apply:
                    try: hub.directory_retire({"admin_token": admin, "alias": p["alias"], "successor": successor}); item["status"] = "retired"
                    except Exception as exc: item["status"] = "skipped: " + getattr(exc, "code", type(exc).__name__)
                found.append(item)
    finally: hub.close()
    return found


def status(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home(); config_dir = home / ".config/tproj"
    hub = _read_json(config_dir / "msg-hub.json"); host = _read_json(config_dir / "msg-host.json")
    return {"configured": bool(hub and host), "host_id": host.get("host_id"), "socket": host.get("hub_socket"), "remote_enrollment": _remote_enrollment_detected(config_dir, home / ".local/share/tproj-msg-unified/hub.sock"), "hub_config": str(config_dir / "msg-hub.json"), "host_config": str(config_dir / "msg-host.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup"); p.add_argument("--refresh", action="store_true"); p.add_argument("--migrate", action="store_true"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--no-start", action="store_true")
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true")
    d = sub.add_parser("dry-run"); d.add_argument("--refresh", action="store_true"); d.add_argument("--no-start", action="store_true")
    sub.add_parser("enroll").add_argument("alias")
    r = sub.add_parser("retire-alias"); r.add_argument("alias"); r.add_argument("--successor", required=True)
    c = sub.add_parser("reconcile"); c.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status": print(json.dumps(status(), sort_keys=True)); return 0
    if args.command in ("retire-alias", "reconcile"):
        try:
            result = retire_alias(Path.home(), args.alias, args.successor) if args.command == "retire-alias" else reconcile(Path.home(), args.apply)
        except Exception as exc:
            print("%s: %s" % (getattr(exc, "code", type(exc).__name__), exc), file=sys.stderr); return 2
        print(json.dumps(result, sort_keys=True)); return 0
    if args.command == "enroll":
        try:
            from . import enrollment  # parent-owned implementation
        except ImportError:
            import enrollment  # type: ignore
        return enrollment.main([args.alias])
    try: result = setup(refresh=getattr(args, "refresh", False), dry_run=args.command == "dry-run" or getattr(args, "dry_run", False), migrate=getattr(args, "migrate", False), no_start=getattr(args, "no_start", False))
    except RuntimeError as exc: print(str(exc), file=sys.stderr); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())

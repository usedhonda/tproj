#!/usr/bin/env python3
"""Small, fail-closed topology configuration store for tproj."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

CONFIG = Path(os.environ.get("TPROJ_TOPOLOGY_CONFIG", Path.home() / ".config/tproj/topology.json"))
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _local_name() -> str:
    return os.environ.get("TPROJ_TOPOLOGY_LOCAL_NAME") or os.uname().nodename.split(".", 1)[0]


def load() -> dict[str, Any]:
    legacy_host = Path.home() / ".config/tproj/msg-host.json"
    if not CONFIG.exists():
        legacy_id = None
        if legacy_host.exists():
            try:
                legacy_id = json.loads(legacy_host.read_text()).get("host_id")
            except (OSError, ValueError, json.JSONDecodeError):
                legacy_id = None
        return {"version": 1, "mode": "standalone", "local": {"id": legacy_id or str(uuid.uuid4()), "display_name": _local_name(), "ssh_alias": None}, "hosts": []}
    try:
        raw = json.loads(CONFIG.read_text())
        if not isinstance(raw, dict):
            raise ValueError("topology config must be an object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"topology config is invalid: {CONFIG}: {exc}")
    raw.setdefault("version", 1)
    raw.setdefault("mode", "standalone")
    raw.setdefault("mode_explicit", False)
    raw.setdefault("hosts", [])
    local = raw.setdefault("local", {})
    if not local.get("id"):
        legacy_id = None
        if legacy_host.exists():
            try:
                legacy_id = json.loads(legacy_host.read_text()).get("host_id")
            except (OSError, ValueError, json.JSONDecodeError):
                legacy_id = None
        local["id"] = legacy_id or str(uuid.uuid4())
    local.setdefault("display_name", _local_name())
    local.setdefault("ssh_alias", None)
    return raw


def save(cfg: dict[str, Any]) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, CONFIG)


def live_reasons(cfg: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if any(h.get("kind") == "remote" for h in cfg.get("hosts", [])):
        reasons.append("registered_remote_host")
    ws = Path.home() / ".config/tproj/workspace.yaml"
    if ws.exists():
        text = ws.read_text(errors="replace")
        if re.search(r"(?im)^\s*(remote|host|ssh)\s*:", text) or re.search(r"(?i)ssh://|remote_host", text):
            reasons.append("workspace_remote_config")
    enrolled = Path.home() / ".config/tproj/msg-client.enrolled"
    client = Path.home() / ".config/tproj/msg-client.json"
    if enrolled.exists() or (client.exists() and '"active"' in client.read_text(errors="replace") and re.search(r'"active"\s*:\s*true', client.read_text(errors="replace"))):
        reasons.append("messaging_enrollment")
    hub = Path.home() / ".config/tproj/msg-hub.json"
    if hub.exists():
        try:
            data = json.loads(hub.read_text())
            peers = data.get("federation", {}).get("peers", {}) if isinstance(data, dict) else {}
            hosts = data.get("hosts", {}) if isinstance(data, dict) else {}
            if peers or (isinstance(hosts, dict) and len(hosts) > 1):
                reasons.append("messaging_federation")
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return reasons


def status() -> dict[str, Any]:
    cfg = load()
    reasons = live_reasons(cfg)
    if not CONFIG.exists():
        # A newly bootstrapped host is explicitly standalone. Legacy remote
        # state, when present before first read, remains inferred multi-host.
        cfg["mode_explicit"] = not bool(reasons)
        save(cfg)
    effective = cfg.get("mode", "standalone") if cfg.get("mode_explicit") else ("multi" if reasons else "standalone")
    return {"version": 1, "configured_mode": cfg.get("mode", "standalone"), "effective_mode": effective,
            "live_setup_detected": bool(reasons), "detection_reasons": reasons,
            "local": cfg["local"], "host_id": cfg["local"]["id"], "management_host_id": cfg.get("management_host_id", cfg["local"]["id"]),
            "hosts": cfg.get("hosts", [])}


def probe(alias: str) -> dict[str, Any]:
    if not ALIAS_RE.fullmatch(alias):
        raise SystemExit("invalid SSH alias")
    command = os.environ.get("TPROJ_TOPOLOGY_IDENTITY_COMMAND", 'PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" "$HOME/bin/tproj-topology" identity --json')
    try:
        proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-T", "--", alias, command], text=True, capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": "ssh_unavailable", "detail": type(exc).__name__}
    if proc.returncode != 0:
        return {"ok": False, "error": "ssh_failed", "exit_code": proc.returncode}
    try:
        identity = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "identity_invalid"}
    local = identity.get("local") if isinstance(identity.get("local"), dict) else {}
    host_id = identity.get("id") or identity.get("host_id") or local.get("id")
    capabilities = identity.get("capabilities", [])
    if not isinstance(host_id, str) or not host_id or not isinstance(capabilities, list) or "topology" not in capabilities:
        return {"ok": False, "error": "identity_incompatible"}
    return {"ok": True, "id": host_id, "capabilities": capabilities, "identity": {"id": host_id, "capabilities": capabilities}}


def command(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: tproj-topology status [--json] | set standalone|multi [--json] | host list [--json] | host add SSH_ALIAS --name NAME | host remove SSH_ALIAS | host check SSH_ALIAS")
        return 0
    if argv[0] == "identity":
        # Remote capability endpoint. It is intentionally read-only and local-id based.
        cfg = load()
        print(json.dumps({"id": cfg["local"]["id"], "capabilities": ["topology", "host-check"]}, separators=(",", ":")))
        return 0
    if argv[0] == "status":
        data = status()
        print(json.dumps(data, indent=None if "--json" in argv else 2, sort_keys=True))
        return 0
    if argv[0] == "set" and len(argv) >= 2 and argv[1] in ("standalone", "multi"):
        cfg = load(); cfg["mode"] = argv[1]; cfg["mode_explicit"] = True
        runtime = os.environ.get("TPROJ_MSG_RUNTIME", "tproj-msg-runtime")
        save(cfg)
        try:
            refreshed = subprocess.run([runtime, "setup", "--refresh"], check=False, capture_output=True, text=True)
            if refreshed.returncode:
                print('Mode saved; messaging setup needs attention: '+refreshed.stderr.strip(), file=sys.stderr)
        except OSError:
            pass
        print(json.dumps(status(), sort_keys=True) if "--json" in argv else f"mode: {argv[1]}")
        return 0
    if argv[0] != "host" or len(argv) < 2:
        raise SystemExit("invalid topology command")
    action = argv[1]
    if action == "list":
        data = status(); print(json.dumps({"local": data["local"], "hosts": data["hosts"]}, sort_keys=True) if "--json" in argv else "\n".join(f"{h['ssh_alias']}\t{h['display_name']}\t{h['id']}" for h in data["hosts"]))
        return 0
    if action == "check" and len(argv) == 3:
        result = probe(argv[2]); print(json.dumps(result, sort_keys=True)); return 0 if result["ok"] else 1
    if action == "add" and len(argv) >= 3:
        alias = argv[2]; name = None
        if "--name" in argv:
            idx = argv.index("--name"); name = argv[idx + 1] if idx + 1 < len(argv) else None
        if not name: raise SystemExit("host add requires --name NAME")
        result = probe(alias)
        if not result["ok"] and os.environ.get("TPROJ_TOPOLOGY_SKIP_PROVISION") != "1":
            setup = os.environ.get("TPROJ_REMOTE_SETUP", "tproj-remote-setup")
            try:
                provision = subprocess.run([setup, "add", alias], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            except OSError:
                provision = None
            if provision is not None and provision.returncode == 0:
                result = probe(alias)
        if not result["ok"]: print(json.dumps(result, sort_keys=True)); return 1
        runtime = os.environ.get("TPROJ_MSG_RUNTIME", "tproj-msg-runtime")
        if os.environ.get("TPROJ_TOPOLOGY_SKIP_ENROLL") == "1":
            enrolled = None
        else:
            try:
                enrolled = subprocess.run([runtime, "enroll", alias], check=False, capture_output=True, text=True)
            except OSError:
                print(json.dumps({"ok": False, "error": "runtime_unavailable"}, sort_keys=True)); return 1
        if enrolled is not None and enrolled.returncode != 0:
            print(json.dumps({"ok": False, "error": "enrollment_failed", "detail": enrolled.stderr.strip()}, sort_keys=True)); return 1
        cfg = load(); hosts = [h for h in cfg.get("hosts", []) if h.get("ssh_alias") != alias]
        hosts.append({"id": result["id"], "display_name": name, "ssh_alias": alias, "kind": "remote", "capabilities": result["capabilities"]})
        cfg["hosts"] = hosts; cfg["mode"] = "multi"; save(cfg); print(json.dumps(hosts[-1], sort_keys=True)); return 0
    if action == "remove" and len(argv) == 3:
        cfg = load(); cfg["hosts"] = [h for h in cfg.get("hosts", []) if h.get("ssh_alias") != argv[2]]; save(cfg); print(json.dumps(status(), sort_keys=True)); return 0
    raise SystemExit("invalid host command")


if __name__ == "__main__":
    try: raise SystemExit(command(sys.argv[1:]))
    except SystemExit as exc:
        if isinstance(exc.code, str): print(exc.code, file=sys.stderr); raise SystemExit(2)
        raise

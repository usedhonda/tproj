"""Production wiring for the enrolled KAI service principal.

The launchd-owned process is the only process that authenticates to the
unified host. A tunnel-spawned MCP child may use the private bridge socket;
the bridge keeps the launchd PID boundary in the parent service process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
from typing import Any, Mapping

try:
    from .connection import FixedConnectionAuthorizer, KaiServiceBinding, ConnectionBindingError
    from .events import KAIEventDelivery
    from .mailbox_tools import MailboxTools, socket_rpc, MailboxToolError
    from .server import MCPServer, run_stdio
except ImportError:
    from connection import FixedConnectionAuthorizer, KaiServiceBinding, ConnectionBindingError
    from events import KAIEventDelivery
    from mailbox_tools import MailboxTools, socket_rpc, MailboxToolError
    from server import MCPServer, run_stdio


class RuntimeConfigError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RuntimeConfigError(f"invalid {name}")
    return value


class ServiceRuntime:
    def __init__(self, config: Mapping[str, Any]):
        self.config = dict(config)
        binding = KaiServiceBinding(
            _required(config.get("service_id"), "service_id"),
            _required(config.get("address"), "address"),
            _required(config.get("participant_id"), "participant_id"),
            _required(config.get("service_token"), "service_token"),
            tuple(config.get("allowed_addresses", ())),
        )
        self.binding = binding
        self.host_socket = Path(_required(config.get("host_socket"), "host_socket")).expanduser()
        self.state_path = Path(_required(config.get("event_state"), "event_state")).expanduser()
        if self.host_socket.is_symlink() or self.state_path.is_symlink():
            raise RuntimeConfigError("unsafe runtime path")
        bridge = config.get("bridge_socket")
        self.bridge_socket = Path(bridge).expanduser() if bridge else None

    def _request(self, request: Mapping[str, Any]) -> Any:
        req = dict(request)
        req.update({"service_id": self.binding.service_id, "service_token": self.binding.token,
                    "address": self.binding.address})
        if self.bridge_socket:
            return _bridge_rpc(self.bridge_socket, {"op": "call", "request": req})
        return socket_rpc(str(self.host_socket), req)

    def _attest(self) -> Mapping[str, Any]:
        result = self._request({"op": "service_whoami"})
        if not isinstance(result, Mapping):
            raise ConnectionBindingError("service identity unavailable")
        observed = dict(result)
        observed.setdefault("service_id", self.binding.service_id)
        observed.setdefault("address", self.binding.address)
        observed.setdefault("participant_id", self.binding.participant_id)
        observed["allowed_addresses"] = list(self.binding.allowed_addresses)
        # Subscriptions belong to the enrolled service principal; an endpoint
        # incarnation fences stale delivery but does not create a new service.
        observed["binding_id"] = observed.get("participant_id", self.binding.participant_id)
        return observed

    def server(self) -> MCPServer:
        authorizer = FixedConnectionAuthorizer(self.binding, self._attest)
        tools = MailboxTools(service_id=self.binding.service_id, service_address=self.binding.address,
                             service_token=self.binding.token, authorizer=authorizer,
                             host_call=self._request)
        event_auth = authorizer.event_authorizer(
            lambda cursor: self._request({"op": "service_inbox", "cursor": cursor, "limit": 100}))
        events = KAIEventDelivery(event_auth, self.state_path)
        return MCPServer(tools=tools, events=events)


def load_config(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink():
        raise RuntimeConfigError("config must not be a symlink")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeConfigError("invalid runtime config") from exc
    if not isinstance(value, dict):
        raise RuntimeConfigError("runtime config must be an object")
    return value


def _bridge_rpc(path: Path, request: Mapping[str, Any]) -> Any:
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(12)
            sock.connect(str(path))
            sock.sendall((json.dumps(dict(request), separators=(",", ":")) + "\n").encode())
            with sock.makefile("rb") as stream:
                raw = stream.readline(262145)
    except OSError as exc:
        raise MailboxToolError("unavailable", "service bridge unavailable") from exc
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MailboxToolError("unavailable", "invalid service bridge response") from exc
    if not response.get("ok"):
        error = response.get("error") or {}
        raise MailboxToolError(error.get("code", "unavailable"), error.get("message", "service bridge rejected"))
    return response.get("result")


def bridge(config: Mapping[str, Any]) -> int:
    path = Path(_required(config.get("bridge_socket"), "bridge_socket")).expanduser()
    if path.is_symlink():
        raise RuntimeConfigError("bridge socket must not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    runtime = ServiceRuntime(dict(config, bridge_socket=None))
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path)); os.chmod(path, 0o600); listener.listen(16)
    try:
        while True:
            conn, _ = listener.accept()
            with conn:
                raw = conn.makefile("rb").readline(262145)
                try:
                    request = json.loads(raw)
                    if request.get("op") == "whoami":
                        result = runtime._attest()
                    elif request.get("op") == "call" and isinstance(request.get("request"), dict):
                        result = runtime._request(request["request"])
                    else:
                        raise RuntimeConfigError("invalid bridge request")
                    response = {"ok": True, "result": result}
                except Exception:
                    response = {"ok": False, "error": {"code": "identity_rejected", "message": "bridge request rejected"}}
                conn.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode())
    finally:
        listener.close(); path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the enrolled KAI MCP service")
    parser.add_argument("--config", required=True)
    parser.add_argument("--bridge", action="store_true", help="serve the launchd-owned private bridge")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.bridge:
            return bridge(config)
        return run_stdio(ServiceRuntime(config).server())
    except (RuntimeConfigError, ConnectionBindingError, MailboxToolError) as exc:
        print(f"kai runtime failed: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

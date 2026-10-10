"""Production wiring for the enrolled KAI service principal.

The launchd-owned process is the only process that authenticates to the
unified host. A tunnel-spawned MCP child may use the private bridge socket;
the bridge keeps the launchd PID boundary in the parent service process.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hmac
import json
import os
from pathlib import Path
import socket
import stat
import threading
import time
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


BRIDGE_OPS = frozenset({
    "list", "status", "service_send", "service_reply", "service_inbox",
    "service_message", "service_ack", "service_begin_present", "service_whoami",
    "service_repo_list", "service_repo_tree", "service_repo_read", "service_repo_search",
    "service_repo_write", "service_repo_revert",
})
CANCELLED_STATES = frozenset(("cancelled", "canceled", "expired", "terminal", "rejected", "stale_session", "presented"))
BRIDGE_CONNECTION_TIMEOUT = 2.0
BRIDGE_FRAME_LIMIT = 262_144


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
            _required(config.get("binding_generation"), "binding_generation"),
        )
        self.binding = binding
        self.host_socket = Path(_required(config.get("host_socket"), "host_socket")).expanduser()
        self.state_path = Path(_required(config.get("event_state"), "event_state")).expanduser()
        if self.host_socket.is_symlink() or self.state_path.is_symlink():
            raise RuntimeConfigError("unsafe runtime path")
        bridge = config.get("bridge_socket")
        self.bridge_socket = Path(bridge).expanduser() if bridge else None
        self._events = None

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
        observed["binding_generation"] = self.binding.binding_generation
        return observed

    def server(self) -> MCPServer:
        authorizer = FixedConnectionAuthorizer(self.binding, self._attest)
        tools = MailboxTools(service_id=self.binding.service_id, service_address=self.binding.address,
                             service_token=self.binding.token, authorizer=authorizer.authorize,
                             host_call=self._request)
        events = self.events(authorizer)
        server = MCPServer(tools=tools, events=events)
        server.event_pump_enabled = self.bridge_socket is None
        return server

    def events(self, authorizer: FixedConnectionAuthorizer | None = None) -> KAIEventDelivery:
        if self._events is None:
            if authorizer is None:
                authorizer = FixedConnectionAuthorizer(self.binding, self._attest)
            event_auth = authorizer.event_authorizer(
                lambda cursor: self._request({"op": "service_inbox", "cursor": cursor, "limit": 100}))
            self._events = KAIEventDelivery(event_auth, self.state_path)
        return self._events

    def retry_event(self, message_id: str, actor_endpoint: str) -> dict[str, Any]:
        """Retry a single event after bridge and host party checks."""
        if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
            raise MailboxToolError("invalid_request", "invalid message ID")
        if not isinstance(actor_endpoint, str) or not actor_endpoint or len(actor_endpoint) > 256:
            raise MailboxToolError("identity_rejected", "invalid actor endpoint")
        observed = self._attest()
        endpoint_id = observed.get("endpoint_id")
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise MailboxToolError("identity_rejected", "service endpoint unavailable")
        original = self._request({"op": "service_message", "message_id": message_id})
        if not isinstance(original, Mapping) or original.get("recipient_endpoint") != endpoint_id:
            raise MailboxToolError("identity_rejected", "message is not addressed to current KAI")
        if actor_endpoint not in (original.get("sender_endpoint"), original.get("recipient_endpoint")):
            raise MailboxToolError("identity_rejected", "actor is not a message party")
        expiry = original.get("expires_at")
        if (original.get("state") not in ("accepted", "queued", "adapter_received") or
                not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or expiry <= time.time()):
            raise MailboxToolError("ineligible", "message is not eligible for event retry")
        try:
            result = self.events().retry_once(message_id, actor_endpoint=actor_endpoint)
        except MailboxToolError:
            raise
        except Exception as exc:
            raise MailboxToolError("unavailable", "event retry unavailable") from exc
        if not isinstance(result, Mapping):
            raise MailboxToolError("unavailable", "event retry unavailable")
        allowed = {"message_id", "event_id", "status", "attempts", "total_attempts", "status_code", "error_class"}
        return {key: result[key] for key in allowed if key in result}


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


def _bridge_request(runtime: ServiceRuntime, request: Mapping[str, Any]) -> Any:
    """Handle one private bridge request; retry is a dedicated authenticated op."""
    if not isinstance(request, Mapping):
        raise RuntimeConfigError("invalid bridge request")
    if request.get("op") == "whoami":
        return runtime._attest()
    if request.get("op") == "retry_event":
        if set(request) != {"op", "message_id", "actor_endpoint", "service_token"}:
            raise RuntimeConfigError("invalid retry request")
        if not hmac.compare_digest(str(request.get("service_token", "")), runtime.binding.token):
            raise RuntimeConfigError("invalid service credential")
        return runtime.retry_event(request["message_id"], request["actor_endpoint"])
    if request.get("op") == "call" and isinstance(request.get("request"), dict):
        forwarded = request["request"]
        if forwarded.get("op") not in BRIDGE_OPS:
            raise RuntimeConfigError("bridge operation is not allowlisted")
        return runtime._request(forwarded)
    raise RuntimeConfigError("invalid bridge request")


def _read_bridge_frame(conn: socket.socket, deadline: float | None = None) -> bytes:
    """Read exactly one newline-terminated frame within one total deadline."""
    if deadline is None:
        deadline = time.monotonic() + BRIDGE_CONNECTION_TIMEOUT
    frame = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bridge frame deadline exceeded")
        conn.settimeout(remaining)
        chunk = conn.recv(min(65_536, BRIDGE_FRAME_LIMIT + 2 - len(frame)))
        if not chunk:
            if not frame:
                return b""
            raise ValueError("incomplete bridge frame")
        frame.extend(chunk)
        if len(frame) > BRIDGE_FRAME_LIMIT + 1:
            raise ValueError("oversized bridge frame")
        newline = frame.find(b"\n")
        if newline >= 0:
            if newline > BRIDGE_FRAME_LIMIT or newline != len(frame) - 1:
                raise ValueError("oversized bridge frame")
            return bytes(frame)


def _bridge_lock(path: Path):
    """Hold an advisory lock while replacing/binding one bridge socket."""
    lock_path = path.with_name(path.name + ".lock")
    if lock_path.is_symlink():
        raise RuntimeConfigError("bridge lock must not be a symlink")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise RuntimeConfigError("bridge lock unavailable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeConfigError("unsafe bridge lock")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except RuntimeConfigError:
        os.close(fd)
        raise
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise RuntimeConfigError("bridge already starting") from exc
        raise RuntimeConfigError("bridge lock unavailable") from exc
    return fd


def _remove_stale_bridge_socket(path: Path) -> None:
    """Remove only a proven-dead Unix socket, never a regular path."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(before.st_mode):
        raise RuntimeConfigError("bridge socket path is not a socket")
    probe = socket.socket(socket.AF_UNIX)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return
        if exc.errno != errno.ECONNREFUSED:
            raise RuntimeConfigError("bridge socket unavailable") from exc
        # ECONNREFUSED is the normal stale-socket case after an unclean exit.
    else:
        raise RuntimeConfigError("bridge already running")
    finally:
        probe.close()
    try:
        after = path.lstat()
    except FileNotFoundError:
        return
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise RuntimeConfigError("bridge socket changed during startup")
    path.unlink()


def bridge(config: Mapping[str, Any]) -> int:
    # Validate all service settings before touching the bridge path. An invalid
    # launch must not destroy a listener owned by a healthy previous process.
    runtime = ServiceRuntime(dict(config, bridge_socket=None))
    path = Path(_required(config.get("bridge_socket"), "bridge_socket")).expanduser()
    if path.is_symlink():
        raise RuntimeConfigError("bridge socket must not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = _bridge_lock(path)
    listener = None
    bound_stat = None
    stop = None
    worker = None
    try:
        _remove_stale_bridge_socket(path)
        try:
            runtime._attest()
        except Exception:
            # Keep the bridge available while launchd/host startup converges; the
            # event pump retries the same attestation without exposing credentials.
            pass
        events = runtime.events()
        stop = threading.Event()
        def pump() -> None:
            while not stop.wait(1.0):
                try:
                    events.pump_once()
                except Exception:
                    continue
        worker = threading.Thread(target=pump, name="kai-bridge-event-pump", daemon=True)
        worker.start()
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path)); os.chmod(path, 0o600); listener.listen(16)
        bound_stat = path.stat()
        while True:
            try:
                conn, _ = listener.accept()
            except OSError as exc:
                if exc.errno in (errno.EINTR, errno.ECONNABORTED):
                    continue
                raise
            try:
                deadline = time.monotonic() + BRIDGE_CONNECTION_TIMEOUT
                with conn:
                    raw = _read_bridge_frame(conn, deadline)
                    if not raw:
                        continue
                    response = None
                    try:
                        request = json.loads(raw)
                        result = _bridge_request(runtime, request)
                        response = {"ok": True, "result": result}
                    except MailboxToolError as exc:
                        response = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
                    except Exception:
                        response = {"ok": False, "error": {"code": "identity_rejected", "message": "bridge request rejected"}}
                    conn.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode())
            except (OSError, ValueError, TypeError):
                # A client may disconnect, time out, or send an oversized/bad
                # frame; isolate that transport failure to this connection.
                continue
    finally:
        if stop is not None:
            stop.set()
        if worker is not None:
            worker.join(timeout=2)
        if listener is not None:
            listener.close()
        if bound_stat is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (bound_stat.st_dev, bound_stat.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


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

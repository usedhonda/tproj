import importlib.util
import errno
import json
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kai_runtime", ROOT / "runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RuntimeTest(unittest.TestCase):
    def config(self, directory):
        return {
            "service_id": "kai", "address": "kai", "participant_id": "kai.service",
            "service_token": "secret", "allowed_addresses": ["voyager.cc"],
            "binding_generation": "gen-1",
            "host_socket": str(Path(directory) / "host.sock"),
            "event_state": str(Path(directory) / "events.json"),
        }

    def test_whoami_binds_principal_and_incarnation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.ServiceRuntime(self.config(directory))
            runtime._request = lambda req: {
                "endpoint_id": "ep-1", "participant_id": "kai.service",
                "address": "kai", "incarnation": "inc-1", "service_id": "kai",
                "binding_generation": "gen-1", "allowed_addresses": ["voyager.cc"],
                "policy_state": "valid", "policy_revision": "bedae4adef88af75695c8b54b827ac939cdf0d321c13358e3681c2e2734d30b1",
            } if req["op"] == "service_whoami" else {"messages": [], "next_cursor": req.get("cursor", 0)}
            observed = runtime._attest()
            self.assertEqual(observed["binding_id"], "kai.service")
            self.assertEqual(observed["allowed_addresses"], ["voyager.cc"])
            self.assertEqual(runtime.server().tools.authorizer("tproj_list", {})["incarnation"], "inc-1")
            self.assertEqual(runtime.events()._binding().binding_id, "kai.service:gen-1")

    def test_runtime_server_tool_call_uses_mocked_authenticated_host(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.ServiceRuntime(self.config(directory))
            def host(req):
                if req["op"] == "service_whoami":
                    return {"endpoint_id": "ep-1", "participant_id": "kai.service",
                            "address": "kai", "incarnation": "inc-1", "service_id": "kai",
                            "binding_generation": "gen-1", "allowed_addresses": ["voyager.cc"],
                            "policy_state": "valid", "policy_revision": "bedae4adef88af75695c8b54b827ac939cdf0d321c13358e3681c2e2734d30b1"}
                if req["op"] == "service_list":
                    return {"participants": [{"address": "voyager.cc", "online": True}]}
                return {"messages": [], "next_cursor": req.get("cursor", 0)}
            runtime._request = host
            response = runtime.server().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": "tproj_list", "arguments": {}}})
            self.assertEqual(response["result"]["structuredContent"],
                             {"participants": [{"address": "voyager.cc", "kind": "participant", "available": True}]})

    def test_mismatched_host_service_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.ServiceRuntime(self.config(directory))
            runtime._request = lambda req: {"participant_id": "other", "address": "kai", "incarnation": "inc"}
            with self.assertRaises(module.ConnectionBindingError):
                runtime.server().tools.authorizer("tproj_list", {})

    def test_bridge_allowlist_excludes_admin_operations(self):
        self.assertIn("service_whoami", module.BRIDGE_OPS)
        self.assertIn("service_inbox", module.BRIDGE_OPS)
        self.assertNotIn("directory-sync", module.BRIDGE_OPS)
        self.assertNotIn("service_claim", module.BRIDGE_OPS)

    def test_invalid_config_does_not_remove_live_bridge_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(path))
            listener.listen(1)
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            config.pop("service_token")
            try:
                with self.assertRaises(module.RuntimeConfigError):
                    module.bridge(config)
                self.assertTrue(path.exists())
                probe = socket.socket(socket.AF_UNIX)
                probe.settimeout(1)
                probe.connect(str(path))
                probe.close()
            finally:
                listener.close()
                path.unlink(missing_ok=True)

    def test_idle_client_does_not_stop_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            config["bridge_socket"] = str(Path(directory) / "bridge.sock")
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "runtime.py"), "--config", str(config_path), "--bridge"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            path = Path(config["bridge_socket"])
            idle = None
            try:
                deadline = time.time() + 5
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.02)
                self.assertTrue(path.exists())
                idle = socket.socket(socket.AF_UNIX)
                idle.connect(str(path))
                time.sleep(module.BRIDGE_CONNECTION_TIMEOUT + 0.2)
                disconnected = socket.socket(socket.AF_UNIX)
                disconnected.connect(str(path))
                disconnected.sendall(b'{"op":"whoami"}\n')
                disconnected.close()
                time.sleep(0.1)
                request = socket.socket(socket.AF_UNIX)
                request.settimeout(2)
                request.connect(str(path))
                request.sendall(b'{"op":"whoami"}\n')
                response = request.makefile("rb").readline()
                request.close()
                self.assertTrue(response)
                self.assertFalse(json.loads(response)["ok"])
            finally:
                if idle is not None:
                    idle.close()
                process.terminate()
                process.wait(timeout=5)

    def test_connection_reset_probe_does_not_remove_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(path))
            before = path.stat()
            class ResetProbe:
                def settimeout(self, _timeout):
                    pass
                def connect(self, _path):
                    raise OSError(errno.ECONNRESET, "connection reset")
                def close(self):
                    pass
            try:
                with mock.patch.object(module.socket, "socket", return_value=ResetProbe()):
                    with self.assertRaises(module.RuntimeConfigError):
                        module._remove_stale_bridge_socket(path)
                after = path.stat()
                self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            finally:
                listener.close()
                path.unlink(missing_ok=True)

    def test_bridge_lock_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            target = Path(directory) / "lock-target"
            target.touch()
            lock_path = path.with_name(path.name + ".lock")
            lock_path.symlink_to(target)
            with self.assertRaises(module.RuntimeConfigError):
                module._bridge_lock(path)

    def test_bridge_frame_reader_rejects_incomplete_and_oversized_frames(self):
        class Chunks:
            def __init__(self, *chunks):
                self.chunks = list(chunks)
            def settimeout(self, _timeout):
                pass
            def recv(self, _size):
                return self.chunks.pop(0) if self.chunks else b""
        with self.assertRaises(ValueError):
            module._read_bridge_frame(Chunks(b'{"op":"whoami"}'))
        oversized = b"{}\n" + b"x" * module.BRIDGE_FRAME_LIMIT
        with self.assertRaises(ValueError):
            module._read_bridge_frame(Chunks(oversized))
        boundary = b"x" * module.BRIDGE_FRAME_LIMIT + b"\n"
        self.assertEqual(module._read_bridge_frame(Chunks(boundary)), boundary)
        self.assertEqual(module._read_bridge_frame(Chunks(b"{}\n")), b"{}\n")

    def test_bridge_frame_reader_uses_total_monotonic_deadline_for_trickle(self):
        class Trickle:
            def settimeout(self, _timeout):
                pass
            def recv(self, _size):
                return b"x"
        with mock.patch.object(module.time, "monotonic", side_effect=(0.0, 0.0, 1.0, 2.1)):
            with self.assertRaises(TimeoutError):
                module._read_bridge_frame(Trickle())

    def test_bridge_real_connections_bound_frames_before_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            real_socket = socket.socket
            listeners = []
            dispatches = []
            listener_errors = []

            class Events:
                def pump_once(self):
                    pass

            class Runtime:
                def __init__(self, _config):
                    self.binding = mock.Mock(token="token")
                def _attest(self):
                    return {"service_id": "kai"}
                def events(self):
                    return Events()

            def socket_factory(*args, **kwargs):
                created = real_socket(*args, **kwargs)
                if args and args[0] == socket.AF_UNIX:
                    listeners.append(created)
                return created

            def dispatch(_runtime, request):
                dispatches.append(request)
                return {"accepted": True}

            def serve():
                try:
                    module.bridge(config)
                except OSError as exc:
                    listener_errors.append(exc)

            with mock.patch.object(module, "ServiceRuntime", Runtime), \
                 mock.patch.object(module, "_bridge_request", side_effect=dispatch), \
                 mock.patch.object(module.socket, "socket", side_effect=socket_factory), \
                 mock.patch.object(module, "BRIDGE_CONNECTION_TIMEOUT", 0.2):
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                deadline = time.time() + 2
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())
                trickle = real_socket(socket.AF_UNIX)
                trickle.connect(str(path))
                trickle.sendall(b"{")
                trickle_done = threading.Event()

                def trickle_sender():
                    try:
                        while True:
                            trickle.sendall(b" ")
                            time.sleep(0.05)
                    except OSError:
                        trickle_done.set()

                sender = threading.Thread(target=trickle_sender, daemon=True)
                sender.start()
                self.addCleanup(sender.join, 1)
                self.addCleanup(trickle.close)
                self.assertTrue(trickle_done.wait(2))

                def request(frame):
                    client = real_socket(socket.AF_UNIX)
                    client.settimeout(2)
                    client.connect(str(path))
                    client.sendall(frame)
                    response = client.makefile("rb").readline()
                    client.close()
                    return response

                prefix = b'{"op":"whoami"}'
                padded_invalid = prefix + b" " * (262_145 - len(prefix)) + b"x\n"
                self.assertEqual(json.loads(request(padded_invalid)),
                                 {"ok": False, "error": {"code": "frame_too_large", "message": "invalid bridge frame"}})
                self.assertEqual(len(dispatches), 0)
                incomplete = real_socket(socket.AF_UNIX)
                incomplete.connect(str(path))
                incomplete.sendall(prefix)
                incomplete.close()
                oversized = b"{}" + b"x" * module.BRIDGE_FRAME_LIMIT + b"\n"
                oversized_response = json.loads(request(oversized))
                self.assertEqual(oversized_response,
                                 {"ok": False, "error": {"code": "frame_too_large", "message": "invalid bridge frame"}})
                self.assertEqual(len(dispatches), 0)
                response = request(b'{"op":"whoami"}\n')
                self.assertTrue(json.loads(response)["ok"])
                self.assertEqual(len(dispatches), 1)
                trickle.close()
                sender.join(timeout=1)
                listeners[0].close()
                thread.join(timeout=2)
                self.assertEqual(len(listener_errors), 1)

    def test_bridge_unicode_response_roundtrips_with_utf8_frame_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            real_socket = socket.socket
            listeners = []
            listener_errors = []

            class Events:
                def pump_once(self):
                    pass

            class Runtime:
                def __init__(self, _config):
                    self.binding = mock.Mock(token="token")
                def _attest(self):
                    return {"service_id": "kai"}
                def events(self):
                    return Events()

            def socket_factory(*args, **kwargs):
                created = real_socket(*args, **kwargs)
                if args and args[0] == socket.AF_UNIX:
                    listeners.append(created)
                return created

            body = "あ" * 50_000

            def dispatch(_runtime, _request):
                return {"body": body}

            def serve():
                try:
                    module.bridge(config)
                except OSError as exc:
                    listener_errors.append(exc)

            with mock.patch.object(module, "ServiceRuntime", Runtime), \
                 mock.patch.object(module, "_bridge_request", side_effect=dispatch), \
                 mock.patch.object(module.socket, "socket", side_effect=socket_factory):
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                deadline = time.time() + 2
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())

                result = module._bridge_rpc(path, {"op": "whoami"})
                self.assertEqual(result["body"], body)

                listeners[0].close()
                thread.join(timeout=2)
                self.assertEqual(len(listener_errors), 1)

    def test_bridge_response_timeout_does_not_redispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            real_socket = socket.socket
            listeners = []
            dispatches = []
            listener_errors = []

            class Events:
                def pump_once(self):
                    pass

            class Runtime:
                def __init__(self, _config):
                    self.binding = mock.Mock(token="token")
                def _attest(self):
                    return {"service_id": "kai"}
                def events(self):
                    return Events()

            def socket_factory(*args, **kwargs):
                created = real_socket(*args, **kwargs)
                if args and args[0] == socket.AF_UNIX:
                    listeners.append(created)
                return created

            def dispatch(_runtime, _request):
                dispatches.append(True)
                return {"payload": "x" * (8 * 1024 * 1024)}

            def serve():
                try:
                    module.bridge(config)
                except OSError as exc:
                    listener_errors.append(exc)

            with mock.patch.object(module, "ServiceRuntime", Runtime), \
                 mock.patch.object(module, "_bridge_request", side_effect=dispatch), \
                 mock.patch.object(module.socket, "socket", side_effect=socket_factory), \
                 mock.patch.object(module, "BRIDGE_CONNECTION_TIMEOUT", 0.05):
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                deadline = time.time() + 2
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())
                client = real_socket(socket.AF_UNIX)
                client.settimeout(2)
                client.connect(str(path))
                client.sendall(b'{"op":"whoami"}\n')
                response = client.makefile("rb").readline()
                client.close()
                self.assertEqual(len(dispatches), 1)
                self.assertEqual(json.loads(response),
                                 {"ok": False, "error": {"code": "response_too_large",
                                                            "message": "service bridge response too large"}})
                self.assertTrue(thread.is_alive())
                listeners[0].close()
                thread.join(timeout=2)
                self.assertEqual(len(listener_errors), 1)

    def test_slow_dispatch_does_not_block_next_authorized_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            real_socket = socket.socket
            listeners = []
            listener_errors = []
            release_slow = threading.Event()
            dispatches = []

            class Events:
                def pump_once(self):
                    pass

            class Runtime:
                def __init__(self, _config):
                    self.binding = mock.Mock(token="token")
                def _attest(self):
                    return {"service_id": "kai"}
                def events(self):
                    return Events()

            def socket_factory(*args, **kwargs):
                created = real_socket(*args, **kwargs)
                if args and args[0] == socket.AF_UNIX:
                    listeners.append(created)
                return created

            def dispatch(_runtime, request):
                dispatches.append(request)
                if request.get("slow"):
                    release_slow.wait(2)
                return {"accepted": True}

            def serve():
                try:
                    module.bridge(config)
                except OSError as exc:
                    listener_errors.append(exc)

            with mock.patch.object(module, "ServiceRuntime", Runtime), \
                 mock.patch.object(module, "_bridge_request", side_effect=dispatch), \
                 mock.patch.object(module.socket, "socket", side_effect=socket_factory), \
                 mock.patch.object(module, "BRIDGE_CONNECTION_TIMEOUT", 1.0), \
                 mock.patch.object(module, "BRIDGE_MAX_CONNECTIONS", 2):
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                deadline = time.time() + 2
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())

                slow = real_socket(socket.AF_UNIX)
                slow.settimeout(2)
                slow.connect(str(path))
                slow.sendall(b'{"op":"slow"}\n')
                deadline = time.time() + 2
                while not dispatches and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(dispatches)

                healthy = real_socket(socket.AF_UNIX)
                healthy.settimeout(1)
                healthy.connect(str(path))
                healthy.sendall(b'{"op":"whoami"}\n')
                response = healthy.makefile("rb").readline()
                self.assertTrue(json.loads(response)["ok"])
                healthy.close()

                release_slow.set()
                slow.makefile("rb").readline()
                slow.close()
                listeners[0].close()
                thread.join(timeout=2)
                self.assertEqual(len(listener_errors), 1)
                self.assertEqual(len(dispatches), 2)

    def test_bridge_response_uses_fresh_timeout_after_near_deadline_receive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            config = self.config(directory)
            config["bridge_socket"] = str(path)
            real_socket = socket.socket
            listeners = []
            dispatches = []
            listener_errors = []

            class Events:
                def pump_once(self):
                    pass

            class Runtime:
                def __init__(self, _config):
                    self.binding = mock.Mock(token="token")
                def _attest(self):
                    return {"service_id": "kai"}
                def events(self):
                    return Events()

            def socket_factory(*args, **kwargs):
                created = real_socket(*args, **kwargs)
                if args and args[0] == socket.AF_UNIX:
                    listeners.append(created)
                return created

            payload = "x" * (8 * 1024 * 1024)
            real_read_frame = module._read_bridge_frame
            real_dumps = json.dumps
            received_connection = []
            send_timeouts = []

            def receive_with_known_remaining_timeout(conn, deadline):
                raw = real_read_frame(conn, deadline)
                # Fix the receive-end state without relying on scheduler timing.
                conn.settimeout(0.05)
                received_connection.append(conn)
                return raw

            def encode_response(*args, **kwargs):
                # Encoding is evaluated immediately before sendall.
                send_timeouts.append(received_connection[-1].gettimeout())
                return real_dumps(*args, **kwargs)

            def dispatch(_runtime, _request):
                dispatches.append(True)
                return {"payload": payload}

            def serve():
                try:
                    module.bridge(config)
                except OSError as exc:
                    listener_errors.append(exc)

            with mock.patch.object(module, "ServiceRuntime", Runtime), \
                 mock.patch.object(module, "_bridge_request", side_effect=dispatch), \
                 mock.patch.object(module.socket, "socket", side_effect=socket_factory), \
                 mock.patch.object(module, "BRIDGE_CONNECTION_TIMEOUT", 0.2), \
                 mock.patch.object(module, "_read_bridge_frame", side_effect=receive_with_known_remaining_timeout), \
                 mock.patch.object(module.json, "dumps", side_effect=encode_response):
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                deadline = time.time() + 2
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())
                client = real_socket(socket.AF_UNIX)
                client.settimeout(3)
                client.connect(str(path))
                client.sendall(b'{"op":"who')
                time.sleep(0.15)
                client.sendall(b'ami"}\n')
                time.sleep(0.1)
                response = bytearray()
                while not response.endswith(b"\n"):
                    chunk = client.recv(65_536)
                    self.assertTrue(chunk)
                    response.extend(chunk)
                client.close()
                decoded = json.loads(response)
                self.assertEqual(decoded,
                                 {"ok": False, "error": {"code": "response_too_large",
                                                            "message": "service bridge response too large"}})
                self.assertEqual(len(dispatches), 1)
                self.assertEqual(send_timeouts, [0.2, 0.2])
                listeners[0].close()
                thread.join(timeout=2)
                self.assertEqual(len(listener_errors), 1)


if __name__ == "__main__":
    unittest.main()

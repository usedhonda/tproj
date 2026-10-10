import importlib.util
import errno
import json
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
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
                            "address": "kai", "incarnation": "inc-1", "service_id": "kai"}
                if req["op"] == "list":
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
            try:
                deadline = time.time() + 5
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.02)
                self.assertTrue(path.exists())
                idle = socket.socket(socket.AF_UNIX)
                idle.connect(str(path))
                idle.close()
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


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import tempfile
import unittest

UNIFIED = Path(__file__).parents[2] / "unified"
import sys
sys.path.insert(0, str(UNIFIED))
sys.path.insert(0, str(Path(__file__).parent))
host_spec = importlib.util.spec_from_file_location("unified_host", UNIFIED / "host.py")
host_module = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(host_module)
runtime_spec = importlib.util.spec_from_file_location("kai_runtime_retry", Path(__file__).with_name("runtime.py"))
runtime_module = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime_module)


class HostRetryRouteTest(unittest.TestCase):
    def host(self, bridge="/tmp/kai-bridge.sock"):
        obj = object.__new__(host_module.Host)
        obj.config = {"host_id": "mini", "services": {"kai": {
            "participant_id": "kai.service", "address": "kai", "token": "secret",
            "event_bridge_socket": bridge,
        }}}
        return obj

    def test_routes_only_current_kai_party_without_body(self):
        obj = self.host()
        calls = []
        obj.hub = lambda op, **args: (
            {"endpoints": [{"endpoint_id": "kai-ep", "host_id": "mini", "participant_id": "kai.service", "retired": 0}]}
            if op == "endpoints_list" else
            {"participants": [{"participant_id": "kai.service", "address": "kai", "host_id": "mini"}]}
            if op == "directory_list" else
            {"message_id": "m1", "sender_endpoint": "sender", "recipient_endpoint": "kai-ep", "state": "accepted", "expires_at": 9999999999}
        )
        old = host_module.rpc
        host_module.rpc = lambda path, request: calls.append((path, request)) or {
            "message_id": "m1", "event_id": "evt-1", "status": "unknown", "status_code": 202,
            "error_class": None, "attempts": 1, "total_attempts": 4, "body": "must not escape",
        }
        try:
            result = obj._retry_event({"endpoint_id": "sender"}, "m1")
        finally:
            host_module.rpc = old
        self.assertEqual(result["event_id"], "evt-1")
        self.assertNotIn("body", result)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(calls[0][1], {"op": "retry_event", "message_id": "m1",
                                       "actor_endpoint": "sender", "service_token": "secret"})

    def test_rejects_foreign_recipient_before_bridge(self):
        obj = self.host()
        obj.hub = lambda op, **args: ({"endpoints": [{"endpoint_id": "kai-ep", "host_id": "mini",
            "participant_id": "kai.service", "retired": 0}]}
            if op == "endpoints_list" else {"participants": [{"participant_id": "kai.service", "address": "kai", "host_id": "mini"}]}
            if op == "directory_list" else {"recipient_endpoint": "foreign", "state": "accepted"})
        with self.assertRaises(host_module.HubError):
            obj._retry_event({"endpoint_id": "sender"}, "m1")


class RuntimeRetryRouteTest(unittest.TestCase):
    def test_bridge_rejects_forged_token_and_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"service_id": "kai", "address": "kai", "participant_id": "kai.service",
                      "service_token": "secret", "allowed_addresses": ["voyager.cc"],
                      "binding_generation": "gen-1", "host_socket": str(Path(directory) / "host.sock"),
                      "event_state": str(Path(directory) / "events.json")}
            runtime = runtime_module.ServiceRuntime(config)
            with self.assertRaises(runtime_module.RuntimeConfigError):
                runtime_module._bridge_request(runtime, {"op": "retry_event", "message_id": "m1",
                    "actor_endpoint": "sender", "service_token": "wrong"})
            runtime._attest = lambda: {"endpoint_id": "kai-ep"}
            runtime._request = lambda req: {"recipient_endpoint": "kai-ep", "sender_endpoint": "sender",
                                            "state": "accepted", "expires_at": 9999999999}
            with self.assertRaises(runtime_module.MailboxToolError):
                runtime.retry_event("m1", "other")


if __name__ == "__main__":
    unittest.main()

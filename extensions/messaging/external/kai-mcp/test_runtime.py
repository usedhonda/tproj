import importlib.util
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

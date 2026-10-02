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
            self.assertEqual(runtime.server().tools.authorizer.authorize()["incarnation"], "inc-1")

    def test_mismatched_host_service_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.ServiceRuntime(self.config(directory))
            runtime._request = lambda req: {"participant_id": "other", "address": "kai", "incarnation": "inc"}
            with self.assertRaises(module.ConnectionBindingError):
                runtime.server().tools.authorizer.authorize()


if __name__ == "__main__":
    unittest.main()

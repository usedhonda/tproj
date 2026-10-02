import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kai_connection", ROOT / "connection.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConnectionAuthorizerTest(unittest.TestCase):
    def setUp(self):
        self.observed = {
            "binding_id": "endpoint-1", "incarnation": "inc-1",
            "service_id": "kai", "address": "kai",
            "participant_id": "kai.service", "allowed_addresses": ["voyager.cc"],
        }
        binding = module.KaiServiceBinding("kai", "kai", "kai.service", "secret", ("voyager.cc",), "gen-1")
        self.authorizer = module.FixedConnectionAuthorizer(binding, lambda: dict(self.observed))

    def test_fixed_scope_and_host_incarnation_are_returned(self):
        result = self.authorizer.authorize("tproj_send", {"target": "voyager.cc"})
        self.assertEqual(result["principal"], "kai-service")
        self.assertEqual(result["allowed_addresses"], ["voyager.cc"])
        self.assertEqual(result["incarnation"], "inc-1")

    def test_scope_or_enrollment_mismatch_fails_closed(self):
        self.observed["allowed_addresses"] = ["secret.cc"]
        with self.assertRaises(module.ConnectionBindingError):
            self.authorizer.authorize()
        self.observed["allowed_addresses"] = ["voyager.cc"]
        self.observed["service_id"] = "openclaw"
        with self.assertRaises(module.ConnectionBindingError):
            self.authorizer.authorize()

    def test_event_view_uses_same_binding(self):
        event_auth = self.authorizer.event_authorizer(lambda cursor: {"messages": [], "next_cursor": cursor})
        value = event_auth.authorize()
        self.assertEqual((value.binding_id, value.incarnation), ("kai.service:gen-1", "inc-1"))
        self.assertTrue(callable(value.reader))

    def test_restart_keeps_generation_but_rotation_changes_event_owner(self):
        event_auth = self.authorizer.event_authorizer(lambda cursor: {"messages": [], "next_cursor": cursor})
        first = event_auth.authorize()
        self.observed["incarnation"] = "inc-2"
        resumed = event_auth.authorize()
        self.assertEqual(first.binding_id, resumed.binding_id)
        self.authorizer.binding.binding_generation = "gen-2"
        rotated = event_auth.authorize()
        self.assertNotEqual(first.binding_id, rotated.binding_id)


if __name__ == "__main__":
    unittest.main()

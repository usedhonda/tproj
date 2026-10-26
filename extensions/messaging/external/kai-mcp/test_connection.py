import importlib.util
from pathlib import Path
import unittest
import hashlib
import json

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
            "binding_generation": "gen-1", "policy_state": "valid",
        }
        self.observed["policy_revision"] = hashlib.sha256(json.dumps(["voyager.cc"], separators=(",", ":")).encode()).hexdigest()
        binding = module.KaiServiceBinding("kai", "kai", "kai.service", "secret", ("voyager.cc",), "gen-1")
        self.authorizer = module.FixedConnectionAuthorizer(binding, lambda: dict(self.observed))

    def test_workspace_policy_is_not_exposed_as_an_empty_allowlist(self):
        self.observed.update(messaging_scope='workspace',allowed_addresses=[],
            policy_revision=hashlib.sha256(b'[]').hexdigest())
        for op in ('tproj_list','tproj_status','tproj_send'):
            result=self.authorizer.authorize(op,{'target':'new-project.cc'})
            self.assertNotIn('allowed_addresses',result)
            self.assertEqual(result['messaging_scope'],'workspace')
            self.assertEqual(result['new_message_targets'],'tproj_list available participants')
        catalog=json.loads((ROOT/'external-assistant-tools.json').read_text())
        for t in catalog['tools']:
            if t['name'] in ('tproj_send','tproj_status'):
                self.assertIn('No per-destination user approval',t['description'])

    def test_fixed_scope_and_host_incarnation_are_returned(self):
        result = self.authorizer.authorize("tproj_send", {"target": "voyager.cc"})
        self.assertEqual(result["principal"], "kai-service")
        self.assertEqual(result["allowed_addresses"], ["voyager.cc"])
        self.assertEqual(result["incarnation"], "inc-1")

    def test_scope_or_enrollment_mismatch_fails_closed(self):
        self.observed["binding_generation"] = "gen-2"
        with self.assertRaises(module.ConnectionBindingError):
            self.authorizer.authorize()

    def test_attestation_rejection_is_sanitized(self):
        self.authorizer.attestor = lambda: (_ for _ in ()).throw(
            RuntimeError("socket /private/credential=secret timed out"))
        with self.assertRaises(module.ConnectionBindingError) as raised:
            self.authorizer.authorize()
        self.assertIs(type(raised.exception), module.ConnectionBindingError)
        self.assertEqual(str(raised.exception), "host service attestation rejected")

        self.authorizer.attestor = lambda: (_ for _ in ()).throw(
            OSError("socket /private/credential=secret unavailable"))
        with self.assertRaises(module.ConnectionTransportUnavailable) as unavailable:
            self.authorizer.authorize()
        self.assertEqual(str(unavailable.exception), "host service unavailable")
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
        self.observed["binding_generation"] = "gen-2"
        rotated = event_auth.authorize()
        self.assertNotEqual(first.binding_id, rotated.binding_id)


if __name__ == "__main__":
    unittest.main()

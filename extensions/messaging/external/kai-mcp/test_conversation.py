import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kai_conversation", ROOT / "conversation.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def digest(value):
    return module.provider_digest(value)


class ConversationBindingRegistryTest(unittest.TestCase):
    def setUp(self):
        self.config = {"bindings": [
            {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
             "provider_session_digest": digest("sess-a"), "binding_id": "bind-a",
             "service_id": "svc-a", "address": "a@example", "participant_id": "p-a"},
            {"principal_id": "owner-b", "provider_subject_digest": digest("sub-b"),
             "provider_session_digest": digest("sess-b"), "binding_id": "bind-b",
             "service_id": "svc-b", "address": "b@example", "participant_id": "p-b"},
        ]}
        self.registry = module.ConversationBindingRegistry(self.config)

    def test_two_independent_contexts_resolve_distinct_entries(self):
        first = self.registry.resolve(lambda: {"principal_id": "owner-a",
            "provider_subject_digest": digest("sub-a"), "provider_session_digest": digest("sess-a")})
        second = self.registry.resolve(lambda: {"principal_id": "owner-b",
            "provider_subject_digest": digest("sub-b"), "provider_session_digest": digest("sess-b")})
        self.assertEqual((first.binding_id, second.binding_id), ("bind-a", "bind-b"))
        self.assertNotEqual(first.service_id, second.service_id)

    def test_wrong_absent_and_expired_contexts_are_denied(self):
        with self.assertRaises(module.ConversationBindingDenied):
            self.registry.resolve(lambda: {"principal_id": "owner-a",
                "provider_subject_digest": digest("wrong"), "provider_session_digest": digest("sess-a")})
        with self.assertRaises(module.ConversationAttestationError):
            self.registry.resolve(None)
        expired = {"bindings": [{**self.config["bindings"][0], "expires_at": 1}]}
        registry = module.ConversationBindingRegistry(expired, clock=lambda: 2)
        with self.assertRaises(module.ConversationBindingExpired):
            registry.resolve(lambda: {"principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"), "provider_session_digest": digest("sess-a")})

    def test_duplicate_mapping_and_aliases_are_rejected(self):
        duplicate = {"bindings": [self.config["bindings"][0],
            {**self.config["bindings"][1], "participant_id": "p-a"}]}
        with self.assertRaises(module.ConversationBindingConflict):
            module.ConversationBindingRegistry(duplicate)
        duplicate_address = {"bindings": [self.config["bindings"][0],
            {**self.config["bindings"][1], "address": "a@example"}]}
        with self.assertRaises(module.ConversationBindingConflict):
            module.ConversationBindingRegistry(duplicate_address)

    def test_raw_request_metadata_alone_cannot_authorize(self):
        raw = {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
               "provider_session_digest": digest("sess-a")}
        with self.assertRaises(module.ConversationAttestationError):
            self.registry.resolve(None, request_meta=raw, arguments=raw)
        with self.assertRaises(module.ConversationBindingDenied):
            self.registry.resolve(lambda: {"principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"), "provider_session_digest": digest("other")},
                request_meta=raw)

    def test_load_from_json_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(__import__("json").dumps(self.config), encoding="utf-8")
            self.assertEqual(module.ConversationBindingRegistry.load(path).resolve(
                lambda: {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                         "provider_session_digest": digest("sess-a")}).binding_id, "bind-a")


if __name__ == "__main__":
    unittest.main()

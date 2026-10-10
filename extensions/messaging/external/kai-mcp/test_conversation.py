import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
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
            os.chmod(path, 0o600)
            self.assertEqual(module.ConversationBindingRegistry.load(path).resolve(
                lambda: {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                         "provider_session_digest": digest("sess-a")}).binding_id, "bind-a")

    def test_owner_policy_aliases_and_order_roundtrip_as_same_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            embedded = {
                "principals": ["owner-b", "owner-a"],
                "provider_subjects": [digest("sub-b"), digest("sub-a")],
            }
            path.write_text(json.dumps({"bindings": [], "owner_policy": embedded}),
                            encoding="utf-8")
            os.chmod(path, 0o600)
            supplied = {
                "principal_ids": ["owner-a", "owner-b"],
                "provider_subject_digests": [digest("sub-a"), digest("sub-b")],
            }
            registry = module.ConversationBindingRegistry.load(path, owner_policy=supplied)
            self.assertEqual(registry._owner_policy["principal_ids"],
                             frozenset({"owner-a", "owner-b"}))
            enrolled = registry.enroll(lambda: {
                "principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"),
                "provider_session_digest": digest("sess-a"),
            })
            self.assertEqual(registry.resolve(lambda: {
                "principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"),
                "provider_session_digest": digest("sess-a"),
            }).binding_id, enrolled.binding_id)
            restarted = module.ConversationBindingRegistry.load(path, owner_policy=supplied)
            self.assertEqual(restarted.resolve(lambda: {
                "principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"),
                "provider_session_digest": digest("sess-a"),
            }).binding_id, enrolled.binding_id)

    def test_malformed_reload_does_not_publish_policy_or_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            registry = module.ConversationBindingRegistry.load(path)
            policy = {
                "principal_ids": ["fixture-owner"],
                "provider_subject_digests": [digest("fixture-subject")],
            }
            malformed = {
                "bindings": [{"principal_id": "fixture-owner"}],
                "owner_policy": policy,
            }
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(module.ConversationConfigError):
                registry.resolve(lambda: {
                    "principal_id": "fixture-owner",
                    "provider_subject_digest": digest("fixture-subject"),
                    "provider_session_digest": digest("new-session"),
                })
            self.assertIsNone(registry._owner_policy)
            self.assertFalse(registry._policy_persisted)
            self.assertEqual(registry._bindings, ())

            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            with self.assertRaises(module.ConversationBindingDenied):
                registry.enroll(lambda: {
                    "principal_id": "fixture-owner",
                    "provider_subject_digest": digest("fixture-subject"),
                    "provider_session_digest": digest("new-session"),
                })

    def test_explicit_enroll_reconnects_distinct_identity_and_fences_revoke(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            policy = {"principal_ids": ["owner-a", "owner-b"],
                      "provider_subject_digests": [digest("sub-a"), digest("sub-b")]}
            registry = module.ConversationBindingRegistry.load(path, owner_policy=policy)
            identity_a = lambda: {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                                  "provider_session_digest": digest("sess-a"), "generation": 1}
            identity_b = lambda: {"principal_id": "owner-b", "provider_subject_digest": digest("sub-b"),
                                  "provider_session_digest": digest("sess-b"), "generation": 1}
            first = registry.enroll(identity_a)
            self.assertEqual(registry.enroll(identity_a).binding_id, first.binding_id)
            second = registry.enroll(identity_b)
            self.assertNotEqual(first.binding_id, second.binding_id)
            fenced = registry.revoke(first.binding_id)
            self.assertTrue(fenced.revoked)
            with self.assertRaises(module.ConversationBindingDenied):
                registry.resolve(identity_a)
            with self.assertRaises(module.ConversationBindingDenied):
                registry.enroll(identity_a)

    def test_cross_instance_resolve_reloads_revocation_and_expired_enroll_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            policy = {"principal_ids": ["owner-a"],
                      "provider_subject_digests": [digest("sub-a")]}
            first = module.ConversationBindingRegistry.load(path, owner_policy=policy)
            second = module.ConversationBindingRegistry.load(path, owner_policy=policy)
            identity = lambda: {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                                "provider_session_digest": digest("sess-a"), "generation": 1}
            binding = first.enroll(identity)
            self.assertEqual(second.resolve(identity).binding_id, binding.binding_id)
            first.revoke(binding.binding_id)
            with self.assertRaises(module.ConversationBindingDenied):
                second.resolve(identity)
            before = path.read_bytes()
            with self.assertRaises(module.ConversationBindingExpired):
                first.enroll(lambda: identity(), expires_at=1)
            self.assertEqual(path.read_bytes(), before)

    def test_removed_persisted_owner_policy_fails_closed_without_resurrection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            policy = {"principal_ids": ["fixture-owner"],
                      "provider_subject_digests": [digest("fixture-subject")]}
            path.write_text(json.dumps({"bindings": [], "owner_policy": policy}), encoding="utf-8")
            os.chmod(path, 0o600)
            registry = module.ConversationBindingRegistry.load(path)
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            before = path.read_bytes()
            attestor = lambda: {"principal_id": "fixture-owner",
                                "provider_subject_digest": digest("fixture-subject"),
                                "provider_session_digest": digest("new-session")}
            with self.assertRaises(module.ConversationConfigError):
                registry.enroll(attestor)
            self.assertEqual(path.read_bytes(), before)

    def test_expiry_rechecked_after_reload_when_clock_advances_while_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            policy = {"principal_ids": ["fixture-owner"],
                      "provider_subject_digests": [digest("fixture-subject")]}
            now = [99]
            registry = module.ConversationBindingRegistry.load(
                path, owner_policy=policy, clock=lambda: now[0])
            original_reload = registry._reload_locked

            def reload_then_advance(locked_path):
                bindings = original_reload(locked_path)
                now[0] = 101
                return bindings

            registry._reload_locked = reload_then_advance
            before = path.read_bytes()
            attestor = lambda: {"principal_id": "fixture-owner",
                                "provider_subject_digest": digest("fixture-subject"),
                                "provider_session_digest": digest("new-session")}
            with self.assertRaises(module.ConversationBindingExpired):
                registry.enroll(attestor, expires_at=100)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(registry._bindings, ())

    def test_load_rejects_group_readable_or_symlinked_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            path = parent / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o640)
            with self.assertRaises(module.ConversationConfigError):
                module.ConversationBindingRegistry.load(path)
            os.chmod(path, 0o600)
            link = parent / "link.json"
            link.symlink_to(path)
            with self.assertRaises(module.ConversationConfigError):
                module.ConversationBindingRegistry.load(link)

    def test_malformed_owner_private_registry_returns_fixed_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.json"
            path.write_text('{"bindings":', encoding="utf-8")
            os.chmod(path, 0o600)
            with self.assertRaises(module.ConversationConfigError) as raised:
                module.ConversationBindingRegistry.load(path)
            self.assertEqual(str(raised.exception), "conversation binding configuration rejected")

    def test_policy_denial_and_nonfinite_expiry_do_not_mutate_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            policy = {"principal_ids": ["owner-a"],
                      "provider_subject_digests": [digest("sub-a")]}
            registry = module.ConversationBindingRegistry.load(path, owner_policy=policy)
            before = path.read_bytes()
            denied = lambda: {"principal_id": "owner-x", "provider_subject_digest": digest("sub-x"),
                              "provider_session_digest": digest("sess-x")}
            with self.assertRaises(module.ConversationBindingDenied):
                registry.enroll(denied)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(module.ConversationConfigError):
                module.ConversationBindingRegistry({"bindings": [{**self.config["bindings"][0],
                                                                   "expires_at": math.inf}]})
            with self.assertRaises(module.ConversationConfigError):
                module.ConversationBindingRegistry({"bindings": [{**self.config["bindings"][0],
                                                                   "expires_at": math.nan}]})

    def test_concurrent_enrollment_creates_one_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            os.chmod(path, 0o600)
            policy = {"principal_ids": ["owner-a"],
                      "provider_subject_digests": [digest("sub-a")]}
            registries = [module.ConversationBindingRegistry.load(path, owner_policy=policy) for _ in range(2)]
            identity = lambda: {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                                "provider_session_digest": digest("sess-a")}
            barrier = threading.Barrier(2)
            results = []

            def run(registry):
                barrier.wait()
                results.append(registry.enroll(identity).binding_id)

            threads = [threading.Thread(target=run, args=(registry,)) for registry in registries]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len(results), 2)
            self.assertEqual(len(set(results)), 1)


if __name__ == "__main__":
    unittest.main()

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

mailbox_spec = importlib.util.spec_from_file_location("kai_mailbox_tools", ROOT / "mailbox_tools.py")
mailbox = importlib.util.module_from_spec(mailbox_spec)
sys.modules[mailbox_spec.name] = mailbox
mailbox_spec.loader.exec_module(mailbox)


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

    def test_resolver_revalidates_persisted_revoke_after_factory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            path.write_text(json.dumps({"bindings": self.config["bindings"]}), encoding="utf-8")
            os.chmod(path, 0o600)
            registry = module.ConversationBindingRegistry.load(path)
            revoker = module.ConversationBindingRegistry.load(path)
            identity = {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                        "provider_session_digest": digest("sess-a")}
            calls = []

            class Tools:
                def dispatch(self, name, arguments):
                    calls.append((name, arguments))
                    return {"ok": True}

            resolver = module.ConversationToolResolver(
                registry, lambda _request: identity,
                lambda binding: (revoker.revoke(binding.binding_id), Tools())[1])
            with self.assertRaises(module.ConversationBindingDenied):
                resolver.dispatch({"id": "request-a"}, "tproj_send", {"body": "x"})
            self.assertEqual(calls, [])

    def test_resolver_revalidates_expiry_after_factory_without_reattesting(self):
        now = [10.0]
        config = {"bindings": [{**self.config["bindings"][0], "expires_at": 20}]}
        registry = module.ConversationBindingRegistry(config, clock=lambda: now[0])
        attestations = []
        calls = []

        class Tools:
            def dispatch(self, name, arguments):
                calls.append(name)
                return {"ok": True}

        def attestor(_request):
            attestations.append(True)
            return {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                    "provider_session_digest": digest("sess-a")}

        def factory(_binding):
            now[0] = 20.0
            return Tools()

        resolver = module.ConversationToolResolver(registry, attestor, factory)
        with self.assertRaises(module.ConversationBindingExpired):
            resolver.dispatch({"id": "request-a"}, "tproj_send", {"body": "x"})
        self.assertEqual(len(attestations), 1)
        self.assertEqual(calls, [])

    def test_send_and_reply_submission_ids_are_binding_and_operation_scoped(self):
        captured = []

        class Tools:
            def dispatch(self, name, arguments):
                captured.append((name, dict(arguments)))
                return {"ok": True}

        config = {"bindings": self.config["bindings"]}
        registry = module.ConversationBindingRegistry(config)
        attestations = {
            "a": {"principal_id": "owner-a", "provider_subject_digest": digest("sub-a"),
                  "provider_session_digest": digest("sess-a")},
            "b": {"principal_id": "owner-b", "provider_subject_digest": digest("sub-b"),
                  "provider_session_digest": digest("sess-b")},
        }
        resolver = module.ConversationToolResolver(
            registry, lambda request: attestations[request["id"]], lambda _binding: Tools())
        original = {"target": "peer.cc", "body": "first", "submission_id": "same-input"}
        resolver.dispatch({"id": "a"}, "tproj_send", original)
        resolver.dispatch({"id": "a"}, "tproj_send", {**original, "body": "changed"})
        resolver.dispatch({"id": "a"}, "tproj_reply", {**original, "message_id": "m-1"})
        resolver.dispatch({"id": "b"}, "tproj_send", original)
        self.assertEqual(original["submission_id"], "same-input")
        send_ids = [args["submission_id"] for name, args in captured if name == "tproj_send"]
        self.assertEqual(send_ids[0], send_ids[1])
        self.assertNotEqual(send_ids[0], captured[2][1]["submission_id"])
        self.assertNotEqual(send_ids[0], captured[3][1]["submission_id"])

    def test_submission_namespace_encoding_separates_delimiter_like_values(self):
        first = module.ConversationBinding.from_config({
            **self.config["bindings"][0], "binding_id": "x\u0000tproj_send\u0000y"})
        second = module.ConversationBinding.from_config({
            **self.config["bindings"][1], "binding_id": "x"})
        left = module.ConversationToolResolver._namespaced_arguments(
            first, "tproj_send", {"submission_id": "z"})["submission_id"]
        right = module.ConversationToolResolver._namespaced_arguments(
            second, "tproj_send", {"submission_id": "y\u0000tproj_send\u0000z"})["submission_id"]
        self.assertNotEqual(left, right)

    def test_invalid_submission_ids_use_existing_validator_without_host_call(self):
        host_calls = []
        tools = mailbox.MailboxTools(
            service_id="svc-a", service_address="a@example", service_token="private",
            authorizer=lambda _name, _args: {"allowed_addresses": ["peer.cc"]},
            host_call=lambda request: host_calls.append(request) or {"message_id": "m-1", "thread_id": "t-1"})
        registry = module.ConversationBindingRegistry(self.config)
        resolver = module.ConversationToolResolver(
            registry, lambda _request: {"principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"),
                "provider_session_digest": digest("sess-a")}, lambda _binding: tools)
        invalid = (None, 7, [], "", "bad id", "bad\tid", "x" * 129)
        for value in invalid:
            original = {"target": "peer.cc", "body": "body", "submission_id": value}
            with self.assertRaises(mailbox.MailboxToolError) as raised:
                resolver.dispatch({"id": "a"}, "tproj_send", original)
            self.assertEqual(raised.exception.code, "invalid_message")
            self.assertEqual(original["submission_id"], value)
        missing = {"target": "peer.cc", "body": "body"}
        with self.assertRaises(mailbox.MailboxToolError):
            resolver.dispatch({"id": "a"}, "tproj_send", missing)
        self.assertEqual(host_calls, [])

    def test_changed_payload_keeps_namespaced_id_for_host_conflict(self):
        host_calls = []
        seen = {}

        def host_call(request):
            host_calls.append(request)
            key = request["submission_id"]
            payload = request["body"]
            if key in seen and seen[key] != payload:
                raise mailbox.MailboxToolError("idempotency_conflict", "submission payload conflict")
            seen[key] = payload
            return {"message_id": "m-1", "thread_id": "t-1"}

        tools = mailbox.MailboxTools(
            service_id="svc-a", service_address="a@example", service_token="private",
            authorizer=lambda _name, _args: {"allowed_addresses": ["peer.cc"]},
            host_call=host_call)
        registry = module.ConversationBindingRegistry(self.config)
        resolver = module.ConversationToolResolver(
            registry, lambda _request: {"principal_id": "owner-a",
                "provider_subject_digest": digest("sub-a"),
                "provider_session_digest": digest("sess-a")}, lambda _binding: tools)
        base = {"target": "peer.cc", "body": "first", "submission_id": "same-input"}
        resolver.dispatch({"id": "a"}, "tproj_send", base)
        with self.assertRaises(mailbox.MailboxToolError) as raised:
            resolver.dispatch({"id": "a"}, "tproj_send", {**base, "body": "changed"})
        self.assertEqual(raised.exception.code, "idempotency_conflict")
        self.assertEqual(host_calls[0]["submission_id"], host_calls[1]["submission_id"])


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import unittest
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kai_mailbox_tools", ROOT / "mailbox_tools.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

connection_spec = importlib.util.spec_from_file_location("kai_connection", ROOT / "connection.py")
connection = importlib.util.module_from_spec(connection_spec)
connection_spec.loader.exec_module(connection)


class MailboxToolsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def host(req):
            self.calls.append(req)
            op = req["op"]
            if op == "service_list":
                return {"participants": [{"address": "voyager.cc", "kind": "cc", "online": True},
                                          {"address": "secret.cc", "kind": "cc", "online": True}]}
            if op == "service_send":
                return {"message_id": req["submission_id"], "state": "queued"}
            if op == "service_reply":
                return {"message_id": req["submission_id"], "state": "queued"}
            if op == "service_message":
                return {"message_id": req["message_id"], "thread_id": "thread-1", "target_address": "kai",
                        "sender_address": "voyager.cc", "body": "hello", "state": "queued"}
            if op == "service_inbox":
                return {"messages": [], "next_cursor": req["cursor"]}
            if op == "service_status":
                return {"online": True}
            return {"state": "presented"}

        self.host = host
        self.authorizer = lambda _name, _args: {"allowed_addresses": ["voyager.cc"]}
        self.tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                          authorizer=self.authorizer, host_call=self.host)

    def test_message_preserves_response_evidence_without_synthesizing_ack(self):
        item = {'message_id':'original','thread_id':'thread','target_address':'voyager.cc',
                'body':'example','state':'uncertain','response_state':'recipient_replied',
                'recipient_reply_count':1,'recipient_reply_message_ids':['reply'],
                'delivery_summary':{'status':'recipient_replied','lifecycle':'ttl_elapsed',
                                    'pending_age_seconds':None,'reason_observed_at':None}}
        out = module.MailboxTools._view(item)
        self.assertEqual(out['state'], 'uncertain')
        self.assertEqual(out['response_state'], 'recipient_replied')
        self.assertEqual(out['recipient_reply_message_ids'], ['reply'])
        self.assertNotIn('ack', out)
        self.assertEqual(out['delivery_summary'], item['delivery_summary'])

    def test_repo_tools_send_only_declared_fields_to_the_service_ops(self):
        seen = []
        def host(req):
            seen.append(req)
            if req["op"] == "service_repo_list":
                return {"repos": [{"repo_id": "p1", "name": "proj"}]}
            return {"repo_id": "p1", "cite": "proj@abc:f.txt:L1-L2", "lines": [{"n": 1, "text": "SECRET-BODY-LINE"}], "truncated": False, "consistent": True}
        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=self.authorizer, host_call=host)
        listing = tools.dispatch("tproj_repo_list", {})
        self.assertEqual(listing["repos"][0]["repo_id"], "p1"); self.assertIn("1 readable", listing["_summary"])
        out = tools.dispatch("tproj_repo_read", {"repo_id": "p1", "path": "f.txt", "start": 1, "end": 2})
        self.assertEqual(seen[-1]["op"], "service_repo_read")
        self.assertEqual({k: seen[-1][k] for k in ("repo_id", "path", "start", "end")}, {"repo_id": "p1", "path": "f.txt", "start": 1, "end": 2})
        self.assertIn("proj@abc:f.txt:L1-L2", out["_summary"])        # one-line text, not a second copy
        self.assertNotIn("SECRET-BODY-LINE", out["_summary"])
        before = len(seen)
        for bad in ({"repo_id": "p1", "path": "f.txt", "host": "mini"}, {"repo_id": "p1", "path": "f.txt", "absolute_path": "/etc"},
                    {"repo_id": "p1"}, {"path": "f.txt"}):
            with self.assertRaises(module.MailboxToolError):
                tools.dispatch("tproj_repo_read", bad)
        self.assertEqual(len(seen), before)                           # rejected before the host is touched
        with self.assertRaises(module.MailboxToolError) as raised:
            tools.dispatch("tproj_repo_read", {"repo_id": "p1", "path": "f.txt", "session": "fake"})
        self.assertEqual(raised.exception.code, "identity_rejected")

    def test_write_tools_send_only_declared_fields_and_never_a_content_copy_in_the_text(self):
        seen = []
        def host(req):
            seen.append(req)
            return {"patch_id": req["patch_id"], "applied": True, "files": [{"path": "a.md", "status": "ok"}]}
        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=self.authorizer, host_call=host)
        change = {"repo_id": "p1", "patch_id": "44444444-4444-4444-8444-444444444444",
                  "changes": [{"path": "a.md", "action": "create", "content": "PRIVATE-CONTENT"}]}
        out = tools.dispatch("tproj_repo_write", change)
        self.assertEqual(seen[-1]["op"], "service_repo_write")
        self.assertNotIn("PRIVATE-CONTENT", out["_summary"]); self.assertIn("1 file", out["_summary"])
        tools.dispatch("tproj_repo_revert", {"repo_id": "p1", "patch_id": change["patch_id"]})
        self.assertEqual(seen[-1]["op"], "service_repo_revert")
        before = len(seen)
        for bad in (dict(change, host="mini"), dict(change, path="/etc/x"), {"repo_id": "p1"}):
            with self.assertRaises(module.MailboxToolError):
                tools.dispatch("tproj_repo_write", bad)
        self.assertEqual(len(seen), before)

    def test_rejected_authorizer_makes_zero_host_calls(self):
        self.tools.authorizer = lambda _name, _args: None
        with self.assertRaises(module.MailboxToolError) as raised:
            self.tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "s1"})
        self.assertEqual(raised.exception.code, "identity_rejected")
        self.assertEqual(self.calls, [])

    def test_diagnose_is_metadata_only_and_bypasses_adapter_whoami(self):
        seen = []
        def host(req):
            seen.append(req)
            return {"submission_id": req["submission_id"], "state": "unknown",
                    "failure_stage": "authority_rpc", "acceptance": "unknown"}
        def should_not_attest(_name, _args):
            raise AssertionError("diagnose must use authenticated service_diagnose directly")
        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=should_not_attest, host_call=host)
        result = tools.dispatch("tproj_diagnose", {"submission_id": "diag-1"})
        self.assertEqual(result["failure_stage"], "authority_rpc")
        self.assertEqual(seen[0]["op"], "service_diagnose")
        self.assertNotIn("body", result)

    def test_nested_transport_unavailable_is_not_identity_rejection(self):
        binding = connection.KaiServiceBinding("kai", "kai", "kai.service", "secret", ("voyager.cc",), "gen-1")
        authorizer = connection.FixedConnectionAuthorizer(
            binding, lambda: (_ for _ in ()).throw(OSError("credential=secret socket unavailable")))
        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                     authorizer=authorizer.authorize, host_call=self.host)
        with self.assertRaises(module.MailboxToolError) as raised:
            tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "s1"})
        self.assertEqual(raised.exception.code, "unavailable")
        self.assertEqual(raised.exception.message, "trusted conversation service unavailable")
        self.assertEqual(self.calls, [])

        rejecting = connection.FixedConnectionAuthorizer(
            binding, lambda: {"binding_id": "wrong", "incarnation": "inc-1",
                              "service_id": "other", "address": "kai",
                              "participant_id": "kai.service", "allowed_addresses": ["voyager.cc"]})
        tools.authorizer = rejecting.authorize
        with self.assertRaises(module.MailboxToolError) as rejected:
            tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "s2"})
        self.assertEqual(rejected.exception.code, "identity_rejected")
        self.assertEqual(self.calls, [])

    def test_invalid_identity_selector_is_rejected_before_host(self):
        with self.assertRaises(module.MailboxToolError) as raised:
            self.tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "s1", "session": "fake"})
        self.assertEqual(raised.exception.code, "identity_rejected")
        self.assertEqual(self.calls, [])

    def test_send_uses_stable_submission_id_and_fixed_service_binding(self):
        result = self.tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "stable-1"})
        self.assertEqual(result["message_id"], "stable-1")
        self.assertEqual(result["thread_id"], "stable-1")
        self.assertEqual(self.calls[0]["service_id"], "kai")
        self.assertEqual(self.calls[0]["address"], "kai")
        self.assertEqual(self.calls[0]["target"], "voyager.cc")
        self.assertEqual(self.calls[0]["submission_id"], "stable-1")

    def test_authorized_service_target_sends_once_and_rejects_out_of_scope_forms(self):
        result = self.tools.dispatch("tproj_send", {"target": "kai", "body": "x", "submission_id": "kai-out"})
        self.assertEqual(result["message_id"], "kai-out")
        self.tools.authorizer = lambda _name, _args: {"allowed_addresses": ["kai", "voyager.cc"]}
        result = self.tools.dispatch("tproj_send", {"target": "kai", "body": "x", "submission_id": "kai-1"})
        self.assertEqual(result["message_id"], "kai-1")
        self.assertEqual([call["op"] for call in self.calls], ["service_send", "service_send"])
        for target in ("cc", "cdx", "../kai", "kai\n", "kai\x01", "kai..service"):
            with self.assertRaises(module.MailboxToolError) as raised:
                self.tools.dispatch("tproj_send", {"target": target, "body": "x", "submission_id": "bad-" + str(len(self.calls))})
            self.assertEqual(raised.exception.code, "unknown_target")
        self.assertEqual(len(self.calls), 2)

    def test_unicode_project_target_remains_compatible(self):
        self.tools.authorizer = lambda _name, _args: {"allowed_addresses": ["航海.cc"]}
        result = self.tools.dispatch("tproj_send", {"target": "航海.cc", "body": "x", "submission_id": "unicode-1"})
        self.assertEqual(result["message_id"], "unicode-1")
        self.assertEqual(self.calls[0]["target"], "航海.cc")

    def test_internal_dot_unicode_project_target_status_and_send_are_authorized(self):
        target = "航海.v2.cc"
        self.tools.authorizer = lambda _name, _args: {"allowed_addresses": [target]}
        status = self.tools.dispatch("tproj_status", {"target": target})
        sent = self.tools.dispatch("tproj_send", {"target": target, "body": "x", "submission_id": "unicode-dot-1"})
        self.assertEqual(status["target"], target)
        self.assertEqual(sent["message_id"], "unicode-dot-1")
        self.assertEqual([call["op"] for call in self.calls], ["service_status", "service_send"])
        self.assertEqual(self.calls[0]["target"], target)
        self.assertEqual(self.calls[1]["target"], target)

    def test_internal_dot_unicode_project_target_is_delegated_to_host_scope_policy(self):
        target = "航海.v2.cc"
        self.tools.authorizer = lambda _name, _args: {"allowed_addresses": ["航海.v3.cc"]}
        result = self.tools.dispatch("tproj_send", {"target": target, "body": "x", "submission_id": "unicode-dot-out"})
        self.assertEqual(result["message_id"], "unicode-dot-out")
        self.assertEqual(self.calls[-1]["target"], target)

    def test_project_address_regex_rejects_long_dotted_nonmatching_target(self):
        self.assertIsNone(module.PROJECT_ADDRESS_RE.fullmatch(("a." * 25) + "x"))

    def test_reply_is_pinned_and_ack_is_scoped(self):
        reply = self.tools.dispatch("tproj_reply", {"message_id": "original", "body": "back", "submission_id": "reply-1"})
        self.assertEqual(reply["in_reply_to"], "original")
        self.assertEqual([call["op"] for call in self.calls[:2]], ["service_message", "service_reply"])
        self.assertEqual({key: self.calls[1][key] for key in ("message_id", "body", "submission_id")},
                         {"message_id": "original", "body": "back", "submission_id": "reply-1"})
        ack = self.tools.dispatch("tproj_ack", {"message_id": "original"})
        self.assertEqual(ack, {"message_id": "original", "state": "presented"})
        self.assertEqual(self.calls[-1]["op"], "service_ack")
        self.assertEqual(self.calls[-1]["message_id"], "original")

    def test_reply_preloads_thread_and_never_reads_after_commit(self):
        seen = []
        committed = {"message_id": "reply-2", "state": "queued"}

        def host(req):
            seen.append(req["op"])
            if req["op"] == "service_message":
                return {"thread_id": "thread-original"}
            if req["op"] == "service_reply":
                return committed
            raise AssertionError(req["op"])

        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=self.authorizer, host_call=host)
        result = tools.dispatch("tproj_reply", {"message_id": "original", "body": "back", "submission_id": "reply-2"})
        self.assertEqual(result["thread_id"], "thread-original")
        self.assertEqual(seen, ["service_message", "service_reply"])

    def test_reply_thread_lookup_failure_prevents_mutation(self):
        seen = []

        def host(req):
            seen.append(req["op"])
            if req["op"] == "service_message":
                raise module.MailboxToolError("unavailable", "host offline")
            raise AssertionError(req["op"])

        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=self.authorizer, host_call=host)
        with self.assertRaises(module.MailboxToolError) as raised:
            tools.dispatch("tproj_reply", {"message_id": "original", "body": "back", "submission_id": "reply-3"})
        self.assertEqual(raised.exception.code, "unavailable")
        self.assertEqual(seen, ["service_message"])

    def test_long_lived_adapter_uses_fresh_host_scope_and_reply_survives_empty_scope(self):
        state = {"scope": ["voyager.cc"]}
        calls = []

        def authorizer(name, _args):
            calls.append((name, list(state["scope"])))
            return {"allowed_addresses": list(state["scope"])}

        tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                    authorizer=authorizer, host_call=self.host)
        first = tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "one", "submission_id": "long-1"})
        self.assertEqual(first["message_id"], "long-1")
        state["scope"] = []
        reply = tools.dispatch("tproj_reply", {"message_id": "original", "body": "back", "submission_id": "long-2"})
        self.assertEqual(reply["message_id"], "long-2")
        self.assertEqual([name for name, _scope in calls], ["tproj_send", "tproj_reply"])

    def test_list_preserves_authoritative_host_projection(self):
        # Scope filtering belongs to Host, not this adapter/mock.
        result = self.tools.dispatch("tproj_list", {})
        self.assertEqual(result, {"participants": [{"address": "voyager.cc", "kind": "cc", "available": True},
                                                     {"address": "secret.cc", "kind": "cc", "available": True}]})

    def test_inbox_hides_cancelled_envelopes(self):
        def cancelled_host(req):
            if req["op"] == "service_inbox":
                return {"messages": [{"message_id": "gone", "thread_id": "t", "target_address": "kai",
                                       "body": "do not deliver", "state": "cancelled"},
                                      {"message_id": "live", "thread_id": "t2", "target_address": "kai",
                                       "body": "deliver", "state": "queued"}], "next_cursor": 2}
            return self.host(req)
        self.tools.host_call = cancelled_host
        result = self.tools.dispatch("tproj_inbox", {})
        self.assertEqual([item["message_id"] for item in result["messages"]], ["live"])

    def test_begin_present_race_suppresses_cancelled_before_body(self):
        seen = []
        def race_host(req):
            seen.append(req["op"])
            if req["op"] == "service_inbox":
                return {"messages": [{"message_id": "race", "thread_id": "t", "target_address": "kai",
                                       "body": "must not surface", "state": "queued"}], "next_cursor": 1}
            if req["op"] == "service_begin_present":
                raise module.MailboxToolError("cancelled", "cancelled before presentation")
            return self.host(req)
        self.tools.host_call = race_host
        result = self.tools.dispatch("tproj_inbox", {})
        self.assertEqual(result["messages"], [])
        self.assertEqual(seen, ["service_inbox", "service_begin_present"])

    def test_begin_present_unrelated_error_is_not_hidden(self):
        def failing_host(req):
            if req["op"] == "service_inbox":
                return {"messages": [{"message_id": "x", "state": "queued"}], "next_cursor": 1}
            if req["op"] == "service_begin_present":
                raise module.MailboxToolError("unavailable", "host offline")
            return self.host(req)
        self.tools.host_call = failing_host
        with self.assertRaises(module.MailboxToolError) as raised:
            self.tools.dispatch("tproj_inbox", {})
        self.assertEqual(raised.exception.code, "unavailable")

    def test_real_host_cancellation_race_reread_and_sent_query(self):
        sys.path.insert(0, str(ROOT.parents[1] / "unified"))
        from hub import Hub
        from host import Host
        from protocol import HubError
        with tempfile.TemporaryDirectory() as tmp:
            hub = Hub(Path(tmp) / "hub.db", {"admin_token": "admin", "hosts": {"h": "token"}})
            host = Host({"journal": str(Path(tmp) / "journal.db"), "host_id": "h"}, recover=False)
            self.addCleanup(hub.close); self.addCleanup(host.db.close)
            hub.dispatch(dict(op="directory_import", admin_token="admin",
                              projects=[dict(project_id="p", alias="voyager", host_id="h", path="/p")],
                              services=[dict(participant_id="kai", address="kai", host_id="h", kind="kai")]))
            for eid, participant in (("sender", "p:cc"), ("receiver", "kai")):
                hub.dispatch(dict(op="endpoint_register", host_id="h", host_token="token", endpoint_id=eid,
                                  participant_id=participant, session=eid, pane="", pid=1, pid_start=1,
                                  runtime_id=eid, platform="test"))
            host.service = lambda *_: dict(endpoint_id="receiver", runtime_id="receiver")
            host.hub = lambda op, **kw: hub.dispatch(dict(op=op, host_id="h", host_token="token", **kw))
            def send(mid, sender="sender", target="kai"):
                hub.dispatch(dict(op="submit", host_id="h", host_token="token",
                                  message=dict(message_id=mid, thread_id=mid, sender_endpoint=sender,
                                               target=target, body="payload")))
            send("race")
            def call(req):
                if req["op"] == "service_begin_present" and req["message_id"] == "race":
                    hub.cancel(dict(host_id="h", host_token="token", endpoint_id="sender", message_id="race"))
                return host.dispatch(req, os.getpid(), os.getuid())
            self.tools.host_call = call
            self.assertEqual(self.tools.dispatch("tproj_inbox", {})["messages"], [])
            send("live")
            self.assertEqual(self.tools.dispatch("tproj_inbox", {})["messages"][0]["message_id"], "live")
            with self.assertRaisesRegex(HubError, "execution is not cancelled"):
                hub.cancel(dict(host_id="h", host_token="token", endpoint_id="sender", message_id="live"))
            self.assertEqual(self.tools.dispatch("tproj_message", {"message_id": "live"})["body"], "payload")
            send("outbound", "receiver", "voyager.cc")
            self.assertEqual(self.tools.dispatch("tproj_message", {"message_id": "outbound"})["state"], "accepted")


if __name__ == "__main__":
    unittest.main()

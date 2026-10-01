import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kai_mailbox_tools", ROOT / "mailbox_tools.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MailboxToolsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def host(req):
            self.calls.append(req)
            op = req["op"]
            if op == "list":
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
            return {"state": "presented"}

        self.host = host
        self.authorizer = lambda _name, _args: {"allowed_addresses": ["voyager.cc"]}
        self.tools = module.MailboxTools(service_id="kai", service_address="kai", service_token="private",
                                          authorizer=self.authorizer, host_call=self.host)

    def test_rejected_authorizer_makes_zero_host_calls(self):
        self.tools.authorizer = lambda _name, _args: None
        with self.assertRaises(module.MailboxToolError) as raised:
            self.tools.dispatch("tproj_send", {"target": "voyager.cc", "body": "x", "submission_id": "s1"})
        self.assertEqual(raised.exception.code, "identity_rejected")
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
        self.assertNotIn("target", {"service_id", "service_token", "address"})

    def test_reply_is_pinned_and_ack_is_scoped(self):
        reply = self.tools.dispatch("tproj_reply", {"message_id": "original", "body": "back", "submission_id": "reply-1"})
        self.assertEqual(reply["in_reply_to"], "original")
        self.assertEqual(self.calls[0]["op"], "service_reply")
        ack = self.tools.dispatch("tproj_ack", {"message_id": "original"})
        self.assertEqual(ack, {"message_id": "original", "state": "presented"})
        self.assertEqual(self.calls[-1]["op"], "service_ack")
        self.assertEqual(self.calls[-1]["message_id"], "original")

    def test_list_filters_to_authorized_scope(self):
        result = self.tools.dispatch("tproj_list", {})
        self.assertEqual(result, {"participants": [{"address": "voyager.cc", "kind": "cc", "available": True}]})


if __name__ == "__main__":
    unittest.main()

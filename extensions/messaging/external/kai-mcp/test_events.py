import base64
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import events


class Authorizer:
    def __init__(self):
        self.binding = "binding-one"
        self.incarnation = "incarnation-one"
        self.reads = 0

    def reader(self, cursor):
        self.reads += 1
        return {"messages": [{"message_id": "message-one", "body": "not in webhook"}] if cursor == 0 else [], "next_cursor": 1}

    def authorize(self):
        return events.TrustedBinding(self.binding, self.incarnation, self.reader)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.authorizer = Authorizer()
        self.path = Path(self.directory.name) / "state.json"
        self.delivery = events.KAIEventDelivery(self.authorizer, self.path)
        self.secret = "whsec_" + base64.b64encode(b"x" * 24).decode()
        self.addCleanup(patch.stopall)
        patch.object(events._secure, "public_https", return_value=True).start()
        self.delivery._post = lambda url, eid, secret, payload, *rest: (True, {"challenge": payload.get("challenge")})

    def subscribe(self):
        return self.delivery.subscribe("https://callback.example/event?route=one", self.secret)["id"]

    def test_missing_auth_and_invalid_page_fail_before_send(self):
        denied = events.KAIEventDelivery(None, self.path)
        with self.assertRaises(RuntimeError):
            denied.pump_once()
        with self.assertRaises(RuntimeError):
            denied.subscribe("https://callback.example/event", self.secret)
        self.assertEqual(self.authorizer.reads, 0)
        self.subscribe()
        self.authorizer.reader = lambda cursor: {"messages": [{"message_id": "one"}], "next_cursor": -1}
        self.delivery._post = lambda *args: self.fail("invalid cursor caused a post")
        with self.assertRaises(RuntimeError):
            self.delivery.pump_once()

    def test_post_crash_recovers_exact_persisted_id_and_payload(self):
        sid = self.subscribe()
        sent = []

        def crash_after_accept(url, eid, secret, payload, subscription):
            persisted = self.delivery._load()
            self.assertEqual(persisted["outbox"][eid]["payload"], payload)
            self.assertEqual(persisted["cursor"][sid], 1)
            self.assertEqual(persisted["outbox"][eid]["attempts"], 1)
            sent.append((eid, copy.deepcopy(payload), subscription))
            raise RuntimeError("process crashed after callback accepted")

        self.delivery._post = crash_after_accept
        with self.assertRaisesRegex(RuntimeError, "process crashed"):
            self.delivery.pump_once()
        restarted = events.KAIEventDelivery(self.authorizer, self.path)
        restarted._post = lambda url, eid, secret, payload, subscription: (sent.append((eid, copy.deepcopy(payload), subscription)) or (True, {}))
        future = time.time() + 10
        with patch.object(events.time, "time", return_value=future):
            self.assertEqual(restarted.pump_once(), 0)
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(sent[0][1]["data"], {"messageId": "message-one"})
        self.assertIsInstance(sent[0][1]["timestamp"], str)
        self.assertEqual(restarted._load()["outbox"][sent[0][0]]["status"], "sent")
        restarted._post = lambda *args: self.fail("successful event duplicated")
        restarted.pump_once()

    def test_expiry_incarnation_and_unsubscribe_fence_pending_delivery(self):
        for operation in ("expiry", "incarnation", "unsubscribe"):
            with self.subTest(operation=operation):
                path = Path(self.directory.name) / (operation + ".json")
                auth = Authorizer()
                delivery = events.KAIEventDelivery(auth, path)
                delivery._post = lambda url, eid, secret, payload, *rest: (True, {"challenge": payload.get("challenge")})
                sid = delivery.subscribe("https://callback.example/event", self.secret)["id"]
                delivery._post = lambda *args: (False, {})
                delivery.pump_once()
                state = delivery._load()
                if operation == "expiry":
                    state["subscriptions"][sid]["expiresAt"] = 0
                    with delivery._lock():
                        delivery._save(state)
                elif operation == "incarnation":
                    auth.incarnation = "incarnation-two"
                    delivery.pump_once()
                    self.assertEqual(delivery._load()["subscriptions"][sid]["incarnation"], "incarnation-two")
                else:
                    delivery.unsubscribe(sid)
                delivery._post = lambda *args: self.fail("revoked, expired, or stale event posted")
                future = time.time() + 10
                with patch.object(events.time, "time", return_value=future):
                    delivery.pump_once()
                self.assertEqual(next(iter(delivery._load()["outbox"].values()))["status"], "revoked")

    def test_failed_delivery_has_bounded_attempts(self):
        self.subscribe()
        posted = []
        self.delivery._post = lambda *args: (posted.append(args[1]) or (False, {}))
        now = time.time()
        for offset in (0, 10, 20, 30):
            with patch.object(events.time, "time", return_value=now + offset):
                self.delivery.pump_once()
        self.assertEqual(len(posted), events.MAX_ATTEMPTS)
        self.assertEqual(len(set(posted)), 1)
        self.assertEqual(next(iter(self.delivery._load()["outbox"].values()))["status"], "terminal")

    def test_one_active_callback_per_binding(self):
        self.subscribe()
        with self.assertRaisesRegex(RuntimeError, "already bound"):
            self.delivery.subscribe("https://callback.example/other", self.secret)

    def test_cancelled_mailbox_entry_never_becomes_event(self):
        self.authorizer.reader = lambda cursor: {
            "messages": [{"message_id": "gone", "state": "cancelled"}], "next_cursor": 1}
        self.subscribe()
        self.delivery._post = lambda *args: self.fail("cancelled entry was posted")
        self.assertEqual(self.delivery.pump_once(), 0)
        self.assertEqual(self.delivery._load()["outbox"], {})


if __name__ == "__main__":
    unittest.main()

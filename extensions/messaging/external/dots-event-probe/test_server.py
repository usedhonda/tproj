import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("kai_event_probe", ROOT / "server.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProbeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "subscriptions.json"
        self.env = patch.dict(os.environ, {"KAI_EVENT_PROBE_STATE": str(self.state)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_corrupt_state_fails_closed(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text("not-json")
        with self.assertRaises(MODULE.StateError):
            MODULE.Probe()

    def test_malformed_unsubscribe_is_json_rpc_error(self):
        probe = MODULE.Probe()
        response = probe.handle({"jsonrpc": "2.0", "id": 1, "method": "events/unsubscribe", "params": {"name": MODULE.EVENT_NAME, "delivery": []}})
        self.assertEqual(response["error"]["code"], -32602)

    def test_stable_event_id_reuses_payload_and_rejects_conflict(self):
        probe = MODULE.Probe()
        secret = "whsec_" + MODULE.base64.b64encode(b"x" * 24).decode()
        subscription = {"id": "sub_test", "url": "https://example.com/callback", "secret": secret, "expiresAt": None}
        with MODULE.state_lock():
            state = MODULE.load_state()
            state["subscriptions"]["sub_test"] = subscription
            MODULE.save_state(state)
        calls = []
        probe.post = lambda *args: (calls.append(args) or (True, {}, "ok"))
        self.assertEqual(probe.send_one("sub_test", "one", "evt_fixed")[1], "ok")
        self.assertEqual(probe.send_one("sub_test", "one", "evt_fixed")[1], "already_sent")
        self.assertEqual(probe.send_one("sub_test", "two", "evt_fixed")[1], "event_id_conflict")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][4], "evt_fixed")

    def test_expired_subscription_is_not_delivered(self):
        probe = MODULE.Probe()
        with MODULE.state_lock():
            state = MODULE.load_state()
            state["subscriptions"]["sub_expired"] = {"id": "sub_expired", "url": "https://example.com", "secret": "whsec_" + MODULE.base64.b64encode(b"x" * 24).decode(), "expiresAt": 1}
            MODULE.save_state(state)
        probe.post = lambda *args: self.fail("expired subscription delivered")
        self.assertEqual(probe.send_one("sub_expired", "one", "evt_expired")[1], "subscription_expired")

    def test_context_is_digest_only(self):
        probe = MODULE.Probe()
        response = probe.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "connection_status", "_meta": {"openai/subject": "secret-subject"}}})
        text = response["result"]["structuredContent"]
        self.assertNotIn("secret-subject", json.dumps(text))
        self.assertEqual(text["context"]["digests"]["openai/subject"], MODULE.hashlib.sha256(b"secret-subject").hexdigest())


if __name__ == "__main__":
    unittest.main()

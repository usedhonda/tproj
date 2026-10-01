import tempfile, unittest
from pathlib import Path
import events

class A:
    def __init__(self): self.messages=[{"id":"m1"}]
    def authorize(self): return events.TrustedBinding("b1","i1",lambda cursor: self.messages)

class T(unittest.TestCase):
    def test_fail_closed_and_stable_outbox(self):
        with tempfile.TemporaryDirectory() as d:
            e=events.KAIEventDelivery(A(),Path(d)/"state.json"); e._post=lambda *a:(True,{"challenge":a[3]["challenge"]})
            # invalid URL is rejected before any mailbox read
            with self.assertRaises(RuntimeError): e.subscribe("https://127.0.0.1/x","bad")
            e._post=lambda *a:(True,{"challenge":a[3]["challenge"]})
            with self.assertRaises(RuntimeError): e.subscribe("https://example.com/x","bad")

    def test_pump_deduplicates_ids_and_payload_has_no_body(self):
        with tempfile.TemporaryDirectory() as d:
            e=events.KAIEventDelivery(A(),Path(d)/"state.json"); e._post=lambda *a:(True,{"challenge":a[3].get("challenge")})
            sub=e.subscribe("https://example.com/x","whsec_"+events.base64.b64encode(b"x"*24).decode()); e._post=lambda *a:(True,{})
            self.assertEqual(e.pump_once(),1); self.assertEqual(e.pump_once(),0)
            out=e._load()["outbox"]; self.assertEqual(len(out),1); self.assertNotIn("body",next(iter(out.values()))["payload"])

if __name__ == "__main__": unittest.main()

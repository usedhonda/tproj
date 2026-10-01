import tempfile, unittest
from pathlib import Path
import events

class A:
    def __init__(self): self.messages=[{"message_id":"m1"}]
    def authorize(self): return events.TrustedBinding("b1","i1",lambda cursor: {"messages":self.messages,"next_cursor":1})

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

    def test_restart_and_expiry_do_not_duplicate_or_send(self):
        with tempfile.TemporaryDirectory() as d:
            e=events.KAIEventDelivery(A(),Path(d)/"state.json"); e._post=lambda *a:(True,{"challenge":a[3].get("challenge")})
            sub=e.subscribe("https://example.com/x","whsec_"+events.base64.b64encode(b"x"*24).decode()); sent=[]; e._post=lambda *a:(sent.append((a[1],a[3])) or (True,{})); e.pump_once(); first=sent[-1]
            e2=events.KAIEventDelivery(A(),Path(d)/"state.json"); e2._post=lambda *a:(sent.append((a[1],a[3])) or (True,{})); self.assertEqual(e2.pump_once(),0); self.assertEqual(first,sent[-1])
            state=e2._load(); state["subscriptions"][sub["id"]]["expiresAt"]=0; state["outbox"][first[0]]["status"]="unknown"; e2._save(state); e2._post=lambda *a:self.fail("expired delivery"); e2.pump_once()

if __name__ == "__main__": unittest.main()

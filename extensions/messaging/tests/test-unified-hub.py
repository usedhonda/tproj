#!/usr/bin/env python3
import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from extensions.messaging.unified import Hub, HubError
from extensions.messaging.unified.protocol import MAX_TTL

class HubTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.h=Hub(pathlib.Path(self.tmp.name)/"hub.db", {"admin_token":"adm","hosts":{"a":"ta","b":"tb"}})
        self.h.dispatch({"op":"directory_import","admin_token":"adm","projects":[{"project_id":"p","alias":"proj","host_id":"a","path":"/p"}]})
        self.h.db.execute("UPDATE participants SET host_id='b' WHERE participant_id='p:cdx'")
        self.reg("a","ta","ea","p:cc",1); self.reg("b","tb","eb","p:cdx",2)
    def tearDown(self): self.h.close(); self.tmp.cleanup()
    def reg(self,h,t,e,p,pid): return self.h.dispatch({"op":"endpoint_register","host_id":h,"host_token":t,"endpoint_id":e,"participant_id":p,"host_id":h,"session":"s","pane":"0","pid":pid,"pid_start":"x","runtime_id":"r","platform":"test"})
    def send(self,mid="m1",body="hello",target="cdx"):
        return self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":mid,"thread_id":"t","sender_endpoint":"ea","target":target,"body":body,"kind":"chat"}})
    def test_durable_idempotency_and_relative_route(self):
        self.assertEqual(self.send(), {"message_id":"m1","state":"queued"})
        self.assertTrue(self.send()["duplicate"])
        with self.assertRaisesRegex(HubError,"different payload"): self.send(body="changed")
        inbox=self.h.dispatch({"op":"inbox","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        self.assertEqual(inbox["messages"][0]["recipient_endpoint"],"eb")
    def test_reverse_reply_is_pinned(self):
        self.send(); self.h.dispatch({"op":"claim","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        out=self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"reply","thread_id":"t","in_reply_to":"m1","sender_endpoint":"eb","target":"proj.cc","body":"back"}})
        self.assertEqual(out["state"],"queued")
    def test_auth_maintenance_alias_revision_and_ttl(self):
        with self.assertRaises(HubError): self.send(target="other.cc")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"stopped"})
        with self.assertRaisesRegex(HubError,"paused"): self.send("paused")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"open"})
        with self.assertRaisesRegex(HubError,"24 hours"): self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"ttl","thread_id":"t","sender_endpoint":"ea","target":"cdx","body":"x","ttl_sec":MAX_TTL+1}})
    def test_ambiguous_endpoint_rejected(self):
        self.reg("b","tb","eb2","p:cdx",3)
        with self.assertRaisesRegex(HubError,"ambiguous"): self.send("amb")

if __name__ == "__main__": unittest.main()

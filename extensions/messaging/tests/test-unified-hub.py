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
    def test_diagnosis_is_metadata_only_and_operator_permission_is_explicit(self):
        self.send(body='private-body-sentinel')
        self.h.dispatch({'op':'directory_import','admin_token':'adm','projects':[{'project_id':'support','alias':'support','host_id':'a','path':'/support'}]})
        self.reg('a','ta','support-ep','support:cc',3)
        request={'op':'diagnose','host_id':'a','host_token':'ta','endpoint_id':'support-ep','message_id':'m1','operator_diagnostic':True}
        with self.assertRaises(HubError):self.h.dispatch(request)
        self.h.config['diagnostic_hosts']=['a']
        before=self.h.db.total_changes
        result=self.h.dispatch(request)
        self.assertEqual(self.h.db.total_changes,before)
        self.assertNotIn('body',result)
        self.assertNotIn('payload_hash',result)
        self.assertNotIn('private-body-sentinel',str(result))
        self.assertFalse(result['presentation_confirmed'])
        self.assertIsNone(result['delivery_reason'])

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
    def test_reply_to_restarted_openclaw_service_uses_sole_current_endpoint(self):
        self.h.dispatch({"op":"directory_import","admin_token":"adm","services":[{"participant_id":"gate","address":"gate","host_id":"a","kind":"openclaw"}]})
        self.reg("a","ta","gate-old","gate",3)
        self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"main-msg","thread_id":"main-thread","sender_endpoint":"gate-old","target":"proj.cdx","body":"hello"}})
        self.h.dispatch({"op":"endpoint_retire","host_id":"a","host_token":"ta","endpoint_id":"gate-old"})
        self.reg("a","ta","gate-new","gate",4)
        out=self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"main-reply","thread_id":"main-thread","in_reply_to":"main-msg","sender_endpoint":"eb","body":"back"}})
        self.assertEqual(out["state"],"queued")
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='main-reply'")[0], "gate-new")
        self.send("agent-msg")
        self.h.dispatch({"op":"endpoint_retire","host_id":"a","host_token":"ta","endpoint_id":"ea"})
        self.reg("a","ta","ea-new","p:cc",5)
        with self.assertRaisesRegex(HubError,"original sender endpoint is unavailable"):
            self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"agent-reply","thread_id":"t","in_reply_to":"agent-msg","sender_endpoint":"eb","body":"back"}})
    def test_auth_maintenance_alias_revision_and_ttl(self):
        with self.assertRaises(HubError): self.send(target="other.cc")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"stopped"})
        with self.assertRaisesRegex(HubError,"paused"): self.send("paused")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"open"})
        with self.assertRaisesRegex(HubError,"24 hours"): self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"ttl","thread_id":"t","sender_endpoint":"ea","target":"cdx","body":"x","ttl_sec":MAX_TTL+1}})
    def test_ambiguous_endpoint_rejected(self):
        self.reg("b","tb","eb2","p:cdx",3)
        with self.assertRaisesRegex(HubError,"ambiguous"): self.send("amb")

    def test_sender_cancel_fences_presentation_and_is_not_task_cancellation(self):
        self.send('cancel')
        owner=dict(host_id='a',host_token='ta',endpoint_id='ea',message_id='cancel')
        receiver=dict(host_id='b',host_token='tb',endpoint_id='eb',message_id='cancel')
        self.h.claim(receiver)
        with self.assertRaisesRegex(HubError,'original sender'): self.h.cancel(receiver)
        self.assertEqual(self.h.cancel(owner)['state'],'cancelled')
        with self.assertRaises(HubError): self.h.begin_present(receiver)
        with self.assertRaises(HubError): self.h.receipt(dict(receiver,state='presented'))
        self.assertEqual(self.h.claim(receiver)['messages'],[])
        self.send('started'); receiver['message_id']='started';owner['message_id']='started'
        self.h.begin_present(receiver)
        with self.assertRaisesRegex(HubError,'execution is not cancelled'): self.h.cancel(owner)

    def test_missing_heartbeat_rejects_send_without_retirement(self):
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='eb'")
        with self.assertRaisesRegex(HubError,'liveness'): self.send('old')
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='eb'")[0],0)

if __name__ == "__main__": unittest.main()

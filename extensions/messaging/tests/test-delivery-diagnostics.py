import sys, tempfile, unittest, os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
from host import Host

class DiagnosticsTest(unittest.TestCase):
 def test_notification_diagnostics_preserve_party_and_host_boundaries(self):
  import time
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as raw:
   host=Host({'journal':str(Path(raw)/'host.db'), 'host_id':'owner',
              'services':{'dots':{'participant_id':'dots-party','event_bridge_socket':'bridge','token':'private'}}})
   self.addCleanup(host.db.close)
   host.caller_read_only=lambda *args: {'endpoint_id':'sender','project_id':'project'}
   message={'message_id':'m','sender_endpoint':'sender','recipient_endpoint':'dots-ep',
            'recipient_host_id':'owner','created_at':time.time()-400,'state':'accepted',
            'presentation_confirmed':False}
   def hub(op,**fields):
    if op=='diagnose': return dict(message)
    if op=='endpoints_list': return {'endpoints':[{'endpoint_id':'dots-ep','participant_id':'dots-party','host_id':'owner'}]}
    raise AssertionError(op)
   host.hub=hub
   with patch('host.rpc',return_value={'pump':{'status':'ready'},'notifications':[]}) as bridge:
    result=host.dispatch({'op':'diagnose','message_id':'m'},1,os.getuid())
    self.assertEqual(result['notification']['status'],'available')
    self.assertTrue(result['presentation_wait_prolonged'])
    self.assertEqual(bridge.call_args.kwargs['timeout'],2)
   with patch('host.rpc',side_effect=TimeoutError):
    result=host.dispatch({'op':'diagnose','message_id':'m'},1,os.getuid())
    self.assertEqual(result['state'],'accepted')
    self.assertEqual(result['notification']['reason'],'bridge_unavailable')
   for change in ({'recipient_host_id':'remote'},{'sender_endpoint':'someone-else'}):
    saved=dict(message);message.update(change)
    with patch('host.rpc') as bridge:
     result=host.dispatch({'op':'diagnose','message_id':'m'},1,os.getuid())
     bridge.assert_not_called()
     self.assertEqual(result['notification']['status'],'unknown')
    message.clear();message.update(saved)

 def test_only_new_uncertainty_gets_evidenced_reason(self):
  with tempfile.TemporaryDirectory() as raw:
   cfg={'journal':str(Path(raw)/'host.db')}
   host=Host(cfg,recover=False)
   for mid,state in [('interrupted','dispatching'),('historical','uncertain')]:
    host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',(mid,'ep','{}',state,None,0))
   host.db.commit();host.db.close()
   host=Host(cfg)
   self.assertEqual(host.db.execute('SELECT reason FROM delivery_diagnostics WHERE message_id=?',('interrupted',)).fetchone()[0],'adapter_interrupted')
   self.assertIsNone(host.db.execute('SELECT reason FROM delivery_diagnostics WHERE message_id=?',('historical',)).fetchone())
   host.db.close()

 def test_codex_receipt_carries_native_binding_and_accepts_pinned_thread(self):
  import json,hashlib
  from unittest.mock import patch
  import receipt
  with tempfile.TemporaryDirectory() as raw:
   host=Host({'journal':str(Path(raw)/'host.db')})
   native='11111111-1111-4111-8111-111111111111'
   prompt='[from:other.cc] [tproj-message:m] example'
   ep={'endpoint_id':'ep','runtime_id':'tmux:bootstrap','platform':'cdx','thread_id':native}
   seen=[]
   def caller(pid,uid,req):
    seen.append(req)
    self.assertEqual(req['conversation']['thread_id'],native)
    return ep
   host.caller=caller
   host.hub=lambda op,**fields:fields
   host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',('m','ep','{}','uncertain',hashlib.sha256(prompt.encode()).hexdigest(),0));host.db.commit()
   with patch.object(receipt,'config',return_value={'socket':'test'}), patch.object(receipt,'_caller_request',side_effect=lambda op,**kw:dict(kw,op=op)), patch.object(receipt,'rpc',side_effect=lambda socket,req:host.dispatch(req,1,os.getuid())):
    self.assertTrue(receipt.submit_prompt_receipt({'session_id':native,'prompt':prompt},platform='cdx'))
   self.assertEqual(host.db.execute('SELECT state FROM deliveries').fetchone()[0],'presented')
   host.db.close()

 def test_codex_exact_transcript_recovery_rejects_wrong_evidence(self):
  import json,hashlib
  from receipt import codex_transcript_presented
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); native='11111111-1111-4111-8111-111111111111'
   folder=root/'2026/10/19';folder.mkdir(parents=True)
   path=folder/('rollout-test-'+native+'.jsonl')
   ep={'thread_id':native,'project_path':str(root/'project')}
   prompt='[from:peer] [tproj-message:example] exact body'
   digest=hashlib.sha256(prompt.encode()).hexdigest()
   header={'type':'session_meta','payload':{'id':native,'source':'cli','originator':'codex-tui','thread_source':'user','cwd':ep['project_path']}}
   user={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':prompt}]}}
   def write(item):path.write_text(json.dumps(header)+'\n'+json.dumps(item)+'\n')
   write(user)
   self.assertTrue(codex_transcript_presented(ep,digest,sessions_root=root))
   import time
   from unittest.mock import patch
   host=Host({'journal':str(root/'host.db'),'delivery_enabled':True})
   host.endpoints=[{'endpoint_id':'ep','platform':'cdx','project_path':ep['project_path']}];host.refreshed=time.monotonic()
   calls=[]
   host.hub=lambda op,**kw: calls.append((op,kw)) or ({'endpoint_native':[{'endpoint_id':'ep','native_kind':'thread_id','native_id':native}]} if op=='diagnostic_identity' else {'messages':[], 'next_sequence':0})
   host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',('example','ep',json.dumps({'message_id':'example'}),'uncertain',digest,0));host.db.commit()
   with patch('host.codex_transcript_presented',return_value=False):
    host.delivery_tick()
   self.assertEqual(host.db.execute('SELECT state FROM deliveries').fetchone()[0],'uncertain')
   with patch('host.codex_transcript_presented',side_effect=lambda endpoint,digest:codex_transcript_presented(endpoint,digest,sessions_root=root)):
    host.delivery_tick()
   self.assertEqual(host.db.execute('SELECT state FROM deliveries').fetchone()[0],'presented')
   self.assertTrue(any(op=='receipt' and fields.get('state')=='presented' for op,fields in calls))
   host.db.close()

   self.assertFalse(codex_transcript_presented(ep,'wrong-hash',sessions_root=root))
   self.assertFalse(codex_transcript_presented(dict(ep,project_path=str(root/'other')),digest,sessions_root=root))
   self.assertFalse(codex_transcript_presented(dict(ep,thread_id='22222222-2222-4222-8222-222222222222'),digest,sessions_root=root))
   for invalid in [dict(user,type='compacted'),{'type':'event_msg','payload':user['payload']},
                   {'type':'response_item','payload':dict(user['payload'],role='assistant')},
                   {'type':'response_item','payload':dict(user['payload'],content=[{'type':'input_text','text':'quoted '+prompt}])}]:
    write(invalid);self.assertFalse(codex_transcript_presented(ep,digest,sessions_root=root))
   write(user); header['payload']['id']='different';write(user)
   self.assertFalse(codex_transcript_presented(ep,digest,sessions_root=root))

 def test_native_host_ignores_self_asserted_operator_flag(self):
  seen=[]
  class NativeHost:
   config={'diagnostic_projects':['support']}
   def caller_read_only(self,pid,uid,req):return {'endpoint_id':'e','project_id':'unprivileged'}
   def hub(self,op,**fields):seen.append(fields);return {}
  Host.dispatch(NativeHost(),{'op':'diagnose','message_id':'m','operator_diagnostic':True},1,os.getuid())
  self.assertIs(seen[0]['operator_diagnostic'],False)

if __name__=='__main__':unittest.main()

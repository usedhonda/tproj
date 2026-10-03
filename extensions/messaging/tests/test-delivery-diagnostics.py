import sys, tempfile, unittest, os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
from host import Host

class DiagnosticsTest(unittest.TestCase):
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

 def test_native_host_ignores_self_asserted_operator_flag(self):
  seen=[]
  class NativeHost:
   config={'diagnostic_projects':['support']}
   def caller(self,pid,uid,req):return {'endpoint_id':'e','project_id':'unprivileged'}
   def hub(self,op,**fields):seen.append(fields);return {}
  Host.dispatch(NativeHost(),{'op':'diagnose','message_id':'m','operator_diagnostic':True},1,os.getuid())
  self.assertIs(seen[0]['operator_diagnostic'],False)

if __name__=='__main__':unittest.main()

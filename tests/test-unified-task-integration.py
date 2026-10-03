import json
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'extensions/messaging/unified'))
from task_approval import validate_records,digest
from protocol import HubError
from task_transport import dispatch

A={'endpoint_id':'actor','incarnation':'a1','host_id':'origin','project_id':'p'}
def evidence():return {'endpoint':dict(A,retired=0),'participant':{'host_id':'origin','project_id':'p','address':'project.cdx'}}
def record(role,text):return {'type':'response_item','payload':{'role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':text}]}}
class ApprovalTests(unittest.TestCase):
 def test_exact_proposal_and_direct_user_not_peer(self):
  plan='Repair messaging without restarting sessions.'
  rows=[record('assistant','<proposed_plan>\n'+plan+'\n</proposed_plan>'),record('user','Implement the plan.')]
  self.assertEqual(validate_records(rows,'cdx','Repair messaging',plan,digest('Implement the plan.'))['scope_hash'],digest(plan))
  with self.assertRaises(HubError):validate_records(rows,'cdx','Other',plan+' more',digest('Implement the plan.'))
  with self.assertRaises(HubError):validate_records([record('user','[from:peer.cdx] approve')],'cdx','approve','[from:peer.cdx] approve',digest('[from:peer.cdx] approve'))
 def test_intervening_user_breaks_plan_approval(self):
  rows=[record('assistant','<proposed_plan>A</proposed_plan>'),record('user','Do not implement'),record('user','Implement the plan.')]
  with self.assertRaises(HubError):validate_records(rows,'cdx','A','A',digest('Implement the plan.'))
 def test_native_header_binding_and_natural_user_instruction(self):
  import tempfile
  from task_approval import attest
  tid='11111111-1111-4111-8111-111111111111'
  instruction='選択したモジュールだけ修正して。'
  with tempfile.TemporaryDirectory() as d:
   home=Path(d).resolve(); project=home/'project'; project.mkdir()
   root=home/'.codex/sessions/2026/01/01'; root.mkdir(parents=True)
   path=root/('rollout-2026-01-01T00-00-00-'+tid+'.jsonl')
   header={'type':'session_meta','payload':{'id':tid,'cwd':str(project)}}
   path.write_text(json.dumps(header)+'\n'+json.dumps(record('user',instruction))+'\n')
   ep=dict(A,platform='cdx',thread_id=tid,project_path=str(project))
   req={'approval_id':'a','intent':'モジュール','scope':instruction,'evidence_hash':digest(instruction)}
   self.assertTrue(attest(ep,req,home)['host_attested'])
   with self.assertRaises(HubError):attest(dict(ep,project_path=str(home/'other')),req,home)

class MasterTests(unittest.TestCase):
 def test_peer_dispatch_does_not_call_waiting_origin_back(self):
  class Hub:
   local_id='master'
   db=sqlite3.connect(':memory:',isolation_level=None)
   def _auth(self,req):return 'origin'
   def topology(self):return {'mode':'multi','task_master_host_id':'master'}
   def peers(self):return {'origin':{}}
   def remote(self,*args,**kwargs):raise AssertionError('would deadlock on serialized origin')
  result=dispatch(Hub(),{'task_protocol':1,'actor_evidence':evidence(),'request':{'op':'task_list'}},peer=True)
  self.assertEqual(result,{'task_protocol':1,'result':{'tasks':[]}})
 def test_peer_without_task_capability_is_rejected_before_dispatch(self):
  class Hub:
   local_id='master'
   def _auth(self,req):return 'origin'
   def topology(self):return {'mode':'multi','task_master_host_id':'master'}
   def peers(self):return {'origin':{}}
  with self.assertRaises(HubError) as error:dispatch(Hub(),{'actor_evidence':evidence(),'request':{'op':'task_list'}},peer=True)
  self.assertEqual(error.exception.code,'incompatible_peer')

 def test_multi_never_falls_back_to_local_master(self):
  class Hub:
   local_id='origin'
   def _auth(self,req):return 'origin'
   def topology(self):return {'mode':'multi'}
   def peers(self):return {'master':{}}
  with self.assertRaises(HubError) as error:dispatch(Hub(),{'op':'task_list'})
  self.assertEqual(error.exception.code,'task_master_unavailable')
class HostDispatchTests(unittest.TestCase):
 def test_status_and_submit_reach_master_once(self):
  from task_host import dispatch as host_dispatch
  class Host:
   db=sqlite3.connect(':memory:')
   calls=[]
   def hub(self,op,**body):
    self.calls.append((op,body))
    return {'task':{'task_id':'task-one','epoch':0}}
   def submit(self,ep,body):
    self.calls.append(('notification',body))
    return {'message_id':body['submission_id'],'state':'queued'}
  host=Host()
  self.assertEqual(host_dispatch(host,A,{'op':'task_status','task_id':'task-one'})['task']['task_id'],'task-one')
  out=host_dispatch(host,A,{'op':'task_submit','executor':'other.cdx','intent':'repair','scope':'repair messaging','host_attested':True})
  self.assertEqual([c[0] for c in host.calls],['task_status','task_submit','notification'])
  self.assertNotIn('host_attested',host.calls[1][1])
  self.assertEqual(host.calls[1][1]['intent_hash'],digest('repair'))
  self.assertEqual(out['notification']['state'],'queued')

class AssignedLifecycleTests(unittest.TestCase):
 def test_host_to_master_lifecycle_and_offline_fence(self):
  import tempfile, os
  from unittest.mock import patch
  from task_host import dispatch as host_dispatch, binding_marker
  from tasks import TaskAuthority
  owner=dict(A)
  executor=dict(A,endpoint_id='executor',incarnation='e1',runtime_id='native-executor')
  authority=TaskAuthority(':memory:')
  authority.dispatch({'op':'task_approval','approval_id':'approval-one','host_attested':True,'source_endpoint':owner['endpoint_id'],'intent_hash':digest('repair'),'scope_hash':digest('repair scope'),'evidence_hash':'evidence'},owner)
  class Host:
   def __init__(self):
    self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
    self.offline=False
   def hub(self,op,endpoint_id,**body):
    if self.offline: raise HubError('host_unavailable','offline')
    actor=owner if endpoint_id==owner['endpoint_id'] else executor
    if 'executor' in body:body['executor']=executor
    return authority.dispatch(dict(body,op=op),actor)
   def submit(self,ep,body):return {'state':'queued','message_id':body['submission_id']}
  host=Host()
  with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'TPROJ_TASK_BINDING_DIR':d}):
   r=host_dispatch(host,owner,{'op':'task_submit','intent':'repair','scope':'repair scope','approval_id':'approval-one','idempotency_key':'one','executor':'other.cdx'})
   tid=r['task']['task_id']
   host_dispatch(host,executor,{'op':'task_ack','task_id':tid,'expected_epoch':0})
   self.assertTrue(binding_marker('native-executor').exists())
   self.assertTrue(host_dispatch(host,executor,{'op':'task_context'})['can_mutate'])
   host.offline=True
   with self.assertRaises(HubError):host_dispatch(host,executor,{'op':'task_guard_begin','tool_use_id':'u1'})
   host.offline=False
   host_dispatch(host,executor,{'op':'task_progress','task_id':tid,'expected_epoch':0})
   host_dispatch(host,executor,{'op':'task_guard_begin','tool_use_id':'u1'})
   host_dispatch(host,executor,{'op':'task_guard_end','tool_use_id':'u1'})
   host_dispatch(host,executor,{'op':'task_done','task_id':tid,'expected_epoch':0})
   self.assertFalse(host_dispatch(host,executor,{'op':'task_context'})['can_mutate'])
   host_dispatch(host,owner,{'op':'task_verify','task_id':tid,'expected_epoch':0})
   host_dispatch(host,owner,{'op':'task_report','task_id':tid,'expected_epoch':0})
   host_dispatch(host,executor,{'op':'task_detach','task_id':tid})
   self.assertFalse(binding_marker('native-executor').exists())

if __name__=='__main__':unittest.main()

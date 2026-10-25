import unittest,sqlite3,tempfile,json,time,copy,threading,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
from host import Host
from federation import FederatedHub
from protocol import HubError
import submission_queue as queue
from unittest.mock import patch


class AsyncSubmission(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='msg-async-');self.addCleanup(self.tmp.cleanup)
  self.hub=FederatedHub(Path(self.tmp.name)/'hub.db',{'host_id':'local','hosts':{'local':'FAKE'}});self.addCleanup(self.hub.close)
  self.hub.topology=lambda:{'mode':'multi','hosts':[{'id':'local'},{'id':'remote','ssh_alias':'fixture-peer'}]}
  for ident,address,owner,kind in [('kai','kai','local','kai'),('peer','fixture.cdx','remote','cdx')]:
   self.hub.db.execute('INSERT INTO participants VALUES(?,?,?,?,?)',(ident,None,address,owner,kind))
   self.hub.db.execute('INSERT INTO endpoints VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident+'-ep',ident,owner,address,'',0,'0','fixture-'+ident,kind,'inc-'+ident,time.time(),0))
  now=time.time();self.hub.db.execute('INSERT INTO messages(message_id,thread_id,sender_endpoint,target_address,recipient_endpoint,body,kind,created_at,expires_at,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',('original','original','peer-ep','kai','kai-ep','fixture','chat',now,now+3600,'fixture-original'))
  self.host=self.make_host();self.addCleanup(self.host.db.close);self.remote_calls=[]
  def remote(owner,op,**kw):
   self.remote_calls.append(op)
   if op=='resolve':return self.hub.evidence('peer-ep')
   if op=='accept':return {'message_id':kw['payload']['record']['message_id'],'state':'accepted'}
   raise AssertionError('unexpected remote operation')
  self.hub.remote=remote
 def make_host(self):
  h=Host.__new__(Host);h.config={'services':{'kai':{'address':'kai','participant_id':'kai','binding_generation':'GEN','token':'FAKE','allowed_addresses':['fixture.cdx']}}}
  h.db=sqlite3.connect(Path(self.tmp.name)/'host.db',check_same_thread=False);h.db.row_factory=sqlite3.Row
  h.db.execute('CREATE TABLE IF NOT EXISTS submissions(message_id TEXT PRIMARY KEY,endpoint_id TEXT,envelope TEXT)');h.db.commit()
  h.hub=lambda op,**kw:self.hub.dispatch(dict(kw,op=op,host_id='local',host_token='FAKE'))
  return h
 def send(self,mid='new',body='fixture',reply=False,host=None):
  h=host or self.host;ep={'endpoint_id':'kai-ep','service_id':'kai'}
  req={'service_id':'kai','submission_id':mid,'body':body,'defer_remote':True}
  if reply:req['message_id']='original'
  else:req['target']='fixture.cdx'
  return h.submit(ep,req,reply=reply)
 def work(self,**kw):queue.work_once(self.host,**kw)
 def row(self,mid='new'):return self.host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone()

 def test_request_durable_journal_only_never_resolves_or_claims_hub_acceptance(self):
  result=self.send();self.assertEqual(result['state'],'journaled');self.assertEqual(result['hub_acceptance'],'unconfirmed')
  self.assertEqual(self.remote_calls,[]);self.assertEqual(self.row()['state'],'pending')
  separate=sqlite3.connect(Path(self.tmp.name)/'host.db')
  try:self.assertEqual(separate.execute('SELECT count(*) FROM submission_work').fetchone()[0],1)
  finally:separate.close()
  self.assertIsNone(self.hub._row('SELECT 1 FROM messages WHERE message_id="new"'))

 def test_workspace_queue_needs_no_address_grant_and_old_scope_stays_bounded(self):
  self.host.config['services']['kai'].update(messaging_scope='workspace',allowed_addresses=[])
  self.send('mesh');self.assertEqual(json.loads(self.row('mesh')['scope']),None)
  self.work();self.assertEqual(self.row('mesh')['state'],'hub_committed')
  self.host.config['services']['kai'].pop('messaging_scope')
  self.host.config['services']['kai']['allowed_addresses']=['fixture.cdx']
  self.send('bounded')
  self.host.config['services']['kai']['messaging_scope']='workspace'
  self.hub.resolve_destination=lambda target:dict(self.hub.evidence('peer-ep'),renamed_to='other.cdx')
  self.work();self.assertEqual(self.row('bounded')['reason'],'scope_denied')

 def test_reply_request_uses_local_original_and_resolve_runs_only_in_worker(self):
  result=self.send(reply=True);self.assertEqual(result['state'],'journaled');self.assertEqual(self.remote_calls,[])
  self.work();self.assertEqual(self.remote_calls,['resolve']);self.assertEqual(self.row()['state'],'hub_committed')

 def test_commit_response_defers_accept_then_tick_delivers_once(self):
  self.send();self.work();self.assertEqual(self.remote_calls,['resolve'])
  self.assertEqual(self.hub._row('SELECT state FROM federated_outbox WHERE message_id="new"')['state'],'pending')
  self.hub.tick();self.hub.tick();self.assertEqual(self.remote_calls,['resolve','accept'])
  view=queue.local_view(self.host,{'endpoint_id':'kai-ep'},'new')
  self.assertEqual(view['hub_acceptance'],'committed');self.assertEqual(view['remote_state'],'not_checked');self.assertFalse(view['delivery_pending'])

 def test_worker_resolve_wait_does_not_hold_request_or_local_inbox(self):
  self.send(reply=True);entered=threading.Event();release=threading.Event();old=self.hub.remote
  def remote(owner,op,**kw):
   if op=='resolve':entered.set();assert release.wait(3)
   return old(owner,op,**kw)
  self.hub.remote=remote;thread=threading.Thread(target=self.work);thread.start()
  try:
   self.assertTrue(entered.wait(1))
   self.assertEqual(self.row()['state'],'dispatching')
   inbox=self.hub.inbox({'host_id':'local','host_token':'FAKE','endpoint_id':'kai-ep'})
   self.assertEqual(inbox['messages'][0]['message_id'],'original')
  finally:release.set();thread.join(3)
  self.assertFalse(thread.is_alive());self.assertEqual(self.row()['state'],'hub_committed')

 def test_idempotence_and_changed_payload_rejection(self):
  self.send();duplicate=self.send();self.assertTrue(duplicate['duplicate'])
  with self.assertRaises(HubError) as e:self.send(body='different')
  self.assertEqual(e.exception.code,'id_conflict');self.assertEqual(self.host.db.execute('SELECT count(*) FROM submission_work').fetchone()[0],1)
  self.work();self.work();self.assertEqual(self.remote_calls,['resolve'])

 def test_legacy_unknown_ids_are_never_scheduled_or_retried(self):
  for mid in ['legacy-uncertain-a','legacy-uncertain-b']:
   env={'message_id':mid,'sender_endpoint':'kai-ep','body':'fixture','kind':'chat','target':'fixture.cdx'}
   self.host.db.execute('INSERT INTO submissions VALUES(?,?,?)',(mid,'kai-ep',json.dumps(env,sort_keys=True,ensure_ascii=False)));self.host.db.commit()
   with self.assertRaises(HubError) as e:self.send(mid)
   self.assertEqual(e.exception.code,'reconciliation_required')
   diagnostic=queue.legacy_diagnostic(self.host,{'endpoint_id':'kai-ep'},mid)
   self.assertEqual(diagnostic['hub_acceptance'],'unconfirmed');self.assertFalse(diagnostic['scheduler_enabled'])
  self.work();self.assertEqual(self.remote_calls,[]);self.assertEqual(self.host.db.execute('SELECT count(*) FROM submission_work').fetchone()[0],0)

 def test_changed_scope_and_generation_block_before_remote(self):
  self.send('scope');self.host.config['services']['kai']['allowed_addresses']=[];self.work()
  self.assertEqual(self.row('scope')['reason'],'scope_denied');self.assertEqual(self.remote_calls,[])
  self.host.config['services']['kai']['allowed_addresses']=['fixture.cdx'];self.send('generation')
  self.host.config['services']['kai']['binding_generation']='DIFFERENT';self.work()
  self.assertEqual(self.row('generation')['reason'],'stale_session');self.assertEqual(self.remote_calls,[])

 def test_new_scope_does_not_expand_queued_alias_authorization(self):
  self.send();self.host.config['services']['kai']['allowed_addresses'].append('other.cdx')
  self.hub.resolve_destination=lambda target:dict(self.hub.evidence('peer-ep'),renamed_to='other.cdx')
  self.work();self.assertEqual(self.row()['reason'],'scope_denied')
  self.assertIsNone(self.hub._row('SELECT 1 FROM messages WHERE message_id="new"'))

 def test_accepted_then_lost_rpc_reconciles_locally_without_resolve_replay(self):
  self.send();real=self.host.hub;lost=[False]
  def hub(op,**kw):
   result=real(op,**kw)
   if op=='submit' and not lost[0]:lost[0]=True;raise HubError('unavailable','synthetic lost response')
   return result
  self.host.hub=hub;self.work();self.assertEqual(self.row()['state'],'held')
  self.work(now=time.time()+31);self.assertEqual(self.row()['state'],'held')
  queue.reconcile_only(self.host,{'endpoint_id':'kai-ep'},'new')
  self.assertEqual(self.row()['state'],'hub_committed');self.assertEqual(self.remote_calls,['resolve'])

 def test_transient_resolve_failure_does_not_create_hub_message(self):
  self.send()
  def offline(*a,**kw):raise HubError('host_unavailable','synthetic offline')
  self.hub.remote=offline;self.work();self.assertEqual(self.row()['state'],'held')
  self.work(now=time.time()+1000);self.assertEqual(self.row()['attempts'],1)
  self.assertIsNone(self.hub._row('SELECT 1 FROM messages WHERE message_id="new"'))
  diag=queue.local_view(self.host,{'endpoint_id':'kai-ep'},'new',diagnostic=True)
  self.assertEqual(diag['hub_acceptance'],'unconfirmed');self.assertEqual(diag['receipt_stage'],'host_journaled')

 def test_pending_deadline_stops_new_dispatch_without_claiming_nonacceptance(self):
  self.send();self.host.db.execute('UPDATE submission_work SET expires_at=?',(time.time()-1,));self.host.db.commit();self.work()
  self.assertEqual(self.row()['state'],'blocked');self.assertEqual(self.row()['reason'],'pending_deadline_elapsed');self.assertEqual(self.remote_calls,[])
  self.assertEqual(queue.local_view(self.host,{'endpoint_id':'kai-ep'},'new',diagnostic=True)['hub_acceptance'],'unconfirmed')

 def test_restart_retains_work_and_does_not_import_legacy_rows(self):
  self.send();second=self.make_host();self.addCleanup(second.db.close)
  queue.work_once(second);self.assertEqual(self.row()['state'],'hub_committed');self.assertEqual(self.remote_calls,['resolve'])

 def test_local_status_rejects_different_payload_or_actor(self):
  self.send();self.work();envelope=json.loads(self.host.db.execute('SELECT envelope FROM submissions WHERE message_id="new"').fetchone()[0])
  with self.assertRaises(HubError) as e:self.host.hub('submission_status',endpoint_id='kai-ep',message=dict(envelope,body='different'))
  self.assertEqual(e.exception.code,'id_conflict')
  with self.assertRaises(HubError):self.host.hub('submission_status',endpoint_id='kai-ep',message=dict(envelope,sender_endpoint='peer-ep'))

 def test_journal_and_work_insert_are_atomic_on_storage_failure(self):
  queue.init_schema(self.host.db)
  self.host.db.execute("CREATE TRIGGER fail_work BEFORE INSERT ON submission_work BEGIN SELECT RAISE(ABORT,'fixture full disk'); END");self.host.db.commit()
  with self.assertRaises(sqlite3.IntegrityError):self.send()
  self.assertEqual(self.host.db.execute('SELECT count(*) FROM submissions').fetchone()[0],0)
  self.assertEqual(self.host.db.execute('SELECT count(*) FROM submission_work').fetchone()[0],0)
  self.assertEqual(self.remote_calls,[])

 def test_dispatch_pause_preserves_work_without_network_or_replay(self):
  self.send();self.host.config['deferred_submit_dispatch']=False;self.work()
  self.assertEqual(self.row()['state'],'pending');self.assertEqual(self.remote_calls,[])
  self.host.config['deferred_submit_dispatch']=True;self.work()
  self.assertEqual(self.row()['state'],'hub_committed');self.assertEqual(self.remote_calls,['resolve'])

 def test_due_order_allows_new_pending_work_before_older_retry(self):
  self.send('older');self.send('fresh')
  now=time.time()
  self.host.db.execute("UPDATE submission_work SET next_attempt=?,state='pending' WHERE message_id='older'",(now+20,))
  self.host.db.execute("UPDATE submission_work SET next_attempt=? WHERE message_id='fresh'",(now,));self.host.db.commit()
  self.work(now=now+21,limit=1)
  self.assertEqual(self.row('fresh')['state'],'hub_committed');self.assertEqual(self.row('older')['state'],'pending')


 def test_two_workers_select_same_job_only_one_cas_can_dispatch(self):
  self.send();second=self.make_host();self.addCleanup(second.db.close)
  barrier=threading.Barrier(2);real_claim=queue.claim;errors=[]
  def racing_claim(db,mid):
   barrier.wait(timeout=3)
   return real_claim(db,mid)
  def run(host):
   try:queue.work_once(host)
   except BaseException as exc:errors.append(exc)
  with patch.object(queue,'claim',racing_claim):
   threads=[threading.Thread(target=run,args=(h,)) for h in (self.host,second)]
   for thread in threads:thread.start()
   for thread in threads:thread.join(4)
  self.assertEqual(errors,[]);self.assertTrue(all(not t.is_alive() for t in threads))
  self.assertEqual(self.row()['attempts'],1);self.assertEqual(self.remote_calls,['resolve'])
  self.assertEqual(self.hub._row('SELECT count(*) AS n FROM federated_outbox WHERE message_id="new"')['n'],1)

 def test_crash_after_durable_claim_holds_on_startup_without_submit(self):
  self.send()
  class Crash(BaseException):pass
  real=self.host.hub
  self.host.hub=lambda *a,**kw:(_ for _ in ()).throw(Crash())
  with self.assertRaises(Crash):self.work()
  self.assertEqual(self.row()['state'],'dispatching')
  self.host.hub=real;queue.hold_interrupted(self.host.db);self.work(now=time.time()+1000)
  self.assertEqual(self.row()['state'],'held');self.assertEqual(self.remote_calls,[])
  view=queue.reconcile_only(self.host,{'endpoint_id':'kai-ep'},'new')
  self.assertEqual(view['hub_acceptance'],'unconfirmed');self.assertEqual(self.row()['state'],'held')

 def test_delayed_rpc_absent_record_never_releases_hold(self):
  self.send();entered=threading.Event();release=threading.Event();real=self.host.hub;old_remote=self.hub.remote;errors=[];threads=[]
  def remote(owner,op,**kw):
   if op=='resolve':entered.set();assert release.wait(3)
   return old_remote(owner,op,**kw)
  self.hub.remote=remote
  def run(kw):
   try:real('submit',**kw)
   except BaseException as exc:errors.append(exc)
  def lost(op,**kw):
   if op=='submit':
    t=threading.Thread(target=run,args=(kw,));threads.append(t);t.start()
    assert entered.wait(1)
    raise HubError('unavailable','synthetic caller timeout while RPC remains live')
   return real(op,**kw)
  self.host.hub=lost
  try:
   self.work();self.assertEqual(self.row()['state'],'held')
   self.assertIsNone(self.hub._row('SELECT 1 FROM messages WHERE message_id="new"'))
   self.work(now=time.time()+1000)
   queue.reconcile_only(self.host,{'endpoint_id':'kai-ep'},'new')
   self.assertEqual(self.row()['state'],'held');self.assertEqual(len(threads),1)
  finally:
   release.set()
   for t in threads:t.join(3)
  self.assertEqual(errors,[]);self.assertTrue(all(not t.is_alive() for t in threads))
  queue.reconcile_only(self.host,{'endpoint_id':'kai-ep'},'new')
  self.assertEqual(self.row()['state'],'hub_committed');self.assertEqual(self.remote_calls,['resolve'])
  self.hub.tick();self.hub.tick();self.assertEqual(self.remote_calls,['resolve','accept'])

 def test_old_request_shape_cannot_bypass_work_fence(self):
  self.send();req={'service_id':'kai','submission_id':'new','body':'fixture','target':'fixture.cdx'}
  result=self.host.submit({'endpoint_id':'kai-ep','service_id':'kai'},req)
  self.assertTrue(result['duplicate']);self.assertEqual(result['hub_acceptance'],'unconfirmed');self.assertEqual(self.remote_calls,[])
  req['body']='changed'
  with self.assertRaises(HubError) as exc:self.host.submit({'endpoint_id':'kai-ep','service_id':'kai'},req)
  self.assertEqual(exc.exception.code,'id_conflict')

 def test_metadata_failure_before_submit_can_retry_without_ambiguous_effect(self):
  self.send();real=self.host.hub;calls=[]
  def offline(op,**kw):calls.append(op);raise HubError('unavailable','synthetic metadata failure')
  self.host.hub=offline;self.work()
  self.assertEqual(calls,['submission_status']);self.assertEqual(self.row()['state'],'pending');self.assertEqual(self.remote_calls,[])
  self.host.hub=real;self.work(now=time.time()+1000)
  self.assertEqual(self.row()['state'],'hub_committed');self.assertEqual(self.remote_calls,['resolve'])

 def test_legacy_unknown_work_state_is_held_not_scheduled(self):
  self.send();self.host.db.execute("UPDATE submission_work SET state='hub_unknown'");self.host.db.commit()
  queue.hold_interrupted(self.host.db);self.work()
  self.assertEqual(self.row()['state'],'held');self.assertEqual(self.row()['reason'],'worker_interrupted');self.assertEqual(self.remote_calls,[])


 def test_legacy_enqueue_race_rechecks_fence_inside_journal_transaction(self):
  real=queue.duplicate_work_receipt;calls=[0]
  def interleave(host,ep,envelope):
   calls[0]+=1
   if calls[0]==1:
    # Deferred writer commits after legacy pre-check, before legacy DB lock.
    self.send()
    return None
   return real(host,ep,envelope)
  req={'service_id':'kai','submission_id':'new','body':'fixture','target':'fixture.cdx'}
  with patch.object(queue,'duplicate_work_receipt',interleave):
   result=self.host.submit({'endpoint_id':'kai-ep','service_id':'kai'},req)
  self.assertTrue(result['duplicate']);self.assertEqual(self.remote_calls,[])
  self.work();self.assertEqual(self.remote_calls,['resolve'])


 def control(self,action='reconcile',mid='new',ep=None):
  return queue.control(self.host,ep or {'endpoint_id':'kai-ep','service_id':'kai'},
                       {'service_id':'kai','submission_id':mid},action)

 def test_public_cancel_is_durable_idempotent_and_worker_never_sends(self):
  self.send();result=self.control('cancel');self.assertTrue(result['cancelled'])
  self.assertEqual(result['cancellation_scope'],'host_undispatched_work_only')
  self.assertEqual(result['hub_acceptance'],'unconfirmed');self.assertFalse(result['delivery_pending'])
  second=self.make_host();self.addCleanup(second.db.close);queue.hold_interrupted(second.db);queue.work_once(second)
  self.assertTrue(self.control('cancel')['cancelled']);self.assertEqual(self.remote_calls,[])
  self.assertTrue(self.send()['duplicate']);self.assertEqual(self.row()['state'],'cancelled')

 def test_public_reconcile_absence_never_unholds_or_retries(self):
  self.send();self.host.db.execute("UPDATE submission_work SET state='held',attempts=1");self.host.db.commit()
  result=self.control();self.assertFalse(result['reconciled']);self.assertEqual(result['work_state'],'held')
  self.work(now=time.time()+1000);self.assertEqual(self.remote_calls,[])
  self.assertFalse(self.control('cancel')['cancelled']);self.assertEqual(self.row()['state'],'held')

 def test_public_reconcile_lost_commit_and_cancel_committed_are_truthful(self):
  self.send();self.work();self.host.db.execute("UPDATE submission_work SET state='held',hub_receipt=NULL");self.host.db.commit()
  result=self.control();self.assertTrue(result['reconciled']);self.assertEqual(result['hub_acceptance'],'committed')
  result=self.control('cancel');self.assertFalse(result['cancelled']);self.assertEqual(result['control_reason'],'already_committed')
  self.assertEqual(self.remote_calls,['resolve'])

 def test_public_controls_deny_other_endpoint_before_any_hub_query(self):
  self.send();real=self.host.hub;calls=[]
  self.host.hub=lambda *a,**kw:calls.append(a)
  for mid,ep in [('new',{'endpoint_id':'peer-ep','service_id':'kai'}),('unknown',{'endpoint_id':'kai-ep','service_id':'kai'})]:
   for action in ('cancel','reconcile'):
    with self.assertRaises(HubError) as exc:self.control(action,mid,ep)
    self.assertEqual(exc.exception.code,'not_found')
  self.assertEqual(calls,[]);self.host.hub=real

 def test_public_controls_require_current_binding_and_original_scope(self):
  self.send();cfg=self.host.config['services']['kai'];original=copy.deepcopy(cfg)
  for field,value in [('binding_generation','OTHER'),('participant_id','OTHER'),('token','OTHER'),('address','OTHER'),('read_only',True)]:
   cfg.update(original);cfg[field]=value
   for action in ('cancel','reconcile'):
    with self.assertRaises(HubError) as exc:self.control(action)
    self.assertEqual(exc.exception.code,'stale_session')
  cfg.clear();cfg.update(original);cfg['allowed_addresses']=[]
  for action in ('cancel','reconcile'):
   with self.assertRaises(HubError) as exc:self.control(action)
   self.assertEqual(exc.exception.code,'scope_denied')
  cfg['allowed_addresses']=['fixture.cdx','other.cdx']
  self.host.db.execute("UPDATE submission_work SET scope='[]'");self.host.db.commit()
  with self.assertRaises(HubError) as exc:self.control('cancel')
  self.assertEqual(exc.exception.code,'scope_denied');self.assertEqual(self.row()['state'],'pending')

 def test_public_reply_control_rechecks_exact_original_party(self):
  self.send(reply=True);self.hub.db.execute("UPDATE messages SET recipient_endpoint='peer-ep' WHERE message_id='original'");self.hub.db.commit()
  for action in ('cancel','reconcile'):
   with self.assertRaises(HubError):self.control(action)
  self.assertEqual(self.row()['state'],'pending');self.assertEqual(self.remote_calls,[])

 def test_public_cancel_loses_to_durable_dispatch_claim(self):
  self.send();self.assertTrue(queue.claim(self.host.db,'new'))
  result=self.control('cancel');self.assertFalse(result['cancelled'])
  self.assertEqual(self.row()['state'],'dispatching');self.assertEqual(self.remote_calls,[])

 def test_public_cancel_wins_race_after_worker_select_before_worker_claim(self):
  self.send();real=queue.claim
  def interleave(db,mid):
   self.assertTrue(self.control('cancel')['cancelled'])
   return real(db,mid)
  with patch.object(queue,'claim',interleave):self.work()
  self.assertEqual(self.row()['state'],'cancelled');self.assertEqual(self.remote_calls,[])

 def test_public_cancel_does_not_claim_attempted_pending_as_untouched(self):
  self.send();self.host.db.execute('UPDATE submission_work SET attempts=1');self.host.db.commit()
  self.assertFalse(self.control('cancel')['cancelled']);self.assertEqual(self.row()['state'],'pending')

 def test_public_reconcile_rejects_payload_conflict_not_promotes_acceptance(self):
  self.send();self.work()
  old=json.loads(self.host.db.execute("SELECT envelope FROM submissions WHERE message_id='new'").fetchone()[0]);old['body']='tampered'
  self.host.db.execute("UPDATE submissions SET envelope=? WHERE message_id='new'",(json.dumps(old),));self.host.db.execute("UPDATE submission_work SET state='held'");self.host.db.commit()
  with self.assertRaises(HubError) as exc:self.control()
  self.assertEqual(exc.exception.code,'id_conflict');self.assertEqual(self.row()['state'],'held')


 def test_public_cancel_commit_then_lost_response_does_not_resume_work(self):
  self.send();real=queue.receipt
  class Crash(BaseException):pass
  with patch.object(queue,'receipt',side_effect=Crash()):
   with self.assertRaises(Crash):self.control('cancel')
  self.assertEqual(self.row()['state'],'cancelled')
  second=self.make_host();self.addCleanup(second.db.close);queue.hold_interrupted(second.db);queue.work_once(second)
  self.assertTrue(self.control('cancel')['cancelled']);self.assertEqual(self.remote_calls,[])

 def test_public_reconcile_after_crash_after_hub_commit_only_records_proof(self):
  self.send();real=self.host.hub
  class Crash(BaseException):pass
  def crash(op,**kw):
   result=real(op,**kw)
   if op=='submit':raise Crash()
   return result
  self.host.hub=crash
  with self.assertRaises(Crash):self.work()
  self.host.hub=real;queue.hold_interrupted(self.host.db)
  self.assertEqual(self.row()['state'],'held')
  result=self.control();self.assertTrue(result['reconciled']);self.assertEqual(result['hub_acceptance'],'committed')
  self.assertEqual(self.remote_calls,['resolve']);self.work();self.assertEqual(self.remote_calls,['resolve'])

if __name__=='__main__':unittest.main(verbosity=2)

"""Explicit new-submission journal. Never imports/replays legacy submissions.

Host journal persistence is NOT Hub acceptance. Only a matching local Hub
message record proves that second boundary; no recipient acceptance is inferred.
"""
import hashlib,json,time,sqlite3
from protocol import HubError,MAX_TTL

SCHEMA='''CREATE TABLE IF NOT EXISTS submission_work (
 message_id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL, service_id TEXT NOT NULL,
 binding_hash TEXT NOT NULL, scope TEXT NOT NULL, target_address TEXT NOT NULL,
 state TEXT NOT NULL, reason TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL,
 next_attempt REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, hub_receipt TEXT);'''

def init_schema(db):db.executescript(SCHEMA)
def exists(db):return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='submission_work'").fetchone() is not None
def binding_hash(service_id,cfg):
 values={k:cfg.get(k) for k in ('participant_id','address','binding_generation','token')}
 values['service_id']=service_id
 return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def receipt(row,envelope):
 committed=row['state']=='hub_committed'
 result=json.loads(row['hub_receipt']) if committed else {'message_id':row['message_id'],'state':'journaled'}
 result.update(thread_id=envelope.get('thread_id') or row['message_id'],
  receipt_stage='hub_message_committed' if committed else 'host_journaled',
  hub_acceptance='committed' if committed else 'unconfirmed',work_state=row['state'],
  delivery_pending=(row['state']!='cancelled') and (not committed or bool(result.get('delivery_pending'))))
 if row['reason']:result['work_reason']=row['reason']
 return result

def duplicate_work_receipt(host,ep,envelope):
 """A call without the new flag must not bypass an existing work fence."""
 if not exists(host.db):return None
 row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(envelope['message_id'],)).fetchone()
 if not row:return None
 old=host.db.execute('SELECT * FROM submissions WHERE message_id=?',(envelope['message_id'],)).fetchone()
 if (row['endpoint_id']!=ep['endpoint_id'] or not old or old['envelope']!=json.dumps(envelope,sort_keys=True,ensure_ascii=False)):
  raise HubError('id_conflict','submission work belongs to different sender or payload')
 return dict(receipt(row,envelope),duplicate=True)

def hold_interrupted(db):
 """Startup recovery only: an old worker may have left a live Hub RPC."""
 if exists(db):
  db.execute("UPDATE submission_work SET state='held',reason='worker_interrupted' WHERE state IN ('dispatching','hub_unknown')")
  db.commit()

def claim(db,mid):
 """Durable one-winner fence, written before any possible submission RPC."""
 changed=db.execute("UPDATE submission_work SET state='dispatching',attempts=attempts+1 WHERE message_id=? AND state='pending'",(mid,)).rowcount
 db.commit()
 return changed==1

def reconcile_only(host,ep,mid):
 """Exact sender-bound observation. Never submits, resumes or releases a hold."""
 view=local_view(host,ep,mid,diagnostic=True)
 if view is None:raise HubError('not_found','submission work not found')
 if view.get('hub_acceptance')=='committed':
  stored=host.db.execute('SELECT envelope FROM submissions WHERE message_id=?',(mid,)).fetchone()
  status=host.hub('submission_status',endpoint_id=ep['endpoint_id'],message=json.loads(stored['envelope']))
  if not status.get('found'):raise HubError('unavailable','positive acceptance proof no longer available')
  host.db.execute("UPDATE submission_work SET state='hub_committed',reason=NULL,hub_receipt=? WHERE message_id=? AND endpoint_id=?",(json.dumps(status['receipt']),mid,ep['endpoint_id']));host.db.commit()
 return view

def enqueue(host,ep,request,envelope,*,target_address,now=None):
 now=time.time() if now is None else now
 ident,cfg=host._service_binding(request)
 if ep.get('service_id')!=ident or cfg.get('read_only',False):raise HubError('scope_denied','deferred submission requires current writable service')
 scope=host.service_policy(request)
 if scope is None:raise HubError('configuration_error','explicit service scope required')
 body=envelope.get('body')
 if not isinstance(body,str) or any(ord(c)<32 and c not in '\n\t' for c in body) or '\x7f' in body:raise HubError('invalid_message','invalid deferred body')
 serialized=json.dumps(envelope,sort_keys=True,ensure_ascii=False)
 if host.db.in_transaction:raise HubError('unavailable','deferred submission requires isolated journal transaction')
 init_schema(host.db);host.db.execute('BEGIN IMMEDIATE')
 try:
  old=host.db.execute('SELECT * FROM submissions WHERE message_id=?',(envelope['message_id'],)).fetchone()
  work=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(envelope['message_id'],)).fetchone()
  if old and (old['endpoint_id']!=ep['endpoint_id'] or old['envelope']!=serialized):raise HubError('id_conflict','submission ID has different sender or payload')
  if old and not work:raise HubError('reconciliation_required','legacy journal outcome remains unknown; no automatic retry')
  if not old:
   host.db.execute('INSERT INTO submissions VALUES(?,?,?)',(envelope['message_id'],ep['endpoint_id'],serialized))
   host.db.execute('INSERT INTO submission_work(message_id,endpoint_id,service_id,binding_hash,scope,target_address,state,created_at,expires_at,next_attempt) VALUES(?,?,?,?,?,?,?,?,?,?)',
    (envelope['message_id'],ep['endpoint_id'],ident,binding_hash(ident,cfg),json.dumps(scope),target_address,'pending',now,now+MAX_TTL,now))
  host.db.commit()
 except Exception:
  host.db.rollback();raise
 row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(envelope['message_id'],)).fetchone()
 result=receipt(row,envelope)
 if old:result['duplicate']=True
 return result

def local_view(host,ep,mid,*,diagnostic=False):
 if not exists(host.db):return None
 row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone()
 if not row or row['endpoint_id']!=ep['endpoint_id']:return None
 envelope=json.loads(host.db.execute('SELECT envelope FROM submissions WHERE message_id=?',(mid,)).fetchone()['envelope'])
 result=receipt(row,envelope)
 status=host.hub('submission_status',endpoint_id=ep['endpoint_id'],message=envelope)
 if status.get('found'):
  result=dict(status['receipt'],receipt_stage='hub_message_committed',hub_acceptance='committed',work_state='hub_committed')
 if diagnostic:return result
 if status.get('found'):
  view=host.hub('query_local',endpoint_id=ep['endpoint_id'],message_id=mid)
  return dict(view,**{k:v for k,v in result.items() if k not in ('state','thread_id','message_id')})
 return dict(result,target_address=row['target_address'],body=envelope['body'])

def legacy_diagnostic(host,ep,mid):
 """Expose only sender-owned legacy persistence; never schedule its work."""
 old=host.db.execute('SELECT * FROM submissions WHERE message_id=?',(mid,)).fetchone()
 if not old or old['endpoint_id']!=ep['endpoint_id']:return None
 envelope=json.loads(old['envelope'])
 status=host.hub('submission_status',endpoint_id=ep['endpoint_id'],message=envelope)
 if status.get('found'):
  return dict(status['receipt'],receipt_stage='hub_message_committed',hub_acceptance='committed',work_state='legacy_unmanaged',scheduler_enabled=False)
 return {'message_id':mid,'state':'journaled','receipt_stage':'host_journaled',
  'hub_acceptance':'unconfirmed','work_state':'legacy_unmanaged',
  'work_reason':'explicit_reconciliation_only','scheduler_enabled':False}

TRANSIENT={'host_unavailable','unavailable','endpoint_unavailable','resource_exhausted'}
def work_once(host,*,now=None,limit=4):
 """Run on its own thread, with freshly loaded config. No legacy-row scan."""
 now=time.time() if now is None else now
 if host.config.get('deferred_submit_dispatch',True) is False:return
 if not exists(host.db):return
 rows=host.db.execute("SELECT * FROM submission_work WHERE state='pending' AND next_attempt<=? ORDER BY next_attempt,created_at LIMIT ?",(now,limit)).fetchall()
 for row in rows:
  mid=row['message_id'];envelope=json.loads(host.db.execute('SELECT envelope FROM submissions WHERE message_id=?',(mid,)).fetchone()['envelope'])
  if not claim(host.db,mid):continue
  submitted=False
  try:
   # Query existing acceptance locally before any repeat of a submit operation.
   status=host.hub('submission_status',endpoint_id=row['endpoint_id'],message=envelope)
   if status.get('found'):
    host.db.execute("UPDATE submission_work SET state='hub_committed',reason=NULL,hub_receipt=? WHERE message_id=? AND state='dispatching'",(json.dumps(status['receipt']),mid));host.db.commit();continue
   if now>=row['expires_at']:
    host.db.execute("UPDATE submission_work SET state='blocked',reason='pending_deadline_elapsed' WHERE message_id=? AND state='dispatching'",(mid,));host.db.commit();continue
   cfg=(host.config.get('services') or {}).get(row['service_id'])
   if (not cfg or cfg.get('read_only',False) or binding_hash(row['service_id'],cfg)!=row['binding_hash']):raise HubError('stale_session','current enrollment no longer matches queued submission')
   current=host.service_policy({'service_id':row['service_id']})
   permitted=sorted(set(json.loads(row['scope'])) & set(current or []))
   if not envelope.get('in_reply_to') and row['target_address'] not in permitted:raise HubError('scope_denied','queued target no longer authorized')
   submitted=True
   result=host.hub('submit',message=envelope,authorized_targets=permitted,
                   defer_flush=True,pending_deadline=row['expires_at'])
   # An RPC result alone is not substituted for a matching durable message.
   status=host.hub('submission_status',endpoint_id=row['endpoint_id'],message=envelope)
   if not status.get('found'):raise HubError('unavailable','Hub acceptance remains unconfirmed')
   host.db.execute("UPDATE submission_work SET state='hub_committed',reason=NULL,hub_receipt=? WHERE message_id=? AND state='dispatching'",(json.dumps(status['receipt']),mid));host.db.commit()
  except (HubError,OSError,sqlite3.Error) as exc:
   code=exc.code if isinstance(exc,HubError) else 'unavailable'
   transient=code in TRANSIENT
   # No body, address, credential or exception text is recorded as a reason.
   safe=code if code in TRANSIENT|{'stale_session','scope_denied','identity_rejected','id_conflict','invalid_message','expired','no_recipient','unknown_target','ambiguous_target','policy_blocked'} else 'unavailable'
   host.db.execute("UPDATE submission_work SET state=?,reason=?,next_attempt=? WHERE message_id=? AND state='dispatching'",
    ('held' if submitted else ('pending' if transient else 'blocked'),safe,max(now,time.time())+min(300,30*(2**min(row['attempts'],3))),mid));host.db.commit()


def control(host,ep,req,action):
 """Authenticated exact-ID control; never submits or releases dispatch fences."""
 mid=req.get('submission_id')
 if not isinstance(mid,str) or not mid or len(mid)>128:
  raise HubError('invalid_message','submission ID required')
 if action not in ('reconcile','cancel'):raise HubError('invalid_request','unknown submission control')
 row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone() if exists(host.db) else None
 # Deny before any Hub query or revealing whether another sender owns this ID.
 if not row or row['endpoint_id']!=ep.get('endpoint_id'):
  raise HubError('not_found','owned submission work not found')
 ident,cfg=host._service_binding(req)
 if (ident!=row['service_id'] or ep.get('service_id')!=ident or cfg.get('read_only',False)
     or binding_hash(ident,cfg)!=row['binding_hash']):
  raise HubError('stale_session','current writable binding no longer matches queued submission')
 scope=host.service_policy(req)
 if scope is None or row['target_address'] not in set(scope)&set(json.loads(row['scope'])):
  raise HubError('scope_denied','queued target is outside current and original scope')
 stored=host.db.execute('SELECT * FROM submissions WHERE message_id=?',(mid,)).fetchone()
 if not stored or stored['endpoint_id']!=ep['endpoint_id']:
  raise HubError('identity_rejected','submission owner mismatch')
 envelope=json.loads(stored['envelope'])
 if envelope.get('sender_endpoint')!=ep['endpoint_id'] or envelope.get('message_id')!=mid:
  raise HubError('identity_rejected','submission party mismatch')
 if envelope.get('in_reply_to'):
  original=host.hub('query_local',endpoint_id=ep['endpoint_id'],message_id=envelope['in_reply_to'])
  if (not original.get('reader_is_recipient',original.get('recipient_endpoint')==ep['endpoint_id'])
      or original.get('sender_address')!=row['target_address']):
   raise HubError('identity_rejected','original reply party mismatch')
 elif envelope.get('target')!=row['target_address']:
  raise HubError('identity_rejected','submission target mismatch')
 status=host.hub('submission_status',endpoint_id=ep['endpoint_id'],message=envelope)
 if status.get('found'):
  host.db.execute("UPDATE submission_work SET state='hub_committed',reason=NULL,hub_receipt=? WHERE message_id=? AND endpoint_id=?",
                  (json.dumps(status['receipt']),mid,ep['endpoint_id']));host.db.commit()
  row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone()
  return dict(receipt(row,envelope),operation=action,reconciled=True,
              **({'cancelled':False,'control_reason':'already_committed'} if action=='cancel' else {}))
 if action=='reconcile':
  # Absence is never evidence of failed acceptance, nor permission to retry.
  row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone()
  return dict(receipt(row,envelope),operation=action,reconciled=False,control_reason='no_positive_commit_proof')
 # The same durable CAS competes with worker.claim. attempts==0 deliberately
 # excludes even known pre-submit metadata retries: only untouched work cancels.
 changed=host.db.execute("UPDATE submission_work SET state='cancelled',reason='cancelled_before_dispatch' WHERE message_id=? AND endpoint_id=? AND state='pending' AND attempts=0",
                         (mid,ep['endpoint_id'])).rowcount
 host.db.commit()
 row=host.db.execute('SELECT * FROM submission_work WHERE message_id=?',(mid,)).fetchone()
 cancelled=changed==1 or (row['state']=='cancelled' and row['attempts']==0)
 result=receipt(row,envelope)
 if cancelled:result['delivery_pending']=False
 return dict(result,operation=action,cancelled=cancelled,cancellation_scope='host_undispatched_work_only',
             control_reason='cancelled_before_dispatch' if cancelled else 'dispatch_started_or_work_not_pending')

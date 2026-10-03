"""Authenticated local formal-task bindings and mutation admission."""
import json
import time
import uuid
from pathlib import Path
import os
from protocol import HubError
from task_approval import attest, digest


def binding_marker(native_id):
    # Presence is only a restrictive fence, never a copy of task authority.
    root = Path(os.environ.get('TPROJ_TASK_BINDING_DIR', str(Path.home()/'.local/state/tproj/task-bindings')))
    return root / digest(native_id)


def dispatch(host, ep, req):
    host.db.execute('CREATE TABLE IF NOT EXISTS formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT NOT NULL, task_id TEXT NOT NULL, epoch INTEGER NOT NULL, native_id TEXT NOT NULL)')
    op=req['op']
    if op in ('task_begin_operation','task_end_operation'):
        raise HubError('unsupported','operation admission uses the formal tool hook')
    if op == 'task_approval':
        body=attest(ep,req)
        result=host.hub(op,endpoint_id=ep['endpoint_id'],**body)
        return result
    body={k:v for k,v in req.items() if k not in ('op','endpoint_id','conversation','as','session','host_attested','source_endpoint','actor','actor_evidence','host_id','host_token')}
    if op == 'task_submit':
        if not isinstance(body.get('intent'),str) or not isinstance(body.get('scope'),str):
            raise HubError('invalid_request','intent and approved scope text required')
        body['intent_hash']=digest(body.pop('intent'));body['scope_hash']=digest(body.pop('scope'))
    bound=host.db.execute('SELECT * FROM formal_task_binding WHERE endpoint_id=?',(ep['endpoint_id'],)).fetchone()
    if op == 'task_context':
        if not bound:return {'assigned':False}
        snapshot=host.hub('task_status',endpoint_id=ep['endpoint_id'],task_id=bound['task_id'])
        task=snapshot['task']; handoff=snapshot.get('handoff') or {}
        active=(bound['incarnation']==ep['incarnation'] and task['executor_endpoint']==ep['endpoint_id']
                and task['executor_incarnation']==ep['incarnation'] and task['epoch']==bound['epoch']
                and task['status'] in ('accepted','in_progress')
                and handoff.get('state') not in ('prepared','released','accepted'))
        return {'assigned':True,'task_id':task['task_id'],'task_epoch':task['epoch'],
                'task_status':task['status'],'can_mutate':active}
    if op in ('task_guard_begin','task_guard_end'):
        if not bound:return {'assigned':False}
        if bound['incarnation']!=ep['incarnation']:raise HubError('stale_executor','formal task conversation changed')
        ident=req.get('tool_use_id')
        if not isinstance(ident,str) or not ident:raise HubError('invalid_request','tool-use identity required for guarded operation')
        actual='task_begin_operation' if op.endswith('begin') else 'task_end_operation'
        result=host.hub(actual,endpoint_id=ep['endpoint_id'],task_id=bound['task_id'],expected_epoch=bound['epoch'],tool_use_id=ident)
        return dict(result,assigned=True)
    if op == 'task_detach':
        if not bound:return {'detached':True}
        result=host.hub('task_status',endpoint_id=ep['endpoint_id'],task_id=bound['task_id'])
        task=result['task']
        if result.get('open_operations'):
            raise HubError('operations_open','operation completion is still unconfirmed')
        if task['status'] not in ('reported','cancelled'):
            raise HubError('task_active','finish/report or cancel task before detaching')
        host.db.execute('DELETE FROM formal_task_binding WHERE endpoint_id=?',(ep['endpoint_id'],));host.db.commit()
        binding_marker(bound['native_id']).unlink(missing_ok=True)
        return {'detached':True}
    if op in ('task_ack','task_accept_handoff'):
        # Durable restrictive marker precedes remote effect and survives uncertainty.
        tid=body.get('task_id'); epoch=body.get('expected_epoch')
        if not isinstance(tid,str) or not isinstance(epoch,int):raise HubError('invalid_request','task ID and epoch required')
        if bound and bound['task_id']!=tid:raise HubError('task_active','detach the existing formal assignment first')
        snapshot=host.hub('task_status',endpoint_id=ep['endpoint_id'],task_id=tid)
        task=snapshot['task']
        if task['epoch'] != epoch:raise HubError('epoch_conflict','task epoch changed')
        if op=='task_ack' and (task['executor_endpoint'] != ep['endpoint_id'] or task['executor_incarnation'] != ep['incarnation']):
            raise HubError('stale_executor','task is not assigned to this conversation')
        if op=='task_accept_handoff':
            target=snapshot.get('handoff') or {}
            if target.get('target_endpoint') != ep['endpoint_id'] or target.get('target_incarnation') != ep['incarnation']:
                raise HubError('stale_executor','handoff is not assigned to this conversation')
            epoch+=1
        native_id = str(ep.get('thread_id') or ep.get('session_id') or ep.get('runtime_id') or '')
        if not native_id: raise HubError('identity_rejected','native conversation ID required for task binding')
        marker = binding_marker(native_id)
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with marker.open('ab') as handle:
            handle.flush()
            os.fsync(handle.fileno())
        host.db.execute('INSERT INTO formal_task_binding VALUES(?,?,?,?,?) ON CONFLICT(endpoint_id) DO UPDATE SET epoch=excluded.epoch', (ep['endpoint_id'],ep['incarnation'],tid,epoch,str(ep.get('thread_id') or ep.get('session_id') or ep.get('runtime_id') or '')));host.db.commit()
    result=host.hub(op,endpoint_id=ep['endpoint_id'],**body)
    if op == 'task_submit':
        task=result['task']
        mid=str(uuid.uuid5(uuid.NAMESPACE_URL, 'tproj-task:'+task['task_id']))
        # Message is a notification, not authority. Recipient must read the
        # master and explicitly accept through its native authenticated host.
        text='Formal task '+task['task_id']+' is assigned. Read it with tproj-task status '+task['task_id']+'. Accept with tproj-task ack '+task['task_id']+' --epoch '+str(task['epoch'])+'. Normal MSG does not change Role or grant authority.'
        try: result['notification']=host.submit(ep,{'submission_id':mid,'target':req['executor'],'body':text})
        except HubError as exc: result['notification']={'state':'pending','error':exc.code,'message_id':mid}
    return result

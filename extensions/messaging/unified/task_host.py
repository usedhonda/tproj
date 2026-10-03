"""Authenticated local formal-task bindings and mutation admission."""
import json
import time
import uuid
from pathlib import Path
import os
import re
from protocol import HubError
from task_approval import attest, digest

def _file_change_witness(ep, tool_use_id, created_at, home=None):
    """Verify one exact completed Codex FileChange in the bound transcript."""
    tid = str(ep.get('thread_id') or ep.get('session_id') or '')
    project = ep.get('project_path')
    if ep.get('platform') != 'cdx' or not tid or not project or not isinstance(tool_use_id, str): return False
    root = Path(home or Path.home()) / '.codex/sessions'
    paths = list(root.glob('[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*-' + tid + '.jsonl'))
    paths = [p for p in paths if p.is_file() and not any(x.is_symlink() for x in (p, *p.parents))]
    if len(paths) != 1: return False
    try:
        with paths[0].open(encoding='utf-8') as stream:
            header = json.loads(next(stream)); meta = header.get('payload') or {}
            if (header.get('type') != 'session_meta' or meta.get('id') != tid
                    or Path(str(meta.get('cwd', ''))).resolve() != Path(str(project)).resolve()): return False
            matches = []
            for line in stream:
                if not line.strip(): continue
                payload = (json.loads(line).get('payload') or {})
                item = payload.get('item') if payload.get('type') == 'item_completed' else None
                if (payload.get('thread_id') != tid or not isinstance(item, dict)
                        or item.get('type') != 'FileChange' or item.get('id') != tool_use_id
                        or item.get('status') != 'completed'): continue
                started = item.get('started_at_ms'); completed = item.get('completed_at_ms')
                if type(started) is int and type(completed) is int and completed >= started >= int(float(created_at) * 1000): matches.append(item)
            return len(matches) == 1
    except (OSError, ValueError, TypeError): return False


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
    if op == 'task_reconcile_operation':
        if not bound or bound['incarnation'] != ep['incarnation'] or body.get('task_id') != bound['task_id']:
            raise HubError('stale_executor', 'task binding does not match this conversation')
        epoch = body.get('expected_epoch'); ident = body.get('tool_use_id')
        if not isinstance(epoch, int) or epoch != bound['epoch'] or not isinstance(ident, str) or not ident:
            raise HubError('epoch_conflict', 'task epoch or operation identity is stale')
        snapshot = host.hub('task_status', endpoint_id=ep['endpoint_id'], task_id=bound['task_id'])
        details = [item for item in snapshot.get('actor_open_operation_details', []) if item.get('tool_use_id') == ident]
        if len(details) != 1 or not _file_change_witness(ep, ident, details[0].get('created_at')):
            raise HubError('witness_unavailable', 'native FileChange completion witness is unavailable')
        result = host.hub('task_end_operation', endpoint_id=ep['endpoint_id'], task_id=bound['task_id'], expected_epoch=epoch, tool_use_id=ident)
        return dict(result, assigned=True, reconciled=True)
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
        if req.get('expected_epoch') != bound['epoch']:
            raise HubError('epoch_conflict','detach must name the bound assignment epoch')
        if req.get('task_id') != bound['task_id']:
            raise HubError('task_mismatch','detach must name the bound task')
        result=host.hub('task_status',endpoint_id=ep['endpoint_id'],task_id=bound['task_id'])
        task=result['task']
        pending=result.get('handoff') or {}
        pending_target=(pending.get('state') in ('prepared','released','accepted') and
                        pending.get('target_endpoint')==ep['endpoint_id'])
        transferred=(not pending_target and task['epoch'] >= bound['epoch'] and
                     (task['executor_endpoint'],task['executor_incarnation'],task['executor_host_id']) !=
                     (ep['endpoint_id'],ep['incarnation'],ep['host_id']))
        if result.get('actor_open_operations',result.get('open_operations')):
            raise HubError('operations_open','operation completion is still unconfirmed')
        if not transferred and task['status'] not in ('reported','cancelled'):
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
        # Reject a deterministically obsolete ACK before installing the local
        # restrictive fence. The durable pre-effect marker is still required for
        # an eligible ACK whose remote outcome can become uncertain.
        if op=='task_ack' and task['status'] not in ('submitted','accepted'):
            raise HubError('stale_task','task no longer awaits acceptance')
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
        text=('Formal task notification: '+task['task_id']+'. Read current status with '
              'tproj-task status '+task['task_id']+'. Only if status is submitted and the '
              'executor matches this conversation, accept with tproj-task ack '+task['task_id']+
              ' --epoch N, where N is the current status epoch. Already accepted, completed, '
              'cancelled, frozen, or transferred tasks need no new ACK from this delayed notice. '
              'Normal MSG does not change Role or grant authority.')
        try: result['notification']=host.submit(ep,{'submission_id':mid,'target':req['executor'],'body':text})
        except HubError as exc: result['notification']={'state':'pending','error':exc.code,'message_id':mid}
    return result

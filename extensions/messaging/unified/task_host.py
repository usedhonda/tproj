"""Authenticated local formal-task bindings and mutation admission."""
import json
import time
import uuid
from pathlib import Path
import os
import re
import math
from datetime import datetime, timezone
from protocol import HubError
from task_approval import attest, digest

def _file_change_witness(ep, tool_use_id, created_at, home=None):
    """Verify one exact completed Codex FileChange in the bound transcript."""
    tid = str(ep.get('thread_id') or ep.get('session_id') or '')
    project = ep.get('project_path')
    if (ep.get('platform') != 'cdx' or not re.fullmatch(r'[0-9a-fA-F-]{36}', tid)
            or not project or not isinstance(tool_use_id, str)): return False
    root = Path(home or Path.home()) / '.codex/sessions'
    paths = list(root.glob('[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*-' + tid + '.jsonl'))
    paths = [p for p in paths if p.is_file() and not any(x.is_symlink() for x in (p, *p.parents))]
    if len(paths) != 1: return False
    try:
        with paths[0].open(encoding='utf-8') as stream:
            header = json.loads(next(stream)); meta = header.get('payload') or {}
            if (header.get('type') != 'session_meta' or meta.get('id') != tid
                    or not meta.get('cwd') or Path(str(meta['cwd'])).resolve() != Path(str(project)).resolve()): return False
            matches = []
            for line in stream:
                if not line.strip(): continue
                row = json.loads(line)
                payload = (row.get('payload') or {})
                item = payload.get('item') if row.get('type') == 'event_msg' and payload.get('type') == 'item_completed' else None
                if (payload.get('thread_id') != tid or not isinstance(item, dict)
                        or item.get('type') != 'FileChange' or item.get('id') != tool_use_id
                        or item.get('status') != 'completed'): continue
                started = payload.get('started_at_ms'); completed = payload.get('completed_at_ms')
                if type(started) is int and type(completed) is int and completed >= started >= int(float(created_at) * 1000): matches.append(item)
            return len(matches) == 1
    except (OSError, ValueError, TypeError, AttributeError, StopIteration, OverflowError): return False


def _command_execution_observation(ep, tool_use_id, created_at, home=None):
    """Return whether target command/file items were seen and its strict outcome."""
    tid = str(ep.get('thread_id') or ep.get('session_id') or '')
    project = ep.get('project_path')
    if (ep.get('platform') != 'cdx' or not re.fullmatch(r'[0-9a-fA-F-]{36}', tid)
            or not project or not isinstance(tool_use_id, str) or not tool_use_id):
        return False, False, None
    try:
        created_ms = int(float(created_at) * 1000)
        if not math.isfinite(float(created_at)):
            return True, False, None
    except (TypeError, ValueError, OverflowError):
        return True, False, None
    root = Path(home or Path.home()) / '.codex/sessions'
    paths = list(root.glob('[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*-' + tid + '.jsonl'))
    paths = [p for p in paths if p.is_file() and not any(x.is_symlink() for x in (p, *p.parents))]
    if len(paths) != 1:
        return True, False, None
    matches = []
    saw_command = False
    saw_file_change = False
    try:
        with paths[0].open(encoding='utf-8') as stream:
            header = json.loads(next(stream))
            meta = header.get('payload') or {}
            if (header.get('type') != 'session_meta' or meta.get('id') != tid
                    or not meta.get('cwd') or Path(str(meta['cwd'])).resolve() != Path(str(project)).resolve()):
                return True, False, None
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                payload = row.get('payload') or {}
                if row.get('type') != 'event_msg' or payload.get('type') != 'item_completed':
                    continue
                item = payload.get('item')
                if not isinstance(item, dict) or item.get('id') != tool_use_id:
                    continue
                if item.get('type') == 'FileChange':
                    saw_file_change = True
                    continue
                if item.get('type') == 'CommandExecution':
                    saw_command = True
                else:
                    continue
                if payload.get('thread_id') != tid:
                    return saw_command, saw_file_change, None
                if (item.get('type') != 'CommandExecution' or item.get('status') != 'completed'
                        or type(item.get('exit_code')) is not int):
                    return saw_command, saw_file_change, None
                started = payload.get('started_at_ms'); completed = payload.get('completed_at_ms')
                if (type(started) is not int or type(completed) is not int
                        or completed < started or started < created_ms):
                    return saw_command, saw_file_change, None
                matches.append(item)
        if saw_command and saw_file_change:
            return saw_command, saw_file_change, None
        if len(matches) != 1:
            return saw_command, saw_file_change, None
        return saw_command, saw_file_change, ('success' if matches[0]['exit_code'] == 0 else 'error')
    except (OSError, ValueError, TypeError, AttributeError, StopIteration, OverflowError):
        return saw_command, saw_file_change, None


def _command_execution_outcome(ep, tool_use_id, created_at, home=None):
    """Return success/error for one exact completed Codex CommandExecution."""
    return _command_execution_observation(ep, tool_use_id, created_at, home)[2]


_CC_LOCAL_TOOLS = frozenset(('Bash', 'Edit', 'Write'))


def _cc_timestamp(value):
    """Return a finite epoch timestamp for a native CC row timestamp."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        number = parsed.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return number if math.isfinite(number) else None


def _cc_tool_outcome(ep, tool_use_id, created_at, home=None):
    """Return success/error for one exact native CC local-tool pair."""
    tid = str(ep.get('thread_id') or ep.get('session_id') or '')
    project = ep.get('project_path')
    created = _cc_timestamp(created_at)
    if (ep.get('platform') != 'cc' or not re.fullmatch(r'[0-9a-fA-F-]{36}', tid)
            or not project or not isinstance(tool_use_id, str) or not tool_use_id
            or created is None):
        return None
    root = Path(home or Path.home()) / '.claude/projects'
    paths = list(root.glob('*/' + tid + '.jsonl'))
    paths = [p for p in paths if p.is_file() and not any(x.is_symlink() for x in (p, *p.parents))]
    if len(paths) != 1:
        return None
    calls = []
    results = []
    outcome = None
    try:
        with paths[0].open(encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    return None
                content = (row.get('message') or {}).get('content')
                if not isinstance(content, list):
                    continue
                target_items = [item for item in content if isinstance(item, dict) and (
                    item.get('id') == tool_use_id or item.get('tool_use_id') == tool_use_id)]
                if not target_items:
                    continue
                if row.get('isSidechain') is True or row.get('sessionId') != tid or not isinstance(row.get('cwd'), str):
                    return None
                if row.get('type') not in ('assistant', 'user') or not any(
                        (row.get('type') == 'assistant' and item.get('type') == 'tool_use' and item.get('id') == tool_use_id)
                        or (row.get('type') == 'user' and item.get('type') == 'tool_result' and item.get('tool_use_id') == tool_use_id)
                        for item in target_items):
                    return None
                if Path(row['cwd']).resolve() != Path(str(project)).resolve():
                    return None
                timestamp = _cc_timestamp(row.get('timestamp'))
                if timestamp is None:
                    return None
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if row.get('type') == 'assistant' and item.get('type') == 'tool_use' and item.get('id') == tool_use_id:
                        if item.get('name') not in _CC_LOCAL_TOOLS:
                            return None
                        calls.append((index, timestamp))
                    if row.get('type') == 'user' and item.get('type') == 'tool_result' and item.get('tool_use_id') == tool_use_id:
                        if 'is_error' in item and not isinstance(item['is_error'], bool):
                            return None
                        outcome = 'error' if item.get('is_error') is True else 'success'
                        results.append((index, timestamp))
        if len(calls) != 1 or len(results) != 1:
            return None
        call_index, call_time = calls[0]
        result_index, result_time = results[0]
        return (outcome if result_time >= created and result_index > call_index
                and result_time >= call_time else None)
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        return None


def _cc_tool_witness(ep, tool_use_id, created_at, home=None):
    return _cc_tool_outcome(ep, tool_use_id, created_at, home) == 'success'


def _completion_witness(ep, tool_use_id, created_at):
    if ep.get('platform') == 'cc':
        return _cc_tool_witness(ep, tool_use_id, created_at)
    return _file_change_witness(ep, tool_use_id, created_at)


def _completion_outcome(ep, tool_use_id, created_at):
    if ep.get('platform') == 'cc':
        return _cc_tool_outcome(ep, tool_use_id, created_at)
    if ep.get('platform') == 'cdx':
        saw_command, saw_file_change, command_outcome = _command_execution_observation(ep, tool_use_id, created_at)
        if command_outcome is not None:
            return command_outcome
        if saw_command and saw_file_change:
            return None
        if saw_command:
            return None
    return 'success' if _file_change_witness(ep, tool_use_id, created_at) else None


def _native_binding_id(ep):
    return str(ep.get('thread_id') or ep.get('session_id') or ep.get('runtime_id') or '')


def _historical_binding_proof(host, ep, task_id, epoch):
    """Derive one former local binding from the authenticated native context."""
    native_id = _native_binding_id(ep)
    if not native_id or not binding_marker(native_id).is_file():
        raise HubError('identity_rejected', 'native binding continuity is unavailable')
    rows = host.db.execute(
        'SELECT * FROM formal_task_binding WHERE native_id=? ORDER BY endpoint_id', (native_id,)).fetchall()
    if len(rows) != 1:
        raise HubError('identity_rejected', 'native binding continuity is ambiguous')
    row = rows[0]
    if (row['endpoint_id'] == ep['endpoint_id'] or row['task_id'] != task_id
            or row['epoch'] != epoch):
        raise HubError('identity_rejected', 'historical binding does not match detach request')
    directory = host.hub('endpoints_list').get('endpoints', [])
    matches = [item for item in directory if item.get('endpoint_id') == row['endpoint_id']]
    if len(matches) != 1:
        raise HubError('identity_rejected', 'historical endpoint continuity is unavailable')
    old = matches[0]
    if (old.get('host_id') != ep.get('host_id') or old.get('participant_id') != ep.get('participant_id')
            or old.get('platform') != ep.get('platform') or old.get('incarnation') != row['incarnation']):
        raise HubError('identity_rejected', 'historical endpoint continuity differs')
    return {
        'endpoint_id': old['endpoint_id'], 'incarnation': old['incarnation'],
        'host_id': old['host_id'], 'project_id': ep.get('project_id'),
        'platform': old['platform'], 'native_id': native_id,
    }


def binding_marker(native_id):
    # Presence is only a restrictive fence, never a copy of task authority.
    root = Path(os.environ.get('TPROJ_TASK_BINDING_DIR', str(Path.home()/'.local/state/tproj/task-bindings')))
    return root / digest(native_id)


def _binding_status(host, ep):
    """Return read-only native marker/formal-binding correlation evidence."""
    native_id = str(ep.get('thread_id') or ep.get('session_id') or ep.get('runtime_id') or '')
    if not native_id:
        raise HubError('identity_rejected', 'native conversation ID required for binding diagnostics')
    marker_present = binding_marker(native_id).is_file()
    try:
        rows = host.db.execute(
            'SELECT endpoint_id, incarnation, task_id, epoch FROM formal_task_binding WHERE native_id=? ORDER BY endpoint_id',
            (native_id,)).fetchall()
    except Exception as exc:
        # A diagnostic must not create the optional table.  A missing table is
        # equivalent to no local formal bindings; other database failures fail
        # closed without attempting recovery or mutation.
        if 'no such table' not in str(exc).lower():
            raise HubError('unavailable', 'formal binding records are unavailable') from exc
        rows = []
    current = next((row for row in rows if row['endpoint_id'] == ep['endpoint_id']), None)
    current_binding = {'status': 'not_bound', 'task_id': None, 'epoch': None,
                       'incarnation_matches': False}
    if current is not None:
        incarnation_matches = current['incarnation'] == ep['incarnation']
        current_binding.update(task_id=current['task_id'], epoch=current['epoch'],
                               incarnation_matches=incarnation_matches)
        current_binding['status'] = 'bound' if incarnation_matches else 'stale_incarnation'
        if incarnation_matches:
            try:
                snapshot = host.hub('task_status', endpoint_id=ep['endpoint_id'], task_id=current['task_id'])
            except HubError as exc:
                if exc.code in ('not_found', 'not_visible'):
                    current_binding['status'] = 'task_not_visible'
                else:
                    current_binding['status'] = 'task_status_unavailable'
            else:
                task = snapshot.get('task') or {}
                current_binding['task_status'] = task.get('status')
                current_binding['task_epoch_matches'] = task.get('epoch') == current['epoch']
    matching = [{
        'task_id': row['task_id'],
        'epoch': row['epoch'],
        'current_endpoint': row['endpoint_id'] == ep['endpoint_id'],
        'current_incarnation': row['incarnation'] == ep['incarnation'],
    } for row in rows]
    return {
        'marker_present': marker_present,
        'current_binding': current_binding,
        'matching_native_bindings': matching,
        'matching_native_bindings_count': len(matching),
    }


def dispatch(host, ep, req):
    op=req['op']
    if op == 'task_binding_status':
        return _binding_status(host, ep)
    host.db.execute('CREATE TABLE IF NOT EXISTS formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT NOT NULL, task_id TEXT NOT NULL, epoch INTEGER NOT NULL, native_id TEXT NOT NULL)')
    if op == 'task_binding_release_check':
        raise HubError('unsupported', 'binding release permission is host-internal')
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
        task = snapshot.get('task') or {}
        if (task.get('epoch') != bound['epoch'] or task.get('executor_endpoint') != ep['endpoint_id']
                or task.get('executor_incarnation') != ep['incarnation']
                or task.get('status') not in ('accepted', 'in_progress')
                or (snapshot.get('handoff') or {}).get('state') in ('prepared', 'released', 'accepted')):
            raise HubError('stale_executor', 'task authority no longer matches this binding')
        details = [item for item in snapshot.get('actor_open_operation_details', []) if item.get('tool_use_id') == ident]
        outcome = None if len(details) != 1 or type(details[0].get('epoch')) is not int \
                or details[0]['epoch'] != bound['epoch'] else _completion_outcome(ep, ident, details[0].get('created_at'))
        if outcome is None:
            raise HubError('witness_unavailable', 'native completion witness is unavailable')
        result = host.hub('task_end_operation', endpoint_id=ep['endpoint_id'], task_id=bound['task_id'], expected_epoch=epoch, tool_use_id=ident)
        return dict(result, assigned=True, reconciled=True, native_outcome=outcome)
    if op in ('task_guard_begin','task_guard_end'):
        if not bound:return {'assigned':False}
        if bound['incarnation']!=ep['incarnation']:raise HubError('stale_executor','formal task conversation changed')
        ident=req.get('tool_use_id')
        if not isinstance(ident,str) or not ident:raise HubError('invalid_request','tool-use identity required for guarded operation')
        actual='task_begin_operation' if op.endswith('begin') else 'task_end_operation'
        result=host.hub(actual,endpoint_id=ep['endpoint_id'],task_id=bound['task_id'],expected_epoch=bound['epoch'],tool_use_id=ident)
        return dict(result,assigned=True)
    if op == 'task_detach':
        if not bound:
            if not isinstance(req.get('expected_epoch'), int) or not isinstance(req.get('task_id'), str):
                raise HubError('epoch_conflict', 'detach must name the historical assignment epoch and task')
            native_id = _native_binding_id(ep)
            matching = host.db.execute('SELECT 1 FROM formal_task_binding WHERE native_id=?', (native_id,)).fetchone()
            marker = binding_marker(native_id)
            if native_id and not marker.exists() and not matching:
                return {'detached': True}
            host.db.execute('BEGIN IMMEDIATE')
            try:
                if host.db.execute('SELECT 1 FROM formal_task_binding WHERE endpoint_id=?', (ep['endpoint_id'],)).fetchone():
                    raise HubError('stale_executor', 'current binding appeared during detach')
                proof = _historical_binding_proof(host, ep, req['task_id'], req['expected_epoch'])
                result = host.hub('task_binding_release_check', endpoint_id=ep['endpoint_id'],
                                  task_id=req['task_id'], expected_epoch=req['expected_epoch'],
                                  native_id=proof['native_id'], previous=proof)
                if not isinstance(result, dict) or result.get('allowed') is not True:
                    raise HubError('identity_rejected', 'master did not authorize historical binding release')
                deleted = host.db.execute(
                    'DELETE FROM formal_task_binding WHERE endpoint_id=? AND task_id=? AND epoch=?',
                    (proof['endpoint_id'], req['task_id'], req['expected_epoch'])).rowcount
                if deleted != 1:
                    raise HubError('identity_rejected', 'historical binding changed during detach')
                host.db.commit()
                try:
                    host.db.execute('BEGIN IMMEDIATE')
                    remaining = host.db.execute('SELECT 1 FROM formal_task_binding WHERE native_id=?', (proof['native_id'],)).fetchone()
                    if not remaining:
                        binding_marker(proof['native_id']).unlink(missing_ok=True)
                    host.db.commit()
                except Exception as exc:
                    if host.db.in_transaction: host.db.rollback()
                    raise HubError('unavailable', 'native binding marker cleanup is incomplete') from exc
                return {'detached': True, 'resynchronized': True}
            except Exception:
                if host.db.in_transaction: host.db.rollback()
                raise
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
        host.db.execute('BEGIN IMMEDIATE')
        try:
            marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with marker.open('ab') as handle:
                handle.flush()
                os.fsync(handle.fileno())
            host.db.execute('INSERT INTO formal_task_binding VALUES(?,?,?,?,?) ON CONFLICT(endpoint_id) DO UPDATE SET epoch=excluded.epoch', (ep['endpoint_id'],ep['incarnation'],tid,epoch,str(ep.get('thread_id') or ep.get('session_id') or ep.get('runtime_id') or '')))
            host.db.commit()
        except Exception:
            if host.db.in_transaction: host.db.rollback()
            raise
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

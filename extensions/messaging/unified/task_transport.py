"""Single-master task routing over existing authenticated host federation."""
from __future__ import annotations
from protocol import HubError

TASK_PROTOCOL = 1


def actor(evidence):
    ep = evidence['endpoint']
    if ep.get('retired') or evidence['participant'].get('project_id') is None:
        raise HubError('identity_rejected', 'formal tasks require a live AI project endpoint')
    return {k: ep[k] for k in ('endpoint_id', 'incarnation', 'host_id')} | {'project_id': evidence['participant']['project_id']}


def master(hub):
    top = hub.topology()
    if top.get('mode') != 'multi': return hub.local_id
    selected = top.get('task_master_host_id')
    if selected not in {hub.local_id, *hub.peers()}:
        raise HubError('task_master_unavailable', 'configure one task_master_host_id for formal tasks')
    return selected


def _attest_binding_release(hub, evidence, body):
    """Bind historical release proof to this host's enrolled endpoint directory."""
    previous = body.get('previous')
    native_id = body.get('native_id')
    fields = ('endpoint_id', 'incarnation', 'host_id', 'project_id', 'platform', 'native_id')
    if not isinstance(native_id, str) or not native_id or not isinstance(previous, dict):
        raise HubError('identity_rejected', 'historical native binding evidence is incomplete')
    if any(not isinstance(previous.get(k), str) or not previous[k] for k in fields):
        raise HubError('identity_rejected', 'historical native binding evidence is incomplete')
    current_ep = evidence['endpoint']; current_participant = evidence['participant']
    authenticated_native = str(current_ep.get('thread_id') or current_ep.get('session_id') or current_ep.get('runtime_id') or '')
    if not authenticated_native or native_id != authenticated_native:
        raise HubError('identity_rejected', 'historical native context does not match authenticated endpoint')
    if previous['native_id'] != native_id:
        raise HubError('identity_rejected', 'historical native context does not match current caller')
    if previous['host_id'] != current_ep['host_id'] or previous['project_id'] != current_participant.get('project_id'):
        raise HubError('identity_rejected', 'historical binding is not the same enrolled participant')
    if previous['platform'] != current_ep.get('platform'):
        raise HubError('identity_rejected', 'historical binding platform differs')
    # Same endpoint with a new incarnation is a valid native restart.  The
    # current authenticated tuple plus exact native identity proves continuity;
    # do not require the directory to retain the retired incarnation.
    if previous['endpoint_id'] == current_ep.get('endpoint_id'):
        return dict(previous)
    old = hub._row('SELECT * FROM endpoints WHERE endpoint_id=?', (previous['endpoint_id'],))
    participant = hub._row('SELECT * FROM participants WHERE participant_id=?', (old['participant_id'],)) if old else None
    if (not old or not participant or old['host_id'] != current_ep['host_id']
            or old['participant_id'] != current_ep['participant_id']
            or str(old['incarnation']) != previous['incarnation']
            or str(old['platform']) != previous['platform']
            or participant['project_id'] != previous['project_id']):
        raise HubError('identity_rejected', 'historical endpoint continuity is unavailable')
    return dict(previous)


def dispatch(hub, req, peer=False):
    from tasks import TaskAuthority, TaskAuthorityError
    origin = hub._auth(req)
    selected = master(hub)
    if peer:
        if req.get('task_protocol') != TASK_PROTOCOL:
            raise HubError('incompatible_peer','formal task protocol is unsupported')
        if selected != hub.local_id:
            raise HubError('task_master_mismatch', 'this host is not the task master')
        evidence=req.get('actor_evidence') or {}
        if evidence.get('endpoint',{}).get('host_id') != origin or evidence.get('participant',{}).get('host_id') != origin:
            raise HubError('identity_rejected', 'task actor is not owned by enrolled sending host')
        # Native authentication and destination resolution happened at trusted
        # owner ingress. Calling that serialized host back here would deadlock.
        # The executor must still attest its exact incarnation when accepting.
        body=dict(req.get('request') or {})
        if not str(body.get('op','')).startswith('task_'):
            raise HubError('invalid_request','formal task operation required')
        if body.get('op') in ('task_binding_release_check', 'task_cancelled_release_check') and (
                body.get('previous') is not None or body.get('native_id') is not None):
            previous = body.get('previous')
            current = evidence.get('endpoint') or {}
            participant = evidence.get('participant') or {}
            attested = evidence.get('binding_release') or {}
            authenticated_native = str(current.get('thread_id') or current.get('session_id') or current.get('runtime_id') or '')
            if (not isinstance(previous, dict) or attested.get('previous') != previous
                    or attested.get('native_id') != body.get('native_id')
                    or not authenticated_native or authenticated_native != body.get('native_id')
                    or previous.get('native_id') != body.get('native_id')
                    or previous.get('host_id') != current.get('host_id')
                    or previous.get('project_id') != participant.get('project_id')
                    or previous.get('platform') != current.get('platform')):
                raise HubError('identity_rejected', 'historical native binding evidence is incomplete')
    else:
        if origin != hub.local_id:
            raise HubError('unauthorized','formal tasks require local host ingress')
        evidence=hub.local_resolve(endpoint_id=req.get('endpoint_id'))
        body={k:v for k,v in req.items() if k not in ('host_token','host_id','endpoint_id')}
        for field in ('executor','target'):
            if field not in body:continue
            value=body[field]
            if not isinstance(value,str):raise HubError('invalid_request','task destination must be an address')
            if value in ('cc','cdx'):value=evidence['participant']['address'].rsplit('.',1)[0]+'.'+value
            body[field]=actor(hub.resolve_destination(value))
        if body.get('op') in ('task_binding_release_check', 'task_cancelled_release_check') and (
                body.get('previous') is not None or body.get('native_id') is not None):
            evidence = hub.local_resolve(endpoint_id=req.get('endpoint_id'))
            _attest_binding_release(hub, evidence, body)
        if selected != hub.local_id:
            actor_evidence = evidence
            if body.get('op') in ('task_binding_release_check', 'task_cancelled_release_check') and (
                    body.get('previous') is not None or body.get('native_id') is not None):
                actor_evidence = dict(evidence, binding_release={
                    'native_id': body.get('native_id'), 'previous': body.get('previous')})
            response = hub.remote(selected,'task',actor_evidence=actor_evidence,request=body,task_protocol=TASK_PROTOCOL)
            if not isinstance(response,dict) or response.get('task_protocol') != TASK_PROTOCOL or 'result' not in response:
                raise HubError('incompatible_peer','task master did not confirm formal task protocol')
            return response['result']
    try:
        result = TaskAuthority(hub.db).dispatch(body,actor(evidence))
        return {'task_protocol':TASK_PROTOCOL,'result':result} if peer else result
    except TaskAuthorityError as exc:
        raise HubError(exc.code,str(exc)) from None

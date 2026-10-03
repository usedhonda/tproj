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
        if selected != hub.local_id:
            response = hub.remote(selected,'task',actor_evidence=evidence,request=body,task_protocol=TASK_PROTOCOL)
            if not isinstance(response,dict) or response.get('task_protocol') != TASK_PROTOCOL or 'result' not in response:
                raise HubError('incompatible_peer','task master did not confirm formal task protocol')
            return response['result']
    try:
        result = TaskAuthority(hub.db).dispatch(body,actor(evidence))
        return {'task_protocol':TASK_PROTOCOL,'result':result} if peer else result
    except TaskAuthorityError as exc:
        raise HubError(exc.code,str(exc)) from None

"""Optional model-role-router bridge to live, native-bound task authority."""
from __future__ import annotations
import json
import os
import sys
from task_host import binding_marker
import cli


def _native_context(payload):
    """Extract hook-supplied native IDs without inventing an identity."""
    values = {}
    roots = (payload, payload.get('hook_input'), payload.get('raw_event'))
    for root in roots:
        if not isinstance(root, dict):
            continue
        for key in ('thread_id', 'session_id'):
            value = root.get(key)
            if isinstance(value, str) and value.strip():
                values[key] = value.strip()
        value = root.get('conversation_id')
        if (not values.get('thread_id') and not values.get('session_id')
                and isinstance(value, str) and value.strip()):
            values['thread_id'] = value.strip()
    return values


def _caller_request(payload):
    native = _native_context(payload)
    env = cli.native_conversation_context()
    for key in ('thread_id', 'session_id'):
        if native.get(key) and env.get(key) and native[key] != env[key]:
            raise ValueError('native conversation context conflict')
    request = cli._caller_request('task_context')
    if native:
        merged = dict(env)
        merged.update(native)
        request['conversation'] = merged
    return request


def context(payload):
    ids={os.environ.get('CODEX_THREAD_ID',''),os.environ.get('CODEX_SESSION_ID','')}
    for key in ('session_id','thread_id','conversation_id'):
        if isinstance(payload.get(key),str):ids.add(payload[key])
    ids.discard('')
    if not any(binding_marker(native).exists() for native in ids):return {'assigned':False}
    try:
        request=_caller_request(payload)
        result=cli.rpc(cli.config()['socket'],request)
        if not isinstance(result,dict) or result.get('assigned') is not True:
            raise ValueError('assignment mismatch')
        return result
    except Exception:
        return {'assigned':True,'can_mutate':False,'task_status':'authority_unavailable'}


def main():
    try:
        payload=json.load(sys.stdin)
        if not isinstance(payload,dict):payload={}
        print(json.dumps(context(payload)))
    except Exception:
        print(json.dumps({'assigned':True,'can_mutate':False,'task_status':'binding_unavailable'}))

if __name__=='__main__':main()

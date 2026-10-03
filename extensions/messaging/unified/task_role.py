"""Optional model-role-router bridge to live, native-bound task authority."""
from __future__ import annotations
import json
import os
import sys
from task_host import binding_marker
import cli


def context(payload):
    ids={os.environ.get('CODEX_THREAD_ID',''),os.environ.get('CODEX_SESSION_ID','')}
    for key in ('session_id','thread_id','conversation_id'):
        if isinstance(payload.get(key),str):ids.add(payload[key])
    ids.discard('')
    if not any(binding_marker(native).exists() for native in ids):return {'assigned':False}
    try:
        request=cli._caller_request('task_context')
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

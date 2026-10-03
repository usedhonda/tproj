"""Optional model-role-router bridge to live, native-bound task authority."""
from __future__ import annotations
import json
import os
import sys
from task_host import binding_marker
import cli
from identity import native_thread_metadata

def _blocked(error, phase):
    return {'assigned':True, 'can_mutate':False, 'task_status':'authority_unavailable',
            'authority_error':error, 'authority_phase':phase}

def _failure_code(exc):
    code = getattr(exc, 'code', '')
    if code == 'unavailable':
        return 'transport_unavailable'
    if code != 'identity_rejected':
        return 'protocol_rejected'
    message = str(exc)
    for phrase, category in (
            ('agent ancestor absent', 'ancestor_absent'),
            ('endpoint binding is ambiguous', 'endpoint_ambiguous'),
            ('shared Codex app-server ancestry cannot authenticate caller without native conversation context', 'native_context_missing')):
        if phrase in message:
            return category
    return 'identity_rejected'


def native_context(payload):
    """Extract hook-supplied native IDs without inventing an identity."""
    values = {}
    roots = (payload, payload.get('hook_input'), payload.get('raw_event'))
    for root in roots:
        if not isinstance(root, dict):
            continue
        for key in ('thread_id', 'session_id'):
            value = root.get(key)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                if values.get(key) and values[key] != value:
                    raise ValueError('native conversation context conflict')
                values[key] = value
        value = root.get('conversation_id')
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if values.get('thread_id') and values['thread_id'] != value:
                raise ValueError('native conversation context conflict')
            values['thread_id'] = value
    if values.get('session_id') and not values.get('thread_id'):
        proven = native_thread_metadata(values['session_id'])
        if (len(proven) == 1
                and str(proven[0].get('thread_id', '')) == values['session_id']
                and (not proven[0].get('session_id') or str(proven[0]['session_id']) == values['session_id'])
                and str(proven[0].get('source_kind', '')) in {'cli', 'vscode-rollout'}
                and isinstance(proven[0].get('thread_id'), str)
                and proven[0]['thread_id'].strip()):
            values['thread_id'] = proven[0]['thread_id'].strip()
    return values


def _caller_request(payload):
    native = native_context(payload)
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
    try:
        native = native_context(payload)
    except ValueError:
        return _blocked('native_context_conflict', 'context')
    ids={os.environ.get('CODEX_THREAD_ID',''),os.environ.get('CODEX_SESSION_ID',''),
         native.get('thread_id',''),native.get('session_id','')}
    ids.discard('')
    if not any(binding_marker(native).exists() for native in ids):return {'assigned':False}
    try:
        request=_caller_request(payload)
    except ValueError:
        return _blocked('native_context_conflict', 'context')
    try:
        try:
            cfg = cli.config()
        except cli.ClientError:
            return _blocked('config_unavailable', 'config')
        try:
            result=cli.rpc(cfg['socket'],request)
        except cli.ClientError as exc:
            return _blocked(_failure_code(exc), 'rpc')
        if not isinstance(result,dict) or result.get('assigned') is not True:
            return _blocked('assignment_mismatch', 'assignment')
        return result
    except Exception:
        return _blocked('helper_failure', 'helper')


def main():
    try:
        payload=json.load(sys.stdin)
        if not isinstance(payload,dict):payload={}
        print(json.dumps(context(payload)))
    except Exception:
        print(json.dumps(_blocked('helper_failure', 'helper')))

if __name__=='__main__':main()

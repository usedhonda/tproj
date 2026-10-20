"""Optional Codex queue transport over one existing private Unix socket.

No daemon startup, thread resume, provider connection, inference or automatic
retry. Caller owns authenticated native binding and durable publication state.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import time
import uuid

LIMIT = 262144


class QueueError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def private_socket(path):
    """The normal control-socket symlink is allowed; its target must be private."""
    try:
        source = Path(path)
        entry = source.lstat()
        if entry.st_uid != os.getuid(): raise ValueError('owner')
        target = source.resolve(strict=True)
        current = target.stat()
        if (current.st_uid != os.getuid() or not stat.S_ISSOCK(current.st_mode)
                or current.st_mode & 0o077):
            raise ValueError('unsafe socket')
        return str(target)
    except (OSError, ValueError, RuntimeError):
        raise QueueError('socket_unavailable') from None


def _integer(value):
    return type(value) is int and -(2**63) <= value < 2**63


def _object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs): raise ValueError('duplicate response key')
    return value


def _response(reply, number):
    # Codex App Server rpc.rs deliberately omits jsonrpc. If supplied it may
    # only be the standard version; this is not arbitrary malformed fallback.
    if not isinstance(reply, dict) or ('jsonrpc' in reply and reply['jsonrpc'] != '2.0'):
        raise QueueError('invalid_response')
    if 'method' in reply:
        if (not isinstance(reply['method'], str) or 'result' in reply or 'error' in reply
                or ('id' in reply and not (_integer(reply['id']) or isinstance(reply['id'], str)))):
            raise QueueError('invalid_response')
        return None
    rid = reply.get('id')
    if not (_integer(rid) or isinstance(rid, str)) or (('result' in reply) == ('error' in reply)):
        raise QueueError('invalid_response')
    if 'error' in reply:
        error = reply['error']
        if (not isinstance(error, dict) or not _integer(error.get('code'))
                or not isinstance(error.get('message'), str)):
            raise QueueError('invalid_response')
    if type(rid) is not type(number) or rid != number: return None
    return reply


def request(path, method, params):
    """One request only. Lost add responses are unknown, never retryable success."""
    if method not in ('thread/queue/add', 'thread/queue/list'):
        raise QueueError('unsupported_operation')
    if len(json.dumps(params, ensure_ascii=False).encode()) > LIMIT - 2048:
        raise QueueError('request_too_large')
    target = private_socket(path)
    try:
        from websockets.sync.client import unix_connect
    except ImportError:
        raise QueueError('dependency_unavailable') from None
    sent_add = False
    try:
        with unix_connect(target, uri='ws://localhost', open_timeout=3, close_timeout=1,
                          max_size=LIMIT) as ws:
            def call(number, name, values):
                nonlocal sent_add
                frame = json.dumps({'jsonrpc': '2.0', 'id': number, 'method': name, 'params': values}, ensure_ascii=False)
                # A send error may occur after bytes leave this process.
                if name == 'thread/queue/add': sent_add = True
                deadline = time.monotonic() + 5
                ws.send(frame)
                for _ in range(64):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError()
                    reply = _response(json.loads(ws.recv(timeout=remaining), object_pairs_hook=_object), number)
                    if reply is None: continue
                    if 'error' in reply:
                        error = reply['error']
                        code = error.get('code') if isinstance(error, dict) else None
                        if name == 'thread/queue/add' and code not in (-32601, -32602):
                            raise QueueError('publication_unknown')
                        raise QueueError('operation_rejected')
                    result = reply.get('result')
                    if not isinstance(result, dict): raise QueueError('invalid_response')
                    return result
                raise QueueError('response_unavailable')
            call(1, 'initialize', {'clientInfo': {'name': 'tproj-native-queue', 'version': '1'},
                                   'capabilities': {'experimentalApi': True}})
            ws.send(json.dumps({'jsonrpc': '2.0', 'method': 'initialized'}))
            return call(2, method, params)
    except QueueError as exc:
        # A well-formed rejection is known; malformed/missing add responses are not.
        if sent_add and exc.code != 'operation_rejected':
            raise QueueError('publication_unknown') from None
        raise
    except Exception:
        raise QueueError('publication_unknown' if sent_add else 'transport_unavailable') from None


def _native(native_id):
    try:
        if not isinstance(native_id, str) or str(uuid.UUID(native_id)) != native_id.lower():
            raise ValueError('noncanonical native id')
    except (ValueError, AttributeError):
        raise QueueError('invalid_native_id') from None


def _queued(item):
    return (isinstance(item, dict) and isinstance(item.get('id'), str) and bool(item['id'])
            and isinstance(item.get('clientUserMessageId'), str)
            and isinstance(item.get('input'), list)
            and all(isinstance(x, dict) and isinstance(x.get('type'), str) for x in item['input']))


def publish(path, native_id, notice):
    _native(native_id)
    if (not isinstance(notice, dict) or notice.get('native_id') != native_id
            or not isinstance(notice.get('prompt'), str) or not notice['prompt']
            or not isinstance(notice.get('client_id'), str) or not notice['client_id']):
        raise QueueError('invalid_notice')
    # The provider does not deduplicate clientUserMessageId. It is correlation
    # only; unknown outcomes require queue/history reconciliation by the caller.
    result = request(path, 'thread/queue/add', {'threadId': native_id,
        'input': [{'type': 'text', 'text': notice['prompt']}], 'clientUserMessageId': notice['client_id']})
    item = result.get('queuedSubmission')
    if (not _queued(item)
            or item.get('clientUserMessageId') != notice['client_id']
            or not isinstance(item.get('input'), list) or len(item['input']) != 1
            or not isinstance(item['input'][0], dict) or item['input'][0].get('type') != 'text'
            or item['input'][0].get('text') != notice['prompt']):
        raise QueueError('publication_unknown')
    return result


def pending(path, native_id, cursor=None):
    _native(native_id)
    if cursor is not None and not isinstance(cursor, str): raise QueueError('invalid_cursor')
    params = {'threadId': native_id, 'limit': 32}
    if cursor is not None: params['cursor'] = cursor
    result = request(path, 'thread/queue/list', params)
    if (not isinstance(result.get('data'), list) or len(result['data']) > 32
            or any(not _queued(item) for item in result['data'])
            or 'nextCursor' not in result
            or (result['nextCursor'] is not None and not isinstance(result['nextCursor'], str))):
        raise QueueError('invalid_response')
    return result


def worker_main():
    """Private one-shot transport worker; parent owns its deadline and journal."""
    import sys
    try:
        if len(sys.argv) != 3 or sys.argv[1] != '--worker': raise QueueError('invalid_request')
        with open(sys.argv[2], 'rb') as f: raw = f.read(LIMIT + 1)
        if len(raw) > LIMIT: raise QueueError('request_too_large')
        packet = json.loads(raw)
        if packet['op'] == 'publish':
            result = publish(packet['socket'], packet['native_id'], packet['notice'])
        elif packet['op'] == 'pending':
            result = pending(packet['socket'], packet['native_id'], packet.get('cursor'))
        else: raise QueueError('unsupported_operation')
        output = {'ok': True, 'result': result}
    except QueueError as exc:
        output = {'ok': False, 'code': exc.code}
    except Exception:
        output = {'ok': False, 'code': 'publication_unknown'}
    raw = json.dumps(output, ensure_ascii=False)
    if len(raw.encode()) > LIMIT: raw = json.dumps({'ok': False, 'code': 'publication_unknown'})
    print(raw, flush=True)


if __name__ == '__main__': worker_main()

#!/usr/bin/env python3
"""One metadata-only detection pass. State is notification bookkeeping, not a mailbox."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from vm_client import invoke, load_config

ACTIVE = frozenset(('accepted', 'queued', 'adapter_received', 'dispatching', 'uncertain'))


def decide(state, result, now):
    state = dict(state)
    state.pop('error_notified', None)
    rows = result.get('pending', [])
    cursor = int(state.get('cursor', 0))
    active = state.get('active')
    if active:
        row = next((x for x in rows if x.get('message_id') == active['message_id']), None)
        if row is not None and row.get('state') in ACTIVE and row.get('expires_at', now + 1) > now:
            if now - active['notified_at'] >= 180 and not active.get('stalled_notified'):
                state['active'] = dict(active, stalled_notified=True)
                return dict(decision='wake', reason='tproj-consumer-stalled',
                            payload={'message_id': active['message_id'], 'action': 'inspect_existing_work_not_resend'}, state=state)
            return dict(decision='silent', reason='awaiting-consumption', state=state)
        cursor = max(cursor, int(active['sequence']))
        state.pop('active', None)
    for row in rows:
        if int(row['sequence']) <= cursor:
            continue
        if row.get('state') not in ACTIVE or row.get('expires_at', now + 1) <= now:
            cursor = int(row['sequence']); continue
        state['cursor'] = cursor
        state['active'] = {'message_id': row['message_id'], 'sequence': row['sequence'], 'notified_at': now}
        return dict(decision='wake', reason='tproj-message', payload={k: row[k] for k in (
            'message_id', 'thread_id', 'sender_address', 'in_reply_to') if k in row}, state=state)
    state['cursor'] = max(cursor, int(result.get('next_cursor', cursor)))
    return dict(decision='silent', reason='no-new-message', state=state)


def detect(config, state, now=None):
    now = time.time() if now is None else now
    try:
        result = asyncio.run(invoke(load_config(config), 'tproj_inbox', {
            'cursor': int(state.get('cursor', 0)), 'limit': 100, 'metadata_only': True}))
        if result.get('isError'):
            raise ValueError('tool failure')
        value = result.get('structuredContent')
        if not isinstance(value, dict) or value.get('metadata_only') is not True:
            raise ValueError('metadata capability required')
        return decide(state, value, now)
    except (Exception, BaseExceptionGroup):
        failed = dict(state, error_notified=True)
        return dict(decision='silent' if state.get('error_notified') else 'wake',
                    reason='tproj-connection-unavailable', payload={'action': 'diagnose_no_replay'}, state=failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    state = json.load(sys.stdin)
    if not isinstance(state, dict):
        raise ValueError('state object required')
    print(json.dumps(detect(args.config, state)))


if __name__ == '__main__':
    main()

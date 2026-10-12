"""One-time, idempotent migration of the existing operator-approved KAI scope."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import tempfile

from host import load_config_snapshot, policy_scope, policy_revision
from protocol import HubError


def migrate(host_path, consumer_path, check=False):
    host_path, consumer_path = Path(host_path), Path(consumer_path)
    config = load_config_snapshot(host_path)
    consumer = load_config_snapshot(consumer_path)
    service_id = consumer.get('service_id')
    if service_id != 'kai':
        raise HubError('configuration_error', 'KAI enrollment required')
    service = config.get('services', {}).get(service_id)
    if not isinstance(service, dict):
        raise HubError('configuration_error', 'existing host enrollment required')
    for key in ('address', 'participant_id', 'binding_generation'):
        if not isinstance(service.get(key), str) or not service[key] or service[key] != consumer.get(key):
            raise HubError('configuration_error', 'enrollment mismatch; no configuration changed')
    if (not isinstance(service.get('token'), str) or not service['token'] or
            not isinstance(consumer.get('service_token'), str) or
            not secrets.compare_digest(service['token'], consumer['service_token'])):
        raise HubError('configuration_error', 'enrollment mismatch; no configuration changed')
    scope = policy_scope(consumer)
    if 'allowed_addresses' in service:
        if policy_scope(service) != scope:
            raise HubError('configuration_error', 'existing policies differ; no configuration changed')
        return {'changed': False, 'policy_revision': policy_revision(scope), 'count': len(scope)}
    if check:
        return {'changed': False, 'migration_required': True,
                'policy_revision': policy_revision(scope), 'count': len(scope)}
    # Serialize this migration and reject an observed competing edit; never merge.
    lock_fd = os.open(str(host_path) + '.policy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load_config_snapshot(host_path) != config:
            raise HubError('revision_conflict', 'configuration changed; no configuration changed')
        config['services'][service_id]['allowed_addresses'] = scope
        fd, temp = tempfile.mkstemp(prefix='.service-policy.', dir=host_path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(config, stream, ensure_ascii=False, sort_keys=True)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, host_path)
            directory = os.open(host_path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return {'changed': True, 'policy_revision': policy_revision(scope), 'count': len(scope)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-config', required=True)
    parser.add_argument('--consumer-config', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.host_config, args.consumer_config, args.check)))
        return 0
    except HubError as exc:
        print(json.dumps({'error': {'code': exc.code, 'message': exc.message}}))
        return 2


if __name__ == '__main__': raise SystemExit(main())

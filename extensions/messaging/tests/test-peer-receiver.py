#!/usr/bin/env python3
"""Isolated quarantine/release gates; no live SSH or pane delivery."""
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tproj-peer-receiver'
loader = importlib.machinery.SourceFileLoader('peer_receiver', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
r = importlib.util.module_from_spec(spec)
loader.exec_module(r)


class ReceiverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = (self.root / 'destination').resolve()
        self.project.mkdir()
        entry = self.root / 'registry' / 'remote-session' / '1' / 'remote.cdx.json'
        entry.parent.mkdir(parents=True)
        entry.write_text(json.dumps({'alias': 'remote.cdx', 'project': str(self.project),
                                     'role_epoch': 7, 'pid': 300, 'pid_start': 5000}))
        self.entry = entry
        self.metadata = {'message_id': 'msg-1', 'task_id': 'task-1',
            'origin_host': 'host-a', 'destination_host': 'host-b',
            'origin_project': 'origin', 'destination_project': 'destination',
            'owner_session': 'source-session', 'destination_session': 'remote-session',
            'owner_alias': 'origin.cc', 'sender': 'origin.cc',
            'sender_role': 'orchestrator', 'target': 'remote.cdx',
            'role_epoch': 4, 'target_epoch': 7, 'orchestrator_alias': 'origin.cc',
            'task_kind': 'delegated', 'intent_hash': 'a' * 64,
            'user_authorized_exact': True, 'body_hash': hashlib.sha256(b'hello').hexdigest(),
            'ttl_sec': 900, 'issued_at': 1000}
        self.task = {'version': 2, 'metadata': self.metadata, 'kind': 'task', 'body': 'hello'}
        self.commit = {'version': 2, 'metadata': self.metadata, 'kind': 'commit', 'body': ''}
        self.calls = []
        def consume(_, request, pid, started, uid):
            self.calls.append(request)
            return {'ok': True, 'digest': hashlib.sha256(r.a.canonical(request['envelope'])).hexdigest()}
        route = {'source_host': 'host-a', 'destination_host': 'host-b',
                 'source_project': 'origin', 'destination_project': 'destination',
                 'owner_session': 'source-session', 'destination_session': 'remote-session',
                 'target': 'remote.cdx'}
        self.receiver = r.Receiver(source_socket='/private/forward.sock',
            db_path=self.root / 'receiver.sqlite', registry_root=self.root / 'registry',
            target_project=self.project, route=route, forward_pid=400,
            forward_start=6000, forward_uid=501, consume_call=consume, now=lambda: 1001)

    def wire(self, envelope):
        return {'envelope': envelope, 'nonce': 'c' * 64,
                'digest': hashlib.sha256(r.a.canonical(envelope)).hexdigest()}

    def test_quarantine_returns_no_body_then_release(self):
        with patch.object(r.a, 'process', return_value=(1, 5000, 501)), patch.object(r.os, 'getuid', return_value=501):
            self.assertEqual(self.receiver.quarantine(self.wire(self.task)),
                             {'message_id': 'msg-1', 'state': 'quarantined'})
            with self.assertRaisesRegex(r.a.Refused, 'wrong envelope phase'):
                self.receiver.release(self.task, self.wire(self.task))
            result = self.receiver.release(self.task, self.wire(self.commit))
            self.assertEqual(result['state'], 'released')
            self.assertEqual(result['envelope']['body'], 'hello')
        self.assertEqual(len(self.calls), 2)

    def test_route_epoch_expiry_and_unquarantined_reject(self):
        with patch.object(r.a, 'process', return_value=(1, 5000, 501)), patch.object(r.os, 'getuid', return_value=501):
            with self.assertRaisesRegex(r.a.Refused, 'not quarantined'):
                self.receiver.release(self.task, self.wire(self.commit))
            with self.assertRaisesRegex(r.a.Refused, 'route mismatch'):
                self.receiver.quarantine(self.wire(dict(self.task, metadata=dict(self.metadata, destination_host='other'))))
            self.receiver.quarantine(self.wire(self.task))
            self.entry.write_text(json.dumps({'alias': 'remote.cdx', 'project': str(self.project),
                                              'role_epoch': 8, 'pid': 300, 'pid_start': 5000}))
            with self.assertRaisesRegex(r.a.Refused, 'stale target epoch'):
                self.receiver.release(self.task, self.wire(self.commit))
        self.receiver.now = lambda: 2000
        with self.assertRaisesRegex(r.a.Refused, 'expired task'):
            self.receiver.validate_envelope(self.task, 'task')

    def test_forward_peer_pid_and_start_binding(self):
        with patch.object(r.a, 'peer_pid', return_value=400), patch.object(
                r.a, 'process', return_value=(1, 6000, 501)):
            r.check_forward_peer(object(), 400, 6000, 501)
            with self.assertRaisesRegex(r.a.Refused, 'changed'):
                r.check_forward_peer(object(), 400, 6001, 501)
        with patch.object(r.a, 'peer_pid', return_value=401):
            with self.assertRaisesRegex(r.a.Refused, 'wrong local SSH'):
                r.check_forward_peer(object(), 400, 6000, 501)

    def test_local_tombstone_prevents_release(self):
        with patch.object(r.a, 'process', return_value=(1, 5000, 501)), patch.object(r.os, 'getuid', return_value=501):
            self.receiver.quarantine(self.wire(self.task))
            db = r.outbox.open_db(self.receiver.db_path)
            r.outbox.mutate(db, 'tombstone', self.metadata, 'd' * 64)
            db.close()
            with self.assertRaisesRegex(r.a.Refused, 'not quarantined'):
                self.receiver.release(self.task, self.wire(self.commit))
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()

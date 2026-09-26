#!/usr/bin/env python3
"""Isolated durable peer task metadata transitions."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'tproj-peer-outbox'
loader = importlib.machinery.SourceFileLoader('peer_outbox', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
a = importlib.util.module_from_spec(spec)
loader.exec_module(a)


def row(**changes):
    value = {'message_id': 'msg-1', 'task_id': 'task-1', 'origin_host': 'host-a',
             'destination_host': 'host-b', 'origin_project': 'project-a',
             'destination_project': 'project-b', 'owner_session': 'session-a',
             'destination_session': 'session-b', 'owner_alias': 'project.cc',
             'sender': 'project.cc', 'target': 'remote.cdx', 'role_epoch': 4,
             'orchestrator_alias': 'project.cc', 'task_kind': 'delegated',
             'intent_hash': 'a' * 64, 'user_authorized_exact': True,
             'body_hash': 'b' * 64, 'ttl_sec': 900, 'issued_at': 1000}
    value.update(changes)
    return value


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'ledger.sqlite'
        self.db = a.open_db(self.db_path)
        self.addCleanup(self.db.close)

    def test_source_durable_idempotent_and_conflicting(self):
        item = row()
        self.assertEqual(a.mutate(self.db, 'prepare', item), 'prepared')
        self.assertEqual(a.mutate(self.db, 'prepare', item), 'prepared')
        with self.assertRaisesRegex(a.Refused, 'conflict'):
            a.mutate(self.db, 'prepare', row(body_hash='c' * 64))
        self.assertEqual(a.mutate(self.db, 'commit', item), 'committed')
        self.db.close()
        self.db = a.open_db(self.db_path)
        self.assertEqual(a.mutate(self.db, 'commit', item), 'committed')
        self.assertEqual(a.mutate(self.db, 'tombstone', item, 'd' * 64), 'tombstoned')
        self.assertEqual(a.mutate(self.db, 'tombstone', item, 'd' * 64), 'tombstoned')
        with self.assertRaises(a.Refused):
            a.mutate(self.db, 'commit', item)
        with self.assertRaises(a.Refused):
            a.mutate(self.db, 'prepare', item)

    def test_quarantine_release_and_validation(self):
        item = row(message_id='msg-2', task_id='task-2')
        self.assertEqual(a.mutate(self.db, 'quarantine', item), 'quarantined')
        self.assertEqual(a.mutate(self.db, 'release', item), 'released')
        with self.assertRaisesRegex(a.Refused, 'task identity conflict'):
            a.mutate(self.db, 'prepare', row(message_id='msg-3', task_id='task-2'))
        for bad in (row(task_id='../escape'), row(owner_session='..'),
                    row(role_epoch=0), row(user_authorized_exact=True, intent_hash=''),
                    row(sender='other.cc')):
            with self.subTest(bad=bad), self.assertRaises(a.Refused):
                a.validate(bad)


if __name__ == '__main__':
    unittest.main()

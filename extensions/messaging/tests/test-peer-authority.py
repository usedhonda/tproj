#!/usr/bin/env python3
"""Isolated authority checks; no launch, SSH, or delivery."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tproj-peer-authority'
loader = importlib.machinery.SourceFileLoader('peer_authority', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
a = importlib.util.module_from_spec(spec)
loader.exec_module(a)


class AuthorityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = (self.root / 'project').resolve()
        self.project.mkdir()
        record = self.root / 'registry' / 'workspace' / '1' / 'project.cc.json'
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'alias': 'project.cc', 'project': str(self.project),
            'pid': 100, 'pid_start': 1000, 'observed_at': 10000,
            'role': 'worker', 'role_epoch': 4}))
        self.envelope = {'session': 'workspace', 'sender': 'project.cc',
            'target': 'project.cdx', 'role': 'worker', 'epoch': 4,
            'kind': 'task', 'task_id': 'task-1', 'body': 'hello'}
        with patch.object(a, 'process', return_value=(1, 3000, 501)), patch.object(a.os, 'getuid', return_value=501):
            self.authority = a.Authority(self.root / 'registry', self.project,
                                         'workspace', 'project.cdx', 200)

    def bind(self, envelope=None, *, inspect=None):
        return a.bind_sender(101, envelope or self.envelope, self.root / 'registry',
                             self.project, 'workspace',
                             inspect=inspect or (lambda pid: {101: (100, 2000, 501),
                                                                 100: (1, 1000, 501)}[pid]),
                             inspect_cwd=lambda pid: self.project, now=10001)

    def test_registry_binding_and_forgery(self):
        with patch.object(a.os, 'getuid', return_value=501):
            self.bind()
            for field, value in [('sender', 'other.cc'), ('role', 'orchestrator'),
                                 ('epoch', 5), ('session', 'other')]:
                forged = dict(self.envelope, **{field: value})
                with self.subTest(field=field), self.assertRaises(a.Refused):
                    self.bind(forged)
            with self.assertRaisesRegex(a.Refused, 'PID reuse'):
                self.bind(inspect=lambda pid: {101: (100, 2000, 501),
                                               100: (1, 999, 501)}[pid])
            with self.assertRaisesRegex(a.Refused, 'ancestor absent'):
                self.bind(inspect=lambda pid: {101: (1, 2000, 501)}[pid])

    def test_nonce_exact_once_and_receiver_bound(self):
        with patch.object(a, 'bind_sender', return_value=None):
            minted = self.authority.mint(101, self.envelope)
        with patch.object(a, 'process', return_value=(1, 3000, 501)), patch.object(a.os, 'getuid', return_value=501):
            with self.assertRaisesRegex(a.Refused, 'wrong receiver'):
                self.authority.consume(999, minted['nonce'], self.envelope)
            with self.assertRaisesRegex(a.Refused, 'mismatched'):
                self.authority.consume(200, minted['nonce'], dict(self.envelope, body='forged'))
        with patch.object(a, 'bind_sender', return_value=None):
            minted = self.authority.mint(101, self.envelope)
        with patch.object(a, 'process', return_value=(1, 3000, 501)), patch.object(a.os, 'getuid', return_value=501):
            self.assertTrue(self.authority.consume(200, minted['nonce'], self.envelope)['ok'])
            with self.assertRaisesRegex(a.Refused, 'absent'):
                self.authority.consume(200, minted['nonce'], self.envelope)


if __name__ == '__main__':
    unittest.main()

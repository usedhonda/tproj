#!/usr/bin/env python3
"""No live SSH; command and registered process binding only."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tproj-peer-forward'
loader = importlib.machinery.SourceFileLoader('peer_forward', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
f = importlib.util.module_from_spec(spec)
loader.exec_module(f)


class ForwardTest(unittest.TestCase):
    def test_fixed_command_and_rejected_routes(self):
        command = f.ssh_command('host-a', '/private/remote.sock', '/private/source.sock')
        self.assertEqual(command[-3:], ['-R', '/private/remote.sock:/private/source.sock', 'host-a'])
        for flag in ('ExitOnForwardFailure=yes', 'StrictHostKeyChecking=yes',
                     'ControlMaster=no', 'StreamLocalBindMask=0177'):
            self.assertIn(flag, command)
        for values in (('-bad', '/r.sock', '/s.sock'), ('host', 'relative', '/s.sock'),
                       ('host', '/r:bad', '/s.sock')):
            with self.assertRaises(f.a.Refused):
                f.ssh_command(*values)

    def test_pid_start_must_remain_registered(self):
        class Process:
            pid = 100
            def poll(self):
                return None
        with patch.object(f.a, 'process', return_value=(1, 200, 501)), patch.object(f.os, 'getuid', return_value=501):
            f.live_forward(Process(), 200)
            with self.assertRaisesRegex(f.a.Refused, 'changed'):
                f.live_forward(Process(), 199)
        class Exited(Process):
            def poll(self):
                return 1
        with self.assertRaisesRegex(f.a.Refused, 'exited'):
            f.live_forward(Exited(), 200)


if __name__ == '__main__':
    unittest.main()

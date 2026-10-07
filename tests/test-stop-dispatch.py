#!/usr/bin/env python3
"""Exercise shutdown dispatch without connecting to a real tmux server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShutdownDispatchTests(unittest.TestCase):
    def test_shutdown_reads_sessions_before_reporting_no_session(self):
        for action in ('stop', 'kill'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                log = base / 'tmux.log'
                stub = base / 'tmux'
                stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TMUX_TEST_LOG"\nexit 1\n')
                stub.chmod(0o755)
                env = dict(os.environ, PATH=f'{base}:/usr/bin:/bin',
                           HOME=tmp, TMUX_TEST_LOG=str(log))
                env.pop('TMUX', None)
                result = subprocess.run([str(ROOT / 'bin/tproj'), action],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('No active tproj session', result.stderr)
                self.assertEqual(log.read_text().strip(),
                                 'list-sessions -F #{session_name}:#{@tproj}')


if __name__ == '__main__':
    unittest.main()

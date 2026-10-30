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


class StopOwnershipTest(unittest.TestCase):
    def test_cli_stop_only_sends_keys_to_local_agents(self):
        source = (ROOT / 'bin/tproj').read_text()
        stop = source[source.index('stop_session() {'):source.index('# Shell functions')]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'commands'
            script = Path(tmp) / 'stop.sh'
            script.write_text('''set -eu
source "$COMMON"
find_tproj_sessions() { echo fixture; }
collect_session_descendants() { :; }
kill_surviving_descendants() { :; }
cleanup_orphaned_mcp() { :; }
stop_tproj_gui_if_needed() { :; }
sleep() { :; }
pkill() { :; }
rm() { :; }
tmux() {
  printf '%s\\n' "$*" >> "$COMMAND_LOG"
  case "$1" in
    list-panes) printf '%%1:claude-p0:\\n%%2:codex-p0:\\n%%3:claude-p1:fixture-host\\n%%4:codex-p1:fixture-host\\n' ;;
    has-session) return 1 ;;
  esac
}
''' + stop + '\nstop_session\n')
            env = dict(os.environ, COMMON=str(ROOT / 'bin/lib/tproj-common.sh'), COMMAND_LOG=str(log))
            subprocess.run(['bash', str(script)], env=env, check=True, capture_output=True, text=True, timeout=10)
            commands = log.read_text().splitlines()
            sent = [line for line in commands if line.startswith('send-keys')]
            self.assertEqual(sent, [
                'send-keys -t %1 C-c', 'send-keys -t %2 C-c',
                'send-keys -t %1 exit C-m', 'send-keys -t %2 /exit C-m',
            ])
            self.assertIn('kill-session -t fixture', commands)

    def test_gui_filters_remote_attachments_before_both_key_passes(self):
        source = (ROOT / 'apps/tproj/Sources/TprojApp/TprojApp.swift').read_text()
        stop = source[source.index('    func stopSession() async {'):source.index('    private func killSession()')]
        self.assertIn('#{pane_id}:#{@role}:#{@remote_host}', stop)
        self.assertIn('guard parts.count == 3, parts[2].isEmpty else { return nil }', stop)
        self.assertEqual(stop.count('for pane in paneRoles {'), 2)
        self.assertNotIn('"tproj-remote-client"', stop)


if __name__ == '__main__':
    unittest.main()

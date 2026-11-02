#!/usr/bin/env python3
"""Exercise shutdown dispatch without connecting to a real tmux server."""
import os
from pathlib import Path
import subprocess
import tempfile
import shlex
import shutil
import time
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


class RemoteRespawnTests(unittest.TestCase):
    def test_remote_pane_death_does_not_reap_or_respawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); log = base/'calls'; stub = base/'tmux'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\ncase "$*" in *"@remote_host"*) echo fixture-host;; *) exit 77;; esac\n')
            stub.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT/'bin/tproj-respawn-guard'), 'fixture', '%1', 'codex-p1'],
                env=dict(os.environ, PATH=str(base)+':/usr/bin:/bin', CALLS=str(log)), capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log.read_text().splitlines(), ["display-message -t %1 -p #{@remote_host}"])


@unittest.skipUnless(shutil.which('tmux'), 'tmux required')
class RemoteCloseBoundaryTest(unittest.TestCase):
    def test_real_attachment_close_preserves_remote_pid_and_allows_reattach(self):
        for action in ('pane', 'column', 'server'):
            with self.subTest(action=action), tempfile.TemporaryDirectory(prefix='tproj-close-') as tmp:
                base = Path(tmp); local = str(base/'local'); remote = str(base/'remote')
                binary = shutil.which('tmux')
                env = dict(os.environ); env.pop('TMUX', None)
                def tm(socket, *args, check=True):
                    return subprocess.run([binary, '-S', socket, *args], env=env,
                                          capture_output=True, text=True, check=check)
                try:
                    tm(remote, 'new-session', '-d', '-s', 'kept', 'sleep 120')
                    before = tm(remote, 'display-message', '-p', '-t', 'kept', '#{pane_pid}').stdout.strip()
                    tm(local, 'new-session', '-d', '-s', 'fixture', '-n', 'dev', 'sleep 120')
                    command = shlex.join(['env', '-u', 'TMUX', binary, '-S', remote, 'attach-session', '-t', 'kept'])
                    pane = tm(local, 'split-window', '-h', '-t', 'fixture:dev', '-P', '-F', '#{pane_id}', command).stdout.strip()
                    tm(local, 'set-option', '-pt', pane, '@role', 'codex-p1')
                    tm(local, 'set-option', '-pt', pane, '@remote_host', 'fixture-host')
                    deadline = time.monotonic() + 5
                    while tm(remote, 'display-message', '-p', '-t', 'kept', '#{session_attached}').stdout.strip() == '0':
                        self.assertLess(time.monotonic(), deadline, 'attachment did not become ready')
                        time.sleep(.05)
                    shim = base/'tmux'
                    shim.write_text('#!/bin/sh\nexec '+shlex.join([binary, '-S', local])+' "$@"\n')
                    shim.chmod(0o755)
                    if action == 'server':
                        tm(local, 'kill-server')
                    else:
                        argv = ([str(ROOT/'bin/tproj-kill-pane'), pane, 'codex-p1'] if action == 'pane' else
                                [str(ROOT/'bin/tproj-drop-column'), '--grace-ms', '1', '--max-ms', '1', 'fixture', '1'])
                        result = subprocess.run(argv, env=dict(env, PATH=str(base)+':/usr/bin:/bin'),
                                                capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                    after = tm(remote, 'display-message', '-p', '-t', 'kept', '#{pane_pid}').stdout.strip()
                    self.assertEqual(before, after)
                    os.kill(int(after), 0)
                    deadline = time.monotonic() + 5
                    while tm(remote, 'display-message', '-p', '-t', 'kept', '#{session_attached}').stdout.strip() != '0':
                        self.assertLess(time.monotonic(), deadline, 'old attachment did not detach')
                        time.sleep(.05)
                    tm(local, 'new-session', '-d', '-s', 'reconnected', command)
                    while tm(remote, 'display-message', '-p', '-t', 'kept', '#{session_attached}').stdout.strip() == '0':
                        self.assertLess(time.monotonic(), deadline, 'new client could not reattach')
                        time.sleep(.05)
                    self.assertEqual(before, tm(remote, 'display-message', '-p', '-t', 'kept', '#{pane_pid}').stdout.strip())
                finally:
                    tm(local, 'kill-server', check=False)
                    tm(remote, 'kill-server', check=False)


if __name__ == '__main__':
    unittest.main()

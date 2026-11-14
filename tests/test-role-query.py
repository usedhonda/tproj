import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'bin/tproj-role-query'


class RoleQueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.router = self.root / 'router'
        self.router.write_text('''#!/usr/bin/env python3
import json,os,pathlib,subprocess,time
r=pathlib.Path(os.environ['HOME'])
with (r/'calls').open('a') as f:f.write('call\\n')
mode=(r/'fixture-mode').read_text()
if mode=='slow':time.sleep(20)
if mode=='child':
 p=subprocess.Popen(['/bin/sleep','20']);(r/'child-pid').write_text(str(p.pid))
if mode=='fail':raise SystemExit(75)
if mode=='invalid':print('{}');raise SystemExit(0)
print(json.dumps({'mode':'solo','main':'cc'}))
''')
        self.router.chmod(0o755)
        self.mode('normal')
        self.env = dict(os.environ, HOME=str(self.root))
        self.command = [sys.executable, str(HELPER), '--router', str(self.router), '--project', '/fixture/project']

    def mode(self, value):
        (self.root / 'fixture-mode').write_text(value)

    def run_query(self, *args):
        return subprocess.run(self.command + list(args), env=self.env, capture_output=True, text=True, timeout=7)

    def expire(self):
        path = next((self.root / '.cache/tproj-role-query').glob('*.json'))
        value = json.loads(path.read_text()); value['at'] -= 31
        path.write_text(json.dumps(value))

    def test_timeout_single_flight_backoff_and_recovery(self):
        self.mode('slow')
        first = subprocess.Popen(self.command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: first.kill() if first.poll() is None else None)
        deadline = time.monotonic() + 2
        while not (self.root / 'calls').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        busy = self.run_query()
        self.assertEqual(busy.returncode, 75)
        self.assertIn('already running', busy.stderr)
        first.communicate(timeout=6)
        self.assertEqual(first.returncode, 75)
        self.mode('normal')
        self.assertEqual(self.run_query().returncode, 75)
        self.assertEqual((self.root / 'calls').read_text().count('call'), 1)
        self.expire()
        self.assertEqual(self.run_query().returncode, 0)

    def test_parent_exit_reaps_owned_descendant(self):
        self.mode('child')
        started = time.monotonic()
        result = self.run_query()
        self.assertEqual(result.returncode, 75)
        self.assertLess(time.monotonic() - started, 5.5)
        self.assertEqual(result.stdout, '')
        pid = int((self.root / 'child-pid').read_text())
        try:
            observed = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
            self.assertTrue(observed.returncode != 0 or observed.stdout.strip().startswith('Z'), observed.stdout)
        finally:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass

    def test_invalid_old_success_cache_is_revalidated(self):
        self.assertEqual(self.run_query().returncode, 0)
        path = next((self.root / '.cache/tproj-role-query').glob('*.json'))
        value = json.loads(path.read_text()); value['stdout'] = '{}'
        path.write_text(json.dumps(value))
        self.mode('invalid')
        self.assertEqual(self.run_query().returncode, 75)

    def test_empty_response_is_not_success(self):
        self.mode('invalid')
        self.assertEqual(self.run_query().returncode, 75)

    def test_failure_preserves_success_but_never_returns_fresh_success(self):
        good = self.run_query()
        self.assertEqual(good.returncode, 0)
        self.mode('fail'); self.expire()
        bad = self.run_query()
        self.assertEqual(bad.returncode, 75)
        self.assertEqual(bad.stdout, '')
        cached = self.run_query('--display-cache')
        self.assertEqual(cached.returncode, 75)
        self.assertEqual(cached.stdout, good.stdout)
        path = next((self.root / '.cache/tproj-role-query').glob('*.json'))
        self.assertEqual(json.loads(path.read_text())['last_success']['stdout'], good.stdout)


if __name__ == '__main__':
    unittest.main()

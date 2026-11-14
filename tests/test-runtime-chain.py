#!/usr/bin/env python3
"""Prove drift is rejected even when a staged seed marker claims it is current."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeChainTests(unittest.TestCase):
    def test_server_wrapper_verifies_bundle_without_client_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wrapper = base / 'dev-app.sh'
            shutil.copy2(ROOT / 'apps/tproj/dev-app.sh', wrapper)
            build = base / 'build-app.sh'
            build.write_text('#!/bin/bash\nexit 0\n'); build.chmod(0o755)
            executable = base / 'dist/release-app/tproj.app/Contents/MacOS/tproj'
            executable.parent.mkdir(parents=True)
            executable.write_text('#!/bin/sh\nexec /bin/sleep 20\n'); executable.chmod(0o755)
            (base / 'verify-runtime.py').write_text(
                'import sys\nassert len(sys.argv)==2, "server must not require unused client staging"\n')
            pidfile = base / 'pid'
            try:
                result = subprocess.run(['bash', str(wrapper), '--server'], capture_output=True,
                    text=True, timeout=5, env=dict(os.environ, TPROJ_GUI_PIDFILE=str(pidfile),
                                                 TPROJ_GUI_LOG=str(base / 'log')))
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()), signal.SIGTERM)
                    except ProcessLookupError: pass

    def test_source_bundle_and_actual_staged_bytes_must_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); app = base/'app'; resources = app/'Contents/Resources'
            resources.mkdir(parents=True); staged = base/'staged'; (staged/'bin').mkdir(parents=True)
            names = ['tproj', 'tproj-role-query', 'tproj-remote-client', 'tproj-remote-host', 'tproj-respawn-guard', 'tproj-kill-pane', 'tproj-drop-column']
            seed = resources/'tproj-runtime-seed.tar.gz'
            with tarfile.open(seed, 'w:gz') as archive:
                for name in names:
                    archive.add(ROOT/'bin'/name, arcname='tproj-runtime/bin/'+name)
                    (staged/'bin'/name).write_bytes((ROOT/'bin'/name).read_bytes())
            hashes = {'bin/'+n: hashlib.sha256((ROOT/'bin'/n).read_bytes()).hexdigest() for n in names}
            (resources/'tproj-runtime-critical.json').write_text(json.dumps(hashes))
            (staged/'.seed-sha256').write_text(hashlib.sha256(seed.read_bytes()).hexdigest())
            command = [sys.executable, str(ROOT/'apps/tproj/verify-runtime.py'), str(app), str(staged)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (staged/'bin/tproj-drop-column').write_text('stale helper')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Staged runtime mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()

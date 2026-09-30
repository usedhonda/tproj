#!/usr/bin/env python3
"""Exercise startup command generation without updating real agent installs."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/tproj').read_text()


class CodexStartupUpdate(unittest.TestCase):
    def test_default_update_failure_and_explicit_skip(self):
        defaults = '\n'.join(re.findall(r'^(?:NO_UPDATE|CODEX_NO_UPDATE)=.*$', SOURCE, re.M))
        helper = re.search(r'^with_codex_update_prefix\(\) \{.*?^\}', SOURCE, re.M | re.S).group()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {
                'npm': 'echo update >> "$TRACE"; exit "${UPDATE_RC:-0}"',
                'sign-codex': 'echo sign >> "$TRACE"',
                'codex': 'echo "launch $*" >> "$TRACE"',
            }.items():
                script = root / name
                script.write_text('#!/bin/sh\n' + body + '\n')
                script.chmod(0o755)
            for fail_update, skip, expected in [
                (0, False, ['update', 'sign', 'launch resume --last']),
                (1, False, ['update', 'sign', 'launch resume --last']),
                (0, True, ['launch resume --last']),
            ]:
                trace = root / 'trace'
                trace.write_text('')
                # Evaluate the real --no-update argument branch when requested.
                option = re.search(r'^\s*-n\|--no-update\) (.*?) ;;', SOURCE, re.M).group(1)
                setup = 'set -- --no-update\n' + option if skip else ''
                program = defaults + '\n' + setup + '\nquoted_runtime_bin_path() { return 0; }\n' + helper
                program += '\neval "$(with_codex_update_prefix \'codex resume --last\')"\n'
                env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], TRACE=str(trace), UPDATE_RC=str(fail_update))
                result = subprocess.run(['bash', '-c', program], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(trace.read_text().splitlines(), expected)


if __name__ == '__main__':
    unittest.main()

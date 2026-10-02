#!/usr/bin/env python3
"""Exercise startup command generation without updating real agent installs."""
import os
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/tproj').read_text()


class CodexStartupUpdate(unittest.TestCase):
    def test_gui_generated_update_uses_helper_and_fails_open(self):
        gui = (ROOT / 'apps/tproj/Sources/TprojApp/TprojApp.swift').read_text()
        template = re.search(r'launchCmd = ("if \[ -x .*?\")$', gui, re.M).group(1)
        resume = re.search(r'let codexResume = (".*?\")$', gui, re.M).group(1)
        with tempfile.TemporaryDirectory(prefix="tproj gui '") as directory:
            root = Path(directory)
            project = root / "project ' space"
            project.mkdir()
            trace = root / 'trace'
            updater = root / 'tproj-cli-update'
            sign = root / 'sign-codex'
            for name, body in {
                'npm': 'echo unlocked-npm >> "$TRACE"; exit 99',
                'codex': 'printf "launch %s %s\\n" "$PWD" "$*" >> "$TRACE"',
            }.items():
                script = root / name
                script.write_text('#!/bin/sh\n' + body + '\n')
                script.chmod(0o755)
            resume_command = json.loads(resume.replace(
                r'\(shellSingleQuote(projPath))', '{project}')).replace(
                '{project}', shlex.quote(str(project)))
            command = json.loads(template.replace(
                r'\(codexUpdater)', '{updater}').replace(
                r'\(codexResume)', '{resume}')).replace(
                '{updater}', shlex.quote(str(updater))).replace('{resume}', resume_command)
            for present, signing, rc in [(True, True, 0), (True, False, 1), (False, True, 0)]:
                with self.subTest(present=present, signing=signing, rc=rc):
                    trace.write_text('')
                    updater.write_text('#!/bin/sh\n'
                                       'printf "helper %s %s\\n" "$1" "${2:-}" >> "$TRACE"\n'
                                       'if [ "$#" = 2 ]; then "$2"; fi\n'
                                       'exit "${UPDATE_RC:-0}"\n')
                    updater.chmod(0o755 if present else 0o644)
                    sign.write_text('#!/bin/sh\necho sign >> "$TRACE"\n')
                    if signing:
                        sign.chmod(0o755)
                    else:
                        sign.unlink()
                    result = subprocess.run(['bash', '-c', command], env=dict(
                        os.environ, PATH=str(root) + ':/usr/bin:/bin',
                        TRACE=str(trace), UPDATE_RC=str(rc)),
                        capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = []
                    if present:
                        expected.append('helper @openai/codex ' + (str(sign) if signing else ''))
                        if signing:
                            expected.append('sign')
                    expected.append(f'launch {project} resume --last -s danger-full-access -a never --search')
                    self.assertEqual(trace.read_text().splitlines(), expected)
                    if not present:
                        self.assertIn('updater missing; using installed agent', result.stderr)

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
                env = dict(os.environ, PATH=str(root) + ':' + str(ROOT / 'bin') + ':' + os.environ['PATH'], TRACE=str(trace), UPDATE_RC=str(fail_update))
                result = subprocess.run(['bash', '-c', program], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(trace.read_text().splitlines(), expected)

    def test_remote_generated_update_failure_still_launches(self):
        remote = (ROOT / 'bin/tproj-remote-host').read_text()
        helper = re.search(r'^start_command\(\) \{.*?^\}', remote, re.M | re.S).group()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace'
            for name, body in {
                'npm': 'echo update >> "$TRACE"; exit 1',
                'sign-codex': 'echo sign >> "$TRACE"',
                'codex': 'echo "launch $*" >> "$TRACE"',
            }.items():
                script = root / name
                script.write_text('#!/bin/sh\n' + body + '\n')
                script.chmod(0o755)
            program = ('resolve_cli() { command -v "$1"; }\n'
                       'cli_for_role() { echo codex; }\n'
                       'die() { exit 1; }\n' + helper + '\neval "$(start_command cdx)"\n')
            script = root / 'remote-launch.sh'
            script.write_text(program)
            result = subprocess.run(['bash', str(script)], env=dict(
                os.environ, PATH=str(root) + ':' + str(ROOT / 'bin') + ':' + os.environ['PATH'],
                TRACE=str(trace)), capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(trace.read_text().splitlines(),
                             ['update', 'sign', 'launch resume --last'])

    def test_npm_keeps_lock_after_helper_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace'
            release = root / 'release'
            waiting = root / 'waiting'
            npm = root / 'npm'
            npm.write_text('#!/usr/bin/env python3\n'
                           'import os, pathlib, sys, time\n'
                           'trace = pathlib.Path(os.environ["TRACE"])\n'
                           'with trace.open("a") as f: f.write("start " + sys.argv[3] + "\\n")\n'
                           'if sys.argv[3] == "@openai/codex":\n'
                           '    pathlib.Path(os.environ["WAITING"]).touch()\n'
                           '    deadline = time.monotonic() + 5\n'
                           '    while not pathlib.Path(os.environ["RELEASE"]).exists():\n'
                           '        if time.monotonic() > deadline: sys.exit(2)\n'
                           '        time.sleep(0.01)\n'
                           'with trace.open("a") as f: f.write("end " + sys.argv[3] + "\\n")\n')
            npm.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       TRACE=str(trace), RELEASE=str(release), WAITING=str(waiting))
            helper = str(ROOT / 'bin/tproj-cli-update')
            first = subprocess.Popen([helper, '@openai/codex'], env=env)
            second = None
            try:
                deadline = time.monotonic() + 5
                while not waiting.exists():
                    self.assertIsNone(first.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                first.terminate()  # Only the synthetic helper; its npm stays alive.
                first.wait(timeout=5)
                second = subprocess.Popen([helper, '@anthropic-ai/claude-code'], env=env)
                time.sleep(0.2)
                self.assertIsNone(second.poll())
                self.assertEqual(trace.read_text().splitlines(), ['start @openai/codex'])
                release.touch()
                self.assertEqual(second.wait(timeout=5), 0)
                self.assertEqual(trace.read_text().splitlines(), [
                    'start @openai/codex', 'end @openai/codex',
                    'start @anthropic-ai/claude-code', 'end @anthropic-ai/claude-code'])
            finally:
                release.touch()
                if first.poll() is None:
                    first.terminate()
                    first.wait()
                if second is not None and second.poll() is None:
                    second.terminate()
                    second.wait()

    def test_concurrent_packages_hold_lock_through_sign_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace'
            npm = root / 'npm'
            npm.write_text('#!/bin/sh\necho "start $3" >> "$TRACE"\n'
                           'touch "$READY"\nsleep 0.2\n'
                           'echo "end $3" >> "$TRACE"\nexit 1\n')
            sign = root / 'sign-codex'
            sign.write_text('#!/bin/sh\necho sign-start >> "$TRACE"\nsleep 0.2\n'
                            'echo sign-end >> "$TRACE"\n')
            npm.chmod(0o755)
            sign.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       TRACE=str(trace), READY=str(root / 'ready'))
            helper = str(ROOT / 'bin/tproj-cli-update')
            first = subprocess.Popen([helper, '@openai/codex', str(sign)], env=env)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists():
                    self.assertIsNone(first.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                # Different TMPDIR must not create a second lock namespace.
                second = subprocess.Popen([helper, '@anthropic-ai/claude-code'],
                                          env=dict(env, TMPDIR=str(root)))
                try:
                    self.assertEqual(first.wait(timeout=5), 1)
                    self.assertEqual(second.wait(timeout=5), 1)
                finally:
                    if second.poll() is None:
                        second.kill()
                        second.wait()
            finally:
                if first.poll() is None:
                    first.kill()
                    first.wait()
            self.assertEqual(trace.read_text().splitlines(), [
                'start @openai/codex', 'end @openai/codex', 'sign-start', 'sign-end',
                'start @anthropic-ai/claude-code', 'end @anthropic-ai/claude-code'])


if __name__ == '__main__':
    unittest.main()

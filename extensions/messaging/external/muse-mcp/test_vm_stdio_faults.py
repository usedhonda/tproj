"""Real SDK/subprocess fault test; no live SSH, credentials or service changes.

Run with the pinned SDK environment. Ordinary dependency-free CI skips this
integration test, rather than substituting a mocked invoke() for transport proof.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SERVER = r'''
import json, os, sys
from pathlib import Path
root = Path(__file__).parent
(root / ('pid-' + str(os.getpid()))).write_text(str(os.getpid()))
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    rid = request.get('id')
    if rid is None:
        continue
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'],
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'fault-fixture', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'inputSchema': {'type': 'object'}}
                            for name in ['tproj_send', 'tproj_message']]}
        schema = root / 'message-schema.json'
        if schema.exists():
            result['tools'][1]['outputSchema'] = json.loads(schema.read_text())
    elif method == 'tools/call':
        params = request['params']; args = params['arguments']
        if params['name'] == 'tproj_send':
            # Simulate durable acceptance followed by a lost response. A second
            # invocation would append another line, making replay observable.
            with (root / 'accepted.jsonl').open('a') as out:
                out.write(json.dumps(args) + '\n')
                out.flush(); os.fsync(out.fileno())
            continue
        if params['name'] != 'tproj_message':
            raise RuntimeError('unexpected tool')
        accepted = [json.loads(x) for x in (root / 'accepted.jsonl').read_text().splitlines()]
        rows = [x for x in accepted if x['submission_id'] == args['message_id']]
        state = root / 'message-state'
        value = {'message_id': args['message_id'], 'thread_id': args['message_id'],
                 'target': 'muse', 'state': state.read_text() if state.exists() else 'accepted',
                 'body': rows[0]['body'], 'acceptance_count': len(rows)}
        if (root / 'message-schema.json').exists():
            value.pop('acceptance_count')
        result = {'content': [{'type': 'text', 'text': json.dumps(value)}],
                  'structuredContent': value, 'isError': False}
    else:
        raise RuntimeError('unexpected method: ' + str(method))
    print(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': result}), flush=True)
'''


@unittest.skipUnless(sys.version_info >= (3, 11) and importlib.util.find_spec('mcp'),
                     'requires Python 3.11+ and pinned official mcp SDK')
class StdioFaultTests(unittest.TestCase):
    def test_already_dispatching_message_can_be_read_with_published_schema(self):
        client = Path(__file__).with_name('vm_client.py')
        catalog = json.loads(client.parent.parent.joinpath('kai-mcp/external-assistant-tools.json').read_text())
        schema = next(t['outputSchema'] for t in catalog['tools'] if t['name'] == 'tproj_message')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_ssh = root / 'ssh'
            fake_ssh.write_text('#!' + sys.executable + '\n' + SERVER)
            fake_ssh.chmod(0o700)
            profile = root / 'profile'; profile.write_text('Host tproj-msg-muse\n'); profile.chmod(0o600)
            config = root / 'client.json'
            config.write_text(json.dumps({'ssh_config': str(profile), 'ssh_host': 'tproj-msg-muse'})); config.chmod(0o600)
            (root / 'message-schema.json').write_text(json.dumps(schema))
            (root / 'message-state').write_text('dispatching')
            (root / 'accepted.jsonl').write_text(json.dumps({'submission_id': 'pinned-message', 'body': 'fixture'}) + '\n')
            args = root / 'args.json'; args.write_text(json.dumps({'message_id': 'pinned-message'}))
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get('PATH', ''),
                       HTTPS_PROXY='http://fixture.invalid:3128')
            result = subprocess.run([sys.executable, str(client), '--config', str(config),
                'call-tool', '--name', 'tproj_message', '--arguments-file', str(args)],
                env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['structuredContent']['state'], 'dispatching')

    def test_lost_ack_after_acceptance_is_unknown_bounded_and_read_back_without_replay(self):
        client = Path(__file__).with_name('vm_client.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Intercept only this subprocess's ssh executable, not any live
            # profile, proxy, key, port or installed connector.
            fake_ssh = root / 'ssh'
            fake_ssh.write_text('#!' + sys.executable + '\n' + SERVER)
            fake_ssh.chmod(0o700)
            profile = root / 'profile'; profile.write_text('Host tproj-msg-muse\n')
            profile.chmod(0o600)
            config = root / 'client.json'
            config.write_text(json.dumps({'ssh_config': str(profile), 'ssh_host': 'tproj-msg-muse'}))
            config.chmod(0o600)
            args = root / 'args.json'
            body = 'fixture accepted before response loss'
            args.write_text(json.dumps({'submission_id': 'stable-fixture', 'target': 'project.cdx', 'body': body}))
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get('PATH', ''),
                       HTTPS_PROXY='http://fixture.invalid:3128')
            command = [sys.executable, str(client), '--config', str(config), 'call-tool']
            started = time.monotonic()
            failed = subprocess.run(command + ['--name', 'tproj_send', '--arguments-file', str(args)],
                                    env=env, capture_output=True, text=True, timeout=25)
            elapsed = time.monotonic() - started
            self.assertEqual(failed.returncode, 1, failed.stderr)
            error = json.loads(failed.stdout)['error']
            self.assertEqual(error['outcome'], 'unknown')
            self.assertEqual(error['submission_id'], 'stable-fixture')
            self.assertFalse(error['replayed'])
            self.assertLess(elapsed, 25)
            self.assertEqual(len((root / 'accepted.jsonl').read_text().splitlines()), 1)
            for pidfile in root.glob('pid-*'):
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pidfile.read_text()), 0)
            args.write_text(json.dumps({'message_id': 'stable-fixture'}))
            recovered = subprocess.run(command + ['--name', 'tproj_message', '--arguments-file', str(args)],
                                       env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            actual = json.loads(recovered.stdout)['structuredContent']
            self.assertEqual(actual['body'], body)
            self.assertEqual(actual['state'], 'accepted')
            self.assertEqual(actual['acceptance_count'], 1)
            self.assertEqual(len(list(root.glob('pid-*'))), 2)


if __name__ == '__main__':
    unittest.main()

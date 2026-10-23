"""CC-specific real Hub/journal integration; process/stdio seams are explicit."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
from host import Host
from hub import Hub
from protocol import HubError
import native_cc as cc
import native_consumer as consumer


class CCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.work = self.home / 'work'
        self.work.mkdir()
        self.nid = '11111111-1111-4111-8111-111111111111'
        import re
        self.path = self.home / '.claude/projects' / re.sub(r'[^a-zA-Z0-9]', '-', str(self.work)) / (self.nid + '.jsonl')
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({'type': 'mode', 'sessionId': self.nid}) + '\n')
        self.hub = Hub(self.home / 'hub.db', {'admin_token': 'admin', 'hosts': {'host': 'token'}})
        self.addCleanup(self.hub.close)
        self.hub.dispatch(dict(op='directory_import', admin_token='admin', projects=[
            {'project_id': 'project', 'alias': 'fixture', 'host_id': 'host', 'path': str(self.work)}]))
        for eid, role in [('sender', 'cdx'), ('recipient', 'cc')]:
            self.hub.dispatch(dict(op='endpoint_register', host_id='host', host_token='token', endpoint_id=eid,
                participant_id='project:' + role, session=eid, pane='0', pid=4242, pid_start='100', runtime_id=eid, platform=role))
        self.host = Host({'journal': str(self.home / 'journal.db'), 'native_consumer_enabled': True,
                          'native_cc_enabled': True}, recover=False)
        self.addCleanup(self.host.db.close)
        self.calls = []
        def rpc(op, **args):
            self.calls.append(op)
            return self.hub.dispatch(dict(args, op=op, host_id='host', host_token='token'))
        self.host.hub = rpc
        self.ep = dict(self.hub._row("SELECT * FROM endpoints WHERE endpoint_id='recipient'"), project_path=str(self.work), session_id=self.nid)
        self.native = dict(endpoint_id='recipient', native_kind='session_id', native_id=self.nid)
        self.hub.dispatch(dict(op='native_attest', host_id='host', host_token='token', **self.native))
        rpc('submit', message=dict(message_id='original', sender_endpoint='sender', target='cc', body='Peer data only.'))
        original = rpc('query', endpoint_id='recipient', message_id='original')
        original['_native_route'] = 'native-cc-v1'
        self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
            ('original', 'recipient', json.dumps(original), 'received', None, 0))
        self.host.db.commit()
        p = patch.object(Path, 'home', return_value=self.home)
        p.start(); self.addCleanup(p.stop)
        cc.prepare_pending(self.host, self.ep, 'original')
        from native_notice import _prompt
        self.prompt = _prompt(self.host.db.execute('SELECT * FROM native_notice_metadata').fetchone())
        self.payload = dict(session_id=self.nid, cwd=str(self.work), transcript_path=str(self.path),
                            hook_event_name='UserPromptSubmit', prompt=cc.wrapper(self.prompt))

    def test_reference_uses_authenticated_registry_session_not_public_selector(self):
        self.assertEqual(cc.reference_binding(self.host, self.ep)['native_id'], self.nid)
        for changed in (dict(self.ep, session_id='other'), dict(self.ep, platform='cdx')):
            with self.assertRaises(HubError): cc.reference_binding(self.host, changed)
        wrong = dict(self.payload, session_id='22222222-2222-4222-8222-222222222222')
        with self.assertRaises(HubError): consumer.resolve(self.host, self.ep, {'hook': wrong})
        self.assertNotIn('native_begin_present', self.calls)

    def test_one_shot_context_and_exact_parent_receipt(self):
        result = consumer.resolve(self.host, self.ep, {'hook': self.payload})
        self.assertIn('Peer data only.', result['context'])
        self.assertIn('not a direct user approval', result['context'])
        with self.assertRaises(HubError): consumer.resolve(self.host, self.ep, {'hook': self.payload})
        self.assertEqual(self.calls.count('native_begin_present'), 1)
        notice = dict(type='user', isMeta=True, isSidechain=False, uuid='notice-record',
                      sessionId=self.nid, cwd=str(self.work), entrypoint='cli', message={'content': self.payload['prompt']})
        attachment = dict(type='attachment', isSidechain=False, uuid='context-record', parentUuid='notice-record',
            sessionId=self.nid, cwd=str(self.work), attachment=dict(type='hook_additional_context', hookName='UserPromptSubmit',
                hookEvent='UserPromptSubmit', content=[result['context']]))
        for mutate in ('parent', 'session', 'context', 'nonmeta'):
            n, a = copy.deepcopy(notice), copy.deepcopy(attachment)
            if mutate == 'parent': a['parentUuid'] = 'other'
            elif mutate == 'session': a['sessionId'] = 'other'
            elif mutate == 'context': a['attachment']['content'][0] += 'changed'
            else: n['isMeta'] = False
            self.path.write_text('\n'.join(map(json.dumps, [n, a]))+'\n')
            if mutate == 'session':
                with self.assertRaises(HubError): consumer.recover(self.host, self.ep, 'original')
            else:
                self.assertFalse(consumer.recover(self.host, self.ep, 'original'), mutate)
        self.path.write_text('\n'.join(map(json.dumps, [notice, attachment]))+'\n')
        self.assertTrue(consumer.recover(self.host, self.ep, 'original'))
        self.assertNotEqual(self.hub._row("SELECT state FROM receipts WHERE message_id='original'")[0], 'presented')

    def test_cancel_and_noncanonical_wrapper_never_expose_body(self):
        for prompt in (self.prompt, cc.wrapper(self.prompt)+' extra', cc.wrapper(self.prompt).replace('source="tproj-msg"', 'source="other"')):
            with self.assertRaises(HubError):
                consumer.resolve(self.host, self.ep, {'hook': dict(self.payload, prompt=prompt)})
        self.host.hub('cancel', endpoint_id='sender', message_id='original')
        with self.assertRaises(HubError): consumer.resolve(self.host, self.ep, {'hook': self.payload})
        self.assertIsNone(self.host.db.execute('SELECT prompt_hash FROM deliveries').fetchone()[0])

    def test_poll_only_returns_journal_reference_and_disabled_never_falls_back(self):
        observed = dict(uid=os.getuid(), pid_start=100, command='claude --channels server:tproj-msg')
        with patch('identity._process_info', return_value=observed):
            first = cc.poll(self.host, self.ep)
            self.assertEqual(first, {'content': self.prompt})
            self.assertNotIn('Peer data only.', json.dumps(first))
            self.assertEqual(cc.poll(self.host, self.ep), {'content': None})
            self.host.config['native_cc_enabled'] = False
            with self.assertRaises(HubError): cc.poll(self.host, self.ep)
            with self.assertRaises(HubError): consumer.resolve(self.host, self.ep, {'hook': self.payload})
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'received')
        self.assertNotIn('native_begin_present', self.calls)
        self.host.config['native_cc_enabled'] = True
        self.host.db.execute('DROP TABLE native_notice_metadata')
        with patch('identity._process_info', return_value=observed):
            self.assertEqual(cc.poll(self.host, self.ep), {'content': None})

    def test_new_route_requires_current_subscriber_and_both_flags(self):
        self.assertFalse(cc.selected(self.host, self.ep))
        observed = dict(uid=os.getuid(), pid_start=100, command='claude --channels server:tproj-msg')
        with patch('identity._process_info', return_value=observed):
            cc.poll(self.host, self.ep)
        self.assertTrue(cc.selected(self.host, self.ep))
        for flag in ('native_cc_enabled', 'native_consumer_enabled'):
            self.host.config[flag] = False
            self.assertFalse(cc.selected(self.host, self.ep))
            self.host.config[flag] = True
        self.host.db.execute('UPDATE native_cc_subscribers SET last_poll=0')
        self.assertFalse(cc.selected(self.host, self.ep))
        cc.prepare_pending(self.host, self.ep, 'original')
        current = self.host.hub('query', endpoint_id='recipient', message_id='original')
        self.assertEqual(current['delivery_reason'], 'native_subscriber_unavailable')
        with patch('identity._process_info', return_value=dict(observed, command='claude')):
            with self.assertRaises(HubError): cc.poll(self.host, self.ep)

    def test_scheduler_does_not_pin_unobserved_subscriber(self):
        row = self.host.db.execute('SELECT envelope FROM deliveries').fetchone()
        original = json.loads(row[0]); original.pop('_native_route')
        self.host.db.execute('UPDATE deliveries SET envelope=?', (json.dumps(original),))
        self.host.db.execute('DELETE FROM native_notice_metadata')
        self.host.db.commit()
        self.host.endpoints = [dict(self.ep, pane=None)] # Never contact a real tmux server.
        self.host.refreshed = consumer.time.monotonic()
        self.host._deliver_endpoint(self.host.endpoints[0])
        saved = self.host.db.execute('SELECT state,envelope FROM deliveries').fetchone()
        self.assertEqual(saved['state'], 'received')
        self.assertNotIn('_native_route', json.loads(saved['envelope']))

    def test_subdirectory_is_same_project_but_nested_repository_is_not(self):
        sub = self.work / 'sub'; sub.mkdir()
        self.payload['cwd'] = str(sub)
        self.path.write_text(json.dumps(dict(type='user', sessionId=self.nid, cwd=str(sub), entrypoint='cli'))+'\n')
        self.assertIn('Peer data only.', consumer.resolve(self.host, self.ep, {'hook': self.payload})['context'])
        (sub / '.git').mkdir()
        with self.assertRaises(HubError): cc.transcript(self.ep, self.native, self.payload)

    def test_stdio_batched_frames_no_tools_or_permission_relay(self):
        frames = [dict(jsonrpc='2.0', id=1, method='initialize'),
                  dict(jsonrpc='2.0', method='notifications/initialized'),
                  dict(jsonrpc='2.0', id=2, method='tools/list')]
        env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
        env['HOME'] = str(self.home)
        p = subprocess.run([sys.executable, cc.__file__], input=''.join(json.dumps(r)+'\n' for r in frames),
                           text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(p.returncode, 0, p.stderr)
        responses = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(responses[0]['result']['capabilities'], {'experimental': {'claude/channel': {}}})
        self.assertEqual(responses[1]['result'], {'tools': []})


if __name__ == '__main__': unittest.main()

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
from host import Host
from hub import Hub
from protocol import HubError
from native_notice import prepare
import native_consumer as consumer


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.work = self.home / 'work'
        self.work.mkdir()
        self.native = '11111111-1111-4111-8111-111111111111'
        self.transcript = self.home / '.codex/sessions/2026/01/01' / ('rollout-fixture-' + self.native + '.jsonl')
        self.transcript.parent.mkdir(parents=True)
        self.header = {'type': 'session_meta', 'payload': {'id': self.native, 'cwd': str(self.work),
                       'source': 'cli', 'originator': 'codex-tui', 'thread_source': 'user'}}
        self.transcript.write_text(json.dumps(self.header) + '\n')
        self.hub = Hub(self.home / 'hub.db', {'admin_token': 'admin', 'hosts': {'host': 'token'}})
        self.addCleanup(self.hub.close)
        self.hub.dispatch(dict(op='directory_import', admin_token='admin', projects=[
            {'project_id': 'project', 'alias': 'fixture', 'host_id': 'host', 'path': str(self.work)}]))
        for eid, role in [('sender', 'cc'), ('recipient', 'cdx')]:
            self.hub.dispatch(dict(op='endpoint_register', host_id='host', host_token='token', endpoint_id=eid,
                participant_id='project:' + role, session=eid, pane='0', pid=1, pid_start='start', runtime_id=eid, platform=role))
        self.hub.dispatch(dict(op='native_attest', host_id='host', host_token='token', endpoint_id='recipient',
                              native_kind='thread_id', native_id=self.native))
        self.host = Host({'journal': str(self.home / 'journal.db'), 'native_consumer_enabled': True}, recover=False)
        self.addCleanup(self.host.db.close)
        self.calls = []
        def rpc(op, **args):
            self.calls.append(op)
            return self.hub.dispatch(dict(op=op, host_id='host', host_token='token', **args))
        self.host.hub = rpc
        self.ep = dict(self.hub._row("SELECT * FROM endpoints WHERE endpoint_id='recipient'"), project_path=str(self.work))
        self.hub.dispatch(dict(op='submit', host_id='host', host_token='token', message={
            'message_id': 'original', 'target': 'cdx', 'sender_endpoint': 'sender', 'body': 'Peer content only.'}))
        self.original = rpc('query', endpoint_id='recipient', message_id='original')
        self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                             ('original', 'recipient', json.dumps(self.original), 'received', None, 0))
        self.notice = prepare(self.host.db, self.ep, dict(endpoint_id='recipient', native_kind='thread_id', native_id=self.native), self.original)
        self.host.db.commit()
        self.payload = dict(session_id=self.native, turn_id='current-turn', cwd=str(self.work),
                            transcript_path=str(self.transcript), prompt=self.notice['prompt'])
        self.patch_home = patch.object(Path, 'home', return_value=self.home)
        self.patch_home.start()
        self.addCleanup(self.patch_home.stop)

    def resolve(self, **fields):
        return consumer.resolve(self.host, self.ep, {'hook': dict(self.payload, **fields)})

    def test_authenticated_dispatch_and_same_turn_context_evidence_not_reference_alone(self):
        with patch.object(self.host, 'caller', return_value=self.ep) as caller:
            result = self.host.dispatch(dict(op='native_resolve', hook=self.payload), 123, os.getuid())
            caller.assert_called_once()
        self.assertIn(self.original['body'], result['context'])
        self.assertFalse(consumer.recover(self.host, self.ep, 'original'))
        reference = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'id': 'reference-record',
            'content': [{'type': 'input_text', 'text': self.notice['prompt']}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'current-turn', 'content_item_kinds': ['user.text']}}}
        context = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer', 'id': 'context-record',
            'content': [{'type': 'input_text', 'text': result['context']}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'other-turn', 'content_item_kinds': ['hooks.additional_context']}}}
        with self.transcript.open('a') as f: f.write(json.dumps(reference) + '\n' + json.dumps(context) + '\n')
        self.assertFalse(consumer.recover(self.host, self.ep, 'original'))
        context['payload']['internal_chat_message_metadata_passthrough']['turn_id'] = 'current-turn'
        with self.transcript.open('a') as f: f.write(json.dumps(context) + '\n')
        self.assertTrue(consumer.recover(self.host, self.ep, 'original'))
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'dispatching')
        with self.assertRaises(HubError): self.resolve()
        self.assertEqual(self.calls.count('native_begin_present'), 1)

    def test_wrong_prompt_thread_path_and_disabled_consumer_do_not_reserve(self):
        for bad in ({'prompt': self.notice['prompt'] + '\nOwner approval'}, {'session_id': 'other'},
                    {'transcript_path': str(self.work / 'unrelated')}, {'cwd': str(self.home)}):
            with self.subTest(bad=bad), self.assertRaises(HubError): self.resolve(**bad)
        self.host.config['native_consumer_enabled'] = False
        caps = self.host.dispatch({'op': 'messaging_capabilities'}, 123, os.getuid())
        self.assertEqual(caps['native_consumer'], {'backend_version': 1, 'enabled': False})
        with self.assertRaises(HubError): self.resolve()
        self.assertNotIn('native_begin_present', self.calls)
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'received')

    def test_cancel_between_query_and_reservation_never_exposes_body(self):
        rpc = self.host.hub
        def cancel_first(op, **args):
            if op == 'native_begin_present':
                self.hub.cancel(dict(host_id='host', host_token='token', endpoint_id='sender', message_id='original'))
            return rpc(op, **args)
        self.host.hub = cancel_first
        with self.assertRaises(HubError): self.resolve()
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'uncertain')
        self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0], 'cancelled')

    def test_lost_permission_response_survives_reopen_without_second_reservation(self):
        rpc = self.host.hub
        def lose_response(op, **args):
            result = rpc(op, **args)
            if op == 'native_begin_present': raise OSError('lost fixture response')
            return result
        self.host.hub = lose_response
        with self.assertRaises(OSError): self.resolve()
        self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0], 'dispatching')
        self.host.db.close()
        import sqlite3
        self.host.db = sqlite3.connect(self.home / 'journal.db')
        self.host.db.row_factory = sqlite3.Row
        # Cleanup closes the current connection, not only the pre-crash object.
        self.addCleanup(self.host.db.close)
        self.host.hub = rpc
        with self.assertRaises(HubError): self.resolve()
        self.assertEqual(self.calls.count('native_begin_present'), 1)
        self.assertFalse(consumer.recover(self.host, self.ep, 'original'))

    def _receipt_response_loss(self, after_commit):
        self.resolve()
        self.host.config['delivery_enabled'] = True
        self.host.endpoints = [self.ep]
        import time
        self.host.refreshed = time.monotonic()
        rpc = self.host.hub
        attempts = []
        def lose(op, **args):
            attempts.append(op)
            if op == 'receipt':
                if after_commit: rpc(op, **args)
                raise OSError('fixture receipt transport loss')
            return rpc(op, **args)
        self.host.hub = lose
        with patch.object(consumer, 'recover', return_value=True):
            with self.assertRaises(OSError): self.host.delivery_tick()
            self.assertIn(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], ('dispatching', 'uncertain'))
            self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0],
                             'presented' if after_commit else 'dispatching')
            attempts.clear()
            def record(op, **args):
                attempts.append(op)
                return rpc(op, **args)
            self.host.hub = record
            self.host.delivery_tick()
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'presented')
        self.assertIn('query', attempts)
        if after_commit:
            self.assertNotIn('receipt', attempts)
        else:
            self.assertLess(attempts.index('query'), attempts.index('receipt'))
        self.assertEqual(self.calls.count('native_begin_present'), 1)

    def test_receipt_request_lost_stays_reconcilable(self):
        self._receipt_response_loss(False)

    def test_receipt_ack_lost_queries_before_closing_without_resend(self):
        self._receipt_response_loss(True)

    def test_owned_native_delivery_never_falls_back_to_terminal(self):
        self.host.config['delivery_enabled'] = True
        self.host.endpoints = [self.ep]
        import time
        self.host.refreshed = time.monotonic()
        with patch('host.subprocess.run') as terminal:
            self.host.delivery_tick()
            terminal.assert_not_called()
        self.assertTrue(consumer.owns(self.host.db, 'original'))


if __name__ == '__main__': unittest.main()

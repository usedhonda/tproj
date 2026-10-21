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
            return self.hub.dispatch(dict(args, op=op, host_id='host', host_token='token'))
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

    def transfer(self):
        old = dict(self.ep)
        self.hub.dispatch(dict(op='endpoint_register', host_id='host', host_token='token', endpoint_id='successor',
            participant_id='project:cdx', session='successor', pane='0', pid=2, pid_start='next-start', runtime_id='successor', platform='cdx'))
        self.hub.dispatch(dict(op='native_attest', host_id='host', host_token='token', endpoint_id='successor',
                              native_kind='thread_id', native_id=self.native))
        self.ep = dict(self.hub._row("SELECT * FROM endpoints WHERE endpoint_id='successor'"), project_path=str(self.work))
        proof = {k: old[k] for k in ('endpoint_id', 'incarnation', 'pid', 'pid_start')}
        proof['reason'] = 'pid_absent'  # Synthetic trusted-input fixture, not actual OS death proof.
        self.hub._handoff_native_delivery(dict(host_id='host', host_token='token', old_endpoint=old['endpoint_id'],
            new_endpoint='successor', old_incarnation=old['incarnation'], new_incarnation=self.ep['incarnation'],
            native_kind='thread_id', native_id=self.native), dead_owner=proof)
        return old

    def test_host_refresh_uses_os_death_and_independent_native_header(self):
        import subprocess
        import identity
        import host as host_module
        processes = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'codex-fixture'],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                     for _ in range(2)]
        def cleanup():
            for process in processes:
                if process.poll() is None: process.terminate()
                process.wait(timeout=5)
        self.addCleanup(cleanup)
        old_process, new_process = processes
        old_info, new_info = [identity._process_info(process.pid) for process in processes]
        # Fixture registration represents an actual OS PID/start incarnation;
        # these Python stubs are not real Codex/provider processes.
        self.hub.db.execute('UPDATE endpoints SET pid=?,pid_start=? WHERE endpoint_id=?',
                            (old_process.pid, str(old_info['pid_start']), 'recipient'))
        self.host.config.update(host_id='host', native_queue_enabled=True)
        candidate = dict(self.ep, endpoint_id='os-successor', pid=new_process.pid, pid_start=new_info['pid_start'],
                         session='replacement', runtime_id='replacement', thread_id=self.native, session_id=self.native)
        with patch.object(host_module, 'discover_endpoints', return_value=[candidate]), patch.object(host_module, 'discover_tmux_endpoints', return_value=[]):
            self.host.refresh()
            self.assertEqual(self.hub._row("SELECT retired FROM endpoints WHERE endpoint_id='recipient'")[0], 0)
            self.assertNotIn('native_handoff', self.calls)
            old_process.terminate()
            old_process.wait(timeout=5)
            hidden = self.transcript.with_suffix('.hidden')
            self.transcript.rename(hidden)
            try:
                self.host.refresh()
                self.assertEqual(self.hub._row("SELECT retired FROM endpoints WHERE endpoint_id='recipient'")[0], 0)
                self.assertNotIn('native_handoff', self.calls)
            finally: hidden.rename(self.transcript)
            self.host.refresh()
        owner = self.hub._row("SELECT * FROM native_delivery_owners WHERE message_id='original'")
        self.assertEqual(owner['actor_endpoint'], 'os-successor')
        self.assertEqual(self.hub._row("SELECT retired FROM endpoints WHERE endpoint_id='recipient'")[0], 1)
        self.assertEqual(self.hub._row("SELECT recipient_endpoint FROM messages WHERE message_id='original'")[0], 'recipient')
        self.assertEqual(self.calls.count('native_handoff'), 1)
        self.ep = next(ep for ep in self.host.endpoints if ep['endpoint_id'] == 'os-successor')
        with patch.object(self.host, 'caller', return_value=self.ep), self.assertRaises(HubError) as public:
            self.host.dispatch(dict(op='native_handoff', dead_owner={'reason': 'pid_absent'}), 1, os.getuid())
        self.assertEqual(public.exception.code, 'unknown_op')
        self.assertEqual(self.calls.count('native_handoff'), 1)

    def test_explicit_old_reservation_rejection_reconciles_only_after_handoff(self):
        rpc = self.host.hub
        def replace_before_reserve(op, **args):
            if op == 'native_begin_present' and args['endpoint_id'] == 'recipient':
                self.transfer()
            return rpc(op, **args)
        self.host.hub = replace_before_reserve
        with self.assertRaises(HubError) as rejected: self.resolve()
        self.assertEqual(rejected.exception.code, 'stale_session')
        self.host.hub = rpc
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'uncertain')
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep):
            self.host._deliver_endpoint(self.ep)
        row = self.host.db.execute('SELECT * FROM deliveries').fetchone()
        self.assertEqual((row['endpoint_id'], row['state']), ('successor', 'received'))
        saved = json.loads(row['envelope'])
        self.assertEqual(saved['_native_reservation_attempt']['outcome'], 'rejected')
        self.assertEqual(saved['_native_reservation_attempt']['reconciled_to']['generation'], 1)
        self.assertNotIn('_native_context_reference', saved)
        result = self.resolve()
        self.assertIn(self.original['body'], result['context'])
        self.assertEqual(self.hub._row("SELECT recipient_endpoint FROM messages WHERE message_id='original'")[0], 'recipient')

    def test_rejected_old_attempt_cannot_reconcile_a_later_global_reservation(self):
        rpc = self.host.hub
        def replace_before_reserve(op, **args):
            if op == 'native_begin_present' and args['endpoint_id'] == 'recipient': self.transfer()
            return rpc(op, **args)
        self.host.hub = replace_before_reserve
        with self.assertRaises(HubError): self.resolve()
        self.host.hub = rpc
        from native_notice import bind_actor, content_digest
        native = dict(endpoint_id='successor', native_kind='thread_id', native_id=self.native)
        rpc('native_begin_present', message_id='original', incarnation=self.ep['incarnation'],
            content_hash=content_digest(self.original), **native)
        current = rpc('query', endpoint_id='successor', message_id='original')
        before = tuple(self.host.db.execute('SELECT * FROM deliveries').fetchone())
        with self.assertRaises(HubError): bind_actor(self.host.db, self.ep, native, current, reconcile_rejected=True)
        self.assertEqual(tuple(self.host.db.execute('SELECT * FROM deliveries').fetchone()), before)
        self.assertEqual(current['state'], 'dispatching')

    def test_unknown_old_reservation_never_reconciles_even_if_new_actor_is_pending(self):
        rpc = self.host.hub
        def unknown_before_reserve(op, **args):
            if op == 'native_begin_present':
                self.transfer()
                raise OSError('fixture unknown response; original must remain fenced')
            return rpc(op, **args)
        self.host.hub = unknown_before_reserve
        with self.assertRaises(OSError): self.resolve()
        self.host.hub = rpc
        before = tuple(self.host.db.execute('SELECT * FROM deliveries').fetchone())
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep), self.assertRaises(HubError):
            self.host._deliver_endpoint(self.ep)
        self.host.db.rollback()
        self.assertEqual(tuple(self.host.db.execute('SELECT * FROM deliveries').fetchone()), before)
        self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0], 'adapter_received')

    def test_new_local_claim_keeps_reserved_transfer_recoverable(self):
        self.transfer()
        # Fixture begins before the first local claim; not recovery by deleting
        # a production journal or discarding unknown effects.
        self.host.db.execute('DELETE FROM native_notice_metadata')
        self.host.db.execute('DELETE FROM deliveries')
        self.host.db.commit()
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep):
            self.host._deliver_endpoint(self.ep)
        saved = json.loads(self.host.db.execute('SELECT envelope FROM deliveries').fetchone()[0])
        self.assertNotIn('delivery_actor', saved)
        self.notice = prepare(self.host.db, self.ep, dict(endpoint_id='successor', native_kind='thread_id', native_id=self.native), saved)
        self.host.db.commit()
        self.payload['prompt'] = self.notice['prompt']
        self.resolve()
        # This case targets the journal/receipt branch. Actual same-turn record
        # verification is covered separately by the transferred integration case.
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep), patch.object(consumer, 'recover', return_value=True):
            self.host._deliver_endpoint(self.ep)
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'presented')

    def test_current_actor_generation_mismatch_stops_before_body_reservation(self):
        self.transfer()
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep):
            self.host._deliver_endpoint(self.ep)
        row = self.host.db.execute('SELECT envelope FROM deliveries').fetchone()
        envelope = json.loads(row[0])
        envelope['_native_actor']['generation'] += 1
        self.host.db.execute('UPDATE deliveries SET envelope=?', (json.dumps(envelope),))
        self.host.db.commit()
        with self.assertRaises(HubError): self.resolve()
        self.assertNotIn('native_begin_present', self.calls)
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'received')

    def test_transferred_original_resolve_recover_and_host_receipt(self):
        old = self.transfer()
        self.host.config['native_queue_enabled'] = False
        current = self.host.hub('query', endpoint_id='successor', message_id='original')
        self.assertTrue(current['delivery_summary']['new_presentation_eligible'])
        origin = tuple(self.host.db.execute('SELECT * FROM native_notice_metadata').fetchone())
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep):
            self.host._deliver_endpoint(self.ep)
        self.assertEqual(self.host.db.execute('SELECT endpoint_id FROM deliveries').fetchone()[0], 'successor')
        self.assertEqual(tuple(self.host.db.execute('SELECT * FROM native_notice_metadata').fetchone()), origin)
        result = self.resolve()
        self.assertIn(self.original['body'], result['context'])
        for role, text, kind in [('user', self.notice['prompt'], 'user.text'), ('developer', result['context'], 'hooks.additional_context')]:
            record = dict(type='response_item', payload=dict(type='message', role=role, id=role+'-record',
                content=[dict(type='input_text', text=text)], internal_chat_message_metadata_passthrough=dict(
                    turn_id='current-turn', content_item_kinds=[kind])))
            with self.transcript.open('a') as f: f.write(json.dumps(record)+'\n')
        self.assertTrue(consumer.recover(self.host, self.ep, 'original'))
        with patch.object(self.host, '_current_delivery_endpoint', return_value=self.ep):
            self.host._deliver_endpoint(self.ep)
        self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0], 'presented')
        self.assertEqual(self.host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'presented')
        self.assertEqual(self.hub._row("SELECT recipient_endpoint FROM messages WHERE message_id='original'")[0], old['endpoint_id'])
        with self.assertRaises(HubError): consumer.resolve(self.host, old, {'hook': self.payload})
        self.host.hub('submit', message=dict(message_id='successor-reply', sender_endpoint='successor',
                      in_reply_to='original', thread_id=self.original['thread_id'], body='received'))
        summary = self.host.hub('query', endpoint_id='sender', message_id='original')
        self.assertEqual(summary['response_state'], 'recipient_replied')
        self.assertEqual(summary['recipient_reply_message_ids'], ['successor-reply'])

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

    def test_pending_set_one_reference_individual_reservations_and_receipts(self):
        for mid in ('second', 'cancelled'):
            self.hub.dispatch(dict(op='submit', host_id='host', host_token='token', message={
                'message_id': mid, 'target': 'cdx', 'sender_endpoint': 'sender', 'body': mid+' body'}))
            message = self.host.hub('query', endpoint_id='recipient', message_id=mid)
            self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                (mid, 'recipient', json.dumps(message), 'received', None, 0))
        self.host.db.commit()
        self.hub.cancel(dict(host_id='host', host_token='token', endpoint_id='sender', message_id='cancelled'))
        result = self.resolve()
        self.assertEqual(result['message_ids'], ['original', 'second'])
        self.assertIn('second body', result['context'])
        self.assertNotIn('cancelled body', result['context'])
        self.assertEqual(self.calls.count('native_begin_present'), 2)
        reference = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'id': 'batch-reference',
            'content': [{'type': 'input_text', 'text': self.notice['prompt']}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'current-turn', 'content_item_kinds': ['user.text']}}}
        context = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer', 'id': 'batch-context',
            'content': [{'type': 'input_text', 'text': result['context']}],
            'internal_chat_message_metadata_passthrough': {'turn_id': 'current-turn', 'content_item_kinds': ['hooks.additional_context']}}}
        with self.transcript.open('a') as f: f.write(json.dumps(reference)+'\n'+json.dumps(context)+'\n')
        for mid in result['message_ids']: self.assertTrue(consumer.recover(self.host, self.ep, mid))
        with self.assertRaises(HubError): self.resolve()
        # A batch member cannot recover after its original pinned body is changed.
        saved = json.loads(self.host.db.execute("SELECT envelope FROM deliveries WHERE message_id='second'").fetchone()[0])
        saved['body'] = 'changed'
        self.host.db.execute("UPDATE deliveries SET envelope=? WHERE message_id='second'", (json.dumps(saved),))
        self.host.db.commit()
        with self.assertRaises(HubError): consumer.recover(self.host, self.ep, 'second')

    def test_pending_set_later_prepare_conflict_preserves_leader_context(self):
        self.hub.dispatch(dict(op='submit',host_id='host',host_token='token',message={
            'message_id':'conflict', 'target':'cdx', 'sender_endpoint':'sender', 'body':'CONFLICT_BODY'}))
        message = self.host.hub('query',endpoint_id='recipient',message_id='conflict')
        self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
            ('conflict','recipient',json.dumps(message),'received',None,0))
        prepare(self.host.db,self.ep,dict(endpoint_id='recipient',native_kind='thread_id',native_id=self.native),message)
        self.host.db.execute("UPDATE native_notice_metadata SET version=999 WHERE message_id='conflict'")
        self.host.db.commit()
        result = self.resolve()
        self.assertEqual(result['message_ids'], ['original'])
        self.assertNotIn('CONFLICT_BODY',result['context'])
        self.assertIsNotNone(self.host.db.execute("SELECT prompt_hash FROM deliveries WHERE message_id='original'").fetchone()[0])
        self.assertEqual(self.host.db.execute("SELECT state FROM deliveries WHERE message_id='conflict'").fetchone()[0],'received')

    def test_pending_set_later_gate_failure_does_not_expose_failed_body(self):
        self.hub.dispatch(dict(op='submit', host_id='host', host_token='token', message={
            'message_id':'second', 'target':'cdx', 'sender_endpoint':'sender', 'body':'MUST_NOT_EXPOSE'}))
        message = self.host.hub('query', endpoint_id='recipient', message_id='second')
        self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
            ('second', 'recipient', json.dumps(message), 'received', None, 0))
        self.host.db.commit()
        rpc = self.host.hub
        def cancel_later(op, **args):
            if op == 'native_begin_present' and args['message_id'] == 'second':
                self.hub.cancel(dict(host_id='host',host_token='token',endpoint_id='sender',message_id='second'))
            return rpc(op, **args)
        self.host.hub = cancel_later
        result = self.resolve()
        self.assertEqual(result['message_ids'], ['original'])
        self.assertNotIn('MUST_NOT_EXPOSE', result['context'])
        row = self.host.db.execute("SELECT state,prompt_hash FROM deliveries WHERE message_id='second'").fetchone()
        self.assertEqual(tuple(row), ('uncertain', None))

    def test_pending_set_new_arrival_before_drain_retains_wake(self):
        rpc = self.host.hub
        def arrive(op, **args):
            if op == 'native_drain':
                self.hub.dispatch(dict(op='submit', host_id='host', host_token='token', message={
                    'message_id':'late', 'target':'cdx', 'sender_endpoint':'sender', 'body':'late'}))
            return rpc(op, **args)
        self.host.hub = arrive
        self.resolve()
        status = rpc('native_pending', endpoint_id='recipient', incarnation=self.ep['incarnation'],
                     native_kind='thread_id', native_id=self.native)
        self.assertTrue(status['wake_needed'])
        self.assertTrue(status['pending'])

    def test_wire_bounded_escaped_body_fits_native_context_without_truncation(self):
        from protocol import MAX_REQUEST, NATIVE_CONTEXT_LIMIT, success
        body = ('\t'*128000) + '\n日本語😀END'
        # Rebuild the fixed original before any notice was published.
        self.host.db.execute('DELETE FROM native_notice_metadata')
        self.host.db.execute('DELETE FROM deliveries')
        self.hub.dispatch(dict(op='submit',host_id='host',host_token='token',message={
            'message_id':'large', 'target':'cdx', 'sender_endpoint':'sender', 'body':body}))
        message = self.host.hub('query',endpoint_id='recipient',message_id='large')
        self.assertLess(len(json.dumps(success(message),ensure_ascii=False).encode()),MAX_REQUEST)
        self.host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
            ('large','recipient',json.dumps(message),'received',None,0))
        notice = prepare(self.host.db,self.ep,dict(endpoint_id='recipient',native_kind='thread_id',native_id=self.native),message)
        self.host.db.commit()
        self.payload['prompt'] = notice['prompt']
        result = self.resolve()
        raw = json.dumps(success(result),ensure_ascii=False).encode()
        self.assertGreater(len(raw), MAX_REQUEST)
        self.assertLess(len(raw),NATIVE_CONTEXT_LIMIT)
        self.assertEqual(json.loads(result['context'].split('\n',1)[1])['body'],body)

    def test_only_native_resolve_client_accepts_larger_response(self):
        import cli
        raw = (json.dumps({'ok':True,'result':{'context':'x'*300000}})+'\n').encode()
        class Socket:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def settimeout(self,*args): pass
            def connect(self,*args): pass
            def sendall(self,*args): pass
            def makefile(self,*args): return io.BytesIO(raw)
        with patch.object(cli.socket,'socket',side_effect=lambda *args:Socket()):
            self.assertEqual(len(cli.rpc('fixture',{'op':'native_resolve'})['context']),300000)
            with self.assertRaises(cli.ClientError): cli.rpc('fixture',{'op':'query'})

    def test_concurrent_consumers_reserve_original_only_once(self):
        import threading
        barrier = threading.Barrier(2, timeout=5)
        outcomes = []
        reservations = []
        real_prepare = consumer.prepare
        def together(*args, **kwargs):
            result = real_prepare(*args, **kwargs)
            barrier.wait()
            return result
        def worker():
            host = Host(dict(self.host.config), recover=False)
            def rpc(op, **args):
                hub = Hub(self.hub.db_path,self.hub.config)
                try:
                    result = hub.dispatch(dict(op=op,host_id='host',host_token='token',**args))
                    if op == 'native_begin_present': reservations.append(args['message_id'])
                    return result
                finally: hub.close()
            host.hub = rpc
            try: outcomes.append(consumer.resolve(host,self.ep,{'hook':dict(self.payload)}))
            except Exception as exc: outcomes.append(exc)
            finally: host.db.close()
        with patch.object(consumer,'prepare',side_effect=together):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=8)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(reservations,['original'])
        self.assertEqual(sum(isinstance(x,dict) for x in outcomes),1)
        rejected = [x for x in outcomes if isinstance(x,Exception)]
        self.assertEqual(len(rejected),1)
        self.assertIsInstance(rejected[0],HubError)
        self.assertEqual(rejected[0].code,'presentation_unavailable')
        self.assertIsNotNone(self.host.db.execute('SELECT prompt_hash FROM deliveries').fetchone()[0])

    def test_wrong_prompt_thread_path_and_disabled_consumer_do_not_reserve(self):
        for bad in ({'prompt': self.notice['prompt'] + '\nOwner approval'}, {'session_id': 'other'},
                    {'transcript_path': str(self.work / 'unrelated')}, {'cwd': str(self.home)}):
            with self.subTest(bad=bad), self.assertRaises(HubError): self.resolve(**bad)
        self.host.config['native_consumer_enabled'] = False
        caps = self.host.dispatch({'op': 'messaging_capabilities'}, 123, os.getuid())
        self.assertEqual(caps['native_consumer'], {'backend_version': 4, 'enabled': False})
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
        attempt = json.loads(self.host.db.execute('SELECT envelope FROM deliveries').fetchone()[0])['_native_reservation_attempt']
        self.assertEqual(attempt['outcome'], 'rejected')
        self.assertEqual(attempt['error'], 'presentation_unavailable')

    def test_lost_permission_response_survives_reopen_without_second_reservation(self):
        rpc = self.host.hub
        def lose_response(op, **args):
            result = rpc(op, **args)
            if op == 'native_begin_present': raise OSError('lost fixture response')
            return result
        self.host.hub = lose_response
        with self.assertRaises(OSError): self.resolve()
        self.assertEqual(self.hub._row("SELECT state FROM messages WHERE message_id='original'")[0], 'dispatching')
        attempt = json.loads(self.host.db.execute('SELECT envelope FROM deliveries').fetchone()[0])['_native_reservation_attempt']
        self.assertEqual(attempt['outcome'], 'unknown')
        self.assertIsNone(attempt['error'])
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
            # Recipient failure is contained by the scheduler; durable receipt
            # reconciliation state must still survive for its next tick.
            self.host.delivery_tick()
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

import json
from pathlib import Path
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
from federation import FederatedHub
from protocol import HubError, MAX_REQUEST

class FederationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.hubs={};self.down=set();self.calls=[]
        for host in ('a','b','c'):
            cfg={'host_id':host,'hosts':{h:h+'-token' for h in ('a','b','c')},'admin_token':'admin'}
            hub=FederatedHub(Path(self.tmp.name)/(host+'.db'),cfg)
            hub.topology=lambda host=host:{'mode':'multi','management_host_id':'a','hosts':[{'id':h,'ssh_alias':h} for h in ('a','b','c') if h!=host]}
            hub.directory_import({'admin_token':'admin','projects':[{'project_id':host,'alias':host,'host_id':host,'path':'/same/path'}]})
            for role in ('cc','cdx'):
                hub.register(dict(host_id=host,host_token=host+'-token',endpoint_id=host+role,participant_id=host+':'+role,session=host,pane='%1',pid=100,pid_start=10,runtime_id=host+role,platform=role))
            self.hubs[host]=hub;self.addCleanup(hub.close)
        for host,hub in self.hubs.items():
            def remote(owner,op,host=host,**args):
                self.calls.append((host,owner,op))
                if owner in self.down:raise HubError('host_unavailable','offline')
                return self.hubs[owner].dispatch(dict(args,op='peer_'+op,host_id=host,host_token=host+'-token',protocol=1))
            hub.remote=remote
    def retire_alias(self, owner, alias='retired', successor='b'):
        hub = self.hubs[owner]
        hub.directory_import(dict(admin_token='admin', projects=[dict(project_id=owner+'-'+alias,
            alias=alias, host_id=owner, path='/retired/'+alias)]))
        hub.directory_retire(dict(admin_token='admin', alias=alias, successor=successor))

    def test_retired_alias_across_owners_and_same_id_retry_without_network(self):
        self.retire_alias('a')
        for sender in ('a', 'b', 'c'):
            with self.subTest(sender=sender):
                mid = 'redirect-'+sender
                result = self.send(sender, mid, 'retired.cdx')
                self.assertEqual((result['renamed_from'], result['renamed_to']), ('retired.cdx', 'b.cdx'))
                stored = self.hubs['b']._row('SELECT * FROM messages WHERE message_id=?', (mid,))
                self.assertEqual(stored['recipient_endpoint'], 'bcdx')
                self.assertEqual(stored['body'], 'hello')
        # Actual incident shape: sender/recipient B, retired namespace owner A.
        self.down.add('a')
        self.calls.clear()
        result = self.send('b', 'redirect-b', 'retired.cdx')
        self.assertTrue(result['duplicate'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.hubs['b']._row("SELECT COUNT(*) FROM messages WHERE message_id='redirect-b'")[0], 1)
        with self.assertRaisesRegex(HubError, 'different payload'):
            self.send('b', 'redirect-b', 'retired.cdx', body='changed')

    def test_alias_redirect_cannot_expand_service_scope(self):
        self.retire_alias('a')
        for sender in ('a', 'b', 'c'):
            req = dict(op='submit', host_id=sender, host_token=sender+'-token',
                authorized_targets=['retired.cdx'], message=dict(message_id='denied-'+sender,
                    sender_endpoint=sender+'cc', target='retired.cdx', body='scoped', kind='chat'))
            with self.subTest(sender=sender), self.assertRaises(HubError) as raised:
                self.hubs[sender].dispatch(req)
            self.assertEqual(raised.exception.code, 'scope_denied')
            self.assertIsNone(self.hubs[sender]._row('SELECT * FROM messages WHERE message_id=?', ('denied-'+sender,)))
            req['authorized_targets'].append('b.cdx')
            self.assertEqual(self.hubs[sender].dispatch(req)['message_id'], 'denied-'+sender)

        # New Hub + old Host must not make a KAI redirect bypass canonical scope.
        owner = self.hubs['b']
        owner.directory_import(dict(admin_token='admin', services=[dict(participant_id='service',
            address='service', host_id='b', kind='kai')]))
        owner.register(dict(host_id='b', host_token='b-token', endpoint_id='service',
            participant_id='service', session='s', pane=None, pid=101, pid_start=10,
            runtime_id='s', platform='kai'))
        req = dict(host_id='b', host_token='b-token', message=dict(message_id='old-host',
            sender_endpoint='service', target='retired.cdx', body='scoped', kind='chat'))
        with self.assertRaises(HubError) as raised: owner.submit(req)
        self.assertEqual(raised.exception.code, 'unsupported')
        self.assertIsNone(owner._row("SELECT * FROM messages WHERE message_id='old-host'"))

    def test_redirect_chain_or_competing_owner_is_rejected(self):
        self.retire_alias('a', successor='middle')
        owner = self.hubs['a']
        old_req = dict(op='peer_resolve', host_id='b', host_token='b-token', protocol=1, address='retired.cdx')
        with self.assertRaises(HubError): owner.dispatch(old_req)
        proof = owner.dispatch(dict(old_req, include_alias_redirect=True))
        self.assertEqual(proof, {'renamed_from': 'retired.cdx', 'renamed_to': 'middle.cdx'})
        self.retire_alias('c', alias='middle', successor='b')
        with self.assertRaisesRegex(HubError, 'chain'):
            self.hubs['b'].resolve_destination('retired.cdx')
        self.retire_alias('c', successor='b')
        with self.assertRaises(HubError) as raised:
            self.hubs['b'].resolve_destination('retired.cdx')
        self.assertEqual(raised.exception.code, 'ambiguous_target')

    def test_concurrent_writable_legacy_migration_is_serialized(self):
        path = Path(self.tmp.name) / 'legacy.db'
        cfg = {'host_id': 'legacy', 'hosts': {'legacy': 'fixture-token'}}
        hub = FederatedHub(path, cfg)
        hub.db.execute('DROP TABLE federated_outbox')
        hub.db.execute("CREATE TABLE federated_outbox (message_id TEXT PRIMARY KEY, host_id TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending')")
        hub.close()
        barrier = threading.Barrier(2)
        begin = FederatedHub._tx
        def synchronized_begin(instance):
            barrier.wait(timeout=5)
            begin(instance)
        def construct():
            instance = FederatedHub(path, cfg)
            try:
                return [row['name'] for row in instance.db.execute('PRAGMA table_info(federated_outbox)')]
            finally:
                instance.close()
        with patch.object(FederatedHub, '_tx', synchronized_begin), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: construct(), range(2)))
        for columns in results:
            self.assertEqual(columns.count('acceptance_state'), 1)

    def test_capability_probe_keeps_peer_without_transport_evidence(self):
        hub = self.hubs['a']
        hub.topology = lambda: {'mode': 'multi', 'hosts': [{'id': 'a'}, {'id': 'b', 'ssh_alias': ''}, {'id': 'c', 'ssh_alias': 'c'}]}
        result = hub.dispatch({'op': 'messaging_capabilities', 'host_id': 'a', 'host_token': 'a-token'})
        self.assertFalse(result['peers']['b']['available'])
        self.assertEqual(result['peers']['b']['error'], 'configuration_error')
        self.assertTrue(result['peers']['c']['available'])
        self.assertIn('native_continuity', result['peers']['c']['capabilities'])
        self.assertEqual(result['native_runtime'], {'hub_version': 3})
        self.assertEqual(result['peers']['c']['native_runtime'], {'hub_version': 3})
        self.assertIn('native_pending', result['peers']['c']['capabilities'])

    def test_owner_route_selection_and_accept_revision_are_independent_of_reply_pins(self):
        owner = self.hubs['b']
        auth = dict(host_id='b', host_token='b-token')
        owner.register(dict(auth, endpoint_id='tui', participant_id='b:cdx', session='b',
            pane='%2', pid=201, pid_start=11, runtime_id='tui', platform='cdx'))
        owner.attest_native(dict(auth, endpoint_id='tui', native_kind='thread_id', native_id='native'))
        candidate = owner.dispatch(dict(auth, op='recipient_observe', observed_endpoint='tui'))['candidate']
        owner.dispatch(dict(auth, op='recipient_select', actor_endpoint='tui', operation_id='select',
            target='b.cdx', candidate=candidate, expected_revision=0))
        source = self.hubs['a']
        request = dict(host_id='a', host_token='a-token', message=dict(message_id='chosen',
            sender_endpoint='acc', target='b.cdx', body='peer data'))
        source.submit(request)
        self.assertEqual(owner._row("SELECT recipient_endpoint FROM messages WHERE message_id='chosen'")[0], 'tui')
        snapshot = owner.local_resolve('b.cdx')
        self.assertEqual(snapshot['routing_revision'], 1)
        owner.dispatch(dict(auth, op='recipient_clear', actor_endpoint='tui', operation_id='clear',
            target='b.cdx', expected_revision=1))
        with self.assertRaises(HubError): owner.local_resolve('b.cdx')
        # History and explicit endpoint lookup do not consult the new preference.
        self.assertEqual(owner.local_resolve(endpoint_id='bcdx')['endpoint']['endpoint_id'], 'bcdx')

    def test_recovery_reply_is_authorized_only_by_original_recipient_owner(self):
        source = self.hubs['a']; owner = self.hubs['b']
        source.submit(dict(host_id='a',host_token='a-token',message=dict(message_id='recover-original',
            sender_endpoint='acc',target='b.cdx',body='peer data')))
        auth = dict(host_id='b',host_token='b-token')
        owner.register(dict(auth, endpoint_id='recovery-tui',participant_id='b:cdx',session='b',pane='%2',
            pid=201,pid_start=11,runtime_id='tui',platform='cdx'))
        owner.attest_native(dict(auth, endpoint_id='recovery-tui',native_kind='thread_id',native_id='other-native'))
        key = owner.dispatch(dict(auth,op='recipient_observe',observed_endpoint='recovery-tui'))['candidate']
        grant = owner.dispatch(dict(auth,op='recovery_grant',actor_endpoint='recovery-tui',operation_id='grant',
            candidate=key,message_id='recover-original',expected_revision=0,allow_read=True,allow_reply=True))
        out = owner.dispatch(dict(auth,op='recovery_reply',actor_endpoint='recovery-tui',operation_id='reply-op',
            grant_id=grant['grant_id'],message_id='recover-original',submission_id='recovered-reply',body='answer'))
        self.assertEqual(out['message_id'],'recovered-reply')
        self.assertIsNotNone(source._row("SELECT * FROM messages WHERE message_id='recovered-reply'"))
        self.assertIsNone(source._row('SELECT * FROM message_recovery_grants WHERE grant_id=?',(grant['grant_id'],)))
        evidence = source.response_evidence(source._row("SELECT * FROM messages WHERE message_id='recover-original'"))
        self.assertEqual(evidence['recipient_reply_count'],0)
        self.assertEqual(evidence['authorized_recovery_reply_ids'],['recovered-reply'])

    def test_slow_recovery_reply_preflight_does_not_block_unrelated_local_submit(self):
        self._slow_recovery_case(False)

    def test_pending_recovery_retry_does_not_flush_inside_owner_write_transaction(self):
        self._slow_recovery_case(True)

    def _slow_recovery_case(self, pending):
        source = self.hubs['a']; owner = self.hubs['b']
        source.submit(dict(host_id='a',host_token='a-token',message=dict(message_id='slow-original',
            sender_endpoint='acc',target='b.cdx',body='peer data')))
        auth = dict(host_id='b',host_token='b-token')
        owner.attest_native(dict(auth,endpoint_id='bcdx',native_kind='thread_id',native_id='native'))
        key = owner.dispatch(dict(auth,op='recipient_observe',observed_endpoint='bcdx'))['candidate']
        grant = owner.dispatch(dict(auth,op='recovery_grant',actor_endpoint='bcdx',operation_id='slow-grant',
            candidate=key,message_id='slow-original',expected_revision=0,allow_read=True,allow_reply=True))
        if pending:
            original = owner.remote
            def unavailable(host,op,**args):
                if op=='accept': raise HubError('host_unavailable','fixture offline')
                return original(host,op,**args)
            owner.remote=unavailable
            owner.dispatch(dict(auth,op='recovery_reply',actor_endpoint='bcdx',operation_id='initial-reply',
                grant_id=grant['grant_id'],message_id='slow-original',submission_id='slow-answer',body='answer'))
            owner.remote=original
            self.assertEqual(owner._row("SELECT state FROM federated_outbox WHERE message_id='slow-answer'")[0],'pending')
        other = FederatedHub(owner.db_path,owner.config)
        self.addCleanup(other.close)
        entered = threading.Event(); release = threading.Event(); committed = threading.Event(); failures=[]
        original_remote = owner.remote
        def remote(host,op,**args):
            if op==('accept' if pending else 'resolve'):
                entered.set(); release.wait(5)
                raise HubError('host_unavailable','fixture timeout')
            return original_remote(host,op,**args)
        owner.remote=remote
        def recovery():
            try: owner.dispatch(dict(auth,op='recovery_reply',actor_endpoint='bcdx',operation_id='slow-reply',
                grant_id=grant['grant_id'],message_id='slow-original',submission_id='slow-answer',body='answer'))
            except HubError: pass
            except Exception as exc: failures.append(type(exc).__name__)
        def local():
            try:
                other.submit(dict(auth,message=dict(message_id='unrelated-local',sender_endpoint='bcc',
                    target='b.cc',body='local data')))
                committed.set()
            except Exception as exc: failures.append(type(exc).__name__)
        first=threading.Thread(target=recovery); second=threading.Thread(target=local)
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            second.start()
            self.assertTrue(committed.wait(2),'remote preflight held the owner write lock')
        finally:
            release.set(); first.join(3)
            if second.ident:second.join(3)
        self.assertEqual(failures,[])
        proof = owner._row("SELECT * FROM message_recovery_replies WHERE message_id='slow-answer'")
        self.assertEqual(proof is not None,pending)

    def test_accepted_retry_preserves_result_after_recipient_revocation(self):
        sender, recipient = self.hubs['a'], self.hubs['b']
        original_remote = sender.remote
        lost = [False]
        def remote(owner, op, **args):
            result = original_remote(owner, op, **args)
            if op == 'accept' and not lost[0]:
                lost[0] = True
                raise HubError('host_unavailable', 'response lost after acceptance')
            return result
        sender.remote = remote
        self.send('a', 'lost-result', 'b.cdx')
        recipient.db.execute("UPDATE messages SET state='presented' WHERE message_id='lost-result'")
        recipient.db.execute("UPDATE endpoints SET retired=1,platform='kai' WHERE endpoint_id='bcdx'")
        row = sender._row("SELECT * FROM federated_outbox WHERE message_id='lost-result'")
        result = sender.flush_one(row)
        self.assertEqual(result['state'], 'presented')
        delivered = sender._row("SELECT * FROM federated_outbox WHERE message_id='lost-result'")
        calls = len(self.calls)
        self.assertEqual(sender.flush_one(delivered)['state'], 'presented')
        self.assertEqual(len(self.calls), calls)
        self.assertNotEqual(sender._row("SELECT state FROM messages WHERE message_id='lost-result'")['state'], 'rejected')
        self.assertEqual(recipient._row("SELECT state FROM messages WHERE message_id='lost-result'")['state'], 'presented')
        payload = json.loads(row['payload']); payload['record']['body'] = 'changed'
        with self.assertRaises(HubError) as error:
            recipient.accept({'host_id': 'a', 'host_token': 'a-token', 'payload': payload})
        self.assertEqual(error.exception.code, 'id_conflict')

    def test_delivered_retries_preserve_authority_state_atomically(self):
        sender = self.hubs['a']
        for state in ('dispatching', 'uncertain'):
            mid = 'saved-' + state
            remote = sender.remote
            sender.remote = lambda owner, op, **args: ({'message_id': mid, 'state': state}
                                                       if op == 'accept' else remote(owner, op, **args))
            try:
                self.send('a', mid, 'b.cdx')
            finally:
                sender.remote = remote
            row = sender._row('SELECT * FROM federated_outbox WHERE message_id=?', (mid,))
            self.assertEqual((row['state'], row['acceptance_state']), ('delivered', state))
            self.assertEqual(sender.flush_one(row)['state'], state)
        sender.db.execute("UPDATE federated_outbox SET acceptance_state=NULL WHERE message_id=?", (mid,))
        with self.assertRaises(HubError) as error:
            sender.flush_one(sender._row('SELECT * FROM federated_outbox WHERE message_id=?', (mid,)))
        self.assertEqual(error.exception.code, 'host_unavailable')

    def test_invalid_acceptance_result_preserves_pending_outcome(self):
        sender = self.hubs['a']
        original_remote = sender.remote
        def remote(owner, op, **args):
            if op == 'accept':
                original_remote(owner, op, **args)
                return None
            return original_remote(owner, op, **args)
        sender.remote = remote
        result = self.send('a', 'invalid-result', 'b.cdx')
        self.assertTrue(result['delivery_pending'])
        self.assertEqual(sender._row("SELECT state FROM federated_outbox WHERE message_id='invalid-result'")['state'], 'pending')
        self.assertIsNotNone(self.hubs['b']._row("SELECT * FROM messages WHERE message_id='invalid-result'"))

    def test_rotated_sender_diagnosis_preserves_remote_presented_evidence(self):
        self.send('a', 'historical-diag', 'b.cdx')
        self.hubs['b'].db.execute("UPDATE messages SET state='presented' WHERE message_id='historical-diag'")
        current = self.rotate_native('a')
        req = {'op': 'diagnose', 'host_id': 'a', 'host_token': 'a-token',
               'endpoint_id': current, 'message_id': 'historical-diag', 'operator_diagnostic': True}
        result = self.hubs['a'].dispatch(req)
        self.assertEqual(result['state'], 'presented')
        self.assertTrue(result['presentation_confirmed'])
        self.assertEqual(result['diagnostic_host_id'], 'b')
        proof = {'historical_endpoint': 'acc', 'current': {
            'endpoint_id': current, 'host_id': 'a', 'participant_id': 'wrong', 'platform': 'cc'}}
        with self.assertRaises(HubError):
            self.hubs['b'].dispatch(dict(req, op='peer_diagnose', protocol=1, diagnostic_party=proof))

    def send(self,host,mid,target=None,reply=None,body='hello'):
        message=dict(message_id=mid,sender_endpoint=host+'cc',body=body,kind='chat')
        if target:message['target']=target
        if reply:message['in_reply_to']=reply
        return self.hubs[host].submit(dict(host_id=host,host_token=host+'-token',message=message))
    def rotate_native(self, host, role='cc', native='native-thread'):
        hub = self.hubs[host]
        old = host+role
        auth = dict(host_id=host, host_token=host+'-token')
        hub.attest_native(dict(auth, endpoint_id=old, native_kind='thread_id', native_id=native))
        hub.dispatch(dict(auth, op='endpoint_retire', endpoint_id=old))
        new = old+'-new'
        hub.register(dict(auth, endpoint_id=new, participant_id=host+':'+role, session=host,
                          pane='%1', pid=101, pid_start=11, runtime_id=new, platform=role))
        hub.attest_native(dict(auth, endpoint_id=new, native_kind='thread_id', native_id=native))
        return new

    def test_exact_remote_reply_lands_on_same_native_rotated_sender(self):
        self.send('a', 'rotation-original', 'b.cc')
        new = self.rotate_native('a')
        self.send('b', 'rotation-reply', reply='rotation-original')
        self.assertEqual(self.hubs['a']._row("SELECT recipient_endpoint FROM messages WHERE message_id='rotation-reply'")[0], new)
        result = self.hubs['a'].dispatch(dict(op='query', host_id='a', host_token='a-token', endpoint_id=new, message_id='rotation-original'))
        self.assertEqual(result['sender_endpoint'], 'acc')

    def test_proven_stale_session_tombstones_outbox_without_retry(self):
        original = self.hubs['a'].remote
        def stale(owner, op, **args):
            if owner == 'b' and op == 'accept':
                raise HubError('stale_session', 'retired')
            return original(owner, op, **args)
        self.hubs['a'].remote = stale
        result = self.send('a', 'stale-wire', 'b.cc')
        self.assertEqual(result['state'], 'stale_session')
        self.assertEqual(self.hubs['a']._row("SELECT state FROM messages WHERE message_id='stale-wire'")[0], 'stale_session')
        self.assertEqual(self.hubs['a']._row("SELECT state FROM federated_outbox WHERE message_id='stale-wire'")[0], 'rejected')

    def test_rotated_recipient_remote_reply_owner_attestation(self):
        self.send('a', 'recipient-original', 'b.cc')
        new = self.rotate_native('b')
        result = self.hubs['b'].submit(dict(host_id='b', host_token='b-token', message=dict(message_id='recipient-reply', sender_endpoint=new, in_reply_to='recipient-original', body='received')))
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(self.hubs['a']._row("SELECT sender_endpoint FROM messages WHERE message_id='recipient-reply'")[0], new)

    def test_local_without_any_remote_and_same_path_isolated(self):
        self.down={'b','c'}
        self.assertEqual(self.send('a','local','cdx')['state'],'queued')
        self.assertEqual(self.calls,[])
        self.assertIsNotNone(self.hubs['a']._row('SELECT * FROM messages WHERE message_id="local"'))
        self.assertIsNone(self.hubs['b']._row('SELECT * FROM messages WHERE message_id="local"'))
    def test_remote_reply_receipt_and_no_foreign_directory(self):
        self.send('a','out','b.cc')
        self.assertEqual(self.hubs['b']._row('SELECT sender_endpoint FROM messages WHERE message_id="out"')[0],'acc')
        self.send('b','back',reply='out',body='received')
        self.assertEqual(self.hubs['a']._row('SELECT recipient_endpoint FROM messages WHERE message_id="back"')[0],'acc')
        self.assertEqual([p['alias'] for p in self.hubs['b'].local_directory()['projects']],['b'])
        self.hubs['b'].receipt(dict(host_id='b',host_token='b-token',endpoint_id='bcc',message_id='out',state='presented'))
        r=self.hubs['a'].dispatch(dict(op='query',host_id='a',host_token='a-token',endpoint_id='acc',message_id='out'))
        self.assertEqual(r['state'],'presented')
        self.assertTrue(self.send('a','out','b.cc')['duplicate'])

    def test_large_multibyte_send_and_reply_are_retained_exactly(self):
        # 45,000 Japanese characters are over 64 KiB in UTF-8 but remain below
        # the bounded request frame; federation must preserve the body exactly.
        sent = '海' * 45000
        self.assertGreater(len(sent.encode('utf-8')), 64 * 1024)
        self.send('a', 'large-out', 'b.cc', body=sent)
        received = self.hubs['b']._row('SELECT body FROM messages WHERE message_id=?', ('large-out',))[0]
        self.assertEqual(received, sent)
        reply = '帆' * 45000
        self.send('b', 'large-reply', reply='large-out', body=reply)
        returned = self.hubs['a']._row('SELECT body FROM messages WHERE message_id=?', ('large-reply',))[0]
        self.assertEqual(returned, reply)
    def test_bounded_wire_recovers_saved_multilingual_payload(self):
        sender = self.hubs['a']
        original_remote = sender.remote
        def hold_accept(owner, op, **args):
            if op == 'accept': raise HubError('host_unavailable', 'offline')
            return original_remote(owner, op, **args)
        sender.remote = hold_accept
        body = '海🚢' * 18000
        self.assertTrue(self.send('a', 'wire-large', 'b.cc', body=body)['delivery_pending'])
        row = sender._row('SELECT * FROM federated_outbox WHERE message_id=?', ('wire-large',))
        saved = row['payload']
        diagnostic = sender.dispatch(dict(op='diagnose', host_id='a', host_token='a-token',
                                          endpoint_id='acc', message_id='wire-large'))
        sizes = diagnostic['federated_outbox']
        self.assertGreater(sizes['legacy_request_bytes'], MAX_REQUEST)
        self.assertLess(sizes['current_request_bytes'], MAX_REQUEST)
        self.assertEqual(diagnostic['remote_error'], 'not_found')
        self.assertNotIn(body, json.dumps(diagnostic))
        with self.assertRaises(HubError):
            sender.dispatch(dict(op='diagnose', host_id='a', host_token='a-token',
                                 endpoint_id='acdx', message_id='wire-large'))
        sender.remote = FederatedHub.remote.__get__(sender)
        frames = []
        def transport(command, **kwargs):
            frame = kwargs['input']; frames.append(frame)
            self.assertLessEqual(len(frame.encode('utf-8')), MAX_REQUEST)
            request = json.loads(frame)
            self.assertNotIn('message', request['payload'])
            # host.rpc's forwarding serializer is bounded by the same limit.
            self.assertLessEqual(len((json.dumps(request, ensure_ascii=False) + '\n').encode()), MAX_REQUEST)
            result = self.hubs['b'].dispatch(request)
            return SimpleNamespace(returncode=0, stdout=json.dumps({'ok':True,'result':result}))
        with patch('federation.subprocess.run', side_effect=transport):
            self.assertEqual(sender.flush_one(row)['state'], 'queued')
            self.assertTrue(self.send('a', 'wire-large', 'b.cc', body=body)['duplicate'])
            with self.assertRaises(HubError) as caught:
                self.send('a', 'wire-large', 'b.cc', body='changed')
            self.assertEqual(caught.exception.code, 'id_conflict')
            sender.cancel(dict(host_id='a',host_token='a-token',endpoint_id='acc',message_id='wire-large'))
        self.assertEqual(len(frames), 2)
        self.assertEqual(sender._row('SELECT payload FROM federated_outbox WHERE message_id=?', ('wire-large',))[0], saved)
        self.assertEqual(self.hubs['b']._row('SELECT body FROM messages WHERE message_id=?', ('wire-large',))[0], body)
        # A frame that cannot fit is deterministic rejection, without SSH/retry.
        sender.remote = hold_accept
        self.send('a', 'wire-oversize', 'b.cc', body='x' * 100)
        oversized = sender._row('SELECT * FROM federated_outbox WHERE message_id=?', ('wire-oversize',))
        payload = json.loads(oversized['payload'])
        payload['sender']['padding'] = 'x' * MAX_REQUEST
        sender.db.execute('UPDATE federated_outbox SET payload=? WHERE message_id=?',
                          (json.dumps(payload), 'wire-oversize'))
        oversized = sender._row('SELECT * FROM federated_outbox WHERE message_id=?', ('wire-oversize',))
        sender.remote = FederatedHub.remote.__get__(sender)
        with patch('federation.subprocess.run') as ssh:
            result = sender.flush_one(oversized)
            self.assertEqual((result['state'], result['reason']), ('rejected', 'request_too_large'))
            ssh.assert_not_called()

    def test_offline_no_accept_and_stale_reply_never_retargets(self):
        self.down={'b'}
        with self.assertRaises(HubError):self.send('a','missing','b.cc')
        self.assertIsNone(self.hubs['a']._row('SELECT * FROM messages WHERE message_id="missing"'))
        self.down.clear();self.send('a','sent','b.cc')
        self.hubs['a'].dispatch(dict(op='endpoint_retire',host_id='a',host_token='a-token',endpoint_id='acc'))
        with self.assertRaises(HubError):self.send('b','reply',reply='sent',body='answer')
    def test_resolver_preserves_owner_rejection_without_accepting_or_retargeting(self):
        owner=self.hubs['b']
        owner.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='bcc'")
        with self.assertRaises(HubError) as caught:self.send('a','stale','b.cc')
        self.assertEqual(caught.exception.code,'endpoint_unavailable')
        self.assertIsNone(self.hubs['a']._row('SELECT * FROM messages WHERE message_id="stale"'))
        owner.db.execute("UPDATE endpoints SET retired=1 WHERE endpoint_id='bcc'")
        with self.assertRaises(HubError) as caught:self.send('a','absent','b.cc')
        self.assertEqual(caught.exception.code,'no_recipient')
        self.down={'c'}
        with self.assertRaises(HubError) as caught:self.send('a','mixed','b.cc')
        self.assertEqual(caught.exception.code,'host_unavailable')
        self.assertEqual(caught.exception.message,'remote destination unresolved: host_unavailable, no_recipient')

    def test_unknown_peer_cannot_inject(self):
        with self.assertRaises(HubError):self.hubs['b'].dispatch(dict(op='peer_directory',host_id='a',host_token='bad',protocol=1))

    def test_remote_cancel_reconnect_keeps_id_and_prevents_delivery(self):
        self.send('a','cancel-me','b.cc')
        self.down={'b'}
        req=dict(host_id='a',host_token='a-token',endpoint_id='acc',message_id='cancel-me')
        self.assertEqual(self.hubs['a'].cancel(req)['state'],'cancellation_pending')
        self.down.clear();self.hubs['a'].tick()
        self.assertEqual(self.hubs['b']._row('SELECT state FROM messages WHERE message_id=?',('cancel-me',))[0],'cancelled')
        self.assertEqual(self.send('a','cancel-me','b.cc')['state'],'cancelled')
        self.assertEqual(self.hubs['b'].claim(dict(host_id='b',host_token='b-token',endpoint_id='bcc'))['messages'],[])
        self.send('a','too-late','b.cc')
        self.hubs['b'].begin_present(dict(host_id='b',host_token='b-token',endpoint_id='bcc',message_id='too-late'))
        with self.assertRaisesRegex(HubError,'execution is not cancelled'):
            self.hubs['a'].cancel(dict(req,message_id='too-late'))

if __name__=='__main__':unittest.main()

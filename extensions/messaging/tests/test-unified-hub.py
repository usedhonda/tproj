#!/usr/bin/env python3
import contextlib, io, json, pathlib, socket, sys, tempfile, unittest, errno
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from extensions.messaging.unified import Hub, HubError
from extensions.messaging.unified.native_notice import content_digest
from extensions.messaging.unified.protocol import MAX_REQUEST, MAX_TTL, serve_socket, success, resource_error

class ProtocolTest(unittest.TestCase):
    def test_first_start_creates_socket_parent_before_lock(self):
        import subprocess, time
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            sock_path = root / "new" / "hub.sock"
            config = root / "hub.json"
            config.write_text(json.dumps({"hosts": {"fixture-host": "fixture-token"}}))
            # Provision the DB as runtime.setup does; socket parent remains absent.
            Hub(root / "hub.db", {"hosts": {"fixture-host": "fixture-token"}}).close()
            script = pathlib.Path(__file__).resolve().parents[1] / "unified/hub.py"
            proc = subprocess.Popen([sys.executable, str(script), "--config", str(config),
                                     "--socket", str(sock_path), "--db", str(root / "hub.db")],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not sock_path.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertIsNone(proc.poll(), "hub exited before creating its listener")
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(2); client.connect(str(sock_path))
                    client.sendall(b'{"op":"messaging_capabilities","host_id":"fixture-host","host_token":"fixture-token"}\n')
                    reply = json.loads(client.makefile("rb").readline())
                    self.assertTrue(reply["ok"])
                    self.assertIn("capabilities", reply["result"])
            finally:
                proc.terminate(); proc.wait(timeout=5)
                proc.stderr.close()

    def test_resource_error_is_errno_classified_and_sanitized(self):
        err = resource_error(OSError(errno.ENOSPC, 'private path'), 'local_persistence')
        self.assertEqual(err.code, 'resource_exhausted')
        self.assertEqual(err.details, {'failure_stage': 'local_persistence', 'acceptance': 'unknown'})
        self.assertIsNone(resource_error(OSError(errno.EIO, 'full word is not enough'), 'local_persistence'))
        self.assertIsNone(HubError('internal', 'x', {'secret': 'nope'}).details)

    def test_internal_error_reports_only_type_and_locations(self):
        server, client = socket.socketpair()
        class Listener:
            def __init__(self): self.accepted = False
            def accept(self):
                if self.accepted: raise StopIteration
                self.accepted = True
                return server, None
        calls = []
        def secret_handler(request):
            calls.append(request)
            raise RuntimeError('secret-exception-message ' + request['body'] + request['token'])
        output = io.StringIO()
        with client:
            client.sendall(b'{"body":"secret-body","token":"secret-token"}\n')
            with contextlib.redirect_stderr(output), self.assertRaises(StopIteration):
                serve_socket(Listener(), secret_handler)
            response = json.loads(client.recv(4096))
        self.assertEqual(len(calls), 1)
        self.assertEqual(response, {'ok': False, 'error': {'code': 'internal', 'message': 'hub internal error'}})
        diagnostic = json.loads(output.getvalue())
        self.assertEqual(set(diagnostic), {'error', 'type', 'frames'})
        self.assertEqual(diagnostic['type'], 'RuntimeError')
        self.assertEqual(diagnostic['error'], 'hub_internal_error')
        self.assertEqual([frame['file'] for frame in diagnostic['frames']], ['protocol.py', pathlib.Path(__file__).name])
        for frame in diagnostic['frames']:
            self.assertEqual(set(frame), {'file', 'line'})
            self.assertIsInstance(frame['line'], int)
            self.assertGreater(frame['line'], 0)
        for forbidden in ('secret-exception-message', 'secret-body', 'secret-token', 'raise RuntimeError', str(pathlib.Path(__file__).parent)):
            self.assertNotIn(forbidden, output.getvalue())

class HubTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.h=Hub(pathlib.Path(self.tmp.name)/"hub.db", {"admin_token":"adm","hosts":{"a":"ta","b":"tb"}})
        self.h.dispatch({"op":"directory_import","admin_token":"adm","projects":[{"project_id":"p","alias":"proj","host_id":"a","path":"/p"}]})
        self.h.db.execute("UPDATE participants SET host_id='b' WHERE participant_id='p:cdx'")
        self.reg("a","ta","ea","p:cc",1); self.reg("b","tb","eb","p:cdx",2)
    def attest(self, host, endpoint, native='native-thread'):
        return self.h.dispatch(dict(op='native_attest', host_id=host, host_token='t'+host,
                                    endpoint_id=endpoint, native_kind='thread_id', native_id=native))

    def test_sqlite_full_never_acknowledges_uncommitted_admission(self):
        import sqlite3
        import threading
        self.send('retained')
        retained = tuple(self.h.db.execute("SELECT * FROM messages WHERE message_id='retained'").fetchone())
        pages = self.h.db.execute('PRAGMA page_count').fetchone()[0]
        self.h.db.execute('PRAGMA max_page_count=' + str(pages))
        request = dict(op='submit', host_id='a', host_token='ta', message=dict(
            message_id='capacity-original', thread_id='t', sender_endpoint='ea',
            target='cdx', body='x' * 100000, kind='chat'))
        server, client = socket.socketpair()
        class Listener:
            accepted = False
            def accept(inner):
                if inner.accepted: raise StopIteration
                inner.accepted = True
                return server, None
        def serve_once():
            try: serve_socket(Listener(), self.h.dispatch)
            except StopIteration: pass
        worker = threading.Thread(target=serve_once, daemon=True)
        with contextlib.redirect_stderr(io.StringIO()):
            worker.start()
            with client:
                client.settimeout(5)
                client.sendall(json.dumps(request).encode() + b'\n')
                response = json.loads(client.recv(4096))
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(response['ok'])
        if sys.version_info >= (3, 11):
            self.assertEqual(response['error']['code'], 'resource_exhausted')
            self.assertEqual(response['error']['details']['acceptance'], 'unknown')
        else:
            # Older sqlite3 exceptions expose no numeric error code. Do not
            # infer exhaustion from text or misreport successful acceptance.
            self.assertEqual(response['error']['code'], 'internal')
        self.assertFalse(self.h.db.in_transaction)
        # A separate connection sees only the durable pre-existing original.
        with sqlite3.connect(self.h.db_path) as reader:
            self.assertEqual(reader.execute('SELECT message_id FROM messages').fetchall(), [('retained',)])
            self.assertEqual(reader.execute("SELECT * FROM messages WHERE message_id='retained'").fetchone(), retained)
        # Capacity recovery keeps the immutable ID; a repeated request cannot
        # duplicate acceptance even when the preceding success response is lost.
        self.h.db.execute('PRAGMA max_page_count=' + str(pages + 1000))
        self.assertEqual(self.h.dispatch(request), {'message_id': 'capacity-original', 'state': 'queued'})
        self.assertTrue(self.h.dispatch(request)['duplicate'])
        with sqlite3.connect(self.h.db_path) as reader:
            self.assertEqual(reader.execute("SELECT count(*) FROM messages WHERE message_id='capacity-original'").fetchone()[0], 1)

    def test_active_endpoint_list_excludes_large_retired_history_without_deletion(self):
        for n in range(1000):
            self.reg("a", "ta", "retired-" + str(n), "p:cc", n + 10)
            self.h.db.execute("UPDATE endpoints SET retired=1 WHERE endpoint_id=?", ("retired-" + str(n),))
        req = dict(op="endpoints_list", host_id="a", host_token="ta")
        full = self.h.dispatch(req)
        active = self.h.dispatch(dict(req, active_only=True))
        self.assertGreater(len(json.dumps(full).encode()), MAX_REQUEST)
        self.assertLess(len(json.dumps(active).encode()), MAX_REQUEST)
        self.assertEqual([e["endpoint_id"] for e in active["endpoints"]], ["ea"])
        self.assertEqual(len(self.h.dispatch(req)["endpoints"]), 1001)
        catalog = self.h.directory_list()
        self.assertLess(len(json.dumps(catalog).encode()), MAX_REQUEST)
        participant = next(p for p in catalog['participants'] if p['participant_id'] == 'p:cc')
        self.assertEqual([e['endpoint_id'] for e in participant['endpoints']], ['ea'])
        self.assertTrue(participant['online'])
        with self.assertRaises(HubError):
            self.h.dispatch(dict(req, active_only=True, host_token="wrong"))

    def test_read_only_hub_does_not_initialize_schema_and_reports_capabilities(self):
        path = pathlib.Path(self.tmp.name) / 'ro.db'
        import sqlite3
        sqlite3.connect(path).close()
        ro = Hub(path, {'admin_token': 'adm', 'hosts': {'a': 'ta'}}, read_only=True)
        self.addCleanup(ro.close)
        self.assertEqual(ro.dispatch({'op': 'messaging_capabilities', 'host_id': 'a', 'host_token': 'ta'})['capabilities'],
                         ['native_attest', 'native_continuity', 'read_only_diagnose', 'diagnostic_identity', 'resource_exhausted', 'send_targets_v1', 'native_begin_present', 'native_pending', 'native_drain', 'native_handoff', 'recipient_recovery_v1', 'recipient_native_continuity_v1', 'native_cc_v1'])
        self.assertEqual(ro.dispatch({'op': 'messaging_capabilities', 'host_id': 'a', 'host_token': 'ta'})['peers'], {})
        with self.assertRaises(HubError) as caught:
            ro.dispatch({'op': 'diagnose', 'host_id': 'a', 'host_token': 'ta', 'message_id': 'missing'})
        self.assertEqual(caught.exception.code, 'unavailable')
        self.assertEqual(sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_diagnostic_identity_is_host_scoped_and_excludes_message_bodies(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        result = self.h.dispatch({'op': 'diagnostic_identity', 'host_id': 'b', 'host_token': 'tb'})
        self.assertEqual(result['host_id'], 'b')
        self.assertEqual([row['endpoint_id'] for row in result['endpoints']], ['eb'])
        self.assertEqual(result['endpoint_native'][0]['native_id'], 'native-thread')
        self.assertNotIn('body', str(result))

    def test_active_identity_stays_bounded_without_deleting_history(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        for number in range(800):
            endpoint = 'retired-' + str(number)
            self.h.db.execute("INSERT INTO endpoints SELECT ?,participant_id,host_id,session,pane,pid,pid_start,runtime_id,platform,incarnation,last_heartbeat,1 FROM endpoints WHERE endpoint_id='eb'", (endpoint,))
            self.h.db.execute("INSERT INTO endpoint_native VALUES(?,?,?)", (endpoint, 'thread_id', 'retired-native'))
        req = dict(op='diagnostic_identity', host_id='b', host_token='tb')
        result = self.h.dispatch(dict(req, active_only=True))
        self.assertEqual([row['endpoint_id'] for row in result['endpoints']], ['eb'])
        self.assertEqual([row['endpoint_id'] for row in result['endpoint_native']], ['eb'])
        self.assertLess(len(json.dumps(success(result)).encode()), MAX_REQUEST)
        self.assertEqual(len(self.h.dispatch(req)['endpoints']), 801)
        before = self.h.db.total_changes
        scoped = self.h.dispatch(dict(req, endpoint_ids=['eb', 'retired-1', 'ea']))
        self.assertEqual([row['endpoint_id'] for row in scoped['endpoints']], ['eb', 'retired-1'])
        self.assertEqual([row['endpoint_id'] for row in scoped['endpoint_native']], ['eb', 'retired-1'])
        self.assertLess(len(json.dumps(success(scoped)).encode()), MAX_REQUEST)
        active = self.h.dispatch(dict(req, endpoint_ids=['eb', 'retired-1'], active_only=True))
        self.assertEqual([row['endpoint_id'] for row in active['endpoints']], ['eb'])
        for invalid in ([], ['x'] * 33, 'eb', [None]):
            with self.assertRaises(HubError):
                self.h.dispatch(dict(req, endpoint_ids=invalid))
        self.assertEqual(self.h.db.total_changes, before)

    def test_same_native_rotation_preserves_exact_query_and_reply(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        self.send()
        self.h.dispatch(dict(op='endpoint_retire', host_id='b', host_token='tb', endpoint_id='eb'))
        self.reg('b', 'tb', 'eb-new', 'p:cdx', 3)
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb-new'")
        self.attest('b', 'eb-new')
        queried = self.h.dispatch(dict(op='query', host_id='b', host_token='tb', endpoint_id='eb-new', message_id='m1'))
        self.assertEqual(queried['recipient_endpoint'], 'eb')
        self.assertTrue(queried['reader_is_recipient'])
        self.h.submit(dict(host_id='b', host_token='tb', message=dict(message_id='reply', sender_endpoint='eb-new', in_reply_to='m1', body='reply')))
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='reply'")[0], 'ea')
        self.h.close()
        self.h = Hub(pathlib.Path(self.tmp.name)/'hub.db', {'admin_token':'adm','hosts':{'a':'ta','b':'tb'}})
        self.assertTrue(self.h.dispatch(dict(op='query', host_id='b', host_token='tb', endpoint_id='eb-new', message_id='m1'))['reader_is_recipient'])

    def test_reply_evidence_survives_both_native_rotations(self):
        for host, endpoint in [('a', 'ea'), ('b', 'eb')]:
            self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id=?", (endpoint,))
            self.attest(host, endpoint)
        self.send()
        for host, endpoint, participant in [('a', 'ea', 'p:cc'), ('b', 'eb', 'p:cdx')]:
            self.h.dispatch(dict(op='endpoint_retire', host_id=host, host_token='t'+host, endpoint_id=endpoint))
            self.reg(host, 't'+host, endpoint+'-new', participant, 3)
            self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id=?", (endpoint+'-new',))
            self.attest(host, endpoint+'-new')
        self.h.submit(dict(host_id='b', host_token='tb', message=dict(
            message_id='rotated-reply', sender_endpoint='eb-new', in_reply_to='m1', body='reply')))
        original = self.h._row("SELECT * FROM messages WHERE message_id='m1'")
        before = self.h.db.total_changes
        self.assertEqual(self.h.response_evidence(original)['recipient_reply_message_ids'], ['rotated-reply'])
        self.assertEqual(self.h.db.total_changes, before)
        # Historical acceptance remains evidence even when both successors retire.
        for endpoint in ('ea-new', 'eb-new'):
            self.h.db.execute("UPDATE endpoints SET retired=1,last_heartbeat=0 WHERE endpoint_id=?", (endpoint,))
        self.assertEqual(self.h.response_evidence(original)['recipient_reply_count'], 1)
        for column, value in [('thread_id', 'wrong'), ('sender_endpoint', 'ea-new'),
                              ('recipient_endpoint', 'eb-new')]:
            row = self.h._row("SELECT * FROM messages WHERE message_id='rotated-reply'")
            self.h.db.execute('UPDATE messages SET '+column+'=? WHERE message_id=?', (value, 'rotated-reply'))
            self.assertEqual(self.h.response_evidence(original)['recipient_reply_count'], 0)
            self.h.db.execute('UPDATE messages SET '+column+'=? WHERE message_id=?', (row[column], 'rotated-reply'))

    def test_native_rotation_unknown_different_ambiguous_and_stale_reject(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        self.send()
        self.h.dispatch(dict(op='endpoint_retire', host_id='b', host_token='tb', endpoint_id='eb'))
        self.reg('b', 'tb', 'eb-new', 'p:cdx', 3)
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb-new'")
        query = dict(op='query', host_id='b', host_token='tb', endpoint_id='eb-new', message_id='m1')
        with self.assertRaises(HubError): self.h.dispatch(query)
        self.attest('b', 'eb-new', 'different-thread')
        with self.assertRaises(HubError): self.h.dispatch(query)
        with self.assertRaises(HubError): self.attest('b', 'eb-new')
        self.reg('b', 'tb', 'same', 'p:cdx', 4)
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='same'")
        self.attest('b', 'same')
        query['endpoint_id'] = 'same'
        # A distinct native conversation cannot disable this exact native's history.
        self.assertTrue(self.h.dispatch(query)['reader_is_recipient'])
        self.h.dispatch(dict(op='endpoint_retire', host_id='b', host_token='tb', endpoint_id='eb-new'))
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='same'")
        with self.assertRaises(HubError): self.h.dispatch(query)

    def tearDown(self): self.h.close(); self.tmp.cleanup()
    def reg(self,h,t,e,p,pid): return self.h.dispatch({"op":"endpoint_register","host_id":h,"host_token":t,"endpoint_id":e,"participant_id":p,"host_id":h,"session":"s","pane":"0","pid":pid,"pid_start":"x","runtime_id":"r","platform":"test"})
    def send(self,mid="m1",body="hello",target="cdx"):
        return self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":mid,"thread_id":"t","sender_endpoint":"ea","target":target,"body":body,"kind":"chat"}})
    def test_receipt_transaction_rechecks_cancel_and_retired_owner(self):
        peer = Hub(self.h.db_path, self.h.config)
        self.addCleanup(peer.close)
        for action, terminal, code in [('cancel', 'cancelled', 'terminal_message'),
                                       ('endpoint_retire', 'stale_session', 'stale_session')]:
            with self.subTest(action=action):
                mid = 'receipt-race-' + action
                self.send(mid)
                original_tx = self.h._tx
                def concurrent_change():
                    if action == 'cancel':
                        peer.dispatch(dict(op=action, host_id='a', host_token='ta',
                                           endpoint_id='ea', message_id=mid))
                    else:
                        peer.dispatch(dict(op=action, host_id='b', host_token='tb', endpoint_id='eb'))
                    original_tx()
                self.h._tx = concurrent_change
                try:
                    with self.assertRaises(HubError) as caught:
                        self.h.dispatch(dict(op='receipt', host_id='b', host_token='tb',
                                             endpoint_id='eb', message_id=mid, state='presented'))
                    self.assertEqual(caught.exception.code, code)
                finally:
                    self.h._tx = original_tx
                self.assertEqual(peer._row('SELECT state FROM messages WHERE message_id=?', (mid,))[0], terminal)
                self.assertIsNone(peer._row('SELECT * FROM receipts WHERE message_id=?', (mid,)))
                self.assertFalse(self.h.db.in_transaction)

    def handoff_fixture(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        self.reg('b', 'tb', 'eb-new', 'p:cdx', 3)
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb-new'")
        self.attest('b', 'eb-new')
        old = dict(self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb'"))
        new = dict(self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb-new'"))
        request = dict(host_id='b', host_token='tb', old_endpoint='eb', new_endpoint='eb-new',
                       old_incarnation=old['incarnation'], new_incarnation=new['incarnation'],
                       native_kind='thread_id', native_id='native-thread')
        proof = {k: old[k] for k in ('endpoint_id', 'incarnation', 'pid', 'pid_start')}
        proof['reason'] = 'pid_absent'  # Trusted Host input ONLY; OS proof is a separate acceptance.
        return request, proof

    def test_native_handoff_core_preserves_originals_and_excludes_irreversible_states(self):
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        old_incarnation = self.h._row("SELECT incarnation FROM endpoints WHERE endpoint_id='eb'")[0]
        for mid in ('pending', 'pending-second', 'cancelled', 'reserved', 'unknown', 'presented', 'replied'):
            self.send(mid)
        self.h.dispatch(dict(op='cancel', host_id='a', host_token='ta', endpoint_id='ea', message_id='cancelled'))
        self.h.dispatch(dict(op='native_begin_present', host_id='b', host_token='tb', endpoint_id='eb',
                             message_id='reserved', incarnation=old_incarnation, native_kind='thread_id',
                             native_id='native-thread', content_hash=content_digest(dict(self.h._row("SELECT * FROM messages WHERE message_id='reserved'")))))
        for mid, state in [('unknown', 'uncertain'), ('presented', 'presented')]:
            self.h.dispatch(dict(op='receipt', host_id='b', host_token='tb', endpoint_id='eb', message_id=mid, state=state))
        self.h.dispatch(dict(op='submit', host_id='a', host_token='ta', message=dict(
            message_id='expired', sender_endpoint='ea', target='cdx', body='expired', ttl_sec=1)))
        self.h.dispatch(dict(op='submit', host_id='b', host_token='tb', message=dict(
            message_id='old-owner-reply', sender_endpoint='eb', in_reply_to='replied', thread_id='t', body='received')))
        clock = self.h._now() + 2
        self.h._now = lambda: clock
        before = [tuple(row) for row in self.h.db.execute('SELECT * FROM messages ORDER BY message_id')]
        request, proof = self.handoff_fixture()
        result = self.h._handoff_native_delivery(request, dead_owner=proof)
        self.assertEqual(result['transferred'], 2)
        self.assertEqual([tuple(row) for row in self.h.db.execute('SELECT * FROM messages ORDER BY message_id')], before)
        owner = dict(self.h._row("SELECT * FROM native_delivery_owners WHERE message_id='pending'"))
        self.assertEqual((owner['original_recipient'], owner['actor_endpoint'], owner['generation']), ('eb', 'eb-new', 1))
        self.assertEqual(owner['content_hash'], content_digest(dict(self.h._row("SELECT * FROM messages WHERE message_id='pending'"))))
        self.assertEqual(self.h._row('SELECT count(*) FROM native_delivery_owners')[0], 2)
        self.assertTrue(self.h._handoff_native_delivery(request, dead_owner=proof)['duplicate'])
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='eb'")[0], 1)
        with self.assertRaises(HubError) as late:
            self.h.dispatch(dict(op='native_begin_present', host_id='b', host_token='tb', endpoint_id='eb',
                                 message_id='pending', incarnation=proof['incarnation'], native_kind='thread_id',
                                 native_id='native-thread', content_hash=owner['content_hash']))
        self.assertEqual(late.exception.code, 'stale_session')
        # Owner-service operation requires authenticated death evidence; a
        # previously completed exact request remains idempotent.
        self.assertTrue(self.h.dispatch(dict(request, op='native_handoff', dead_owner=proof))['duplicate'])
        self.h.dispatch(dict(op='submit', host_id='b', host_token='tb', message=dict(
            message_id='successor-reply', sender_endpoint='eb-new', in_reply_to='pending', thread_id='t', body='received')))
        self.h.dispatch(dict(op='submit', host_id='b', host_token='tb', message=dict(
            message_id='successor-second-reply', sender_endpoint='eb-new', in_reply_to='pending-second', thread_id='t', body='received')))
        self.reg('b', 'tb', 'eb-next', 'p:cdx', 4)
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb-next'")
        self.attest('b', 'eb-next')
        successor = dict(self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb-new'"))
        next_owner = dict(self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb-next'"))
        next_request = dict(request, old_endpoint='eb-new', new_endpoint='eb-next',
                            old_incarnation=successor['incarnation'], new_incarnation=next_owner['incarnation'])
        next_proof = {k: successor[k] for k in ('endpoint_id', 'incarnation', 'pid', 'pid_start')}
        next_proof['reason'] = 'pid_absent'
        self.assertEqual(self.h._handoff_native_delivery(next_request, dead_owner=next_proof)['transferred'], 0)
        self.assertEqual(self.h._row("SELECT generation FROM native_delivery_owners WHERE message_id='pending'")[0], 1)

    def test_native_handoff_core_rejects_unproved_or_ambiguous_continuity(self):
        self.send('untouched')
        request, proof = self.handoff_fixture()
        for change, evidence in [(dict(native_id='other-native'), proof), ({}, {}),
                                 (dict(old_incarnation='stale'), proof),
                                 ({}, dict(proof, reason='pid_start_changed', observed_pid_start=proof['pid_start']))]:
            with self.subTest(change=change, evidence=evidence):
                with self.assertRaises(HubError):
                    self.h._handoff_native_delivery(dict(request, **change), dead_owner=evidence)
        self.reg('b', 'tb', 'third', 'p:cdx', 4)
        with self.assertRaises(HubError) as ambiguous:
            self.h._handoff_native_delivery(request, dead_owner=proof)
        self.assertEqual(ambiguous.exception.code, 'ambiguous_target')
        self.assertEqual(self.h._row('SELECT count(*) FROM native_delivery_owners')[0], 0)
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='eb'")[0], 0)
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='untouched'")[0], 'eb')

    def test_native_handoff_core_does_not_transfer_a_different_actor_generation(self):
        self.send('stale-generation')
        request, proof = self.handoff_fixture()
        original = dict(self.h._row("SELECT * FROM messages WHERE message_id='stale-generation'"))
        # Defensive inconsistent-generation fixture, not proof that ordinary
        # register can reuse an existing immutable endpoint incarnation.
        self.h.db.execute('INSERT INTO native_delivery_owners VALUES(?,?,?,?,?,?)',
                          ('stale-generation', 'eb', 'eb', 'earlier-incarnation', content_digest(original), 1))
        owner = tuple(self.h._row("SELECT * FROM native_delivery_owners WHERE message_id='stale-generation'"))
        self.assertEqual(self.h._handoff_native_delivery(request, dead_owner=proof)['transferred'], 0)
        self.assertEqual(tuple(self.h._row("SELECT * FROM native_delivery_owners WHERE message_id='stale-generation'")), owner)
        self.assertEqual(dict(self.h._row("SELECT * FROM messages WHERE message_id='stale-generation'")), original)

    def test_transferred_native_actor_claim_pending_reservation_and_receipt(self):
        self.send('actor-original')
        request, proof = self.handoff_fixture()
        original = dict(self.h._row("SELECT * FROM messages WHERE message_id='actor-original'"))
        self.h._handoff_native_delivery(request, dead_owner=proof)
        actor = dict(host_id='b', host_token='tb', endpoint_id='eb-new')
        native = dict(actor, incarnation=request['new_incarnation'], native_kind='thread_id', native_id='native-thread')
        pending = self.h.dispatch(dict(native, op='native_pending'))
        self.assertTrue(pending['wake_needed'])
        claim = self.h.dispatch(dict(actor, op='claim'))['messages']
        self.assertEqual([m['message_id'] for m in claim], ['actor-original'])
        self.assertEqual(claim[0]['recipient_endpoint'], 'eb')
        actor_view = claim[0]['delivery_actor']
        self.assertEqual((actor_view['endpoint_id'], actor_view['incarnation'], actor_view['generation']),
                         ('eb-new', request['new_incarnation'], 1))
        self.assertEqual(actor_view['content_hash'], content_digest(original))
        queried = self.h.dispatch(dict(actor, op='query', message_id='actor-original'))
        self.assertEqual(queried['delivery_actor'], actor_view)
        self.assertEqual(content_digest(queried), content_digest(original))
        with self.assertRaises(HubError):
            self.h.dispatch(dict(actor, op='begin_present', message_id='actor-original'))
        with self.assertRaises(HubError):
            self.h.dispatch(dict(actor, op='native_begin_present', message_id='actor-original',
                                 incarnation=proof['incarnation'], native_kind='thread_id', native_id='native-thread',
                                 content_hash=content_digest(original)))
        reserved = self.h.dispatch(dict(native, op='native_begin_present', message_id='actor-original', content_hash=content_digest(original)))
        self.assertEqual(reserved['endpoint_id'], 'eb-new')
        for invalid in (actor, dict(native, incarnation='stale')):
            with self.assertRaises(HubError):
                self.h.dispatch(dict(invalid, op='receipt', message_id='actor-original', state='presented'))
        self.h.dispatch(dict(native, op='receipt', message_id='actor-original', state='presented'))
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='actor-original'")[0], 'presented')
        for key in ('recipient_endpoint', 'body', 'payload_hash', 'expires_at'):
            self.assertEqual(self.h._row("SELECT * FROM messages WHERE message_id='actor-original'")[key], original[key])
        self.assertFalse(self.h.dispatch(dict(native, op='native_pending'))['pending'])
        for op in ('claim', 'receipt', 'native_begin_present'):
            with self.subTest(op=op), self.assertRaises(HubError) as stale:
                self.h.dispatch(dict(native, op=op, endpoint_id='eb', message_id='actor-original', state='presented', content_hash=content_digest(original)))
            self.assertEqual(stale.exception.code, 'stale_session')

    def test_transferred_presented_receipt_requires_native_reservation(self):
        self.send('unreserved-actor')
        request, proof = self.handoff_fixture()
        self.h._handoff_native_delivery(request, dead_owner=proof)
        actor = dict(host_id='b', host_token='tb', endpoint_id='eb-new')
        native = dict(actor, incarnation=request['new_incarnation'], native_kind='thread_id', native_id='native-thread')
        for fields in (actor, native):
            with self.subTest(fields=fields), self.assertRaises(HubError):
                self.h.dispatch(dict(fields, op='receipt', message_id='unreserved-actor', state='presented'))
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='unreserved-actor'")[0], 'accepted')
        self.h.dispatch(dict(native, op='receipt', message_id='unreserved-actor', state='uncertain'))
        with self.assertRaises(HubError):
            self.h.dispatch(dict(native, op='receipt', message_id='unreserved-actor', state='presented'))
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='unreserved-actor'")[0], 'uncertain')

    def test_transferred_actor_reply_and_old_sequence_do_not_lose_wake(self):
        self.send('older-original')
        request, proof = self.handoff_fixture()
        actor = dict(host_id='b', host_token='tb', endpoint_id='eb-new')
        native = dict(actor, incarnation=request['new_incarnation'], native_kind='thread_id', native_id='native-thread')
        # A new endpoint may already have drained a newer original before an
        # older row is assigned. Pending truth must not be hidden by that cursor.
        self.h.db.execute("INSERT INTO metadata(key,value) VALUES(?,?)", ('native_drained:eb-new', '999'))
        self.h._handoff_native_delivery(request, dead_owner=proof)
        self.assertTrue(self.h.dispatch(dict(native, op='native_pending'))['wake_needed'])
        self.h.dispatch(dict(actor, op='submit', message=dict(message_id='actor-response', sender_endpoint='eb-new',
                             in_reply_to='older-original', thread_id='t', body='received')))
        self.assertFalse(self.h.dispatch(dict(native, op='native_pending'))['pending'])
        self.assertEqual(self.h.dispatch(dict(actor, op='claim'))['messages'], [])
        with self.assertRaises(HubError) as replied:
            self.h.dispatch(dict(native, op='native_begin_present', message_id='older-original',
                                 content_hash=content_digest(dict(self.h._row("SELECT * FROM messages WHERE message_id='older-original'")))))
        self.assertEqual(replied.exception.code, 'presentation_unavailable')

    def test_native_handoff_core_rolls_back_owner_and_retirement_together(self):
        self.send('pending')
        request, proof = self.handoff_fixture()
        commit = self.h._commit
        self.h._commit = lambda: (_ for _ in ()).throw(RuntimeError('injected precommit failure'))
        try:
            with self.assertRaises(RuntimeError):
                self.h._handoff_native_delivery(request, dead_owner=proof)
        finally:
            self.h._commit = commit
        self.assertFalse(self.h.db.in_transaction)
        self.assertEqual(self.h._row('SELECT count(*) FROM native_delivery_owners')[0], 0)
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='eb'")[0], 0)
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='pending'")[0], 'accepted')

    def test_claim_sequence_passes_old_pending_and_wraps_without_replay(self):
        self.send('old')
        self.send('new')
        receiver = dict(op='claim', host_id='b', host_token='tb', endpoint_id='eb', limit=1)
        first = self.h.dispatch(dict(receiver, after_sequence=0))
        second = self.h.dispatch(dict(receiver, after_sequence=first['next_sequence']))
        self.assertEqual([m['message_id'] for m in first['messages']], ['old'])
        self.assertEqual([m['message_id'] for m in second['messages']], ['new'])
        empty = self.h.dispatch(dict(receiver, after_sequence=second['next_sequence']))
        self.assertEqual(empty, {'messages': [], 'next_sequence': 0})
        self.assertEqual(self.h.dispatch(dict(receiver, after_sequence=0))['messages'][0]['message_id'], 'old')
        # Claim is adapter custody, never presentation or permission to replay.
        self.assertEqual(self.h.db.execute("SELECT state FROM messages WHERE message_id='old'").fetchone()[0], 'adapter_received')
        before = self.h.db.total_changes
        for invalid in (True, -1, '1', [], 2**63):
            with self.assertRaises(HubError): self.h.dispatch(dict(receiver, after_sequence=invalid))
        self.assertEqual(self.h.db.total_changes, before)
        with self.assertRaises(HubError):
            self.h.dispatch(dict(receiver, host_id='a', host_token='ta', after_sequence=0))

    def test_claim_probe_filtered_page_is_not_scan_end(self):
        self.send('excluded')
        self.send('allowed')
        self.h.config['probe_message_ids'] = ['allowed']
        self.h.db.execute("UPDATE metadata SET value='probe' WHERE key='maintenance'")
        self.h.db.commit()
        receiver = dict(op='claim', host_id='b', host_token='tb', endpoint_id='eb', limit=1)
        first = self.h.dispatch(dict(receiver, after_sequence=0))
        self.assertEqual(first['messages'], [])
        self.assertGreater(first['next_sequence'], 0)
        second = self.h.dispatch(dict(receiver, after_sequence=first['next_sequence']))
        self.assertEqual([m['message_id'] for m in second['messages']], ['allowed'])

    def test_native_pending_insert_between_empty_and_drain_and_restart(self):
        self.h._now = lambda: 1000.0
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        ep = self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb'")
        req = dict(host_id='b', host_token='tb', endpoint_id='eb', incarnation=ep['incarnation'],
                   native_kind='thread_id', native_id='native-thread')
        self.send('first')
        first = self.h.dispatch(dict(req, op='native_pending'))
        self.assertTrue(first['wake_needed'])
        self.assertEqual(first['oldest_pending_age_seconds'], 0.0)
        self.assertFalse(self.h.dispatch(dict(req, op='native_drain', generation=first['generation']))['cleared'])
        self.h.db.execute("UPDATE messages SET state='dispatching' WHERE message_id='first'")
        empty = self.h.dispatch(dict(req, op='native_pending'))
        self.assertFalse(empty['pending'])
        self.assertIsNone(empty['oldest_pending_age_seconds'])
        self.send('second')
        stale = self.h.dispatch(dict(req, op='native_drain', generation=empty['generation']))
        self.assertFalse(stale['cleared'])
        self.assertTrue(stale['wake_needed'])
        # A new Hub connection represents consumer crash/restart; wake survives.
        reopened = Hub(self.h.db_path, self.h.config)
        try:
            reopened._now = self.h._now
            self.assertEqual(reopened.dispatch(dict(req, op='native_pending')), {k:v for k,v in stale.items() if k!='cleared'})
            reopened.db.execute("UPDATE messages SET state='dispatching' WHERE message_id='second'")
            cleared = reopened.dispatch(dict(req, op='native_drain', generation=stale['generation']))
            self.assertTrue(cleared['cleared'])
            self.assertEqual(cleared['generation'], cleared['drained_generation'])
            # The other ordering: arrival immediately after a committed drain.
            self.send('third')
            after_clear = reopened.dispatch(dict(req, op='native_pending'))
            self.assertTrue(after_clear['wake_needed'])
            self.assertGreater(after_clear['generation'], after_clear['drained_generation'])
            before = reopened.db.total_changes
            with self.assertRaises(HubError): reopened.dispatch(dict(req, op='native_drain', native_id='other', generation=stale['generation']))
            with self.assertRaises(HubError): reopened.dispatch(dict(req, op='native_drain', host_id='a', host_token='ta', generation=stale['generation']))
            self.assertEqual(reopened.db.total_changes, before)
        finally: reopened.close()

    def test_native_capabilities_are_authenticated_and_read_only(self):
        before = self.h.db.total_changes
        result = self.h.dispatch(dict(op='messaging_capabilities', host_id='b', host_token='tb'))
        self.assertEqual(result['native_runtime'], {'hub_version': 3})
        self.assertTrue({'native_begin_present', 'native_pending', 'native_drain'} <= set(result['capabilities']))
        with self.assertRaises(HubError):
            self.h.dispatch(dict(op='messaging_capabilities', host_id='b', host_token='wrong'))
        self.assertEqual(self.h.db.total_changes, before)

    def test_diagnosis_is_metadata_only_and_operator_permission_is_explicit(self):
        self.send(body='private-body-sentinel')
        self.h.dispatch({'op':'directory_import','admin_token':'adm','projects':[{'project_id':'support','alias':'support','host_id':'a','path':'/support'}]})
        self.reg('a','ta','support-ep','support:cc',3)
        request={'op':'diagnose','host_id':'a','host_token':'ta','endpoint_id':'support-ep','message_id':'m1','operator_diagnostic':True}
        with self.assertRaises(HubError):self.h.dispatch(request)
        self.h.config['diagnostic_hosts']=['a']
        before=self.h.db.total_changes
        result=self.h.dispatch(request)
        self.assertEqual(self.h.db.total_changes,before)
        recipient_request={'op':'diagnose','host_id':'b','host_token':'tb','endpoint_id':'eb','message_id':'m1'}
        recipient_result=self.h.dispatch(recipient_request)
        inbox=self.h.dispatch({'op':'inbox','host_id':'b','host_token':'tb','endpoint_id':'eb'})
        self.assertIsInstance(recipient_result['sequence'],int)
        self.assertEqual(recipient_result['message_id'],inbox['messages'][0]['message_id'])
        self.assertEqual(recipient_result['sequence'],inbox['messages'][0]['sequence'])
        self.assertEqual(result['sequence'],recipient_result['sequence'])
        self.assertNotIn('body',result)
        self.assertNotIn('payload_hash',result)
        self.assertNotIn('private-body-sentinel',str(result))
        self.assertFalse(result['presentation_confirmed'])
        self.assertIsNone(result['delivery_reason'])

    def test_waiting_summary_uses_observed_reason_and_own_age_without_writes(self):
        now = [1000.0]
        self.h._now = lambda: now[0]
        self.send('wait-age')
        now[0] = 1007.0
        self.h.dispatch(dict(op='delivery_status', host_id='b', host_token='tb',
                             endpoint_id='eb', message_id='wait-age', reason='busy'))
        now[0] = 1020.0
        request = dict(host_id='a', host_token='ta', endpoint_id='ea', message_id='wait-age')
        before = self.h.db.total_changes
        message = self.h.dispatch(dict(request, op='query'))
        diagnostic = self.h.dispatch(dict(request, op='diagnose'))
        self.assertEqual(message['delivery_summary'], diagnostic['delivery_summary'])
        summary = message['delivery_summary']
        self.assertEqual((summary['reason'], summary['pending_age_seconds'], summary['reason_observed_at']),
                         ('busy', 20.0, 1007.0))
        self.assertNotIn('oldest_pending_age_seconds', summary, 'sender must not learn other senders activity')
        self.assertEqual(self.h.db.total_changes, before)
        now[0] = 1021.0
        self.h.dispatch(dict(op='delivery_status', host_id='b', host_token='tb',
                             endpoint_id='eb', message_id='wait-age', reason='busy'))
        self.assertEqual(self.h.dispatch(dict(request, op='query'))['delivery_summary']['pending_age_seconds'], 21.0)
        self.h.db.execute("UPDATE endpoints SET incarnation='replacement' WHERE endpoint_id='eb'")
        stale = self.h.dispatch(dict(request, op='query'))['delivery_summary']
        self.assertEqual(stale['reason'], 'pending')
        self.assertIsNone(stale['reason_observed_at'])
        self.h.db.execute("UPDATE messages SET state='uncertain' WHERE message_id='wait-age'")
        unknown = self.h.dispatch(dict(request, op='query'))['delivery_summary']
        self.assertEqual(unknown['reason'], 'presentation_outcome_unknown')
        self.assertIsNone(unknown['pending_age_seconds'])
        self.assertIsNone(unknown['reason_observed_at'])

    def test_native_wait_observation_requires_current_binding(self):
        self.h._now = lambda: 1000.0
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        self.send('native-status')
        ep = self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb'")
        observed = dict(incarnation=ep['incarnation'], native_kind='thread_id', native_id='native-thread',
                        attempt='publication-attempt', generation='publisher-generation')
        req = dict(op='delivery_status', host_id='b', host_token='tb', endpoint_id='eb',
                   message_id='native-status', reason='native_queue_accepted', native_observation=observed)
        self.h.dispatch(req)
        reader = dict(op='query', host_id='a', host_token='ta', endpoint_id='ea', message_id='native-status')
        self.assertEqual(self.h.dispatch(reader)['delivery_summary']['reason'], 'native_queue_accepted')
        self.h.db.execute("UPDATE endpoint_native SET native_id='replacement-thread' WHERE endpoint_id='eb'")
        self.assertEqual(self.h.dispatch(reader)['delivery_summary']['reason'], 'pending')
        before = self.h.db.total_changes
        with self.assertRaises(HubError): self.h.dispatch(req)
        self.assertEqual(self.h.db.total_changes, before)

    def test_delivery_summary_preserves_expired_unknown_and_late_evidence(self):
        self.h._now = lambda: 1000.0
        cases = [
            ('dispatching', True, True, False, 'action_required', 'ttl_elapsed', 'ttl_elapsed_outcome_unknown'),
            ('uncertain', True, False, False, 'action_required', 'ttl_elapsed', 'ttl_elapsed_outcome_unknown'),
            ('accepted', False, False, False, 'waiting', 'active', 'pending'),
            ('accepted', True, False, False, 'action_required', 'ttl_elapsed', 'ttl_elapsed_before_presentation'),
            ('queued', True, False, False, 'action_required', 'ttl_elapsed', 'ttl_elapsed_before_presentation'),
            ('adapter_received', True, False, False, 'action_required', 'ttl_elapsed', 'ttl_elapsed_before_presentation'),
            ('accepted', False, False, True, 'recipient_replied', 'active', 'recipient_replied'),
            ('presented', False, False, True, 'recipient_replied', 'active', 'recipient_replied'),
            ('presented', True, False, True, 'recipient_replied', 'ttl_elapsed', 'ttl_elapsed_with_reply'),
            ('accepted', False, True, False, 'action_required', 'active', 'pinned_recipient_unavailable'),
            ('cancelled', False, False, True, 'action_required', 'cancelled', 'cancelled_with_reply'),
            ('expired', True, False, True, 'action_required', 'expired', 'expired_with_reply'),
            ('dispatching', True, False, True, 'recipient_replied', 'ttl_elapsed', 'ttl_elapsed_with_reply'),
        ]
        for i, (state, elapsed, retired, replied, status, lifecycle, reason) in enumerate(cases):
            with self.subTest(state=state, elapsed=elapsed, retired=retired, replied=replied):
                self.h.db.execute("UPDATE endpoints SET retired=0 WHERE endpoint_id='eb'")
                mid = 'summary-' + str(i)
                self.send(mid)
                if replied:
                    self.h.dispatch({'op':'submit','host_id':'b','host_token':'tb','message':{
                        'message_id':'reply-' + mid,'in_reply_to':mid,'sender_endpoint':'eb',
                        'body':'reply','kind':'chat'}})
                self.h.db.execute('UPDATE messages SET state=?,expires_at=? WHERE message_id=?',
                                  (state, self.h._now() + (-10 if elapsed else 100), mid))
                self.h.db.execute("UPDATE endpoints SET retired=? WHERE endpoint_id='eb'", (int(retired),))
                before = self.h.db.total_changes
                req = {'host_id':'a','host_token':'ta','endpoint_id':'ea','message_id':mid}
                diagnostic = self.h.dispatch(dict(req, op='diagnose'))
                message = self.h.dispatch(dict(req, op='query'))
                self.assertEqual(self.h.db.total_changes, before)
                self.assertEqual(message['state'], state)
                self.assertEqual(diagnostic['delivery_summary'], message['delivery_summary'])
                summary = message['delivery_summary']
                self.assertEqual((summary['status'], summary['lifecycle'], summary['reason']),
                                 (status, lifecycle, reason))
                self.assertEqual(summary['ttl_elapsed'], elapsed)
                self.assertEqual(summary['presentation_confirmed'], state == 'presented')
                self.assertEqual(summary['new_presentation_eligible'],
                                 state == 'accepted' and not elapsed and not retired and not replied)
                self.assertEqual(message['recipient_reply_count'], int(replied))
        self.h.db.execute("UPDATE endpoints SET retired=0 WHERE endpoint_id='eb'")
        self.send('late')
        recipient = {'host_id':'b','host_token':'tb','endpoint_id':'eb','message_id':'late'}
        self.h.dispatch(dict(recipient, op='begin_present'))
        self.h.db.execute("UPDATE messages SET expires_at=0 WHERE message_id='late'")
        self.h.dispatch(dict(recipient, op='receipt', state='presented', evidence='fixture'))
        message = self.h.dispatch({'op':'query','host_id':'a','host_token':'ta',
                                   'endpoint_id':'ea','message_id':'late'})
        self.assertEqual(message['state'], 'presented')
        self.assertEqual(message['delivery_summary']['status'], 'presentation_confirmed')
        self.assertEqual(message['delivery_summary']['lifecycle'], 'ttl_elapsed')
        self.assertFalse(message['delivery_summary']['new_presentation_eligible'])

    def test_expired_query_rejection_is_read_only_for_nonparty(self):
        self.send('private-expired')
        self.h.db.execute("UPDATE messages SET expires_at=0 WHERE message_id='private-expired'")
        self.h.dispatch({'op':'directory_import','admin_token':'adm','projects':[
            {'project_id':'outsider','alias':'outsider','host_id':'a','path':'/outsider'}]})
        self.reg('a','ta','outsider-ep','outsider:cc',3)
        before = self.h.db.total_changes
        with self.assertRaises(HubError) as rejected:
            self.h.dispatch({'op':'query','host_id':'a','host_token':'ta',
                             'endpoint_id':'outsider-ep','message_id':'private-expired'})
        self.assertEqual(rejected.exception.code, 'unauthorized')
        self.assertEqual(self.h.db.total_changes, before)
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='private-expired'")['state'], 'accepted')
        recipient = {'host_id':'b','host_token':'tb','endpoint_id':'eb'}
        self.assertEqual(self.h.dispatch(dict(recipient, op='claim'))['messages'], [])
        with self.assertRaises(HubError) as expired:
            self.h.dispatch(dict(recipient, op='begin_present', message_id='private-expired'))
        self.assertEqual(expired.exception.code, 'expired')
        self.assertEqual(self.h.db.total_changes, before)

    def test_diagnosis_keeps_linked_reply_separate_from_receipt(self):
        self.send()
        self.h.dispatch({'op':'submit','host_id':'b','host_token':'tb','message':{
            'message_id':'reply-1','in_reply_to':'m1','sender_endpoint':'eb',
            'body':'private-reply-sentinel','kind':'chat'}})
        self.h.db.execute("UPDATE messages SET state='uncertain' WHERE message_id='m1'")
        before = self.h.db.total_changes
        result = self.h.dispatch({'op':'diagnose','host_id':'a','host_token':'ta',
                                  'endpoint_id':'ea','message_id':'m1'})
        self.assertEqual(self.h.db.total_changes, before)
        self.assertEqual(result['state'], 'uncertain')
        self.assertFalse(result['presentation_confirmed'])
        self.assertIsNone(result['receipt_state'])
        self.assertEqual(result['reply_count'], 1)
        self.assertEqual(result['reply_message_ids'], ['reply-1'])
        self.assertEqual(result['response_state'], 'recipient_replied')
        self.assertEqual(result['recipient_reply_message_ids'], ['reply-1'])
        self.assertEqual(result['recipient_reply_count'], 1)
        self.h.db.execute("UPDATE messages SET thread_id='other-thread' WHERE message_id='reply-1'")
        wrong = self.h.dispatch({'op':'diagnose','host_id':'a','host_token':'ta',
                                'endpoint_id':'ea','message_id':'m1'})
        self.assertEqual(wrong['response_state'], 'unconfirmed')
        self.h.db.execute("UPDATE messages SET thread_id='m1',sender_endpoint='ea' WHERE message_id='reply-1'")
        wrong = self.h.dispatch({'op':'diagnose','host_id':'a','host_token':'ta',
                                'endpoint_id':'ea','message_id':'m1'})
        self.assertEqual(wrong['recipient_reply_count'], 0)

        self.assertNotIn('private-reply-sentinel', str(result))

    def test_durable_idempotency_and_relative_route(self):
        self.assertEqual(self.send(), {"message_id":"m1","state":"queued"})
        self.assertTrue(self.send()["duplicate"])
        with self.assertRaisesRegex(HubError,"different payload"): self.send(body="changed")
        inbox=self.h.dispatch({"op":"inbox","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        self.assertEqual(inbox["messages"][0]["recipient_endpoint"],"eb")
    def test_query_by_id_carries_the_resolved_sender_address(self):
        self.send()
        inbox=self.h.dispatch({"op":"inbox","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        one=self.h.dispatch({"op":"query","host_id":"b","host_token":"tb","endpoint_id":"eb","message_id":"m1"})
        self.assertEqual(one["sender_address"],"proj.cc")
        self.assertEqual(one["sender_address"],inbox["messages"][0]["sender_address"])

    def test_inbox_notice_is_bounded_metadata_only_and_does_not_present(self):
        self.send(mid="notice-1", body="private-body-sentinel")
        before = self.h.db.total_changes
        result = self.h.dispatch({"op":"inbox_notice", "host_id":"b", "host_token":"tb", "endpoint_id":"eb"})
        self.assertEqual([item["message_id"] for item in result["messages"]], ["notice-1"])
        self.assertEqual(result["messages"][0]["sender_address"], "proj.cc")
        self.assertNotIn("body", result["messages"][0])
        self.assertNotIn("private-body-sentinel", str(result))
        self.assertEqual(self.h.db.total_changes, before)
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='notice-1'")[0], "accepted")

    def test_inbox_notice_excludes_reply_to_message_already_received(self):
        self.send(mid="notice-original")
        self.h.dispatch({"op":"claim", "host_id":"b", "host_token":"tb", "endpoint_id":"eb"})
        self.h.dispatch({"op":"submit", "host_id":"b", "host_token":"tb", "message":{
            "message_id":"notice-reply", "thread_id":"t", "in_reply_to":"notice-original",
            "sender_endpoint":"eb", "body":"reply"}})
        result = self.h.dispatch({"op":"inbox_notice", "host_id":"a", "host_token":"ta", "endpoint_id":"ea"})
        self.assertEqual([item["message_id"] for item in result["messages"]], ["notice-reply"])

    def test_inbox_notice_excludes_candidate_already_replied_to_by_recipient(self):
        self.h.dispatch({"op":"submit", "host_id":"b", "host_token":"tb", "message":{
            "message_id":"incoming-question", "thread_id":"question-thread",
            "sender_endpoint":"eb", "target":"proj.cc", "body":"question"}})
        self.h.dispatch({"op":"submit", "host_id":"a", "host_token":"ta", "message":{
            "message_id":"question-reply", "thread_id":"question-thread",
            "in_reply_to":"incoming-question", "sender_endpoint":"ea", "body":"answer"}})
        result = self.h.dispatch({"op":"inbox_notice", "host_id":"a", "host_token":"ta", "endpoint_id":"ea"})
        self.assertEqual(result["messages"], [])

    def test_inbox_notice_cursor_reaches_fourth_row_on_second_safe_point(self):
        for i in range(4):
            self.send(mid=f"notice-{i}", body=f"body-{i}")
        first = self.h.dispatch({"op":"inbox_notice", "host_id":"b", "host_token":"tb",
                                 "endpoint_id":"eb", "cursor":0})
        self.assertEqual([row["message_id"] for row in first["messages"]], ["notice-0", "notice-1", "notice-2"])
        second = self.h.dispatch({"op":"inbox_notice", "host_id":"b", "host_token":"tb",
                                  "endpoint_id":"eb", "cursor":first["next_cursor"]})
        self.assertEqual([row["message_id"] for row in second["messages"]], ["notice-3"])

    def test_inbox_notice_includes_dispatching_before_cursor_advances(self):
        self.send(mid="dispatching-row", body="in flight")
        self.send(mid="queued-row", body="queued")
        self.h.dispatch({"op":"begin_present", "host_id":"b", "host_token":"tb",
                         "endpoint_id":"eb", "message_id":"dispatching-row"})
        first = self.h.dispatch({"op":"inbox_notice", "host_id":"b", "host_token":"tb",
                                 "endpoint_id":"eb", "cursor":0})
        self.assertEqual([row["message_id"] for row in first["messages"]],
                         ["dispatching-row", "queued-row"])
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='dispatching-row'")[0],
                         "dispatching")
        self.h.dispatch({"op":"receipt", "host_id":"b", "host_token":"tb", "endpoint_id":"eb",
                         "message_id":"dispatching-row", "state":"uncertain"})
        second = self.h.dispatch({"op":"inbox_notice", "host_id":"b", "host_token":"tb",
                                  "endpoint_id":"eb", "cursor":first["next_cursor"]})
        self.assertEqual(second["messages"], [])
    def test_large_first_message_advances_cursor_without_starving_next(self):
        body="x" * 226395
        self.send(mid="large-first",body=body)
        self.send(mid="small-next",body="next")
        request={"op":"inbox","host_id":"b","host_token":"tb","endpoint_id":"eb"}
        first=self.h.dispatch(request)
        self.assertEqual([m["message_id"] for m in first["messages"]],["large-first"])
        self.assertEqual(first["messages"][0]["body"],body)
        self.assertEqual(first["next_cursor"],first["messages"][0]["sequence"])
        one=self.h.dispatch(dict(request,op="query",message_id="large-first"))
        self.assertEqual(one["body"],body)
        self.assertEqual(one["message_id"],"large-first")
        for result in (first,one):
            self.assertLessEqual(len((json.dumps(success(result),ensure_ascii=False)+"\n").encode()),MAX_REQUEST)
        second=self.h.dispatch(dict(request,cursor=first["next_cursor"]))
        self.assertEqual([m["message_id"] for m in second["messages"]],["small-next"])
        self.assertGreater(second["next_cursor"],first["next_cursor"])
    def test_oversized_admission_rejects_before_commit_and_legacy_row_does_not_starve(self):
        body="x" * (MAX_REQUEST-300)
        request={"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"too-large","thread_id":"t","sender_endpoint":"ea","target":"cdx","body":body,"kind":"chat"}}
        self.assertLessEqual(len((json.dumps(request,ensure_ascii=False)+"\n").encode()),MAX_REQUEST)
        with self.assertRaises(HubError) as caught: self.h.dispatch(request)
        self.assertEqual(caught.exception.code, 'invalid_message')
        self.assertIsNone(self.h._row("SELECT 1 FROM messages WHERE message_id='too-large'"))
        # Model an original persisted by an older owner without rewriting it on upgrade.
        self.send(mid='historical-large',body='historical')
        self.h.db.execute("UPDATE messages SET body=? WHERE message_id='historical-large'",(body,))
        self.send(mid='later-small',body='still flows')
        recipient={"host_id":"b","host_token":"tb","endpoint_id":"eb"}
        for op in ('inbox','claim'):
            result=self.h.dispatch(dict(recipient,op=op))
            self.assertEqual([m['message_id'] for m in result['messages']],['later-small'])
            self.assertEqual(result['messages'][0]['body'],'still flows')
            self.assertEqual(result['message_errors'][0]['message_id'],'historical-large')
            self.assertEqual(result['message_error_count'],1)
            self.assertNotIn(body,json.dumps(result))
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='historical-large'")[0],'accepted')
        with self.assertRaises(HubError) as caught:
            self.h.dispatch(dict(recipient,op='query',message_id='historical-large'))
        self.assertEqual(caught.exception.code,'response_too_large')

    def test_reply_lookup_uses_covering_index_instead_of_history_scan(self):
        plan=self.h.db.execute('EXPLAIN QUERY PLAN SELECT 1 FROM messages reply WHERE reply.in_reply_to=? AND reply.sender_endpoint=?',('original','recipient')).fetchall()
        text=' '.join(str(tuple(row)) for row in plan)
        self.assertIn('message_reply',text)
        self.assertNotIn('SCAN reply',text)

    def test_outbox_lists_only_my_unfinished_sends_without_bodies(self):
        self.send(mid="o1",body="private-outbox-sentinel")
        self.send(mid="o2",body="second")
        mine=self.h.dispatch({"op":"outbox","host_id":"a","host_token":"ta","endpoint_id":"ea"})
        self.assertEqual([m["message_id"] for m in mine["messages"]],["o1","o2"])
        self.assertTrue(all(m["state"] in ("accepted","queued") for m in mine["messages"]))
        self.assertEqual(mine["messages"][0]["recipient_host_id"],"b")
        self.assertEqual(mine["messages"][0]["recipient_kind"],"cdx")
        self.assertEqual(mine["messages"][0]["state_scope"],"local_copy")
        self.assertFalse(mine["messages"][0]["owner_verified"])
        self.assertNotIn("private-outbox-sentinel",str(mine))
        # The recipient sent nothing, so its outbox is empty.
        theirs=self.h.dispatch({"op":"outbox","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        self.assertEqual(theirs["messages"],[])
        # A presented message leaves the list.
        self.h.dispatch({"op":"claim","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        self.h.dispatch({"op":"receipt","host_id":"b","host_token":"tb","endpoint_id":"eb","message_id":"o1","state":"presented"})
        left=self.h.dispatch({"op":"outbox","host_id":"a","host_token":"ta","endpoint_id":"ea"})
        self.assertEqual([m["message_id"] for m in left["messages"]],["o2"])
        # Another host cannot read a sender's outbox with its own token.
        with self.assertRaises(HubError): self.h.dispatch({"op":"outbox","host_id":"b","host_token":"tb","endpoint_id":"ea"})
    def test_committed_reply_suppresses_claim_and_pending_presentation(self):
        self.send()
        receiver = {"host_id":"b", "host_token":"tb", "endpoint_id":"eb"}
        self.assertEqual(len(self.h.claim(receiver)["messages"]), 1)
        self.h.dispatch({"op":"submit", "host_id":"b", "host_token":"tb", "message":{
            "message_id":"handled-reply", "in_reply_to":"m1", "sender_endpoint":"eb", "body":"done"}})
        self.send(mid="next-message")
        self.assertEqual([m["message_id"] for m in self.h.claim(receiver)["messages"]], ["next-message"])
        with self.assertRaisesRegex(HubError, "already replied"):
            self.h.begin_present(dict(receiver, message_id="m1"))
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='m1'")[0], "adapter_received")
        self.assertIsNone(self.h._row("SELECT * FROM receipts WHERE message_id='m1'"))
        self.assertEqual(self.h.begin_present(dict(receiver, message_id="next-message"))["state"], "dispatching")

    def test_reverse_reply_is_pinned(self):
        self.send(); self.h.dispatch({"op":"claim","host_id":"b","host_token":"tb","endpoint_id":"eb"})
        out=self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"reply","thread_id":"t","in_reply_to":"m1","sender_endpoint":"eb","target":"proj.cc","body":"back"}})
        self.assertEqual(out["state"],"queued")
        original = self.h._row("SELECT sender_endpoint FROM messages WHERE message_id=?", ("m1",))
        reply = self.h._row("SELECT recipient_endpoint,in_reply_to FROM messages WHERE message_id=?", ("reply",))
        self.assertEqual(tuple(reply), (original[0], "m1"))
    def test_reply_to_restarted_openclaw_service_uses_sole_current_endpoint(self):
        self.h.dispatch({"op":"directory_import","admin_token":"adm","services":[{"participant_id":"gate","address":"gate","host_id":"a","kind":"openclaw"}]})
        self.reg("a","ta","gate-old","gate",3)
        self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"main-msg","thread_id":"main-thread","sender_endpoint":"gate-old","target":"proj.cdx","body":"hello"}})
        self.h.dispatch({"op":"endpoint_retire","host_id":"a","host_token":"ta","endpoint_id":"gate-old"})
        self.reg("a","ta","gate-new","gate",4)
        out=self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"main-reply","thread_id":"main-thread","in_reply_to":"main-msg","sender_endpoint":"eb","body":"back"}})
        self.assertEqual(out["state"],"queued")
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='main-reply'")[0], "gate-new")
        self.send("agent-msg")
        self.h.dispatch({"op":"endpoint_retire","host_id":"a","host_token":"ta","endpoint_id":"ea"})
        self.reg("a","ta","ea-new","p:cc",5)
        with self.assertRaisesRegex(HubError,"original sender endpoint is unavailable"):
            self.h.dispatch({"op":"submit","host_id":"b","host_token":"tb","message":{"message_id":"agent-reply","thread_id":"t","in_reply_to":"agent-msg","sender_endpoint":"eb","body":"back"}})
    def test_auth_maintenance_alias_revision_and_ttl(self):
        with self.assertRaises(HubError): self.send(target="other.cc")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"stopped"})
        with self.assertRaisesRegex(HubError,"paused"): self.send("paused")
        self.h.dispatch({"op":"maintenance","admin_token":"adm","mode":"open"})
        with self.assertRaisesRegex(HubError,"24 hours"): self.h.dispatch({"op":"submit","host_id":"a","host_token":"ta","message":{"message_id":"ttl","thread_id":"t","sender_endpoint":"ea","target":"cdx","body":"x","ttl_sec":MAX_TTL+1}})
    def test_ambiguous_endpoint_rejected(self):
        self.reg("b","tb","eb2","p:cdx",3)
        with self.assertRaisesRegex(HubError,"ambiguous"): self.send("amb")

    def test_native_reservation_binds_original_and_generation_and_remains_one_shot(self):
        from extensions.messaging.unified.native_notice import content_digest
        self.h.db.execute("UPDATE endpoints SET platform='cdx' WHERE endpoint_id='eb'")
        self.attest('b', 'eb')
        self.send('native')
        ep = self.h._row("SELECT * FROM endpoints WHERE endpoint_id='eb'")
        msg = dict(self.h._row("SELECT * FROM messages WHERE message_id='native'"))
        request = dict(op='native_begin_present', host_id='b', host_token='tb', endpoint_id='eb',
                       message_id='native', incarnation=ep['incarnation'], native_kind='thread_id',
                       native_id='native-thread', content_hash=content_digest(msg))
        before = self.h.db.total_changes
        for field, bad in [('incarnation', 'old'), ('native_id', 'foreign'), ('native_kind', 'session_id'),
                           ('content_hash', 'wrong'), ('host_token', 'wrong')]:
            with self.subTest(field=field), self.assertRaises(HubError):
                self.h.dispatch(dict(request, **{field: bad}))
        self.assertEqual(self.h.db.total_changes, before)
        self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id='native'")[0], 'accepted')
        result = self.h.dispatch(request)
        self.assertEqual(result['content_hash'], request['content_hash'])
        self.assertEqual(result['incarnation'], ep['incarnation'])
        self.assertEqual(result['native_id'], 'native-thread')
        with self.assertRaises(HubError): self.h.dispatch(request)
        with self.assertRaises(HubError):
            self.h.cancel(dict(host_id='a', host_token='ta', endpoint_id='ea', message_id='native'))
        for mid, terminal in [('native-cancel', 'cancelled'), ('native-expire', 'expired')]:
            self.send(mid)
            current = dict(self.h._row("SELECT * FROM messages WHERE message_id=?", (mid,)))
            current_request = dict(request, message_id=mid, content_hash=content_digest(current))
            if terminal == 'cancelled':
                self.h.cancel(dict(host_id='a', host_token='ta', endpoint_id='ea', message_id=mid))
            else:
                self.h._now = lambda: current['expires_at'] + 1
            with self.assertRaises(HubError): self.h.dispatch(current_request)
            self.assertEqual(self.h._row("SELECT state FROM messages WHERE message_id=?", (mid,))[0],
                             'cancelled' if terminal == 'cancelled' else 'accepted')

    def test_cancel_rechecks_sender_retirement_inside_transaction(self):
        self.send('cancel-retired-sender')
        peer = Hub(self.h.db_path, self.h.config)
        self.addCleanup(peer.close)
        original_tx = self.h._tx
        def retire_before_transaction():
            peer.dispatch(dict(op='endpoint_retire', host_id='a', host_token='ta', endpoint_id='ea'))
            original_tx()
        self.h._tx = retire_before_transaction
        try:
            with self.assertRaises(HubError) as caught:
                self.h.cancel(dict(host_id='a', host_token='ta', endpoint_id='ea', message_id='cancel-retired-sender'))
            self.assertEqual(caught.exception.code, 'stale_session')
        finally:
            self.h._tx = original_tx
        self.assertFalse(self.h.db.in_transaction)
        self.assertEqual(peer._row("SELECT state FROM messages WHERE message_id='cancel-retired-sender'")[0], 'accepted')

    def test_sender_cancel_fences_presentation_and_is_not_task_cancellation(self):
        self.send('cancel')
        owner=dict(host_id='a',host_token='ta',endpoint_id='ea',message_id='cancel')
        receiver=dict(host_id='b',host_token='tb',endpoint_id='eb',message_id='cancel')
        self.h.claim(receiver)
        with self.assertRaisesRegex(HubError,'original sender'): self.h.cancel(receiver)
        self.assertEqual(self.h.cancel(owner)['state'],'cancelled')
        with self.assertRaises(HubError): self.h.begin_present(receiver)
        with self.assertRaises(HubError): self.h.receipt(dict(receiver,state='presented'))
        self.assertEqual(self.h.claim(receiver)['messages'],[])
        self.send('started'); receiver['message_id']='started';owner['message_id']='started'
        self.h.begin_present(receiver)
        with self.assertRaisesRegex(HubError,'execution is not cancelled'): self.h.cancel(owner)

    def test_missing_heartbeat_rejects_send_without_retirement(self):
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='eb'")
        with self.assertRaisesRegex(HubError,'liveness'): self.send('old')
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='eb'")[0],0)

if __name__ == "__main__": unittest.main()

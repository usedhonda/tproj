import json
from pathlib import Path
import sys
import tempfile
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

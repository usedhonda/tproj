#!/usr/bin/env python3
"""Explicit routing must not turn a live daemon or alias into message authority."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from extensions.messaging.unified.hub import Hub, HubError
from extensions.messaging.unified.identity import observe_tui_native, IdentityError

NATIVE = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'


class RecipientRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Hub(Path(self.tmp.name)/'hub.db', {'host_id':'b', 'admin_token':'admin', 'hosts':{'a':'a-token','b':'b-token'}})
        self.addCleanup(self.h.close)
        self.clock = 1000.0
        self.h._now = lambda: self.clock
        self.h.dispatch(dict(op='directory_import', admin_token='admin', projects=[
            dict(project_id='p', alias='project', host_id='b', path='/project')]))
        self.h.db.execute("UPDATE participants SET host_id='a' WHERE participant_id='p:cc'")
        self.register('sender', 'a', 'p:cc', '%1')
        self.register('app', 'b', 'p:cdx', None)
        self.attest('app', NATIVE)
        self.send('original')
        self.register('tui', 'b', 'p:cdx', '%2')
        self.attest('tui', OTHER)
        self.candidate = self.call('recipient_observe', observed_endpoint='tui')['candidate']

    def register(self, name, host, party, pane):
        return self.h.dispatch(dict(op='endpoint_register', host_id=host, host_token=host+'-token',
            endpoint_id=name, participant_id=party, session='session', pane=pane,
            pid=100 if name=='app' else 200, pid_start='1', runtime_id=name, platform='cc' if host=='a' else 'cdx'))

    def attest(self, endpoint, native):
        self.h.dispatch(dict(op='native_attest', host_id='b', host_token='b-token',
                             endpoint_id=endpoint, native_kind='thread_id', native_id=native))

    def call(self, op, **fields):
        return self.h.dispatch(dict(op=op, host_id='b', host_token='b-token',
                                   actor_endpoint='tui', operation_id=str(uuid.uuid4()), **fields))

    def send(self, mid, **fields):
        return self.h.dispatch(dict(op='submit', host_id='a', host_token='a-token', message=dict(
            message_id=mid, sender_endpoint='sender', target='project.cdx', body='external peer data', **fields)))

    def grant(self, **fields):
        return self.call('recovery_grant', message_id='original', candidate=self.candidate,
                         expected_revision=0, allow_read=True, **fields)

    def test_selection_resolves_only_new_submit_and_does_not_rewrite_old_authority(self):
        original = tuple(self.h.db.execute("SELECT * FROM messages WHERE message_id='original'").fetchone())
        with self.assertRaisesRegex(HubError, 'ambiguous'): self.send('before-select')
        pref = self.call('recipient_select', target='project.cdx', candidate=self.candidate, expected_revision=0)
        self.assertEqual(pref['revision'], 1)
        self.send('selected')
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='selected'")[0], 'tui')
        self.assertEqual(tuple(self.h._row("SELECT * FROM messages WHERE message_id='original'")), original)
        with self.assertRaisesRegex(HubError, 'not party'):
            self.h.dispatch(dict(op='query', host_id='b', host_token='b-token', endpoint_id='tui', message_id='original'))
        with self.assertRaises(HubError):
            self.h.dispatch(dict(op='submit', host_id='b', host_token='b-token', message=dict(
                message_id='unauthorized-reply', sender_endpoint='tui', in_reply_to='original', body='no')))
        with self.assertRaisesRegex(HubError, 'revision changed'):
            self.call('recipient_clear', target='project.cdx', expected_revision=0)
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='tui'")
        with self.assertRaisesRegex(HubError, 'fresh observation'): self.send('unavailable')
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='app'")[0], 0)

    def test_same_native_surface_fence_never_retires_app(self):
        self.h.db.execute("UPDATE endpoint_native SET native_id=? WHERE endpoint_id='tui'", (NATIVE,))
        candidate = self.call('recipient_observe', observed_endpoint='tui')['candidate']
        self.call('recipient_select', target='project.cdx', candidate=candidate, expected_revision=0)
        with self.assertRaisesRegex(HubError, 'consumer fence'):
            self.h.dispatch(dict(op='claim', host_id='b', host_token='b-token', endpoint_id='app'))
        self.send('new')
        claimed = self.h.dispatch(dict(op='claim', host_id='b', host_token='b-token', endpoint_id='tui'))
        self.assertEqual([m['message_id'] for m in claimed['messages']], ['new'])
        self.assertEqual(self.h._row("SELECT retired FROM endpoints WHERE endpoint_id='app'")[0], 0)

    def test_restart_continues_selected_native_and_historical_read_reply(self):
        self.call('recipient_select', target='project.cdx', candidate=self.candidate, expected_revision=0)
        self.send('before-restart')
        original = dict(self.h._row("SELECT * FROM messages WHERE message_id='before-restart'"))
        pref = dict(self.h._row("SELECT * FROM recipient_preferences WHERE participant_id='p:cdx'"))
        self.h.dispatch(dict(op='endpoint_retire', host_id='b', host_token='b-token', endpoint_id='tui'))
        self.register('resumed', 'b', 'p:cdx', '%3')
        self.attest('resumed', OTHER)
        # No recipient_observe/select and no grant after restart.
        self.send('after-restart')
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='after-restart'")[0], 'resumed')
        self.assertEqual(dict(self.h._row("SELECT * FROM recipient_preferences WHERE participant_id='p:cdx'")), pref)
        actor = dict(host_id='b', host_token='b-token', endpoint_id='resumed')
        self.assertEqual(self.h.dispatch(dict(actor, op='query', message_id='before-restart'))['body'], original['body'])
        inbox = self.h.dispatch(dict(actor, op='inbox'))['messages']
        self.assertIn('before-restart', [row['message_id'] for row in inbox])
        self.assertEqual(self.h._reply_endpoint('tui')['endpoint_id'], 'resumed')
        self.h.dispatch(dict(op='submit', host_id='b', host_token='b-token', message=dict(
            message_id='resumed-reply', sender_endpoint='resumed', in_reply_to='before-restart', body='read after restart')))
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='before-restart'")[0], 'tui')
        self.assertEqual(self.h._row("SELECT sender_endpoint FROM messages WHERE message_id='resumed-reply'")[0], 'resumed')
        # A live app process of this same native is not a competing TUI writer.
        self.h.db.execute("UPDATE endpoint_native SET native_id=? WHERE endpoint_id='app'", (OTHER,))
        self.assertEqual(self.h._reply_endpoint('tui')['endpoint_id'], 'resumed')
        with self.assertRaisesRegex(HubError, 'consumer fence'):
            self.h.dispatch(dict(op='claim', host_id='b', host_token='b-token', endpoint_id='app'))
        self.assertEqual([m['message_id'] for m in self.h.dispatch(dict(actor, op='claim'))['messages']], ['after-restart'])

    def test_restart_never_follows_other_native_or_ambiguous_or_stale_writer(self):
        self.call('recipient_select', target='project.cdx', candidate=self.candidate, expected_revision=0)
        self.h.dispatch(dict(op='endpoint_retire', host_id='b', host_token='b-token', endpoint_id='tui'))
        self.register('resumed', 'b', 'p:cdx', '%3')
        self.attest('resumed', NATIVE)
        with self.assertRaises(HubError): self.send('different-native')
        self.assertFalse(self.h._same_native_party(self.h._host_endpoint('b','resumed'), 'tui'))
        self.h.db.execute("UPDATE endpoint_native SET native_id=? WHERE endpoint_id='resumed'", (OTHER,))
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='resumed'")
        with self.assertRaises(HubError): self.send('stale-replacement')
        self.h.db.execute("UPDATE endpoints SET last_heartbeat=? WHERE endpoint_id='resumed'", (self.clock,))
        self.register('second-tui', 'b', 'p:cdx', '%4')
        self.attest('second-tui', OTHER)
        with self.assertRaises(HubError): self.send('two-writers')
        self.assertIsNone(self.h._reply_endpoint('tui'))
        self.assertFalse(self.h._same_native_party(self.h._host_endpoint('b','resumed'), 'tui'))

    def test_grant_read_is_exact_native_and_preserves_unknown_cancel_and_expiry(self):
        for state in ('uncertain', 'cancelled', 'expired'):
            with self.subTest(state=state):
                self.h.db.execute("UPDATE messages SET state=? WHERE message_id='original'", (state,))
                g = self.grant()
                before = tuple(self.h._row("SELECT * FROM messages WHERE message_id='original'"))
                result = self.call('recovery_read', message_id='original', grant_id=g['grant_id'])
                self.assertEqual(result['message']['body'], 'external peer data')
                self.assertTrue(result['archive'])
                self.assertEqual(tuple(self.h._row("SELECT * FROM messages WHERE message_id='original'")), before)
                self.assertIsNone(self.h._row("SELECT * FROM receipts WHERE message_id='original'"))
                with self.assertRaises(HubError):
                    self.call('recovery_read', message_id='different', grant_id=g['grant_id'])
                self.h.db.execute("UPDATE endpoint_native SET native_id=? WHERE endpoint_id='tui'", (NATIVE,))
                with self.assertRaisesRegex(HubError, 'exact authorized native'):
                    self.call('recovery_read', message_id='original', grant_id=g['grant_id'])
                self.h.db.execute("UPDATE endpoint_native SET native_id=? WHERE endpoint_id='tui'", (OTHER,))
                self.call('recovery_revoke', grant_id=g['grant_id'], expected_revision=1)
                with self.assertRaisesRegex(HubError, 'revoked'):
                    self.call('recovery_read', message_id='original', grant_id=g['grant_id'])

    def test_reply_permission_and_provenance_are_separate_from_original_recipient(self):
        denied = self.grant()
        with self.assertRaisesRegex(HubError, 'does not permit reply'):
            self.call('recovery_reply', message_id='original', grant_id=denied['grant_id'], submission_id='reply', body='answer')
        g = self.grant(allow_reply=True)
        req = dict(op='recovery_reply', host_id='b', host_token='b-token', actor_endpoint='tui',
                   operation_id='stable', message_id='original', grant_id=g['grant_id'], submission_id='reply', body='answer')
        self.assertEqual(self.h.dispatch(req)['state'], 'queued')
        self.h.dispatch(req)
        self.assertEqual(self.h._row("SELECT count(*) FROM messages WHERE message_id='reply'")[0], 1)
        evidence = self.h.response_evidence(self.h._row("SELECT * FROM messages WHERE message_id='original'"))
        self.assertEqual(evidence['recipient_reply_count'], 0)
        self.assertEqual(evidence['authorized_recovery_reply_ids'], ['reply'])
        self.assertEqual(self.h._row("SELECT recipient_endpoint FROM messages WHERE message_id='reply'")[0], 'sender')

    def test_other_host_cannot_manage_or_read_a_federated_copy(self):
        g = self.grant()
        with self.assertRaisesRegex(HubError, 'local owner host'):
            self.h.dispatch(dict(op='recovery_read', host_id='a', host_token='a-token', actor_endpoint='sender',
                                 operation_id='foreign', message_id='original', grant_id=g['grant_id']))

    def test_operator_management_does_not_grant_operator_body_consumption(self):
        operator = dict(uid=os.getuid(),pid=300,pid_start=1)
        request = dict(host_id='b',host_token='b-token',actor_operator=operator,actor_endpoint=None)
        self.h.dispatch(dict(request,op='recipient_select',operation_id='operator-select',
            target='project.cdx',candidate=self.candidate,expected_revision=0))
        issuer = json.loads(self.h._row("SELECT set_by FROM recipient_preferences WHERE participant_id='p:cdx'")[0])
        self.assertEqual(issuer['operator'],operator)
        grant = self.h.dispatch(dict(request,op='recovery_grant',operation_id='operator-grant',
            message_id='original',candidate=self.candidate,expected_revision=0,allow_read=True))
        with self.assertRaisesRegex(HubError,'native caller'):
            self.h.dispatch(dict(request,op='recovery_read',operation_id='operator-read',
                message_id='original',grant_id=grant['grant_id']))
        self.assertEqual(self.call('recovery_read',message_id='original',grant_id=grant['grant_id'])['message']['body'],
                         'external peer data')

    def test_selection_operation_retries_are_scope_bound(self):
        req = dict(op='recipient_select', host_id='b', host_token='b-token', actor_endpoint='tui',
                   operation_id='select-once', target='project.cdx', candidate=self.candidate, expected_revision=0)
        self.assertEqual(self.h.dispatch(req), self.h.dispatch(req))
        with self.assertRaisesRegex(HubError, 'different scope'):
            self.h.dispatch(dict(req, target='other.cdx'))

    def test_direct_tui_native_caller_does_not_adopt_live_app_binding(self):
        import time
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'unified'))
        import host as host_module
        import identity as identity_module
        adapter = host_module.Host(dict(journal=str(Path(self.tmp.name)/'journal.db'),
            host_id='b', host_token='b-token'), recover=False)
        self.addCleanup(adapter.db.close)
        project = str(Path(self.tmp.name))
        adapter.endpoints = [dict(e, pid_start=int(e['pid_start']), project_id='p', project_path=project, address='project.cdx')
            for e in self.h.dispatch(dict(op='diagnostic_identity',host_id='b',host_token='b-token'))['endpoints']]
        adapter.refreshed = time.monotonic()
        adapter.hub = lambda op, **kw: self.h.dispatch(dict(kw, op=op, host_id='b',host_token='b-token'))
        def process(pid):
            return dict(uid=os.getuid(),pid_start=1,ppid=1,
                        command='codex app-server' if pid==100 else 'node codex.js resume --last')
        original_adopt = identity_module.adopt_native_conversation
        with patch.object(host_module, 'bind_caller', side_effect=lambda pid, uid, eps, **kw:
                identity_module.bind_caller(pid,uid,eps,inspect_process=process,**kw)), \
             patch.object(host_module, 'adopt_native_conversation', side_effect=lambda eps, ctx:
                original_adopt(eps,ctx,[dict(thread_id=OTHER,session_id=OTHER,cwd=project,source_kind='cli')])):
            result = adapter.caller(200,os.getuid(),dict(conversation=dict(thread_id=OTHER,session_id=OTHER,platform='cdx')))
        self.assertEqual(result['endpoint_id'],'tui')
        self.assertEqual(result['thread_id'],OTHER)
        self.assertEqual(self.h._row("SELECT native_id FROM endpoint_native WHERE endpoint_id='app'")[0],NATIVE)


class TuiObservationTest(unittest.TestCase):
    def test_open_record_not_resume_hint_proves_native_and_rechecks_incarnation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'sessions'
            f = root/'2026/01/01'/('rollout-test-'+NATIVE+'.jsonl')
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps(dict(type='session_meta', payload=dict(id=NATIVE,
                source='cli', originator='codex-tui', thread_source='user', cwd=str(Path(tmp).resolve()))))+'\n')
            ep = dict(platform='cdx', pane='%1', pid=100, pid_start=1, project_path=str(Path(tmp).resolve()))
            process = lambda _: dict(uid=os.getuid(), pid_start=1, command='node codex.js resume --last')
            self.assertEqual(observe_tui_native(ep, sessions_root=root, inspect_process=process,
                descendants=lambda _: [], open_files=lambda _: [str(f)]), {'thread_id':NATIVE})
            with self.assertRaises(IdentityError):
                observe_tui_native(dict(ep, project_path='/different'), sessions_root=root,
                    inspect_process=process, descendants=lambda _: [], open_files=lambda _: [str(f)])
            with self.assertRaises(IdentityError):
                observe_tui_native(ep, sessions_root=root, inspect_process=process,
                    descendants=lambda _: [], open_files=lambda _: [])


if __name__ == '__main__': unittest.main()

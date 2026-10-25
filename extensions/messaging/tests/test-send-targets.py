"""Caller-specific discovery, using real owner resolvers and no message writes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'unified'))
from federation import FederatedHub
from host import Host
from protocol import HubError
import cli


class SendTargetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.hubs, self.calls = {}, []
        for owner in ('a', 'b'):
            h = FederatedHub(Path(self.tmp.name) / (owner + '.db'),
                {'host_id': owner, 'hosts': {'a': 'ta', 'b': 'tb'}, 'admin_token': 'fixture'})
            self.addCleanup(h.close); self.hubs[owner] = h
            h.topology = lambda: {'mode': 'multi', 'hosts': [
                {'id': 'a', 'ssh_alias': 'a'}, {'id': 'b', 'ssh_alias': 'b'}]}
            h.directory_import({'admin_token': 'fixture', 'projects': [
                {'project_id': owner, 'alias': owner, 'host_id': owner, 'path': '/fixture/' + owner}]})
            for kind in ('cc', 'cdx'):
                h.register(dict(host_id=owner, host_token='t' + owner, endpoint_id=owner + kind,
                    participant_id=owner + ':' + kind, platform=kind, pid=10, pid_start=1,
                    session='fixture', pane='%1', runtime_id=owner + kind))
        for owner, h in self.hubs.items():
            def remote(peer, op, _timeout_seconds=None, owner=owner, **args):
                self.calls.append((peer, op, _timeout_seconds, args))
                return self.hubs[peer].dispatch(dict(args, op='peer_' + op,
                    host_id=owner, host_token='t' + owner, protocol=1))
            h.remote = remote
        self.req = dict(op='send_targets', host_id='a', host_token='ta', endpoint_id='acc')

    def rows(self, **fields):
        return {r['address']: r for r in self.hubs['a'].dispatch(dict(self.req, **fields))['participants']}

    def test_scope_resolver_preference_liveness_and_maintenance_are_fresh_read_only(self):
        a, b = self.hubs['a'], self.hubs['b']
        before = [h.db.total_changes for h in (a, b)]
        rows = self.rows(authorized_targets=['a.cdx', 'b.cc'])
        self.assertEqual(set(rows), {'a.cdx', 'b.cc'})
        self.assertTrue(all(r['available'] for r in rows.values()))
        self.assertEqual([h.db.total_changes for h in (a, b)], before)
        self.assertEqual(self.calls[0][1:3], ('target_directory', 3))
        self.assertEqual(self.calls[0][3]['addresses'], ['a.cdx', 'b.cc'])
        b.db.execute("UPDATE endpoints SET last_heartbeat=0 WHERE endpoint_id='bcc'")
        self.assertEqual(self.rows(authorized_targets=['b.cc'])['b.cc']['state'], 'endpoint_unavailable')
        a.register(dict(host_id='a', host_token='ta', endpoint_id='second', participant_id='a:cdx',
            platform='cdx', pid=11, pid_start=2, session='fixture', pane='%2', runtime_id='second'))
        self.assertEqual(self.rows(authorized_targets=['a.cdx'])['a.cdx']['state'], 'ambiguous_target')
        ep = a._row("SELECT * FROM endpoints WHERE endpoint_id='acdx'")
        a.db.execute('INSERT INTO endpoint_native VALUES(?,?,?)', ('acdx', 'thread_id', 'fixture-native'))
        a.db.execute('INSERT INTO recipient_candidates VALUES(?,?,?,?,?,?,?)',
            ('choice', 'acdx', ep['incarnation'], 'a:cdx', 'thread_id', 'fixture-native', a._now()))
        a.db.execute('INSERT INTO recipient_preferences VALUES(?,?,?,?,?)', ('a:cdx', 'choice', 1, '{}', 'fixture'))
        self.assertTrue(self.rows(authorized_targets=['a.cdx'])['a.cdx']['available'])
        a.db.execute("UPDATE metadata SET value='stopped' WHERE key='maintenance'")
        self.assertEqual(self.rows(authorized_targets=['a.cdx'])['a.cdx']['state'], 'maintenance')
        self.assertEqual(self.rows(authorized_targets=[]), {})
        for h in (a, b): self.assertEqual(h._row('SELECT COUNT(*) FROM messages')[0], 0)

    def test_unavailable_old_or_malformed_peer_does_not_claim_remote_ready_or_hide_local(self):
        a = self.hubs['a']
        failures = [HubError('host_unavailable', 'fixture'), HubError('unsupported', 'old owner'),
                    {'participants': [{'address': ['invalid'], 'available': True, 'state': 'ready'}]}]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                def remote(*args, **kw):
                    if isinstance(failure, Exception): raise failure
                    return failure
                with patch.object(a, 'remote', side_effect=remote):
                    result = a.dispatch(dict(self.req, authorized_targets=['a.cc', 'b.cdx']))
                self.assertFalse(result['complete'])
                rows = {r['address']: r for r in result['participants']}
                self.assertTrue(rows['a.cc']['available'])
                self.assertFalse(rows['b.cdx']['available'])
                self.assertEqual(rows['b.cdx']['state'], 'route_unverified')

    def test_host_uses_current_scope_not_request_or_consumer_cache(self):
        h = Host({'host_id': 'a', 'journal': str(Path(self.tmp.name) / 'host.db'),
            'services': {'muse': {'allowed_addresses': ['a.cdx']}}}, recover=False)
        self.addCleanup(h.db.close)
        h.service = lambda *args: {'endpoint_id': 'acc'}
        h.hub = lambda op, **kw: self.hubs['a'].dispatch(dict(kw, op=op, host_id='a', host_token='ta'))
        req = dict(op='service_list', service_id='muse', authorized_targets=['b.cdx'])
        self.assertEqual([r['address'] for r in h.dispatch(req, 1, os.getuid())['participants']], ['a.cdx'])
        req['op'] = 'send_targets'  # Public spelling must not bypass service scope.
        self.assertEqual([r['address'] for r in h.dispatch(req, 1, os.getuid())['participants']], ['a.cdx'])
        h.config['services']['muse']['allowed_addresses'] = ['b.cc']
        self.assertEqual([r['address'] for r in h.dispatch(req, 1, os.getuid())['participants']], ['b.cc'])
        spec = importlib.util.spec_from_file_location('target_mailbox', ROOT / 'external/kai-mcp/mailbox_tools.py')
        mailbox = importlib.util.module_from_spec(spec); spec.loader.exec_module(mailbox)
        tools = mailbox.MailboxTools(service_id='muse', service_address='muse', service_token='fixture',
            authorizer=lambda *args: {'allowed_addresses': ['old-cache.cc']},
            host_call=lambda request: h.dispatch(request, 1, os.getuid()))
        self.assertEqual(tools.dispatch('tproj_list', {}), {
            'participants': [{'address': 'b.cc', 'kind': 'cc', 'available': True}]})
        req.update(op='service_status', target='a.cdx')
        with self.assertRaises(HubError) as error: h.dispatch(req, 1, os.getuid())
        self.assertEqual(error.exception.code, 'scope_denied')

    def test_cli_targets_carries_native_context_and_filters_without_writing(self):
        calls = []
        def rpc(sock, req):
            calls.append(req)
            return {'participants': [{'address': 'ready.cc', 'available': True, 'state': 'ready'},
                    {'address': 'held.cdx', 'available': False, 'state': 'ambiguous_target'}],
                    'checked_at': 1, 'complete': True}
        for flags, count in [([], 1), (['--all'], 2)]:
            with patch.object(cli, 'config', return_value={'socket': 'fixture'}), \
                    patch.object(cli, 'rpc', side_effect=rpc), \
                    patch.object(cli, 'native_conversation_context', return_value={'thread_id': 'bound'}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(['targets', '--json'] + flags), 0)
            self.assertEqual(len(json.loads(out.getvalue())['participants']), count)
            self.assertEqual(calls[-1]['conversation'], {'thread_id': 'bound'})
            self.assertEqual(calls[-1]['op'], 'send_targets')
            self.assertNotIn('submission_id', calls[-1])
        # The legacy global retry branch must never turn discovery into a send.
        with patch.object(cli, 'rpc') as network, patch.object(cli, 'submission') as submit, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['targets', '--retry', 'old-message']), 2)
        network.assert_not_called(); submit.assert_not_called()


if __name__ == '__main__': unittest.main()

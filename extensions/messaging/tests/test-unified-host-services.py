import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("unified_host", ROOT / "unified" / "host.py")
host_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_mod)
from protocol import HubError
from service_policy_migrate import migrate


class UnifiedHostServicesTest(unittest.TestCase):
    def test_service_send_scope_is_fresh_host_metadata_not_public_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            self.addCleanup(host.db.close)
            calls = []
            host.hub = lambda op, **args: calls.append((op, args)) or {'state': 'queued'}
            scope = ['retired.cdx', 'new.cdx']
            with patch.object(host, 'service_policy', return_value=scope):
                host.submit({'endpoint_id': 'service-endpoint', 'service_id': 'kai'},
                    dict(submission_id='stable-redirect', target='retired.cdx', body='read only',
                         authorized_targets=['arbitrary.cdx']))
            self.assertEqual(calls[0][1]['authorized_targets'], scope)
            self.assertEqual(calls[0][1]['message']['target'], 'retired.cdx')

    def test_endpoint_failure_cannot_starve_other_recipients(self):
        import time
        import sqlite3
        errors = (HubError('unavailable', 'fixture claim failure'), OSError('fixture transport failure'),
                  ValueError('fixture malformed response'), sqlite3.OperationalError('fixture journal failure'),
                  subprocess.TimeoutExpired('fixture transport', 5))
        for error in errors:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                host = host_mod.Host({'journal': str(Path(tmp) / 'journal.db'),
                                      'delivery_enabled': True}, recover=False)
                self.addCleanup(host.db.close)
                host.endpoints = [{'endpoint_id': x, 'platform': 'cc'} for x in ('faulted', 'healthy')]
                host.refreshed = time.monotonic()
                host._current_delivery_endpoint = lambda eid: next(ep for ep in host.endpoints if ep['endpoint_id'] == eid)
                seen = []
                def hub(op, **args):
                    self.assertEqual(op, 'claim')
                    seen.append(args['endpoint_id'])
                    if args['endpoint_id'] == 'faulted': raise error
                    return {'messages': [], 'next_sequence': 0}
                host.hub = hub
                host.delivery_tick()
                self.assertEqual(seen, ['faulted', 'healthy'])
                self.assertEqual(host.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)

    def test_endpoint_failure_rolls_back_partial_work_not_committed_reservations(self):
        import time
        import sqlite3
        for rollback_fails in (False, True):
            with self.subTest(rollback_fails=rollback_fails), tempfile.TemporaryDirectory() as tmp:
                host = host_mod.Host({'journal': str(Path(tmp) / 'journal.db'),
                                      'delivery_enabled': True}, recover=False)
                self.addCleanup(lambda host=host: host.db.close())
                host.endpoints = [{'endpoint_id': x} for x in ('faulted', 'healthy')]
                host.refreshed = time.monotonic()
                host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                    ('reserved', 'faulted', '{}', 'dispatching', None, 0))
                host.db.commit()
                if rollback_fails:
                    connection = host.db
                    class FailedRollback:
                        def __getattr__(self, key): return getattr(connection, key)
                        def rollback(self): raise sqlite3.OperationalError('fixture rollback failure')
                    host.db = FailedRollback()
                def endpoint(ep):
                    if ep['endpoint_id'] == 'faulted':
                        host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                            ('partial', 'faulted', '{}', 'received', None, 0))
                        raise OSError('fixture failure with open transaction')
                    host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                        ('healthy', 'healthy', '{}', 'received', None, 0))
                    host.db.commit()
                host._deliver_endpoint = endpoint
                host.delivery_tick()
                self.assertEqual(dict(host.db.execute('SELECT message_id,state FROM deliveries')),
                                 {'reserved': 'dispatching', 'healthy': 'received'})

    def test_failed_journal_reopen_never_recreates_ledger_or_runs_later_work(self):
        import time
        import sqlite3
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.db'
            saved = path.with_suffix('.saved')
            host = host_mod.Host({'journal': str(path), 'delivery_enabled': True}, recover=False)
            self.addCleanup(lambda: host.db.close())
            host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                ('reserved', 'faulted', '{}', 'dispatching', None, 0))
            host.db.commit()
            connection = host.db
            class FailedRollback:
                def __getattr__(self, key): return getattr(connection, key)
                def rollback(self):
                    connection.close()  # Discard partial work, preserve the durable journal.
                    path.rename(saved)  # Temporary loss of the original journal path.
                    raise sqlite3.OperationalError('fixture rollback failure')
            host.db = FailedRollback()
            publisher = host.native_publisher = Mock()
            host.endpoints = [{'endpoint_id': x} for x in ('faulted', 'healthy')]
            host.refreshed = time.monotonic()
            seen = []
            def endpoint(ep):
                seen.append(ep['endpoint_id'])
                if ep['endpoint_id'] == 'faulted' and len(seen) == 1:
                    host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                        ('partial', 'faulted', '{}', 'received', None, 0))
                    raise OSError('fixture failure before rollback')
                if ep['endpoint_id'] == 'healthy':
                    host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                        ('healthy', 'healthy', '{}', 'received', None, 0))
                    host.db.commit()
            host._deliver_endpoint = endpoint
            for _ in range(2):
                with self.assertRaises(sqlite3.OperationalError): host.delivery_tick()
                self.assertFalse(path.exists(), 'reopen created a blank ledger')
                self.assertEqual(seen, ['faulted'])
                publisher.maintain.assert_called_once_with(host)
            saved.rename(path)
            host.delivery_tick()
            self.assertEqual(seen, ['faulted', 'faulted', 'healthy'])
            self.assertEqual(dict(host.db.execute('SELECT message_id,state FROM deliveries')),
                             {'reserved': 'dispatching', 'healthy': 'received'})

    def test_delivery_scan_advances_and_wraps_pending_without_terminal_replay(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            host = host_mod.Host({'journal': str(Path(tmp) / 'journal.db'),
                                  'delivery_enabled': True}, recover=False)
            ep = {'endpoint_id': 'ep', 'platform': 'cdx'}
            host.endpoints = [ep]
            host.refreshed = time.monotonic()
            host._current_delivery_endpoint = lambda _: ep
            seen = []
            def hub(op, **args):
                self.assertEqual(op, 'claim')
                seen.append(args['after_sequence'])
                seq = args['after_sequence']
                return {'messages': [{'message_id': 'm'+str(seq+1)}] if seq < 2 else [],
                        'next_sequence': seq+1 if seq < 2 else 0}
            host.hub = hub
            with patch('native_consumer.owns', return_value=True):
                for _ in range(4): host.delivery_tick()
            self.assertEqual(seen, [0, 1, 2, 0])
            self.assertEqual(host.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 2)
            self.assertEqual({r[0] for r in host.db.execute('SELECT state FROM deliveries')}, {'received'})
            host.db.close()

    def test_native_scheduler_maintains_off_path_and_never_falls_back(self):
        import time
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            host = host_mod.Host({'journal': str(Path(tmp) / 'journal.db'),
                'delivery_enabled': False, 'native_queue_enabled': True,
                'native_consumer_enabled': True}, recover=False)
            publisher = Mock()
            host.native_publisher = publisher
            host.refreshed = time.monotonic()
            host.delivery_tick()
            publisher.maintain.assert_called_once_with(host)
            host.config['delivery_enabled'] = True
            ep = {'endpoint_id': 'ep', 'platform': 'cdx'}
            host.endpoints = [ep]
            host.refreshed = time.monotonic()
            host._current_delivery_endpoint = lambda _: ep
            host.hub = Mock(return_value={'messages': [{'message_id': 'native'}], 'next_sequence': 1})
            publisher.tick.side_effect = HubError('identity_rejected', 'fixture')
            with patch.object(host_mod.subprocess, 'run', side_effect=AssertionError('terminal access')):
                host.delivery_tick()
                publisher.tick.assert_called_once_with(host, ep, 'native')
                host.config['native_consumer_enabled'] = False
                host.delivery_tick()
                self.assertEqual(publisher.tick.call_count, 1)
            self.assertEqual(host.db.execute('SELECT state FROM deliveries').fetchone()[0], 'received')
            # A vanished endpoint/empty scan still drains already running jobs.
            host.endpoints = []
            host.delivery_tick()
            self.assertEqual(publisher.maintain.call_count, 4)
            host.db.close()

    def test_native_route_survives_flag_off_and_host_restart_before_prepare(self):
        import time
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'journal': str(Path(tmp) / 'journal.db'), 'delivery_enabled': True,
                   'native_queue_enabled': True, 'native_consumer_enabled': False}
            ep = {'endpoint_id': 'ep', 'platform': 'cdx'}
            def setup(host):
                host.refreshed = time.monotonic()
                host.endpoints = [ep]
                host._current_delivery_endpoint = lambda _: ep
                host.hub = Mock(return_value={'messages': [{'message_id': 'native'}], 'next_sequence': 1})
            host = host_mod.Host(cfg, recover=False)
            setup(host)
            with patch.object(host_mod.subprocess, 'run', side_effect=AssertionError('terminal fallback')):
                host.delivery_tick()
                host.db.close()
                cfg['native_queue_enabled'] = False
                host = host_mod.Host(cfg, recover=True)
                setup(host)
                host.delivery_tick()
            import json
            row = host.db.execute('SELECT * FROM deliveries').fetchone()
            self.assertEqual(json.loads(row['envelope'])['_native_route'], 'native-v1')
            self.assertEqual(row['state'], 'received')
            host.db.close()

    def test_current_host_policy_controls_legacy_and_new_service_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            cfg = host.config['services']['kai']
            cfg['allowed_addresses'] = ['voyager.cc']
            ep = {'endpoint_id': 'kai-endpoint'}
            host.service = lambda *a, **k: ep
            calls = []
            def hub(op, **args):
                calls.append(op)
                return {'participants': [{'address': 'voyager.cc'}, {'address': 'harbor.cdx'}], 'projects': []}
            host.hub = hub
            request = {'service_id': 'kai', 'op': 'list'}
            self.assertEqual([p['address'] for p in host.dispatch(request, 1, os.getuid())['participants']], ['voyager.cc'])
            cfg['allowed_addresses'] = []
            self.assertEqual(host.dispatch(request, 1, os.getuid())['participants'], [])
            with self.assertRaises(HubError) as error:
                host.dispatch(dict(request, op='service_send', target='voyager.cc', submission_id='stable', body='test'), 1, os.getuid())
            self.assertEqual(error.exception.code, 'scope_denied')
            self.assertEqual(host.db.execute('SELECT count(*) FROM submissions').fetchone()[0], 0)
            self.assertNotIn('submit', calls)
            del cfg['allowed_addresses']
            with self.assertRaises(HubError) as error:
                host.dispatch(request, 1, os.getuid())
            self.assertEqual(error.exception.code, 'configuration_error')
            host.db.close()

    def test_read_only_diagnose_uses_persisted_identity_without_registration(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'journal': str(Path(tmp) / 'journal.db'), 'host_id': 'host-a'}
            with self.assertRaises(HubError):
                host_mod.Host(cfg, recover=False, read_only=True)
            self.assertFalse(Path(cfg['journal']).exists())
            import sqlite3
            db = sqlite3.connect(cfg['journal']); db.execute('CREATE TABLE sentinel(value TEXT)'); db.commit(); db.close()
            before = Path(cfg['journal']).read_bytes()
            host = host_mod.Host(cfg, recover=False, read_only=True)
            live = {'endpoint_id': 'ep-old', 'participant_id': 'p:cc', 'host_id': 'host-a',
                    'session': 's', 'pane': '%1', 'pid': 1, 'pid_start': '2',
                    'runtime_id': 'r', 'platform': 'cc', 'incarnation': 'inc'}
            calls = []
            def hub(op, **args):
                calls.append(op)
                if op == 'diagnostic_identity':
                    return {'host_id': 'host-a', 'endpoints': [live], 'endpoint_native': [], 'projects': []}
                if op == 'diagnose':
                    return {'message_id': args['message_id'], 'state': 'queued'}
                raise AssertionError(op)
            host.hub = hub
            with patch.object(host_mod, 'discover_endpoints', return_value=[dict(live)]), \
                 patch.object(host_mod, 'discover_tmux_endpoints', return_value=[]), \
                 patch.object(host_mod, 'same_live_process_family', return_value=True), \
                 patch.object(host_mod, 'adopt_native_conversation', side_effect=lambda eps, _: eps), \
                 patch.object(host_mod, 'bind_caller', side_effect=lambda pid, uid, eps, **_: eps[0]):
                result = host.dispatch({'op': 'diagnose', 'message_id': 'm1'}, 1, os.getuid())
                self.assertEqual(host.caller_read_only(1, os.getuid(), {})['pid_start'], 2)
            self.assertEqual(result['state'], 'queued')
            self.assertEqual(calls, ['diagnostic_identity', 'diagnose', 'diagnostic_identity'])
            with self.assertRaises(sqlite3.OperationalError):
                host.db.execute("INSERT INTO sentinel VALUES('forbidden')")
            host.db.close()
            self.assertEqual(Path(cfg['journal']).read_bytes(), before)

    def test_identity_diagnostic_forwards_only_bounded_selectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            calls = []
            host.hub = lambda op, **args: calls.append((op, args)) or {}
            host.dispatch({'op': 'diagnostic_identity', 'endpoint_ids': ['old', 'new'],
                           'active_only': False, 'host_id': 'other'}, 1, os.getuid())
            self.assertEqual(calls, [('diagnostic_identity', {'endpoint_ids': ['old', 'new'], 'active_only': False})])
            host.db.close()

    def test_private_snapshot_and_idempotent_scope_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_path, consumer_path = Path(tmp)/'host.json', Path(tmp)/'consumer.json'
            identity = {'address': 'kai', 'participant_id': 'kai-service', 'binding_generation': 'one'}
            config = {'services': {'kai': dict(identity, token='fixture-token', launchd_label='com.example.kai')}}
            consumer = dict(identity, service_id='kai', service_token='fixture-token', allowed_addresses=['voyager.cc'])
            host_path.write_text(__import__('json').dumps(config)); consumer_path.write_text(__import__('json').dumps(consumer))
            self.assertTrue(migrate(host_path, consumer_path)['changed'])
            self.assertFalse(migrate(host_path, consumer_path)['changed'])
            after = host_path.read_bytes()
            consumer['allowed_addresses'] = ['harbor.cdx']
            consumer_path.write_text(__import__('json').dumps(consumer))
            with self.assertRaises(HubError): migrate(host_path, consumer_path)
            self.assertEqual(host_path.read_bytes(), after)
            link = Path(tmp)/'linked'; link.symlink_to(host_path)
            with self.assertRaises(HubError): host_mod.load_config_snapshot(link)
            host_path.chmod(0o666)
            with self.assertRaises(HubError): host_mod.load_config_snapshot(host_path)
    def host(self, tmp, **extra):
        config = {
            "journal": str(Path(tmp) / "journal.db"),
            "host_id": "host-a",
            "services": {
                "openclaw": {
                    "participant_id": "gate",
                    "address": "gate",
                    "token": "open-token",
                    "launchd_label": "com.example.openclaw",
                    "platform": "openclaw",
                },
                "kai": {
                    "participant_id": "kai-service",
                    "address": "kai",
                    "token": "kai-token",
                    "launchd_label": "com.example.kai",
                    "platform": "kai",
                },
            },
        }
        config.update(extra)
        return host_mod.Host(config, recover=False)

    @staticmethod
    def launchd(pid):
        return subprocess.CompletedProcess([], 0, stdout='"PID" = %d;\n' % pid, stderr='')

    def test_native_attestation_is_authenticated_and_old_hub_fail_open_only(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            ep = {'endpoint_id': 'native', 'thread_id': 'verified-thread'}
            host.endpoints = [ep]
            host.refreshed = time.monotonic()
            calls = []
            def hub(op, **args):
                calls.append((op, args))
                raise HubError('unknown_op', 'old hub')
            host.hub = hub
            with patch.object(host_mod, 'adopt_native_conversation', return_value=[ep]), \
                 patch.object(host_mod, 'bind_caller', return_value=ep):
                with self.assertRaises(HubError) as rejected:
                    host.caller(1, 1, {'conversation': {'thread_id': 'untrusted'}})
                self.assertEqual(rejected.exception.code, 'identity_rejected')
                self.assertNotIn('native_attest', [op for op, _ in calls])
                calls.clear()
                self.assertEqual(host.caller(1, 1, {}), ep)
                self.assertEqual([args for op, args in calls if op == 'native_attest'],
                    [{'endpoint_id': 'native', 'native_kind': 'thread_id', 'native_id': 'verified-thread'}])
                host.hub = lambda *a, **k: (_ for _ in ()).throw(HubError('identity_rejected', 'conflict'))
                with self.assertRaises(HubError): host.caller(1, 1, {})
            host.db.close()

    def test_equal_native_session_thread_preserves_existing_attestation(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            ep = {'endpoint_id': 'native', 'thread_id': 'verified-native', 'session_id': 'verified-native'}
            host.endpoints = [ep]
            host.refreshed = time.monotonic()
            marker = {'endpoint_id': 'native', 'native_kind': 'session_id', 'native_id': 'verified-native'}
            calls = []
            def hub(op, **args):
                calls.append((op, args))
                if op == 'diagnostic_identity':
                    return {'endpoint_native': [dict(marker)]}
                if op == 'native_attest':
                    if any(args[k] != marker[k] for k in ('endpoint_id', 'native_kind', 'native_id')):
                        raise HubError('identity_rejected', 'endpoint native identity is immutable')
                    return {'endpoint_id': args['endpoint_id']}
                self.fail(op)
            host.hub = hub
            with patch.object(host_mod, 'adopt_native_conversation', return_value=[ep]), \
                 patch.object(host_mod, 'bind_caller', return_value=ep):
                self.assertEqual(host.caller(1, 1, {}), ep)
                self.assertEqual(calls[-1][1]['native_kind'], 'session_id')
                self.assertEqual(marker['native_kind'], 'session_id')
                marker['native_id'] = 'different-native'
                with self.assertRaises(HubError) as error:
                    host.caller(1, 1, {})
                self.assertEqual(error.exception.code, 'identity_rejected')
                marker.update(native_id='verified-native', endpoint_id='different-endpoint')
                with self.assertRaises(HubError):
                    host.caller(1, 1, {})
            host.db.close()

    def test_service_registry_binds_identity_platform_and_incarnation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.hub = lambda op, **args: {"endpoints": []} if op == "endpoints_list" else {}
            with patch.object(host_mod.subprocess, "run", return_value=self.launchd(os.getpid())), \
                 patch("identity._process_info", return_value={"pid_start": 42}):
                ep = host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            self.assertEqual(ep["participant_id"], "kai-service")
            self.assertEqual(ep["platform"], "kai")
            self.assertEqual(ep["service_id"], "kai")
            host.db.close()

    def test_service_id_prevents_cross_service_token_or_address_confusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            for req in (
                {"service_id": "kai", "service_token": "open-token", "address": "kai"},
                {"service_id": "kai", "service_token": "kai-token", "address": "gate"},
                {"service_id": "missing", "service_token": "kai-token", "address": "kai"},
            ):
                with self.assertRaises(HubError):
                    host.service(os.getpid(), os.getuid(), req)
            host.db.close()

    def test_kai_enrollment_retains_mailbox_across_verified_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.config['services']['kai']['binding_generation'] = 'enrollment-one'
            host.hub = lambda op, **args: {'endpoints': []} if op == 'endpoints_list' else {}
            req={'service_id':'kai','service_token':'kai-token','address':'kai','binding_generation':'enrollment-one'}
            endpoints=[]
            for pid,start in ((100,42),(200,55)):
                with patch.object(host_mod.subprocess,'run',return_value=self.launchd(pid)), \
                     patch('identity._process_info',return_value={'pid_start':start}):
                    endpoints.append(host.service(pid,os.getuid(),req))
            self.assertEqual(endpoints[0]['endpoint_id'],endpoints[1]['endpoint_id'])
            self.assertEqual(endpoints[0]['runtime_id'],endpoints[1]['runtime_id'])
            with patch.object(host_mod.subprocess,'run',return_value=self.launchd(200)), patch('identity._process_info',return_value={'pid_start':55}):
                for generation in (None, 'revoked'):
                    stale = dict(req); stale['binding_generation'] = generation
                    with self.assertRaises(HubError) as error:
                        host.service(200, os.getuid(), stale)
                    self.assertEqual(error.exception.code, 'stale_session')
            with patch.object(host_mod.subprocess,'run',return_value=self.launchd(200)):
                with self.assertRaisesRegex(HubError,'registered main'):
                    host.service(100,os.getuid(),req)
            host.db.close()

    def test_muse_generation_restart_revocation_and_service_separation(self):
        from hub import Hub
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp); self.addCleanup(host.db.close)
            host.config['services']['kai']['binding_generation'] = 'kai-generation'
            host.config['services']['muse'] = dict(participant_id='muse-service', address='muse',
                token='muse-token', launchd_label='com.example.muse', platform='muse',
                binding_generation='muse-generation', allowed_addresses=[], read_only=True)
            hub = Hub(Path(tmp)/'hub.db', dict(admin_token='admin', hosts={'host-a': 'token'}))
            self.addCleanup(hub.close)
            hub.directory_import(dict(admin_token='admin', services=[
                dict(participant_id=x+'-service', address=x, host_id='host-a', kind=x) for x in ('kai','muse')]))
            host.hub = lambda op, **args: hub.dispatch(dict(args, op=op, host_id='host-a', host_token='token'))
            def request(service, generation=None):
                return dict(service_id=service, service_token=service+'-token', address=service,
                    binding_generation=generation or service+'-generation')
            endpoints = []
            for pid, start in ((100,42),(200,55)):
                with patch.object(host_mod.subprocess, 'run', return_value=self.launchd(pid)), patch('identity._process_info', return_value={'pid_start':start}):
                    endpoints.append(host.service(pid, os.getuid(), request('muse')))
            self.assertEqual(endpoints[0]['endpoint_id'], endpoints[1]['endpoint_id'])
            self.assertEqual(endpoints[0]['incarnation'], endpoints[1]['incarnation'])
            self.assertEqual(endpoints[1]['runtime_id'], 'muse:muse-generation')
            with patch.object(host_mod.subprocess,'run',return_value=self.launchd(200)), patch('identity._process_info',return_value={'pid_start':55}):
                kai = host.service(200, os.getuid(), request('kai'))
                self.assertNotEqual(kai['endpoint_id'], endpoints[1]['endpoint_id'])
                self.assertEqual(kai['runtime_id'], 'kai:kai-generation')
                for bad in (dict(request('muse'), binding_generation='kai-generation'),
                            dict(request('muse'), service_token='kai-token'),
                            dict(request('muse'), address='kai')):
                    with self.assertRaises(HubError): host.service(200, os.getuid(), bad)
                for op in ('service_send','service_reply','service_ack','service_begin_present'):
                    with self.assertRaises(HubError) as rejected:
                        host.dispatch(dict(request('muse'),op=op,read_only=False),200,os.getuid())
                    self.assertEqual(rejected.exception.code,'scope_denied')
                # A writable second service uses the same durable boundary;
                # revoking its generation must fence queued work, not replay it.
                host.config['services']['muse'].update(read_only=False, allowed_addresses=['kai'])
                queued = host.dispatch(dict(request('muse'), op='service_send',
                    target='kai', body='fixture', submission_id='muse-deferred',
                    defer_remote=True), 200, os.getuid())
                self.assertEqual(queued['receipt_stage'], 'host_journaled')
                self.assertEqual(queued['hub_acceptance'], 'unconfirmed')
                host.config['services']['muse']['binding_generation'] = 'rotated-generation'
                with self.assertRaises(HubError): host.service(200,os.getuid(),request('muse'),query_only=True)
                self.assertEqual(host.service(200,os.getuid(),request('kai'))['endpoint_id'], kai['endpoint_id'])
                import submission_queue
                submission_queue.work_once(host)
                self.assertEqual(host.db.execute('SELECT state FROM submission_work WHERE message_id=?',
                    ('muse-deferred',)).fetchone()[0], 'blocked')
            self.assertEqual(hub.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)

    def test_muse_scope_sync_is_idempotent_and_mismatch_has_no_effect(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            host_path, client_path = Path(tmp)/'host.json', Path(tmp)/'parent.json'
            identity = dict(address='muse',participant_id='muse-service',binding_generation='fixture-generation')
            host_cfg = dict(services={'kai':{'unchanged':'keep'},'muse':dict(identity,token='fixture-token')})
            client = dict(identity,service_id='muse',service_token='fixture-token',allowed_addresses=[])
            host_path.write_text(json.dumps(host_cfg));host_path.chmod(0o600)
            client_path.write_text(json.dumps(client));client_path.chmod(0o600)
            before=host_path.read_bytes()
            self.assertTrue(migrate(host_path,client_path,check=True)['migration_required'])
            self.assertEqual(host_path.read_bytes(),before)
            self.assertTrue(migrate(host_path,client_path)['changed'])
            after=host_path.read_bytes()
            self.assertFalse(migrate(host_path,client_path)['changed'])
            self.assertEqual(host_path.read_bytes(),after)
            self.assertEqual(json.loads(after)['services']['kai'],{'unchanged':'keep'})
            client['binding_generation']='mismatch';client_path.write_text(json.dumps(client));client_path.chmod(0o600)
            with self.assertRaises(HubError):migrate(host_path,client_path)
            self.assertEqual(host_path.read_bytes(),after)

    def test_kai_cannot_be_declared_as_openclaw_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.config["services"]["kai"]["platform"] = "openclaw"
            with self.assertRaisesRegex(HubError, "cannot use openclaw"):
                host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            host.db.close()

    def test_legacy_service_config_remains_openclaw(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = host_mod.Host({
                "journal": str(Path(tmp) / "journal.db"), "host_id": "host-a",
                "service": {"participant_id": "gate", "address": "gate", "token": "token",
                             "launchd_label": "com.example.openclaw"},
            }, recover=False)
            self.assertEqual(host._service_binding({})[0], "openclaw")
            self.assertEqual(host._service_binding({})[1]["address"], "gate")
            host.hub = lambda op, **args: {"endpoints": []} if op == "endpoints_list" else {}
            with patch.object(host_mod.subprocess, "run", return_value=self.launchd(os.getpid())), \
                 patch("identity._process_info", return_value={"pid_start": 42}):
                ep = host.service(os.getpid(), os.getuid(), {"service_token": "token", "address": "gate"})
            expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "host-a:gate:%d:42" % os.getpid()))
            self.assertEqual(ep["endpoint_id"], expected)
            host.db.close()

    def test_duplicate_service_participant_or_address_rejected_before_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.config["services"]["kai"]["participant_id"] = "gate"
            calls = []
            host.hub = lambda op, **args: calls.append((op, args)) or {"endpoints": []}
            with self.assertRaisesRegex(HubError, "duplicate service participant_id"):
                host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            self.assertEqual(calls, [])

    def test_scoped_inbox_message_and_ack_use_authenticated_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            ep = {"endpoint_id": "kai-endpoint", "runtime_id": "kai-runtime"}
            host.service = lambda pid, uid, req: ep
            calls = []

            def hub(op, **args):
                calls.append((op, args))
                if op in ("query", "query_local"):
                    return {"message_id": args["message_id"], "recipient_endpoint": ep["endpoint_id"]}
                return {"messages": [], "next_cursor": 0} if op == "inbox" else {"state": "presented"}

            host.hub = hub
            self.assertEqual(host.dispatch({"op": "service_inbox", "service_id": "kai"}, os.getpid(), os.getuid())["next_cursor"], 0)
            self.assertEqual(host.dispatch({"op": "service_message", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())["message_id"], "m1")
            host.dispatch({"op": "service_ack", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())
            self.assertEqual([item[0] for item in calls], ["inbox", "query_local", "query", "receipt"])
            host.db.close()


if __name__ == "__main__":
    unittest.main()

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
                self.assertEqual(host.caller(1, 1, {'conversation': {'thread_id': 'untrusted'}}), ep)
                self.assertEqual(calls, [('native_attest', {'endpoint_id': 'native', 'native_kind': 'thread_id', 'native_id': 'verified-thread'})])
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
                if op == "query":
                    return {"message_id": args["message_id"], "recipient_endpoint": ep["endpoint_id"]}
                return {"messages": [], "next_cursor": 0} if op == "inbox" else {"state": "presented"}

            host.hub = hub
            self.assertEqual(host.dispatch({"op": "service_inbox", "service_id": "kai"}, os.getpid(), os.getuid())["next_cursor"], 0)
            self.assertEqual(host.dispatch({"op": "service_message", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())["message_id"], "m1")
            host.dispatch({"op": "service_ack", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())
            self.assertEqual([item[0] for item in calls], ["inbox", "query", "query", "receipt"])
            host.db.close()


if __name__ == "__main__":
    unittest.main()

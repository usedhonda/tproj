#!/usr/bin/env python3
"""Live mixed-version preflight must preserve every dependent installed byte."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import types

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / 'extensions/messaging/install-tproj-messaging-runtime'
sys.path.insert(0, str(ROOT / 'extensions/messaging/unified'))


class CompatibilityTests(unittest.TestCase):
    def test_enrolled_rejection_preserves_tools_and_diagnostics(self):
        task_ok = {'ok': True, 'result': {'host_capabilities': ['task_retired_operation', 'task_binding_status'],
                                           'task_master': {'capabilities': ['task_cancelled_release_check', 'task_binding_release_check']}}}
        required = ['service_policy_v1', 'read_only_diagnose', 'query_only_service', 'resource_exhausted']
        owner_required = ['native_continuity', 'read_only_diagnose', 'diagnostic_identity', 'resource_exhausted']
        responses = [None, {'ok': False, 'error': {'code': 'unknown_op'}},
                     {'ok': True, 'result': {'host_capabilities': ['task_retired_operation', 'task_binding_status'],
                                            'task_master': {'capabilities': ['task_binding_release_check']}}},
                     [task_ok, {'ok': False, 'error': {'code': 'unknown_op'}}],
                     [task_ok, {'ok': True, 'result': {'host_capabilities': required,
                                                     'messaging_owner': {'capabilities': owner_required[:-1], 'peers': {}}}}],
                     [task_ok, {'ok': True, 'result': {'host_capabilities': required[:-1],
                                                     'messaging_owner': {'capabilities': owner_required, 'peers': {}}}}]]
        for response in responses:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                home = Path(temp); config = home / '.config/tproj'; config.mkdir(parents=True)
                path = str(home / 'host.sock')
                (config / 'msg-client.json').write_text(json.dumps({'active': True, 'socket': path}))
                for relative in ('bin/tproj-task', 'bin/tproj-formal-task-guard',
                                 'lib/tproj-msg-unified/host.py', '.codex/hooks.json'):
                    target = home / relative; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('original binding-status diagnostic and tools\n')
                before = {p.relative_to(home): (p.read_bytes(), p.stat().st_mode) for p in home.rglob('*') if p.is_file()}
                server = None
                if response is not None:
                    server = socket.socket(socket.AF_UNIX); server.bind(path); server.listen()
                    def answer():
                        replies = response if isinstance(response, list) else [response]
                        for op, reply in zip(('runtime_capabilities', 'messaging_capabilities'), replies):
                            conn, _ = server.accept()
                            with conn:
                                request = json.loads(conn.makefile('rb').readline())
                                self.assertEqual(request, {'op': op})
                                conn.sendall((json.dumps(reply) + '\n').encode())
                    thread = threading.Thread(target=answer); thread.start()
                result = subprocess.run([str(INSTALLER), '--home', str(home), '--skip-codex-trust'], capture_output=True, text=True)
                if server is not None:
                    thread.join(); server.close()
                self.assertEqual(result.returncode, 1)
                self.assertIn('binding-status diagnostics remain untouched', result.stderr)
                after = {p.relative_to(home): (p.read_bytes(), p.stat().st_mode) for p in home.rglob('*') if p.is_file()}
                self.assertEqual(before, after)

    def test_supported_live_messaging_owner_passes_preflight(self):
        loader = importlib.machinery.SourceFileLoader('runtime_installer', str(INSTALLER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec); loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); config = home / '.config/tproj'; config.mkdir(parents=True)
            path = str(home / 'host.sock')
            (config / 'msg-client.json').write_text(json.dumps({'active': True, 'socket': path}))
            caps = ['service_policy_v1', 'read_only_diagnose', 'query_only_service', 'resource_exhausted']
            owner_caps = ['native_continuity', 'read_only_diagnose', 'diagnostic_identity', 'resource_exhausted']
            results = [
                {'host_capabilities': ['task_retired_operation', 'task_binding_status'],
                 'task_master': {'capabilities': ['task_cancelled_release_check', 'task_binding_release_check']}},
                {'host_capabilities': caps, 'messaging_owner': {'capabilities': owner_caps,
                                                          'peers': {'remote': {'capabilities': owner_caps}}}}]
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path); server.listen()
                def answer():
                    for op, result in zip(('runtime_capabilities', 'messaging_capabilities'), results):
                        conn, _ = server.accept()
                        with conn:
                            self.assertEqual(json.loads(conn.makefile('rb').readline()), {'op': op})
                            conn.sendall((json.dumps({'ok': True, 'result': result}) + '\n').encode())
                thread = threading.Thread(target=answer); thread.start()
                self.assertEqual(module.compatibility_errors(home), [])
                thread.join()

    def test_new_host_does_not_claim_capabilities_of_old_task_module(self):
        from host import Host
        host = object.__new__(Host)
        host.hub = Mock()
        with patch.dict(sys.modules, {'task_host': types.ModuleType('old_task_host')}):
            with self.assertRaises(ImportError):
                host.dispatch({'op': 'runtime_capabilities'}, 1, os.getuid())
        host.hub.assert_not_called()

    def test_route_authentication_and_master_selection(self):
        from host import Host
        from hub import Hub
        from protocol import HubError
        from task_transport import capabilities
        from tasks import task_capabilities
        host = object.__new__(Host); host.hub = Mock(return_value={'capabilities': task_capabilities()})
        with self.assertRaises(HubError):
            host.dispatch({'op': 'runtime_capabilities'}, 1, os.getuid() + 1)
        self.assertIn('task_retired_operation', host.dispatch({'op': 'runtime_capabilities'}, 1, os.getuid())['host_capabilities'])
        host.hub.assert_called_once_with('task_capabilities')
        hub = Mock(); hub.local_id = 'local'; hub._auth.return_value = 'local'
        hub.topology.return_value = {'mode': 'multi', 'task_master_host_id': 'master'}
        hub.peers.return_value = {'master': {}}
        hub.remote.return_value = {'master_host_id': 'master', 'capabilities': []}
        self.assertEqual(capabilities(hub, {}), hub.remote.return_value)
        hub.remote.assert_called_once_with('master', 'task_capabilities')
        self.assertIn('task_cancelled_release_check', task_capabilities())
        self.assertIn('task_binding_release_check', task_capabilities())


if __name__ == '__main__': unittest.main()

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
import native_queue as queue


class QueueTest(unittest.TestCase):
    def setUp(self):
        # Unit coverage does not require an optional third-party installation.
        ws = types.ModuleType('websockets')
        sync = types.ModuleType('websockets.sync')
        client = types.ModuleType('websockets.sync.client')
        client.unix_connect = lambda *args, **kwargs: None
        ws.sync = sync
        sync.client = client
        modules = patch.dict(sys.modules, {'websockets': ws, 'websockets.sync': sync, 'websockets.sync.client': client})
        modules.start()
        self.addCleanup(modules.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'control.sock'
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.path))
        self.addCleanup(self.sock.close)
        self.path.chmod(0o600)
        self.native = '11111111-1111-4111-8111-111111111111'
        self.notice = dict(native_id=self.native, prompt='fixture reference', client_id='stable-correlation')

    def test_conflicting_private_wheel_cannot_silently_fall_back_to_global(self):
        wheel = Path(self.tmp.name) / queue.WHEEL_NAME
        wheel.write_bytes(b'not the pinned package')
        with patch.object(queue,'__file__',str(Path(self.tmp.name)/'native_queue.py')):
            with self.assertRaises(queue.QueueError) as error: queue.queue_client()
        self.assertEqual(error.exception.code,'dependency_unavailable')

    def test_dependency_install_digest_failure_preserves_absence(self):
        import importlib.util, io
        spec=importlib.util.spec_from_file_location('queue_install_fixture',Path(queue.__file__).with_name('install.py'))
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'tampered wheel')):
            with self.assertRaises(RuntimeError):installer.native_queue_dependency(Path(self.tmp.name))
        self.assertFalse((Path(self.tmp.name)/'lib/tproj-msg-unified'/queue.WHEEL_NAME).exists())

    def fake(self, response):
        sent = []
        class WS:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def send(self, data): sent.append(json.loads(data))
            def recv(self, timeout):
                if sent[-1].get('id') == 1: return json.dumps({'id': 1, 'result': {}})
                if isinstance(response, Exception): raise response
                return json.dumps(response)
        return WS(), sent

    def test_existing_private_socket_and_owner_symlink_only(self):
        link = self.path.with_name('control-link')
        link.symlink_to(self.path)
        self.assertEqual(queue.private_socket(link), str(self.path.resolve()))
        self.path.chmod(0o666)
        with self.assertRaises(queue.QueueError): queue.private_socket(link)
        ordinary = self.path.with_name('not-a-socket')
        ordinary.write_text('fixture')
        with self.assertRaises(queue.QueueError): queue.private_socket(ordinary)

    def test_single_publication_preserves_notice_and_correlation_without_retry(self):
        result = {'queuedSubmission': {'id': 'queued', 'input': [{'type': 'text', 'text': self.notice['prompt']}], 'clientUserMessageId': self.notice['client_id']}}
        ws, sent = self.fake({'id': 2, 'result': result})
        with patch('websockets.sync.client.unix_connect', return_value=ws) as connect:
            self.assertEqual(queue.publish(self.path, self.native, self.notice), result)
            connect.assert_called_once()
        calls = [x for x in sent if x['method'] == 'thread/queue/add']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['params']['clientUserMessageId'], self.notice['client_id'])
        self.assertEqual(calls[0]['params']['input'], [{'type': 'text', 'text': self.notice['prompt']}])
        self.assertFalse(any('resume' in x['method'] or 'start' in x['method'] for x in sent))

    def test_lost_or_internal_error_add_result_is_unknown_not_retried(self):
        for response in (TimeoutError(), {'id': 2, 'error': {'code': -32000, 'message': 'internal'}}, {'id': 2, 'result': []}):
            with self.subTest(response=type(response).__name__):
                ws, sent = self.fake(response)
                with patch('websockets.sync.client.unix_connect', return_value=ws):
                    with self.assertRaises(queue.QueueError) as error:
                        queue.publish(self.path, self.native, self.notice)
                self.assertEqual(error.exception.code, 'publication_unknown')
                self.assertEqual(sum(x['method'] == 'thread/queue/add' for x in sent), 1)

    def test_malformed_error_envelope_is_unknown_not_known_rejection(self):
        cases = [
            {'id': 2, 'result': {}, 'error': {'code': -32602, 'message': 'invalid'}},
            {'jsonrpc': '1.0', 'id': 2, 'error': {'code': -32602, 'message': 'invalid'}},
            {'id': 2.0, 'error': {'code': -32602, 'message': 'invalid'}},
            {'id': 2, 'error': {'code': -32602}},
            {'id': 2, 'error': {'code': True, 'message': 'invalid'}},
        ]
        for response in cases:
            with self.subTest(response=response):
                ws, _ = self.fake(response)
                with patch('websockets.sync.client.unix_connect', return_value=ws):
                    with self.assertRaises(queue.QueueError) as error:
                        queue.publish(self.path, self.native, self.notice)
                self.assertEqual(error.exception.code, 'publication_unknown')

    def test_unrelated_notifications_cannot_reset_reply_deadline(self):
        ws, sent = self.fake({'id': 'unrelated', 'result': {}})
        clock = iter(range(1000))
        with patch('websockets.sync.client.unix_connect', return_value=ws), \
             patch.object(queue.time, 'monotonic', side_effect=lambda: next(clock)):
            with self.assertRaises(queue.QueueError) as error:
                queue.publish(self.path, self.native, self.notice)
        self.assertEqual(error.exception.code, 'publication_unknown')
        self.assertEqual(sum(x['method'] == 'thread/queue/add' for x in sent), 1)

    def test_invalid_params_rejection_and_invalid_binding_do_not_become_success(self):
        ws, _ = self.fake({'id': 2, 'error': {'code': -32602, 'message': 'invalid'}})
        with patch('websockets.sync.client.unix_connect', return_value=ws):
            with self.assertRaises(queue.QueueError) as error: queue.publish(self.path, self.native, self.notice)
        self.assertEqual(error.exception.code, 'operation_rejected')
        for native in ('-' * 36, 'not-a-thread'):
            with self.assertRaises(queue.QueueError): queue.publish(self.path, native, self.notice)
        with self.assertRaises(queue.QueueError): queue.publish(self.path, self.native, dict(self.notice, native_id='foreign'))
        with self.assertRaises(queue.QueueError): queue.request(self.path, 'thread/resume', {})

    def test_list_is_bounded_and_initialization_failure_never_sends_add(self):
        ws, sent = self.fake({'id': 2, 'result': {'data': [], 'nextCursor': None}})
        with patch('websockets.sync.client.unix_connect', return_value=ws):
            self.assertEqual(queue.pending(self.path, self.native), {'data': [], 'nextCursor': None})
        self.assertEqual(sent[-1]['params']['limit'], 32)
        with patch('websockets.sync.client.unix_connect', side_effect=OSError()):
            with self.assertRaises(queue.QueueError) as error: queue.publish(self.path, self.native, self.notice)
        self.assertEqual(error.exception.code, 'transport_unavailable')
        with patch.dict(sys.modules, {'websockets.sync.client': None}):
            with self.assertRaises(queue.QueueError) as error: queue.publish(self.path, self.native, self.notice)
        self.assertEqual(error.exception.code, 'dependency_unavailable')


if __name__ == '__main__': unittest.main()

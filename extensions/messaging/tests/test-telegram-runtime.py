"""One fake phone/API -> host -> reply cycle, no model or live credentials."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
from telegram_ingress import TelegramIngressAuthority, TelegramOwnerBinding
from telegram_runtime import TelegramRuntime


class RuntimeTest(unittest.TestCase):
    def test_poll_host_and_reply_use_exact_text_and_durable_cursors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            binding = TelegramOwnerBinding('test-binding', 'test-owner', 101, 202,
                                           202, 'kai', 1, 2000)
            config = {'owner_binding': asdict(binding), 'ingress_secret': 'fixture_ingress_secret',
                      'bot_token_keychain': {'service': 'openclaw.kai.telegram', 'account': '101'},
                      'journal': str(Path(tmp) / 'relay.db'),
                      'kai_endpoint': 'kai-ep', 'host_socket': str(Path(tmp) / 'host.sock'),
                      'service_id': 'telegram', 'service_token': 'fixture-service',
                      'address': 'telegram-owner', 'binding_generation': 'fixture-gen'}
            path.write_text(json.dumps(config)); path.chmod(0o600)
            update = {'update_id': 12, 'message': {'message_id': 30,
                      'from': {'id': 202, 'is_bot': False},
                      'chat': {'id': 202, 'type': 'private'}, 'text': 'original text'}}
            authority = TelegramIngressAuthority(binding, config['ingress_secret'])
            intent = authority.admit(json.dumps(update).encode(), config['ingress_secret'], now=1000)
            reply = {'message_id': 'kai-reply-1', 'thread_id': intent.message_id,
                     'in_reply_to': intent.message_id, 'sender_endpoint': 'kai-ep',
                     'body': 'KAI original answer'}
            host_calls, api_calls = [], []
            inbox = []
            def host(_socket, req):
                host_calls.append(req)
                if req['op'] == 'service_whoami':
                    return {'address': config['address'], 'binding_generation': 'fixture-gen'}
                if req['op'] == 'service_telegram_ingress':
                    self.assertNotIn('external_origin', req)
                    self.assertEqual(json.loads(req['raw_update']), update)
                    return {'message_id': intent.message_id, 'state': 'queued'}
                if req['op'] == 'service_inbox': return {'messages': inbox}
                if req['op'] == 'service_message': return reply
                if req['op'] == 'service_ack': return {'state': 'presented'}
                raise AssertionError(req['op'])
            class API:
                def call(_self, method, payload):
                    api_calls.append((method, payload))
                    if method == 'getMe': return {'id': 101, 'is_bot': True}
                    if method == 'getUpdates': return [update]
                    if method == 'sendMessage': return {'message_id': 80, 'chat': {'id': 202}}
                    raise AssertionError(method)
            runtime = TelegramRuntime(str(path), api=API(), host_call=host, clock=lambda: 1000)
            runtime.verify()
            runtime.receive_once()
            self.assertEqual(runtime.cursor('updates'), 13)
            inbox.append({'message_id': reply['message_id'], 'sequence': 1})
            runtime.replies_once()
            self.assertEqual(runtime.cursor('mailbox'), 1)
            # A stale fake inbox response after restart must not resend text.
            runtime.journal.close()
            runtime = TelegramRuntime(str(path), api=API(), host_call=host, clock=lambda: 1000)
            runtime.verify()
            runtime.receive_once()
            runtime.replies_once()
            sends = [payload for method, payload in api_calls if method == 'sendMessage']
            self.assertEqual(sends, [{'chat_id': 202, 'text': 'KAI original answer',
                                      'reply_parameters': {'message_id': 30,
                                        'allow_sending_without_reply': False}}])
            self.assertEqual(len([r for r in host_calls if r['op'] == 'service_telegram_ingress']), 1)
            runtime.journal.close()


if __name__ == '__main__':
    unittest.main()

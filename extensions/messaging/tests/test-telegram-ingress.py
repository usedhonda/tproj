"""Focused transport contract checks; no live Telegram or KAI claim."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
from telegram_ingress import (TelegramIngressAuthority, TelegramIngressError,
                              TelegramIngressJournal, TelegramMailboxRelay,
                              TelegramOwnerBinding)


class TelegramIngressTest(unittest.TestCase):
    def setUp(self):
        self.binding = TelegramOwnerBinding('fixture-binding', 'fixture-owner',
                                           101, 202, 202, 'kai', 1, 2000)
        self.secret = 'fixture_webhook_secret'
        self.authority = TelegramIngressAuthority(self.binding, self.secret)
        self.update = {'update_id': 12, 'message': {'message_id': 30,
                       'from': {'id': 202, 'is_bot': False},
                       'chat': {'id': 202, 'type': 'private'}, 'text': 'カイ君へ\nそのまま'}}

    def raw(self):
        return json.dumps(self.update, ensure_ascii=False).encode()

    def admit(self):
        return self.authority.admit(self.raw(), self.secret, now=1000)

    def test_tuple_header_and_input_fail_closed(self):
        for header in ('wrong', '日本語', '', None):
            with self.subTest(header=header), self.assertRaises(TelegramIngressError):
                self.authority.admit(self.raw(), header, now=1000)
        for section, key, value in [('from', 'id', 999), ('chat', 'id', 999),
                                    ('chat', 'type', 'group'), ('from', 'is_bot', True)]:
            old = self.update['message'][section][key]
            self.update['message'][section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(TelegramIngressError):
                self.admit()
            self.update['message'][section][key] = old
        for key in ('forward_origin', 'voice', 'via_bot'):
            self.update['message'][key] = {}
            with self.assertRaises(TelegramIngressError): self.admit()
            del self.update['message'][key]
        raw = b'{"update_id":1,"update_id":2,"message":{}}'
        with self.assertRaises(TelegramIngressError):
            self.authority.admit(raw, self.secret, now=1000)

    def test_persistence_conflict_and_unknown_do_not_resubmit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'journal.db')
            journal = TelegramIngressJournal(path)
            calls = []
            def uncertain(envelope):
                calls.append(envelope)
                raise TimeoutError()
            relay = TelegramMailboxRelay(self.authority, journal, lambda: self.binding,
                                         uncertain, None, kai_endpoint='kai-ep')
            with self.assertRaisesRegex(TelegramIngressError, 'submission_unknown'):
                relay.receive(self.raw(), self.secret, now=1000)
            journal.close()
            journal = TelegramIngressJournal(path)
            relay.journal = journal
            result = relay.receive(self.raw(), self.secret, now=1000)
            self.assertTrue(result['duplicate'])
            self.assertEqual(result['state'], 'unknown')
            self.assertEqual(len(calls), 1)
            self.update['message']['text'] = 'different body'
            with self.assertRaisesRegex(TelegramIngressError, 'id_conflict'):
                relay.receive(self.raw(), self.secret, now=1000)
            self.assertEqual(len(calls), 1)
            journal.close()

    def test_round_trip_preserves_text_correlates_and_fences_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TelegramIngressJournal(str(Path(tmp) / 'journal.db'))
            submitted, sent = [], []
            current = [self.binding]
            def submit(envelope):
                submitted.append(envelope)
                return {'message_id': envelope['message_id'], 'state': 'queued'}
            def send(payload):
                sent.append(payload)
                return {'message_id': 90, 'chat_id': payload['chat_id']}
            relay = TelegramMailboxRelay(self.authority, journal, lambda: current[0],
                                         submit, send, kai_endpoint='kai-ep')
            result = relay.receive(self.raw(), self.secret, now=1000)
            self.assertEqual(submitted[0]['body'], self.update['message']['text'])
            mid = result['message_id']
            reply = {'message_id': 'kai-output-1', 'in_reply_to': mid,
                     'thread_id': mid, 'sender_endpoint': 'kai-ep', 'body': '返事をそのまま'}
            with self.assertRaisesRegex(TelegramIngressError, 'reply_not_authorized'):
                relay.deliver_reply(dict(reply, sender_endpoint='other'), now=1000)
            self.assertEqual(sent, [])
            relay.deliver_reply(reply, now=1000)
            relay.deliver_reply(reply, now=1000)
            self.assertEqual(sent, [{'chat_id': 202, 'text': '返事をそのまま',
                                     'reply_to_message_id': 30}])
            relay.deliver_reply(dict(reply, message_id='kai-output-2', body='途中経過'), now=1000)
            self.assertEqual(len(sent), 2)
            current[0] = replace(self.binding, revoked=True)
            with self.assertRaisesRegex(TelegramIngressError, 'binding_inactive'):
                relay.deliver_reply(dict(reply, message_id='kai-output-3'), now=1000)
            self.assertEqual(len(sent), 2)
            journal.close()

    def test_unknown_telegram_send_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = TelegramIngressJournal(str(Path(tmp) / 'journal.db'))
            intent = self.admit()
            journal.reserve(intent)
            calls = []
            def send(payload):
                calls.append(payload)
                raise TimeoutError()
            relay = TelegramMailboxRelay(self.authority, journal, lambda: self.binding,
                                         None, send, kai_endpoint='kai-ep')
            reply = {'message_id': 'output-1', 'in_reply_to': intent.message_id,
                     'thread_id': intent.message_id, 'sender_endpoint': 'kai-ep', 'body': 'hello'}
            with self.assertRaisesRegex(TelegramIngressError, 'delivery_unknown'):
                relay.deliver_reply(reply, now=1000)
            self.assertTrue(relay.deliver_reply(reply, now=1000)['duplicate'])
            self.assertEqual(len(calls), 1)
            journal.close()


if __name__ == '__main__':
    unittest.main()

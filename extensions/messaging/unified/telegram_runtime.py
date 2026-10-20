"""Dedicated bot long-poll adapter. Not installed or enabled by this module.

Requires the separately implemented service_telegram_ingress host operation and
operator-owned enrollment/configuration. It never invokes an OpenClaw model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
import urllib.request

from host import rpc
from telegram_credentials import bot_token
from telegram_ingress import (TelegramIngressAuthority, TelegramIngressError,
                              TelegramIngressJournal, TelegramMailboxRelay,
                              TelegramOwnerBinding)


def private_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 262144):
            raise TelegramIngressError('unsafe_runtime_configuration')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            raw = stream.read(262145)
            after = os.fstat(stream.fileno())
        if (len(raw) > 262144 or (info.st_size, info.st_mtime_ns) !=
                (after.st_size, after.st_mtime_ns)):
            raise TelegramIngressError('unstable_runtime_configuration')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TelegramIngressError('invalid_runtime_configuration')
        return value
    finally:
        if fd is not None:
            os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise TelegramIngressError('telegram_redirect_rejected')


class TelegramAPI:
    def __init__(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
            raise TelegramIngressError('invalid_bot_configuration')
        self._base = 'https://api.telegram.org/bot' + token + '/'

    def call(self, method, payload):
        if method not in ('getMe', 'getUpdates', 'sendMessage'):
            raise TelegramIngressError('unsupported_api_method')
        request = urllib.request.Request(self._base + method,
                                         data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('ok') is not True:
                raise ValueError()
            return value['result']
        except Exception:
            # urllib exceptions can include the credential-bearing URL.
            raise TelegramIngressError('telegram_api_unavailable') from None


class TelegramRuntime:
    def __init__(self, config_path, *, api=None, host_call=None, clock=time.time):
        self.config_path = config_path
        self.config = private_config(config_path)
        self.binding = TelegramOwnerBinding(**self.config['owner_binding'])
        self.api = api or TelegramAPI(bot_token(self.config, self.binding.bot_id))
        self.host_call = host_call or rpc
        self.clock = clock
        self.journal = TelegramIngressJournal(self.config['journal'])
        self.journal.db.execute('CREATE TABLE IF NOT EXISTS telegram_cursors ('
                                'name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        self.authority = TelegramIngressAuthority(self.binding)
        self.verified_bot_id = None
        self.relay = TelegramMailboxRelay(self.authority, self.journal,
                                         self.current_binding, self.submit, self.send,
                                         kai_endpoint=self.config['kai_endpoint'])
        self._raw_current = None

    def current_binding(self):
        # Do not retain revoked binding evidence merely because a process lives.
        latest = private_config(self.config_path)
        if any(latest.get(k) != self.config.get(k) for k in
               ('host_socket', 'service_id', 'service_token', 'address',
                'binding_generation', 'bot_token_keychain', 'kai_endpoint')):
            raise TelegramIngressError('runtime_configuration_changed')
        return TelegramOwnerBinding(**latest['owner_binding'])

    def host(self, op, **args):
        request = dict(args, op=op)
        for key in ('service_id', 'service_token', 'address', 'binding_generation'):
            request[key] = self.config[key]
        return self.host_call(self.config['host_socket'], request)

    def submit(self, envelope):
        if self._raw_current is None:
            raise TelegramIngressError('missing_raw_update')
        # Host reconstructs origin under its own approved tuple; it must NOT
        # accept external_origin as a caller-supplied verification assertion.
        receipt = self.host('service_telegram_ingress', raw_update=self._raw_current,
                            verified_bot_id=self.verified_bot_id)
        if not isinstance(receipt, dict) or receipt.get('message_id') != envelope['message_id']:
            raise TelegramIngressError('submission_unknown')
        return receipt

    def send(self, payload):
        result = self.api.call('sendMessage', {
            'chat_id': payload['chat_id'], 'text': payload['text'],
            'reply_parameters': {'message_id': payload['reply_to_message_id'],
                                 'allow_sending_without_reply': False}})
        if not isinstance(result, dict):
            raise TelegramIngressError('delivery_unknown')
        return {'message_id': result.get('message_id'),
                'chat_id': (result.get('chat') or {}).get('id')}

    def cursor(self, name):
        row = self.journal.db.execute('SELECT value FROM telegram_cursors WHERE name=?',
                                      (name,)).fetchone()
        return row[0] if row else 0

    def advance(self, name, value):
        self.journal.db.execute('INSERT INTO telegram_cursors VALUES(?,?) '
                                'ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, value))

    def verify(self):
        self.relay._active(self.clock())
        me = self.api.call('getMe', {})
        if not isinstance(me, dict) or me.get('id') != self.binding.bot_id or me.get('is_bot') is not True:
            raise TelegramIngressError('bot_identity_mismatch')
        self.verified_bot_id = me['id']
        identity = self.host('service_whoami')
        if (not isinstance(identity, dict) or identity.get('address') != self.config['address']
                or identity.get('binding_generation') != self.config['binding_generation']):
            raise TelegramIngressError('service_identity_mismatch')

    def receive_once(self):
        updates = self.api.call('getUpdates', {'offset': self.cursor('updates'),
                                'timeout': 10, 'limit': 10, 'allowed_updates': ['message']})
        if not isinstance(updates, list):
            raise TelegramIngressError('invalid_updates_response')
        for update in updates:
            if not isinstance(update, dict) or type(update.get('update_id')) is not int:
                raise TelegramIngressError('invalid_updates_response')
            update_id = update['update_id']
            if update_id < self.cursor('updates'):
                continue
            raw = json.dumps(update, ensure_ascii=False).encode()
            try:
                self.authority.admit_authenticated_poll(raw, verified_bot_id=self.verified_bot_id, now=self.clock())
            except TelegramIngressError as exc:
                if str(exc) == 'binding_inactive':
                    raise
                # Unsupported/spam updates cannot enter the mailbox or stop
                # subsequent authenticated owner text on a dedicated bot.
                self.advance('updates', update_id + 1)
                continue
            self._raw_current = raw.decode()
            try:
                result = self.relay.receive(raw, now=self.clock(), authenticated_poll_bot_id=self.verified_bot_id)
            finally:
                self._raw_current = None
            if result.get('state') in ('reserved', 'unknown'):
                raise TelegramIngressError('submission_requires_reconciliation')
            self.advance('updates', update_id + 1)

    def replies_once(self):
        inbox = self.host('service_inbox', cursor=self.cursor('mailbox'), limit=100)
        for item in inbox['messages']:
            # Requery by exact ID through authenticated host before any send.
            reply = self.host('service_message', message_id=item['message_id'])
            result = self.relay.deliver_reply(reply, now=self.clock())
            if result.get('state') != 'accepted':
                raise TelegramIngressError('delivery_requires_reconciliation')
            self.host('service_ack', message_id=item['message_id'])
            self.advance('mailbox', item['sequence'])

    def run(self):
        self.verify()
        while True:
            self.replies_once()
            self.receive_once()


def main():
    parser = argparse.ArgumentParser(description='Run a separately enrolled Telegram-to-KAI transport')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    runtime = None
    try:
        runtime = TelegramRuntime(args.config)
        runtime.run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Do not print bodies, config values, bot URLs or exception reprs.
        print('Telegram transport stopped; inspect private receipts before restarting.', file=sys.stderr)
        return 2
    finally:
        if runtime:
            runtime.journal.close()


if __name__ == '__main__':
    raise SystemExit(main())

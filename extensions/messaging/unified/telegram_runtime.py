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
                              TelegramOwnerBinding, approved_bindings, select_binding,
                              observe_group_candidate, group_discovery_window)

GROUP_DISCOVERY_TTL = 900
GROUP_DISCOVERY_MAX_ROWS = 16


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
        self.journal.db.execute('CREATE TABLE IF NOT EXISTS telegram_group_candidates ('
                                'chat_id INTEGER PRIMARY KEY, metadata TEXT NOT NULL, observed_at REAL NOT NULL, expires_at REAL NOT NULL)')
        if 'expires_at' not in {row[1] for row in self.journal.db.execute('PRAGMA table_info(telegram_group_candidates)')}:
            self.journal.db.execute('ALTER TABLE telegram_group_candidates ADD COLUMN expires_at REAL NOT NULL DEFAULT 0')
        self.journal.db.execute('CREATE TABLE IF NOT EXISTS telegram_reply_holds ('
            'message_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, envelope TEXT NOT NULL, '
            'reason TEXT NOT NULL, prior_reply_state TEXT, held_at REAL NOT NULL)')
        self.authority = TelegramIngressAuthority(self.binding)
        self.verified_bot_id = None
        self.relay = TelegramMailboxRelay(self.authority, self.journal,
                                         self.current_binding, self.submit, self.send,
                                         kai_endpoint=self.config['kai_endpoint'])
        self.relays = {self.binding.binding_id: self.relay}
        for ident, binding in approved_bindings(self.config).items():
            if ident != self.binding.binding_id:
                self.relays[ident] = TelegramMailboxRelay(
                    TelegramIngressAuthority(binding), self.journal,
                    lambda ident=ident: self.current_binding(ident), self.submit, self.send,
                    kai_endpoint=self.config['kai_endpoint'])
        self._raw_current = None

    def current_config(self):
        # Do not retain revoked binding evidence merely because a process lives.
        latest = private_config(self.config_path)
        if any(latest.get(k) != self.config.get(k) for k in
               ('host_socket', 'service_id', 'service_token', 'address',
                'binding_generation', 'bot_token_keychain', 'kai_endpoint')):
            raise TelegramIngressError('runtime_configuration_changed')
        primary = TelegramOwnerBinding(**latest['owner_binding'])
        if any(getattr(primary, key) != getattr(self.binding, key) for key in
               ('binding_id', 'owner_id', 'bot_id', 'user_id', 'chat_id', 'target', 'generation', 'chat_type')):
            raise TelegramIngressError('runtime_configuration_changed')
        return latest

    def current_binding(self, binding_id=None):
        latest = self.current_config()
        binding = approved_bindings(latest).get(binding_id or self.binding.binding_id)
        if binding is None:
            raise TelegramIngressError('binding_inactive')
        return binding

    def maintain_group_candidates(self, settings, candidate=None):
        """Expire diagnostics even on empty polls; enforce one bounded store."""
        now = self.clock()
        window = group_discovery_window(settings, verified_bot_id=self.verified_bot_id, now=now)
        db = self.journal.db
        db.execute('BEGIN IMMEDIATE')
        try:
            if window is None:
                db.execute('DELETE FROM telegram_group_candidates')
            else:
                db.execute('DELETE FROM telegram_group_candidates WHERE expires_at<=? OR observed_at<=?',
                           (now, now-GROUP_DISCOVERY_TTL))
                if candidate is not None:
                    db.execute('INSERT INTO telegram_group_candidates VALUES(?,?,?,?) '
                        'ON CONFLICT(chat_id) DO UPDATE SET metadata=excluded.metadata,observed_at=excluded.observed_at,expires_at=excluded.expires_at',
                        (candidate['chat_id'], json.dumps(candidate, sort_keys=True), now,
                         min(window[1]['expires_at'], now+GROUP_DISCOVERY_TTL)))
                db.execute('DELETE FROM telegram_group_candidates WHERE chat_id NOT IN ('
                    'SELECT chat_id FROM telegram_group_candidates ORDER BY observed_at DESC,chat_id DESC LIMIT ?)',
                    (GROUP_DISCOVERY_MAX_ROWS,))
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise

    def hold_group_reply(self, item, reply, binding_id, reason):
        """Durably retain an authenticated reply; never retry or ACK it here.

        Cursor movement and the hold commit together, so later private items
        can proceed without losing an unsent or ambiguously sent group reply.
        """
        envelope = json.dumps({k: reply.get(k) for k in
            ('message_id', 'in_reply_to', 'thread_id', 'sender_endpoint', 'body')},
            sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        db = self.journal.db
        db.execute('BEGIN IMMEDIATE')
        try:
            previous = db.execute('SELECT envelope FROM telegram_reply_holds WHERE message_id=?',
                                  (item['message_id'],)).fetchone()
            if previous is not None and previous[0] != envelope:
                raise TelegramIngressError('id_conflict')
            db.execute('INSERT OR IGNORE INTO telegram_reply_holds VALUES(?,?,?,?,?,?)',
                (item['message_id'], binding_id, envelope, reason,
                 self.journal.reply_state(item['message_id']), self.clock()))
            self.advance('mailbox', max(self.cursor('mailbox'), item['sequence']))
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise

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
        self.maintain_group_candidates(self.current_config())
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
            latest = self.current_config()
            candidate = observe_group_candidate(latest, raw,
                verified_bot_id=self.verified_bot_id, now=self.clock())
            self.maintain_group_candidates(latest, candidate)
            binding = None
            try:
                binding = select_binding(self.config, raw)
                relay = self.relays[binding.binding_id]
                relay.authority.admit_authenticated_poll(raw, verified_bot_id=self.verified_bot_id, now=self.clock())
                relay._active(self.clock())
            except TelegramIngressError as exc:
                if str(exc) == 'binding_inactive' and binding is not None and binding.chat_type == 'private':
                    raise
                # Unsupported/spam updates cannot enter the mailbox or stop
                # subsequent authenticated owner text on a dedicated bot.
                self.advance('updates', update_id + 1)
                continue
            self._raw_current = raw.decode()
            try:
                result = relay.receive(raw, now=self.clock(), authenticated_poll_bot_id=self.verified_bot_id)
            except TelegramIngressError as exc:
                if str(exc) == 'binding_inactive' and binding.chat_type != 'private':
                    self.advance('updates', update_id + 1)
                    continue
                raise
            finally:
                self._raw_current = None
            if result.get('state') in ('reserved', 'unknown'):
                raise TelegramIngressError('submission_requires_reconciliation')
            self.advance('updates', update_id + 1)

    def replies_once(self):
        self.maintain_group_candidates(self.current_config())
        inbox = self.host('service_inbox', cursor=self.cursor('mailbox'), limit=100)
        for item in inbox['messages']:
            if self.journal.db.execute('SELECT 1 FROM telegram_reply_holds WHERE message_id=?',
                                       (item['message_id'],)).fetchone():
                self.advance('mailbox', max(self.cursor('mailbox'), item['sequence']))
                continue
            # Requery by exact ID through authenticated host before any send.
            reply = self.host('service_message', message_id=item['message_id'])
            original = self.journal.intent(reply.get('in_reply_to'))
            origin = (original or {}).get('external_origin', {})
            ident = origin.get('binding_id')
            is_group = origin.get('chat_type') in ('group', 'supergroup')
            relay = self.relays.get(ident)
            if relay is None:
                if is_group:
                    self.hold_group_reply(item, reply, ident, 'binding_inactive')
                    continue
                raise TelegramIngressError('reply_not_authorized')
            try:
                result = relay.deliver_reply(reply, now=self.clock())
            except TelegramIngressError as exc:
                if is_group and str(exc) in ('binding_inactive', 'delivery_unknown'):
                    self.hold_group_reply(item, reply, ident, str(exc))
                    continue
                raise
            if result.get('state') != 'accepted':
                if is_group:
                    self.hold_group_reply(item, reply, ident, 'delivery_requires_reconciliation')
                    continue
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

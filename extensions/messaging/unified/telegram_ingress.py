"""Disabled-by-default Telegram ingress building block; no network or enrollment.

Only a trusted webhook adapter may construct this authority from operator-owned
configuration. A Telegram secret header authenticates that webhook boundary,
not a ChatGPT conversation or permission to execute arbitrary owner commands.
There is deliberately no public host/MCP operation exposing this module yet.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from typing import Any, Mapping


class TelegramIngressError(ValueError):
    """Fixed, non-secret ingress failure."""


def _positive_integer(value: Any) -> int:
    if type(value) is not int or value < 1 or value > 2**53 - 1:
        raise TelegramIngressError("invalid_identity")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise TelegramIngressError("invalid_binding")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


@dataclass(frozen=True)
class TelegramOwnerBinding:
    """An already-approved tuple, NOT an owner-registration request."""

    binding_id: str
    owner_id: str
    bot_id: int
    user_id: int
    chat_id: int
    target: str
    generation: int
    expires_at: float
    revoked: bool = False

    def __post_init__(self):
        for value in (self.binding_id, self.owner_id, self.target):
            _text(value)
        for value in (self.bot_id, self.user_id, self.chat_id, self.generation):
            _positive_integer(value)
        if (type(self.expires_at) not in (int, float)
                or not 0 < self.expires_at < float("inf")
                or type(self.revoked) is not bool):
            raise TelegramIngressError("invalid_binding")


@dataclass(frozen=True)
class TelegramIngressIntent:
    message_id: str
    target: str
    body: str
    origin_json: str

    def envelope(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "target": self.target,
                "body": self.body, "kind": "chat",
                "external_origin": json.loads(self.origin_json)}


def validate_origin(origin, message, binding, *, now):
    """Check a host-minted origin against a hub-approved current binding.

    A caller must additionally pin the configured attesting host/participant.
    This structural check is not itself ingress process authentication.
    """
    if not isinstance(origin, dict):
        raise TelegramIngressError('invalid_origin')
    synthetic = {'update_id': origin.get('update_id'), 'message': {
        'message_id': origin.get('message_id'),
        'from': {'id': origin.get('user_id'), 'is_bot': False},
        'chat': {'id': origin.get('chat_id'), 'type': 'private'},
        'text': message.get('body')}}
    # Private synthetic reconstruction checks the exact schema, body digest,
    # deterministic ID, recipient, kind, generation and approved tuple.
    key = 'internal_reconstruction_only'
    expected = TelegramIngressAuthority(binding, key).admit(
        json.dumps(synthetic).encode(), key, now=now)
    if (origin != expected.envelope()['external_origin']
            or message.get('message_id') != expected.message_id
            or message.get('target', message.get('target_address')) != binding.target
            or message.get('thread_id') not in (None, expected.message_id)
            or message.get('kind', 'chat') != 'chat' or message.get('in_reply_to')):
        raise TelegramIngressError('invalid_origin')
    return dict(origin)


class TelegramIngressAuthority:
    """Validate raw private-text webhook input under a fixed approved binding.

    Never derive binding, bot, owner, destination, or verified status from input.
    No arbitrary Python caller is an authenticated ingress merely by invoking
    this class; the future host adapter must enforce its process/transport gate.
    """

    def __init__(self, binding: TelegramOwnerBinding, webhook_secret: str | None = None):
        if not isinstance(binding, TelegramOwnerBinding):
            raise TelegramIngressError("invalid_binding")
        if webhook_secret is not None and (not isinstance(webhook_secret, str) or not 16 <= len(webhook_secret) <= 256
                or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
                       for c in webhook_secret)):
            raise TelegramIngressError("invalid_webhook_configuration")
        self.binding = binding
        self._webhook_secret = webhook_secret

    def admit(self, raw_body: bytes, secret_header: str, *, now: float) -> TelegramIngressIntent:
        if (self._webhook_secret is None or not isinstance(secret_header, str)
                or not secret_header.isascii() or len(secret_header) > 256
                or not secrets.compare_digest(secret_header, self._webhook_secret)):
            raise TelegramIngressError("webhook_authentication_failed")
        return self._admit(raw_body, now=now)

    def admit_authenticated_poll(self, raw_body, *, verified_bot_id, now):
        """Only the pinned polling process may invoke this trusted-code entry.

        Its TLS Telegram getMe/getUpdates client must establish the bot identity;
        an arbitrary RPC carrying this integer is NOT authentication. The host
        must first enforce dedicated-service credentials, launchd PID and config.
        No synthetic webhook header is used for polling.
        """
        if type(verified_bot_id) is not int or verified_bot_id != self.binding.bot_id:
            raise TelegramIngressError('bot_identity_mismatch')
        return self._admit(raw_body, now=now)

    def _admit(self, raw_body, *, now):
        binding = self.binding
        if (type(now) not in (int, float) or not 0 < now < float("inf")
                or binding.revoked or now >= binding.expires_at):
            raise TelegramIngressError("binding_inactive")
        if not isinstance(raw_body, bytes) or len(raw_body) > 64 * 1024:
            raise TelegramIngressError("invalid_update")
        try:
            update = json.loads(raw_body, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError):
            raise TelegramIngressError("invalid_update") from None
        if not isinstance(update, dict) or set(update) != {"update_id", "message"}:
            raise TelegramIngressError("unsupported_update")
        update_id = update["update_id"]
        if type(update_id) is not int or not 0 <= update_id <= 2**53 - 1:
            raise TelegramIngressError("invalid_update")
        message = update["message"]
        if not isinstance(message, dict):
            raise TelegramIngressError("invalid_update")
        if any(key in message for key in (
                "forward_origin", "forward_from", "forward_from_chat", "via_bot",
                "sender_chat", "is_automatic_forward", "edit_date", "photo", "document",
                "audio", "voice", "video", "sticker", "contact", "location")):
            raise TelegramIngressError("unsupported_message")
        sender, chat = message.get("from"), message.get("chat")
        if (not isinstance(sender, dict) or not isinstance(chat, dict)
                or sender.get("is_bot") is not False or chat.get("type") != "private"):
            raise TelegramIngressError("sender_not_authorized")
        user_id = _positive_integer(sender.get("id"))
        chat_id = _positive_integer(chat.get("id"))
        message_id = _positive_integer(message.get("message_id"))
        if user_id != binding.user_id or chat_id != binding.chat_id:
            raise TelegramIngressError("sender_not_authorized")
        body = message.get("text")
        if (not isinstance(body, str) or not body.strip()
                or any(0xD800 <= ord(c) <= 0xDFFF for c in body)
                or len(body.encode("utf-8")) > 16 * 1024
                or any(ord(c) < 32 and c not in "\n\t" for c in body) or "\x7f" in body):
            raise TelegramIngressError("invalid_text")
        # Stable across retries, independent of body; changing body/origin is a
        # conflict in the durable store rather than a second request.
        identity = _canonical({"bot": binding.bot_id, "update": update_id,
                               "binding": binding.binding_id, "generation": binding.generation})
        mid = "telegram:" + hashlib.sha256(identity.encode()).hexdigest()
        origin = {"version": 1, "channel": "telegram", "binding_id": binding.binding_id,
                  "owner_id": binding.owner_id, "bot_id": binding.bot_id,
                  "user_id": user_id, "chat_id": chat_id, "message_id": message_id,
                  "update_id": update_id, "generation": binding.generation,
                  "target": binding.target, "kind": "chat", "mailbox_message_id": mid,
                  "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
        return TelegramIngressIntent(mid, binding.target, body, _canonical(origin))


class TelegramIngressJournal:
    """Reserve a stable intent BEFORE sending; unknown sends never auto-repeat.

    This is only a local submission journal, not the authoritative mailbox.
    A binding-generation change must be fenced by the future host integration.
    No method executes a network effect or marks a KAI recipient as presented.
    """

    def __init__(self, path: str):
        parent = Path(path).absolute().parent
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise TelegramIngressError("unsafe_journal_path")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise TelegramIngressError("unsafe_journal_path")
        finally:
            os.close(fd)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS telegram_intents ("
                        "message_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, "
                        "state TEXT NOT NULL CHECK(state IN ('reserved','accepted','unknown')))")
        self.db.execute("CREATE TABLE IF NOT EXISTS telegram_replies ("
                        "message_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, "
                        "state TEXT NOT NULL CHECK(state IN ('reserved','accepted','unknown')))")

    def reserve(self, intent: TelegramIngressIntent) -> bool:
        if not isinstance(intent, TelegramIngressIntent):
            raise TelegramIngressError("invalid_intent")
        envelope = _canonical(intent.envelope())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT envelope FROM telegram_intents WHERE message_id=?",
                                  (intent.message_id,)).fetchone()
            if row is not None:
                if row[0] != envelope:
                    raise TelegramIngressError("id_conflict")
                self.db.execute("COMMIT")
                return False
            self.db.execute("INSERT INTO telegram_intents VALUES(?,?,'reserved')",
                            (intent.message_id, envelope))
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def settle(self, message_id: str, outcome: str) -> None:
        if outcome not in ("accepted", "unknown"):
            raise TelegramIngressError("invalid_outcome")
        # A late timeout cannot overwrite an authoritative acceptance receipt.
        changed = self.db.execute("UPDATE telegram_intents SET state=? "
                                  "WHERE message_id=? AND state IN ('reserved','unknown')",
                                  (outcome, message_id)).rowcount
        if not changed and not self.db.execute(
                "SELECT 1 FROM telegram_intents WHERE message_id=? AND state='accepted'",
                (message_id,)).fetchone():
            raise TelegramIngressError("unknown_intent")

    def state(self, message_id: str) -> str | None:
        row = self.db.execute("SELECT state FROM telegram_intents WHERE message_id=?",
                              (message_id,)).fetchone()
        return row[0] if row else None

    def intent(self, message_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT envelope FROM telegram_intents WHERE message_id=?",
                              (message_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def reserve_reply(self, message_id: str, payload: Mapping[str, Any]) -> bool:
        envelope = _canonical(payload)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT envelope FROM telegram_replies WHERE message_id=?",
                                  (message_id,)).fetchone()
            if row:
                if row[0] != envelope:
                    raise TelegramIngressError("id_conflict")
                self.db.execute("COMMIT")
                return False
            self.db.execute("INSERT INTO telegram_replies VALUES(?,?,'reserved')",
                            (message_id, envelope))
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def settle_reply(self, message_id: str, outcome: str) -> None:
        if outcome not in ("accepted", "unknown"):
            raise TelegramIngressError("invalid_outcome")
        self.db.execute("UPDATE telegram_replies SET state=? WHERE message_id=? "
                        "AND state!='accepted'", (outcome, message_id))

    def reply_state(self, message_id: str) -> str | None:
        row = self.db.execute("SELECT state FROM telegram_replies WHERE message_id=?",
                              (message_id,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.db.close()


class TelegramMailboxRelay:
    """Deterministic transport core. No model, network client, or public RPC.

    Adapters must supply authenticated mailbox submit/query and Telegram send
    callbacks. Neither callback is made for a duplicate or uncertain intent.
    The binding provider must read the current operator-approved configuration,
    never a value supplied in message text. This class does not enroll it.
    """

    def __init__(self, authority, journal, binding_provider, submit, send_text,
                 *, kai_endpoint):
        self.authority = authority
        self.journal = journal
        self.binding_provider = binding_provider
        self.submit = submit
        self.send_text = send_text
        self.kai_endpoint = _text(kai_endpoint)

    def _active(self, now):
        current = self.binding_provider()
        if (current != self.authority.binding or current.revoked
                or type(now) not in (int, float) or not 0 < now < current.expires_at):
            raise TelegramIngressError("binding_inactive")

    def receive(self, raw_body, secret_header=None, *, now, authenticated_poll_bot_id=None):
        intent = (self.authority.admit(raw_body, secret_header, now=now)
                  if authenticated_poll_bot_id is None else
                  self.authority.admit_authenticated_poll(raw_body,
                    verified_bot_id=authenticated_poll_bot_id, now=now))
        self._active(now)
        if not self.journal.reserve(intent):
            return {"message_id": intent.message_id, "duplicate": True,
                    "state": self.journal.state(intent.message_id)}
        try:
            self._active(now)
            receipt = self.submit(intent.envelope())
            if (not isinstance(receipt, Mapping)
                    or receipt.get("message_id") != intent.message_id
                    or receipt.get("state") not in ("accepted", "queued", "adapter_received", "presented")):
                raise TelegramIngressError("submission_unknown")
        except Exception:
            self.journal.settle(intent.message_id, "unknown")
            raise TelegramIngressError("submission_unknown") from None
        self.journal.settle(intent.message_id, "accepted")
        return {"message_id": intent.message_id, "state": receipt["state"]}

    def deliver_reply(self, reply, *, now):
        """Called ONLY with a message read through authenticated mailbox query.

        Preserve the exact KAI text. Continuing outputs may each reference the
        same original request but must have their own mailbox message ID.
        """
        self._active(now)
        if not isinstance(reply, Mapping):
            raise TelegramIngressError("invalid_reply")
        original = self.journal.intent(reply.get("in_reply_to"))
        if (not original or reply.get("sender_endpoint") != self.kai_endpoint
                or reply.get("thread_id") != original["message_id"]):
            raise TelegramIngressError("reply_not_authorized")
        mid = _text(reply.get("message_id"))
        body = reply.get("body")
        if (not isinstance(body, str) or not body.strip() or len(body) > 4096
                or any(0xD800 <= ord(c) <= 0xDFFF for c in body)):
            raise TelegramIngressError("unsupported_reply")
        origin = original["external_origin"]
        try:
            validate_origin(origin, original, self.authority.binding, now=now)
        except (ValueError, TypeError, KeyError):
            raise TelegramIngressError('reply_binding_mismatch') from None
        payload = {"chat_id": origin["chat_id"], "text": body,
                   "reply_to_message_id": origin["message_id"]}
        if not self.journal.reserve_reply(mid, payload):
            return {"message_id": mid, "duplicate": True,
                    "state": self.journal.reply_state(mid)}
        try:
            self._active(now)
            receipt = self.send_text(payload)
            if (not isinstance(receipt, Mapping) or receipt.get("chat_id") != payload["chat_id"]
                    or type(receipt.get("message_id")) is not int or receipt["message_id"] < 1):
                raise TelegramIngressError("delivery_unknown")
        except Exception:
            self.journal.settle_reply(mid, "unknown")
            raise TelegramIngressError("delivery_unknown") from None
        self.journal.settle_reply(mid, "accepted")
        return {"message_id": mid, "state": "accepted"}

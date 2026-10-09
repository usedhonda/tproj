"""Owner-enrolled ChatGPT conversation bindings.

This module is deliberately only a lookup boundary.  Enrollment is supplied by
owner-controlled configuration; a request (including its ``_meta``) cannot add
or move a binding.  A trusted ingress attestor is the sole source of identity
and provider-correlation evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 256


class ConversationBindingError(RuntimeError):
    """Base class for fixed, public conversation-binding failures."""

    code = "conversation_binding_error"
    message = "conversation binding rejected"

    def __init__(self) -> None:
        super().__init__(self.message)


class ConversationConfigError(ConversationBindingError):
    code = "invalid_conversation_config"
    message = "conversation binding configuration rejected"


class ConversationAttestationError(ConversationBindingError):
    code = "conversation_attestation_rejected"
    message = "trusted conversation attestation rejected"


class ConversationBindingDenied(ConversationBindingError):
    code = "conversation_binding_denied"
    message = "conversation binding denied"


class ConversationBindingExpired(ConversationBindingDenied):
    code = "conversation_binding_expired"
    message = "conversation binding expired"


class ConversationBindingConflict(ConversationConfigError):
    code = "conversation_binding_conflict"
    message = "conversation binding configuration conflicts"


# Descriptive aliases for callers that prefer the lookup terminology.
BindingNotFoundError = ConversationBindingDenied
BindingMismatchError = ConversationBindingDenied
BindingExpiredError = ConversationBindingExpired
DuplicateBindingError = ConversationBindingConflict


def provider_digest(value: str) -> str:
    """Return the only provider correlation representation accepted here."""
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError("invalid provider value")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ConversationConfigError()
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ConversationConfigError()
    return value


def _expiry(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConversationConfigError()
    if isinstance(value, (int, float)):
        if value <= 0:
            raise ConversationConfigError()
        return float(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConversationConfigError() from exc
        if parsed.tzinfo is None:
            raise ConversationConfigError()
        return parsed.astimezone(timezone.utc).timestamp()
    raise ConversationConfigError()


@dataclass(frozen=True, slots=True)
class ConversationBinding:
    principal_id: str
    provider_subject_digest: str
    provider_session_digest: str
    binding_id: str
    service_id: str
    address: str
    participant_id: str
    expires_at: float | None = None

    @classmethod
    def from_config(cls, value: Mapping[str, Any]) -> "ConversationBinding":
        if not isinstance(value, Mapping):
            raise ConversationConfigError()
        try:
            return cls(
                principal_id=_text(value["principal_id"]),
                provider_subject_digest=_digest(value["provider_subject_digest"]),
                provider_session_digest=_digest(value["provider_session_digest"]),
                binding_id=_text(value["binding_id"]),
                service_id=_text(value["service_id"]),
                address=_text(value["address"]),
                participant_id=_text(value["participant_id"]),
                expires_at=_expiry(value.get("expires_at")),
            )
        except KeyError as exc:
            raise ConversationConfigError() from exc


class ConversationBindingRegistry:
    """Immutable, thread-safe lookup over owner-enrolled bindings."""

    def __init__(self, config: Mapping[str, Any] | list[Mapping[str, Any]],
                 clock: Callable[[], float] = time.time):
        if isinstance(config, Mapping):
            entries = config.get("bindings")
        else:
            entries = config
        if not isinstance(entries, (list, tuple)):
            raise ConversationConfigError()
        if not callable(clock):
            raise ConversationConfigError()
        bindings = tuple(ConversationBinding.from_config(item) for item in entries)
        self._validate_unique(bindings)
        self._bindings = bindings
        self._clock = clock
        self._lock = threading.RLock()

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | list[Mapping[str, Any]], **kwargs: Any):
        return cls(config, **kwargs)

    @classmethod
    def load(cls, path: str | Path, **kwargs: Any) -> "ConversationBindingRegistry":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConversationConfigError() from exc
        return cls(value, **kwargs)

    @staticmethod
    def _validate_unique(bindings: tuple[ConversationBinding, ...]) -> None:
        fields = ("binding_id", "service_id", "address", "participant_id")
        for field in fields:
            values = [getattr(item, field) for item in bindings]
            if len(values) != len(set(values)):
                raise ConversationBindingConflict()
        principals = [(item.principal_id, item.provider_subject_digest,
                       item.provider_session_digest) for item in bindings]
        if len(principals) != len(set(principals)):
            raise ConversationBindingConflict()

    @staticmethod
    def _attested(attestor: Callable[[], Mapping[str, Any]]) -> tuple[str, str, str]:
        if not callable(attestor):
            raise ConversationAttestationError()
        try:
            value = attestor()
        except Exception:
            raise ConversationAttestationError() from None
        if not isinstance(value, Mapping):
            raise ConversationAttestationError()
        try:
            principal = _text(value["principal_id"])
            subject = _digest(value["provider_subject_digest"])
            session = _digest(value["provider_session_digest"])
        except (KeyError, ConversationBindingError):
            raise ConversationAttestationError() from None
        return principal, subject, session

    def resolve(self, attestor: Callable[[], Mapping[str, Any]], *,
                request_meta: Any = None, arguments: Any = None) -> ConversationBinding:
        """Resolve only trusted ingress evidence; request fields are ignored."""
        del request_meta, arguments
        principal, subject, session = self._attested(attestor)
        with self._lock:
            matches = tuple(item for item in self._bindings
                            if item.principal_id == principal
                            and item.provider_subject_digest == subject
                            and item.provider_session_digest == session)
            if not matches:
                raise ConversationBindingDenied()
            if len(matches) != 1:
                raise ConversationBindingConflict()
            binding = matches[0]
            if binding.expires_at is not None and self._clock() >= binding.expires_at:
                raise ConversationBindingExpired()
            return binding

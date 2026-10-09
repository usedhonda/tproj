"""Owner-enrolled ChatGPT conversation bindings.

This module is deliberately only a lookup boundary.  Enrollment is supplied by
owner-controlled configuration; a request (including its ``_meta``) cannot add
or move a binding.  A trusted ingress attestor is the sole source of identity
and provider-correlation evidence.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import stat
import tempfile
import uuid
import fcntl
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


class ConversationToolFactoryError(ConversationBindingError):
    code = "conversation_tool_factory_rejected"
    message = "conversation tool factory rejected"


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
        if not math.isfinite(value) or value <= 0:
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


@dataclass(frozen=True)
class ConversationBinding:
    principal_id: str
    provider_subject_digest: str
    provider_session_digest: str
    binding_id: str
    service_id: str
    address: str
    participant_id: str
    expires_at: float | None = None
    generation: int = 1
    revoked: bool = False

    @classmethod
    def from_config(cls, value: Mapping[str, Any]) -> "ConversationBinding":
        if not isinstance(value, Mapping):
            raise ConversationConfigError()
        try:
            binding = cls(
                principal_id=_text(value["principal_id"]),
                provider_subject_digest=_digest(value["provider_subject_digest"]),
                provider_session_digest=_digest(value["provider_session_digest"]),
                binding_id=_text(value["binding_id"]),
                service_id=_text(value["service_id"]),
                address=_text(value["address"]),
                participant_id=_text(value["participant_id"]),
                expires_at=_expiry(value.get("expires_at")),
                generation=value.get("generation", 1),
                revoked=value.get("revoked", False),
            )
        except KeyError as exc:
            raise ConversationConfigError() from exc
        if (isinstance(value.get("generation", 1), bool)
                or not isinstance(value.get("generation", 1), int)
                or value.get("generation", 1) < 1
                or not isinstance(value.get("revoked", False), bool)):
            raise ConversationConfigError()
        return binding


class ConversationBindingRegistry:
    """Thread-safe lookup plus explicit owner-approved lifecycle persistence."""

    def __init__(self, config: Mapping[str, Any] | list[Mapping[str, Any]],
                 clock: Callable[[], float] = time.time, *,
                 owner_policy: Mapping[str, Any] | None = None,
                 path: str | Path | None = None):
        if isinstance(config, Mapping):
            entries = config.get("bindings")
            embedded_policy = config.get("owner_policy")
        else:
            entries = config
            embedded_policy = None
        if not isinstance(entries, (list, tuple)):
            raise ConversationConfigError()
        if not callable(clock):
            raise ConversationConfigError()
        embedded_policy_parsed = (self._policy(embedded_policy)
                                   if embedded_policy is not None else None)
        owner_policy_parsed = (self._policy(owner_policy)
                               if owner_policy is not None else None)
        if owner_policy_parsed is None:
            owner_policy_parsed = embedded_policy_parsed
        elif (embedded_policy_parsed is not None
              and owner_policy_parsed != embedded_policy_parsed):
            raise ConversationConfigError()
        bindings = tuple(ConversationBinding.from_config(item) for item in entries)
        self._validate_unique(bindings)
        self._bindings = bindings
        self._clock = clock
        self._lock = threading.RLock()
        self._path = Path(path).expanduser() if path is not None else None
        self._owner_policy = owner_policy_parsed
        self._policy_persisted = embedded_policy is not None

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | list[Mapping[str, Any]], **kwargs: Any):
        return cls(config, **kwargs)

    @classmethod
    def load(cls, path: str | Path, **kwargs: Any) -> "ConversationBindingRegistry":
        path = Path(path).expanduser()
        registry = cls({"bindings": []}, path=path, **kwargs)
        value = registry._read_file(path)
        return cls(value, path=path, **kwargs)

    @staticmethod
    def _policy(value: Mapping[str, Any] | None) -> dict[str, frozenset[str]]:
        if not isinstance(value, Mapping):
            raise ConversationConfigError()
        principals = value.get("principal_ids", value.get("principals"))
        subjects = value.get("provider_subject_digests", value.get("provider_subjects"))
        if (not isinstance(principals, (list, tuple, set))
                or not isinstance(subjects, (list, tuple, set))
                or not principals or not subjects):
            raise ConversationConfigError()
        principal_set = frozenset(_text(item) for item in principals)
        subject_set = frozenset(_digest(item) for item in subjects)
        if len(principal_set) != len(principals) or len(subject_set) != len(subjects):
            raise ConversationConfigError()
        return {"principal_ids": principal_set, "provider_subject_digests": subject_set}

    def _policy_allows(self, principal: str, subject: str) -> bool:
        return (self._owner_policy is not None
                and principal in self._owner_policy["principal_ids"]
                and subject in self._owner_policy["provider_subject_digests"])

    @staticmethod
    def _safe_path(path: Path) -> Path:
        path = path.absolute()
        parent = path.parent
        if (not parent.is_dir()
                or any(ancestor.is_symlink() and ancestor.parent != Path("/")
                        for ancestor in path.parents)):
            raise ConversationConfigError()
        parent_stat = parent.stat()
        if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
            raise ConversationConfigError()
        if path.exists():
            file_stat = path.lstat()
            if (path.is_symlink() or not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.getuid()
                    or stat.S_IMODE(file_stat.st_mode) & 0o077):
                raise ConversationConfigError()
        return path

    @contextlib.contextmanager
    def _file_lock(self):
        if self._path is None:
            raise ConversationConfigError()
        path = self._safe_path(self._path)
        lock_path = Path(str(path) + ".lock")
        if lock_path.parent != path.parent:
            raise ConversationConfigError()
        try:
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(str(lock_path), flags)
            except FileNotFoundError:
                try:
                    fd = os.open(str(lock_path), flags | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    fd = os.open(str(lock_path), flags)
            lock_stat = os.fstat(fd)
            if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.getuid()
                    or stat.S_IMODE(lock_stat.st_mode) & 0o077):
                os.close(fd)
                raise ConversationConfigError()
        except OSError as exc:
            raise ConversationConfigError() from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        path = ConversationBindingRegistry._safe_path(path)
        if not path.exists():
            return {"bindings": []}
        fd = None
        try:
            fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            file_stat = os.fstat(fd)
            if (not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.getuid()
                    or stat.S_IMODE(file_stat.st_mode) & 0o077):
                raise ConversationConfigError()
            stream = os.fdopen(fd, "r", encoding="utf-8")
            fd = None
            with stream:
                value = json.load(stream)
        except (OSError, ValueError) as exc:
            raise ConversationConfigError() from exc
        finally:
            if fd is not None:
                os.close(fd)
        if not isinstance(value, dict) or not isinstance(value.get("bindings"), list):
            raise ConversationConfigError()
        return value

    def _write_file(self, path: Path, bindings: tuple[ConversationBinding, ...]) -> None:
        path = self._safe_path(path)
        payload: dict[str, Any] = {"bindings": [item.__dict__ for item in bindings]}
        if self._owner_policy is not None:
            payload["owner_policy"] = {
                "principal_ids": sorted(self._owner_policy["principal_ids"]),
                "provider_subject_digests": sorted(self._owner_policy["provider_subject_digests"]),
            }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self._policy_persisted = self._owner_policy is not None
        except OSError as exc:
            raise ConversationConfigError() from exc
        finally:
            if "name" in locals() and os.path.exists(name):
                os.unlink(name)

    def _reload_locked(self, path: Path) -> tuple[ConversationBinding, ...]:
        value = self._read_file(path)
        loaded_policy = value.get("owner_policy")
        next_policy = self._owner_policy
        next_policy_persisted = self._policy_persisted
        if loaded_policy is None:
            if self._policy_persisted:
                raise ConversationConfigError()
        else:
            parsed_policy = self._policy(loaded_policy)
            if self._owner_policy is None:
                next_policy = parsed_policy
            elif parsed_policy != self._owner_policy:
                raise ConversationConfigError()
            next_policy_persisted = True
        bindings = tuple(ConversationBinding.from_config(item) for item in value["bindings"])
        self._validate_unique(bindings)
        self._owner_policy = next_policy
        self._policy_persisted = next_policy_persisted
        self._bindings = bindings
        return bindings

    @staticmethod
    def _new_ids() -> tuple[str, str, str, str]:
        token = uuid.uuid4().hex
        return (f"chatgpt-binding-{token}", f"chatgpt-service-{token}",
                f"chatgpt-{token}.cdx", f"chatgpt-{token}")

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
    def _attested(attestor: Callable[[], Mapping[str, Any]]) -> tuple[str, str, str, int | None]:
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
            generation = value.get("generation", value.get("binding_generation"))
            if generation is not None and (isinstance(generation, bool)
                                           or not isinstance(generation, int) or generation < 1):
                raise ConversationAttestationError()
        except (KeyError, ConversationBindingError):
            raise ConversationAttestationError() from None
        return principal, subject, session, generation

    @staticmethod
    def _identity_matches(item: ConversationBinding, principal: str,
                          subject: str, session: str) -> bool:
        return (item.principal_id == principal
                and item.provider_subject_digest == subject
                and item.provider_session_digest == session)

    def enroll(self, attestor: Callable[[], Mapping[str, Any]], *,
               expires_at: Any = None) -> ConversationBinding:
        """Explicitly enroll one attested identity under the owner policy."""
        principal, subject, session, generation = self._attested(attestor)
        expiry = _expiry(expires_at)
        if generation not in (None, 1):
            raise ConversationBindingDenied()
        with self._lock, self._file_lock() as path:
            bindings = self._reload_locked(path)
            if expiry is not None and self._clock() >= expiry:
                raise ConversationBindingExpired()
            if not self._policy_allows(principal, subject):
                raise ConversationBindingDenied()
            matches = tuple(item for item in bindings if self._identity_matches(item, principal, subject, session))
            if len(matches) > 1:
                raise ConversationBindingConflict()
            if matches:
                current = matches[0]
                if current.revoked:
                    raise ConversationBindingDenied()
                if current.expires_at is not None and self._clock() >= current.expires_at:
                    raise ConversationBindingExpired()
                if generation is not None and generation != current.generation:
                    raise ConversationBindingDenied()
                return current
            binding_id, service_id, address, participant_id = self._new_ids()
            if expiry is not None and self._clock() >= expiry:
                raise ConversationBindingExpired()
            created = ConversationBinding(principal, subject, session, binding_id,
                                          service_id, address, participant_id,
                                          expires_at=expiry, generation=1)
            updated = bindings + (created,)
            self._validate_unique(updated)
            self._write_file(path, updated)
            self._bindings = updated
            return created

    def revoke(self, binding_id: str) -> ConversationBinding:
        """Owner operation: fence a binding generation without deleting history."""
        binding_id = _text(binding_id)
        with self._lock, self._file_lock() as path:
            bindings = self._reload_locked(path)
            matches = [item for item in bindings if item.binding_id == binding_id]
            if len(matches) != 1:
                raise ConversationBindingDenied()
            current = matches[0]
            if current.revoked:
                return current
            fenced = replace(current, generation=current.generation + 1, revoked=True)
            updated = tuple(fenced if item.binding_id == binding_id else item for item in bindings)
            self._write_file(path, updated)
            self._bindings = updated
            return fenced

    def resolve(self, attestor: Callable[[], Mapping[str, Any]], *,
                request_meta: Any = None, arguments: Any = None) -> ConversationBinding:
        """Resolve only trusted ingress evidence; request fields are ignored."""
        del request_meta, arguments
        principal, subject, session, generation = self._attested(attestor)
        with self._lock:
            if self._path is not None:
                with self._file_lock() as path:
                    bindings = self._reload_locked(path)
                    return self._resolve_bindings(bindings, principal, subject, session, generation)
            return self._resolve_bindings(self._bindings, principal, subject, session, generation)

    def _resolve_bindings(self, bindings: tuple[ConversationBinding, ...],
                          principal: str, subject: str, session: str,
                          generation: int | None) -> ConversationBinding:
        matches = tuple(item for item in bindings
                            if item.principal_id == principal
                            and item.provider_subject_digest == subject
                            and item.provider_session_digest == session)
        if not matches:
            raise ConversationBindingDenied()
        if len(matches) != 1:
            raise ConversationBindingConflict()
        binding = matches[0]
        if binding.revoked or (generation is None and binding.generation != 1):
            raise ConversationBindingDenied()
        if generation is not None and generation != binding.generation:
            raise ConversationBindingDenied()
        if binding.expires_at is not None and self._clock() >= binding.expires_at:
            raise ConversationBindingExpired()
        return binding


class ConversationToolResolver:
    """Resolve one request to tools built for its enrolled binding.

    ``attestor`` receives request context only to correlate an ingress event;
    the returned principal and provider digests must still be independently
    authenticated.  This class never reads request metadata itself.
    """

    def __init__(self, registry: ConversationBindingRegistry,
                 attestor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
                 tool_factory: Callable[[ConversationBinding], Any]):
        if not isinstance(registry, ConversationBindingRegistry):
            raise ConversationConfigError()
        if not callable(attestor) or not callable(tool_factory):
            raise ConversationConfigError()
        self.registry = registry
        self.attestor = attestor
        self.tool_factory = tool_factory

    def resolve(self, request_context: Mapping[str, Any]) -> Any:
        if not isinstance(request_context, Mapping):
            raise ConversationAttestationError()
        try:
            binding = self.registry.resolve(lambda: self.attestor(request_context))
        except ConversationBindingError:
            raise
        except Exception:
            raise ConversationAttestationError() from None
        try:
            tools = self.tool_factory(binding)
        except Exception:
            raise ConversationToolFactoryError() from None
        if tools is None or not callable(getattr(tools, "dispatch", None)):
            raise ConversationToolFactoryError()
        return tools

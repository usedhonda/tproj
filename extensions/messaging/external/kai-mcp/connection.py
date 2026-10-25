"""Trusted connection-principal binding for the enrolled KAI service.

The cloud client is a service principal, not a cryptographically asserted
model persona.  A host-side attestor supplies the already verified service
endpoint incarnation; request arguments and provider metadata cannot widen
its participant scope.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping


class ConnectionBindingError(RuntimeError):
    """Raised when the host cannot prove the configured KAI binding."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class ConnectionTransportUnavailable(ConnectionBindingError):
    """Raised when attestation could not reach the enrolled host service."""

    transport_unavailable = True


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ConnectionBindingError(f"invalid {label}")
    return value


class ServiceIdentity:
    """Static enrollment selected by the runtime, never by tool input."""

    __slots__ = ("service_id", "address", "participant_id", "allowed_addresses", "binding_generation")

    def __init__(self, service_id: str, address: str, participant_id: str,
                 allowed_addresses: tuple[str, ...], binding_generation: str):
        for value, label in ((service_id, "service identity"),
                             (address, "service address"),
                             (participant_id, "participant identity"),
                             (binding_generation, "binding generation")):
            _text(value, label)
        if allowed_addresses is None:
            allowed_addresses = ()
        if isinstance(allowed_addresses, (str, bytes)):
            raise ConnectionBindingError("authorized participant scope is required")
        scope = tuple(allowed_addresses)
        if any(not isinstance(value, str) or not value for value in scope):
            raise ConnectionBindingError("invalid authorized participant scope", "configuration_error")
        if len(set(scope)) != len(scope):
            raise ConnectionBindingError("authorized participant scope is ambiguous")
        self.service_id = service_id
        self.address = address
        self.participant_id = participant_id
        self.allowed_addresses = scope
        self.binding_generation = binding_generation


class ServiceBinding(ServiceIdentity):
    """Parent-side identity plus credential; never used by the SSH child."""
    __slots__ = ('token',)

    def __init__(self, service_id, address, participant_id, token, allowed_addresses, binding_generation):
        super().__init__(service_id, address, participant_id, allowed_addresses, binding_generation)
        self.token = _text(token, 'service credential')


# Existing integrations keep their source/API binding without a duplicate class.
KaiServiceBinding = ServiceBinding


class FixedConnectionAuthorizer:
    """Revalidate one host-enrolled KAI service on every operation.

    ``attestor`` is trusted host code.  It must return the endpoint evidence
    for this process, including ``binding_id`` and ``incarnation``.  The
    returned identity and generation are compared to the enrollment; current
    participant scope is host policy evidence and is never taken from caller
    input or constrained by stale startup scope.
    """

    def __init__(self, binding: ServiceIdentity,
                 attestor: Callable[[], Mapping[str, Any]]):
        if not isinstance(binding, ServiceIdentity) or not callable(attestor):
            raise ConnectionBindingError("trusted service binding required")
        self.binding = binding
        self.attestor = attestor

    def authorize(self, _operation: str | None = None,
                  _arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            observed = self.attestor()
        except Exception as exc:
            if getattr(exc, "code", None) in {"configuration_error", "scope_denied", "resource_exhausted", "not_found"}:
                raise
            if getattr(exc, "code", None) == "unavailable" or isinstance(exc, (OSError, TimeoutError, ConnectionError)):
                raise ConnectionTransportUnavailable("host service unavailable") from exc
            raise ConnectionBindingError("host service attestation rejected") from exc
        if not isinstance(observed, Mapping):
            raise ConnectionBindingError("host service attestation rejected")
        for field in ("binding_id", "incarnation", "service_id", "address", "participant_id", "binding_generation"):
            _text(observed.get(field), field)
        if (observed["service_id"] != self.binding.service_id or
                observed["address"] != self.binding.address or
                observed["participant_id"] != self.binding.participant_id):
            raise ConnectionBindingError("service enrollment mismatch")
        if observed["binding_generation"] != self.binding.binding_generation:
            raise ConnectionBindingError("service enrollment mismatch")
        scope = observed.get("allowed_addresses")
        scoped = _operation in {"tproj_list", "tproj_status", "tproj_send"}
        policy_state = observed.get("policy_state")
        if scoped and policy_state != "valid":
            raise ConnectionBindingError("authorized participant scope is unavailable", "configuration_error")
        if scoped and not isinstance(scope, (list, tuple)):
            raise ConnectionBindingError("authorized participant scope is unavailable", "configuration_error")
        if scope is not None and (not isinstance(scope, (list, tuple)) or
                                  any(not isinstance(value, str) or not value for value in scope) or
                                  len(set(scope)) != len(scope)):
            if scoped:
                raise ConnectionBindingError("invalid authorized participant scope", "configuration_error")
            scope = []
        if scoped:
            revision = observed.get("policy_revision")
            expected = hashlib.sha256(json.dumps(sorted(scope), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            if not isinstance(revision, str) or revision != expected:
                raise ConnectionBindingError("authorized participant scope revision is invalid", "configuration_error")
        if scope is None:
            scope = []
        return {
            "principal": self.binding.service_id + "-service",
            "service_id": self.binding.service_id,
            "address": self.binding.address,
            "participant_id": self.binding.participant_id,
            "binding_generation": observed["binding_generation"],
            "binding_id": observed["binding_id"],
            "incarnation": observed["incarnation"],
            "allowed_addresses": list(scope),
            "policy_revision": observed.get("policy_revision"),
            "policy_state": policy_state,
            "messaging_scope": observed.get("messaging_scope", "restricted"),
        }

    def event_authorizer(self, reader: Callable[[int], Mapping[str, Any]]):
        """Return the event adapter view using the same fixed binding."""
        if not callable(reader):
            raise ConnectionBindingError("mailbox reader required")
        return _EventAuthorizer(self, reader)


class _EventAuthorizer:
    def __init__(self, connection: FixedConnectionAuthorizer, reader: Callable[[int], Mapping[str, Any]]):
        self.connection = connection
        self.reader = reader

    def authorize(self):
        try:
            from . import events  # package import
        except ImportError:  # direct module loading in the focused tests
            import events
        context = self.connection.authorize()
        stable_id = f"{context['participant_id']}:{context['binding_generation']}"
        return events.TrustedBinding(stable_id, context["incarnation"], self.reader)

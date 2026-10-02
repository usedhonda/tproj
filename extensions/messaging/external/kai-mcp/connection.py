"""Trusted connection-principal binding for the enrolled KAI service.

The cloud client is a service principal, not a cryptographically asserted
model persona.  A host-side attestor supplies the already verified service
endpoint incarnation; request arguments and provider metadata cannot widen
its participant scope.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping


class ConnectionBindingError(RuntimeError):
    """Raised when the host cannot prove the configured KAI binding."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ConnectionBindingError(f"invalid {label}")
    return value


class KaiServiceBinding:
    """Static enrollment selected by the runtime, never by tool input."""

    __slots__ = ("service_id", "address", "participant_id", "token", "allowed_addresses")

    def __init__(self, service_id: str, address: str, participant_id: str,
                 token: str, allowed_addresses: tuple[str, ...]):
        for value, label in ((service_id, "service identity"),
                             (address, "service address"),
                             (participant_id, "participant identity"),
                             (token, "service credential")):
            _text(value, label)
        if isinstance(allowed_addresses, (str, bytes)):
            raise ConnectionBindingError("authorized participant scope is required")
        scope = tuple(allowed_addresses)
        if not scope or any(not isinstance(value, str) or not value for value in scope):
            raise ConnectionBindingError("authorized participant scope is required")
        if len(set(scope)) != len(scope):
            raise ConnectionBindingError("authorized participant scope is ambiguous")
        self.service_id = service_id
        self.address = address
        self.participant_id = participant_id
        self.token = token
        self.allowed_addresses = scope


class FixedConnectionAuthorizer:
    """Revalidate one host-enrolled KAI service on every operation.

    ``attestor`` is trusted host code.  It must return the endpoint evidence
    for this process, including ``binding_id`` and ``incarnation``.  The
    returned scope is compared to the fixed enrollment rather than accepted
    from the caller.
    """

    def __init__(self, binding: KaiServiceBinding,
                 attestor: Callable[[], Mapping[str, Any]]):
        if not isinstance(binding, KaiServiceBinding) or not callable(attestor):
            raise ConnectionBindingError("trusted service binding required")
        self.binding = binding
        self.attestor = attestor

    def authorize(self, _operation: str | None = None,
                  _arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            observed = self.attestor()
        except Exception as exc:
            raise ConnectionBindingError("host service attestation failed") from exc
        if not isinstance(observed, Mapping):
            raise ConnectionBindingError("host service attestation rejected")
        for field in ("binding_id", "incarnation", "service_id", "address", "participant_id"):
            _text(observed.get(field), field)
        if (observed["service_id"] != self.binding.service_id or
                observed["address"] != self.binding.address or
                observed["participant_id"] != self.binding.participant_id):
            raise ConnectionBindingError("service enrollment mismatch")
        scope = observed.get("allowed_addresses")
        if not isinstance(scope, (list, tuple)) or tuple(scope) != self.binding.allowed_addresses:
            raise ConnectionBindingError("authorized participant scope mismatch")
        return {
            "principal": "kai-service",
            "service_id": self.binding.service_id,
            "address": self.binding.address,
            "participant_id": self.binding.participant_id,
            "binding_id": observed["binding_id"],
            "incarnation": observed["incarnation"],
            "allowed_addresses": list(self.binding.allowed_addresses),
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
            import importlib.util
            from pathlib import Path
            import sys
            path = Path(__file__).with_name("events.py")
            spec = importlib.util.spec_from_file_location("kai_mcp_events", path)
            events = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            sys.modules[spec.name] = events
            spec.loader.exec_module(events)
        context = self.connection.authorize()
        return events.TrustedBinding(context["binding_id"], context["incarnation"], self.reader)

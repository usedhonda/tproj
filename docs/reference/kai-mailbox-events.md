# KAI mailbox events

`KAIEventDelivery` is an isolated, fail-closed mailbox event adapter. A trusted
authorizer must return a fixed binding/incarnation and a scoped reader; no
metadata or request arguments are treated as identity. Without that authorizer,
subscription and pump operations fail before mailbox access.

Subscriptions verify an HTTPS callback challenge and persist private state with
owner-only permissions. `pump_once()` reads message IDs only, creates stable
event IDs from subscription plus message ID, stores exact ID-only payloads in a
durable outbox, and retries with bounded backoff. It never sends message bodies,
does not run an unbounded daemon, and distinguishes unknown delivery from a
successful HTTP response.

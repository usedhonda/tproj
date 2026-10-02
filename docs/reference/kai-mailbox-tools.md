# KAI mailbox tool adapter

`extensions/messaging/external/kai-mcp/mailbox_tools.py` contains the local
adapter for the seven reviewed tool shapes: `tproj_list`,
`tproj_status`, `tproj_send`, `tproj_inbox`, `tproj_message`, `tproj_reply`,
and `tproj_ack`.

`extensions/messaging/external/kai-mcp/server.py` adds standard MCP stdio
plumbing (`initialize`, `tools/list`, `tools/call`, `ping`, and notification
handling). It loads the reviewed machine-readable catalog for exact schemas
and annotations. The command-line entrypoint deliberately constructs no
mailbox client: `tools/call` returns a structured `identity_rejected` error
until a trusted runtime injects a configured `MailboxTools` instance. An
embedding runtime may inject that instance explicitly; no caller argument can
provide the authorizer, service identity, or credential.

`MCPServer` also accepts an optional trusted event dispatcher. Only when one is
injected does `initialize` advertise the `events` capability and route
`events/list`, `events/subscribe`, and `events/unsubscribe`; the default CLI
does not advertise or expose event methods. Event-enabled initialization
negotiates protocol `2026-07-28`; mailbox-only initialization remains
compatible with `2024-11-05`. Subscription and unsubscription preserve the
MCP event name, empty arguments, webhook mode, and delivery URL shape.

The sibling `external-assistant-tools.json` is a distributed copy of the
reviewed catalog, so a standalone deployment does not depend on the repository
`docs/` tree. The server validates that all seven expected names are present;
it never logs catalog contents, credentials, or callback secrets.

The adapter is not an MCP server, does not register cloud tools, and does not
start a daemon. A host integration injects a host-socket call and a
`FixedConnectionAuthorizer` from `connection.py`. That authorizer represents
the enrolled KAI **service principal** (not a cryptographically asserted
model persona): every call revalidates the host-derived service identity,
endpoint incarnation, and exact fixed `allowed_addresses` scope. Missing,
rejected, stale, or mismatched authorization fails with `identity_rejected`
before any host request. Caller arguments cannot provide identity selectors
(`role`, `as`, `session`, conversation, PID, host, or endpoint fields).

Service identity, address, and credential are constructor-local configuration,
never tool arguments.  Message operations map directly to the authenticated
host's `service_send`, `service_reply`, `service_inbox`, `service_message`,
and `service_ack` operations.  Reply routing remains pinned to the supplied
original `message_id`; acknowledgement returns `presented` only after the
scoped host operation succeeds.  Submission IDs are passed unchanged and are
used as the stable send/reply message ID when the host does not return one.
Bodies are checked against the host's UTF-8 byte limit and terminal-control
rule; inbox cursors and limits are bounded (`0..`, `1..100`).

List/status use the existing read-only directory/status host primitives, then
filter and sanitize results to the contract.  They fail closed when the
authorizer supplies no participant scope.  Directory visibility is not proof
of enrollment, cloud conversation identity, delivery, or presentation.

## Connection-principal boundary

`KaiServiceBinding` fixes the service ID, address, participant ID, credential,
and participant allowlist at enrollment. The host attestor must return the
matching binding and live incarnation; an address or token never selects a
different service. The unified host remains responsible for the exact
launchd PID and kernel process-start check. The adapter does not infer KAI
conversation identity from `_meta`, display names, or model-supplied values.

## Evidence boundary

The implementation remains unexposed until trusted host-side service
enrollment and the KAI route are enabled. The fixed connection principal does
not prove original Dots conversation identity. Original Dots event delivery,
shared app-server conversation authentication, cloud registration, live KAI
enrollment, and end-to-end mailbox receipts remain unproven and are not
claimed by this module.

Focused verification:

```bash
python3 -m unittest extensions/messaging/external/kai-mcp/test_mailbox_tools.py
python3 -m unittest extensions/messaging/external/kai-mcp/test_server.py
```

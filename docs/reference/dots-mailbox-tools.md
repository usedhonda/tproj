# Dots mailbox tool adapter

`extensions/messaging/external/dots-mcp/mailbox_tools.py` contains the local
adapter for the reviewed tool shapes: `tproj_list`,
`tproj_status`, `tproj_send`, `tproj_inbox`, `tproj_message`, `tproj_reply`,
`tproj_ack`, and metadata-only `tproj_diagnose(submission_id)`.

`extensions/messaging/external/dots-mcp/server.py` adds standard MCP stdio
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

## Production runtime wiring

`extensions/messaging/external/dots-mcp/runtime.py --config CONFIG` is the
service entrypoint. The launchd-owned process calls the unified host's
`service_whoami` with the configured service ID, address, and credential, then
constructs the tools and mailbox event dispatcher from that live endpoint
incarnation. The host's exact launchd-PID check remains authoritative.

When a Secure MCP Tunnel starts a child stdio process, set `bridge_socket` in
the child config and run the launchd-owned process with `--bridge`; the child
can only forward requests over that owner-only UNIX socket and cannot present
its own credential or identity. The bridge is a transport boundary, not a new
service or a PID bypass. `binding_id` is the stable enrolled participant ID;
the endpoint `incarnation` fences stale subscriptions after restart.

The private config contains `service_id`, `address`, `participant_id`,
`service_token`, `allowed_addresses`, persistent `binding_generation`,
`host_socket`, and `event_state`; it is
local-only and must be owner-readable. A launchd manifest should execute:

```text
python3 /path/to/extensions/messaging/external/dots-mcp/runtime.py --config /private/dots.json --bridge
```

The tunnel child uses the same config with `bridge_socket` and omits
`--bridge`, so no credential is copied into the child command line.
The direct stdio runtime runs a bounded background event pump while serving
MCP requests. In bridge mode that pump belongs to the launchd-owned parent;
the tunnel child only serves MCP calls. Mailbox notifications therefore do not
depend on a later tool call, and child restarts reconcile durable subscription
IDs/outbox state rather than replacing the fixed subscription.

The sibling `external-assistant-tools.json` is a distributed copy of the
reviewed catalog, so a standalone deployment does not depend on the repository
`docs/` tree. The server validates that all expected names are present;
it never logs catalog contents, credentials, or callback secrets.

The supported `bin/tproj-msg-reload` path distributes the complete Dots MCP
module closure in one tar stream: `mailbox_tools.py`, `connection.py`,
`conversation.py`, `events.py`, `runtime.py`, `server.py`, and the sibling
`external-assistant-tools.json` catalog. Keeping these files together is
required because runtime imports the connection, event, mailbox, and server
modules, while server dispatch also imports the conversation resolver.

The adapter is not an MCP server, does not register cloud tools, and does not
start a daemon. A host integration injects a host-socket call and a
`FixedConnectionAuthorizer` from `connection.py`. That authorizer represents
the enrolled Dots **service principal** (not a cryptographically asserted
model persona): every call revalidates the host-derived service identity,
endpoint incarnation, and current host-derived policy revision. Outbound scope
is authoritative at the host service list/status/send operations. Missing,
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

List/status use authenticated host service_list/service_status primitives, then
filter and sanitize results to the contract.  They fail closed when the
authorizer supplies no participant scope.  Directory visibility is not proof
of enrollment, cloud conversation identity, delivery, or presentation.

Inbox projections and direct message views hide host envelopes whose durable
state is `cancelled`, `canceled`, `expired`, `terminal`, `rejected`, or
`stale_session`; those states are
never offered to Dots as new work. Before returning any message body, the
adapter calls the host's atomic `service_begin_present` gate; cancellation,
expiry, rejection, stale-session, or unauthorized results suppress that item,
while unrelated host failures remain errors. The host remains responsible for
truthful presentation receipts.

## Connection-principal boundary

`DotsServiceBinding` fixes the service ID, address, participant ID, credential,
and participant allowlist at enrollment. It also requires a persistent
`binding_generation` random identifier. A verified service restart may change endpoint
incarnation while retaining that generation and its one callback subscription;
explicit reenrollment or revocation must rotate the generation. The host
attestor must return the matching binding and live incarnation; an address or
token never selects a different service. The unified host remains responsible for the exact
launchd PID and kernel process-start check. The adapter does not infer Dots
conversation identity from `_meta`, display names, or model-supplied values.

## Evidence boundary

The implementation remains unexposed until trusted host-side service
enrollment and the Dots route are enabled. The fixed connection principal does
not prove original Dots conversation identity. Original Dots event delivery,
shared app-server conversation authentication, cloud registration, live Dots
enrollment, and end-to-end mailbox receipts remain unproven and are not
claimed by this module.

## Single event retry (local party route)

An authenticated local mailbox party may run `tproj-msg retry-event MESSAGE_ID`.
The ordinary wrapper routes this command to the unified host; it is not a legacy
or cross-host operation. The host binds the caller with the normal native
identity, queries the message as that party, and requires the current local
`services.dots` endpoint to be the exact recipient. Canceled, expired, presented,
retired, foreign, or otherwise ineligible messages fail closed.

The host then calls the already configured Dots bridge through
`services.dots.event_bridge_socket`, sending only the message ID, authenticated
actor endpoint, and the existing Dots service token. The private bridge verifies
that token in constant time, re-attests the launchd-owned service, rechecks the
current recipient and original message parties, and invokes the durable
`retry_once` event operation. Retry responses contain only stable IDs, status,
bounded attempt counts, HTTP status code, and a fixed error class; message
bodies and arbitrary bridge arguments are never forwarded. A bridge disconnect
is reported as unknown and is not automatically repeated.

Focused verification:

```bash
python3 -m unittest extensions/messaging/external/dots-mcp/test_mailbox_tools.py
python3 -m unittest extensions/messaging/external/dots-mcp/test_server.py
```

Diagnosis bypasses mutating service_whoami preauthorization and authenticates on
the host read-only service_diagnose path. It never changes the stable submission
ID or retries delivery. Resource error metadata preserves acceptance=unknown.

### Catalog activation diagnosis

The existing no-argument `tproj_capabilities` response includes `server_catalog`
with the actually served `version` fingerprint, `server_name` and advertised
`tools`. This uses the same selected catalog as `tools/list`, including service
subsets. It contains no messages, identity credentials or callback details and
performs no mailbox read or send. It can diagnose a stale provider/client tool
cache without first registering another diagnostic tool. These are server-side
advertisements, not proof that the calling conversation has those tools in its
callable catalog. Compare the two explicitly. For process-local discovery counts
and the distinction between generated catalog responses and client application,
see [catalog refresh observation](dots-mailbox-events.md#catalog-refresh-observation).

### Recover an existing conversation after a catalog update

Keep three observations separate:

1. **Served catalog:** the existing capability response identifies the selected
   server catalog and process-local discovery observations.
2. **Imported connection:** inspect the existing plugin's app-details tool list
   after Refresh. Its read/write counts and tool names describe the connection,
   not the running conversation.
3. **Actual callables:** inspect the existing conversation's available function
   declarations and argument schemas. Documentation or a returned list of names
   does not register those functions.

Use the product's Refresh action and correlate discovery observations within
the same server-process start time. Merely seeing an enabled Refresh button
is insufficient. A current imported list can coexist with old conversation
definitions; reselecting that same plugin in the conversation is not proof of
activation. Do not restart the mailbox server repeatedly to repair a catalog
already imported correctly.

If the existing Dot exposes a normal Reboot action, first read its actual
confirmation. Reboot is distinct from Reset/Delete: proceed only when the UI
explicitly preserves the existing conversations, memories and scheduled tasks,
and account for interruption of active work. Preserve pending output IDs and
uncertain effects. A failed reboot response does not prove no effect; do not
repeat it blindly or invoke private endpoints. Keep the existing conversation
and connection rather than replacing them to hide the failure.

After activation, verify the actual new function declarations, the same existing
receiver task's enabled state, and one retained message's ID-linked operation
and reply. Tool availability is not automatic wake, successful execution, or
completion. An enabled task is not evidence that its next event has run.

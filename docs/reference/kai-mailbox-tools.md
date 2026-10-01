# KAI mailbox tool adapter

`extensions/messaging/external/kai-mcp/mailbox_tools.py` contains the inert,
local adapter for the seven reviewed tool shapes: `tproj_list`,
`tproj_status`, `tproj_send`, `tproj_inbox`, `tproj_message`, `tproj_reply`,
and `tproj_ack`.

The adapter is not an MCP server, does not register cloud tools, and does not
start a daemon.  A host integration must inject both a host-socket call and a
trusted conversation authorizer.  The authorizer is mandatory on every call;
missing, rejected, or incomplete authorization fails with `identity_rejected`
before any host request.  It must provide a host-derived `allowed_addresses`
scope.  Caller arguments cannot provide identity selectors (`role`, `as`,
`session`, conversation, PID, host, or endpoint fields).

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

## Evidence boundary

The implementation is intentionally inert/unexposed until a trusted host-side
authorizer proves the KAI conversation binding.  Original Dots event delivery,
shared app-server conversation authentication, cloud registration, live KAI
enrollment, and end-to-end mailbox receipts remain unproven and are not
claimed by this module.

Focused verification:

```bash
python3 -m unittest extensions/messaging/external/kai-mcp/test_mailbox_tools.py
```

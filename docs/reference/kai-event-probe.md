# KAI MCP Events connection-only probe

This probe is an isolated stdio MCP 2.0 server for checking event delivery to
an existing KAI Dots conversation. It has no mailbox connector and never reads
or imports mailbox data.

## Surface

- `server/discover` advertises MCP `2026-07-28` and `events` capability.
- `tools/list` and `tools/call` expose only `connection_status`.
- `events/list` exposes `kai.connection.probe` with no filter arguments.
- `events/subscribe` verifies a public HTTPS callback with a signed one-use
  challenge, then stores an idempotent subscription in local state.
- `events/unsubscribe` is idempotent.
- `--send-event SUBSCRIPTION_ID` sends exactly one synthetic event. This is an
  explicit operator command; it is not wired to a mailbox or tproj runtime.

Subscriptions are stored at `~/.local/share/tproj/kai-event-probe/` (or
`$KAI_EVENT_PROBE_STATE`) with directory mode `0700` and file mode `0600`.
Secrets are never printed. Callback validation requires HTTPS and rejects
private, loopback, link-local, reserved, multicast, and unspecified addresses;
redirects are not followed. Delivery uses Standard Webhooks HMAC headers and
one event per request, with a 256 KiB body limit.

## Launch

```bash
python3 extensions/messaging/external/kai-event-probe/server.py
```

The stdio process is suitable for an existing Secure MCP Tunnel client. The
probe does not enroll, send, or push anything externally by itself.

## Verification

```bash
python3 -m py_compile extensions/messaging/external/kai-event-probe/server.py
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"server/discover"}' | python3 extensions/messaging/external/kai-event-probe/server.py
```

The second command is discovery-only and should report `supportedVersions` as
`["2026-07-28"]` plus `events` capability.

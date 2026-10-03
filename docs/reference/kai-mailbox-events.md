# KAI mailbox events

`KAIEventDelivery` is an isolated, fail-closed mailbox event adapter. A trusted
authorizer must return a fixed enrollment binding/incarnation and a scoped reader; no
metadata or request arguments are treated as identity. The production KAI
route uses `FixedConnectionAuthorizer.event_authorizer()` so event delivery
shares the enrolled service principal and exact participant scope used by
mailbox tools. Without that authorizer, subscription and pump operations fail
before mailbox access.

Subscriptions verify an HTTPS callback challenge and persist private state with
owner-only permissions. `pump_once()` reads message IDs only, creates stable
event IDs from subscription plus message ID, stores exact ID-only payloads in a
durable outbox, and retries with bounded backoff. It never sends message bodies,
does not run an unbounded daemon, and distinguishes unknown delivery from a
successful HTTP response.

The reader has the actual mailbox shape: `reader(cursor)` returns
`{"messages": [{"message_id": "..."}], "next_cursor": 1}`. Cursors are
non-negative integers; an invalid or oversized page is rejected without sending.
The event definition's `payloadSchema` describes only `data.messageId`.
The full MCP event envelope includes a stable `eventId`, event name,
RFC 3339 timestamp, data, and cursor. No message body or binding ID is exposed.

An exclusive private file lock covers each read/modify/write transaction.
Unique owner-only temporary files, file and directory fsync, and atomic rename
make the outbox and cursor durable **before** a webhook is attempted. An attempt
is also recorded before posting. A crash after remote acceptance can therefore
repeat the same ID and exact payload, not generate a second event. The receiver
must deduplicate by event ID; this is not an exactly-once delivery claim.

After each actual webhook attempt, the outbox record stores only safe delivery
diagnostics: numeric-or-null `last_http_status` and an allowlisted
`last_error_class` (`http_error`, `timeout`, `tls`, `network`,
`target_unavailable`, `oversized_request`, `oversized_response`, or
`invalid_response`). Response bodies, exception text, headers, callback URLs,
and query strings are never persisted. A status observed before a response
read failure is retained; historical terminal records are not annotated until
they are attempted again. Diagnostics are cleared before each new attempt, so
a crash before the callback returns cannot leave an older result attributed to
the current attempt.

Each pump posts at most its bounded batch and attempts an event at most three
times, with persisted backoff. Exhausted uncertain events remain `terminal`
for explicit reconciliation, not automatic resubmission. Before each post,
the authorizer and subscription binding/incarnation/expiry are checked again.
Unsubscribe validates ownership and fences pending delivery; expiry or an
incarnation change also fences pending events. A verified restart may refresh
the stored incarnation when the participant and persistent binding generation
remain identical; the cursor and subscription continue. HTTP success never
acknowledges mailbox consumption.

Subscriptions default to one day; explicit `ttlMs: null` means no expiry.
This is separate from the control-plane credential's lifetime. The adapter
has no default credentials, authorization policy, scheduler, or cloud enrollment.
The original Dots event receipt and authenticated cloud binding remain live
acceptance requirements, not outcomes demonstrated by these local tests.

Focused verification:

```bash
python3 -m unittest discover -s extensions/messaging/external/kai-mcp -p 'test_events.py'
```

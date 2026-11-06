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
`{"messages": [{"message_id": "..."}], "next_cursor": 1}`. These internal scan cursors are
non-negative integers; an invalid or oversized page is rejected without sending.
The event definition's `payloadSchema` describes only `data.messageId`.
The full MCP event envelope includes a stable `eventId`, event name,
RFC 3339 timestamp, data, and `cursor: null`. Protocol replay is not supported:
subscription responses also return `cursor: null`, and non-null subscription
resume cursors are rejected with `-32014` (Unsupported, feature `cursor`, reason
`replay_not_supported`) before callback verification or state changes. Internal
scan progress is never exported as a delivery watermark, including when later
batch events remain undelivered. No message body or binding ID is exposed.

This follows [OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events)
and its linked EventOccurrence draft (`cursor` is string or null). Legacy stored
integer-cursor events are not rewritten: unclaimed manual retries reject them
without changing payload, hash, claim, or history. Previously claimed retries
still return their recorded result without another POST.

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
and query strings are never copied into delivery diagnostics or logs; the
existing private subscription configuration is unchanged. A status observed
before a response read failure is retained; historical terminal records are
not annotated until they are attempted again. Diagnostics are cleared before each new attempt, so
a crash before the callback returns cannot leave an older result attributed to
the current attempt.

Each pump posts at most its bounded batch and attempts an event at most three
times, with persisted backoff. HTTP 410 and 413 terminate immediately and are
not eligible for an unclaimed manual retry. Exhausted uncertain events remain `terminal`
for explicit reconciliation, not automatic resubmission. Before each post,
the authorizer and subscription binding/incarnation/expiry are checked again.
Unsubscribe validates ownership and fences pending delivery; expiry or an
incarnation change also fences pending events. A verified restart may refresh
the stored incarnation when the participant and persistent binding generation
remain identical; the cursor and subscription continue. HTTP success never
acknowledges mailbox consumption.

`retry_once(message_id, actor_endpoint=...)` is the sole manual reconciliation
path for one stored terminal event. The runtime must first authenticate the
original message, verify that it is not cancelled or expired, and verify the
exact current KAI recipient; the event adapter does not perform actor
authentication. Under the private file lock the adapter requires exactly one
matching stored event, an active subscription with the same enrolled binding
and incarnation, and an unexpired callback whose persisted ID and URL binding
still match.
The `actor_endpoint` argument is an authenticated caller context supplied by
the runtime; this adapter does not authenticate actor/message party identity.
It validates the saved envelope and deterministic event ID, and never accepts
caller-supplied payload data. A durable `manual_retry` claim (including a
SHA-256 hash of the exact saved payload) and incremented attempt count are
written before the POST. Existing payload hashes are checked; historical
records without one are pinned only in this claim. A claim is one-per-event:
repeated or concurrent calls return the stored result, while a crash after the
claim remains `unknown` and performs no second POST. The outbox status remains
`terminal` even after manual HTTP success, so `pump_once()` cannot requeue it.
Results contain only message/event IDs, status, attempt counts, HTTP status, and
the fixed error class.

Subscriptions default to one day; explicit `ttlMs: null` means no expiry.
This is separate from the control-plane credential's lifetime. The adapter
has no default credentials, authorization policy, scheduler, or cloud enrollment.
The original Dots event receipt and authenticated cloud binding remain live
acceptance requirements, not outcomes demonstrated by these local tests.

Focused verification:

```bash
python3 -m unittest discover -s extensions/messaging/external/kai-mcp -p 'test_events.py'
```

## Discovery isolation and pump diagnostics

Discovery validates an entire page before adding any of its events. A malformed
page, cursor, message, or failed reader blocks that subscription's discovery
without advancing its cursor. Its existing valid outbox and other subscriptions
continue delivery. No invalid row is silently skipped. The persisted `pump`
metadata records subscription discovery status and timestamps. A corrected page
recovers on the next successful cycle. Whole-state or persistence errors block
the pump; a best-effort failure record and fixed stderr classification expose
that condition without logging exception text. A state file that cannot be read
or written cannot itself hold the failure report; stderr remains the fallback.

The private authenticated `event_diagnostic` bridge operation returns pump state
and a specified message's notification status, attempts and existing safe HTTP
classification. It does not read message bodies, acknowledge, or resend. The
owner Host adds this information to `diagnose` only for a pinned message party
and the locally configured KAI recipient. Remote notification diagnostics are
explicitly unknown; Hub delivery diagnostics remain available. Bridge failure
or a two-second timeout affects only notification diagnostics. A five-minute
wait without presentation confirmation is a diagnostic flag, not proof of an
unread message or a new resend policy.

Receiver recovery must distinguish discovery progress, actual reading, and
business completion. A discovery cursor is not an unread watermark. Persist
unfinished IDs before advancing it; retain acknowledged work until a matching
own reply, an explicit no-reply decision, or authoritative terminal state.
Reuse saved reply submission IDs after uncertain results. Periodic wake and
single-consumer persistence require evidence from the actual receiving surface;
without those capabilities, no bounded automatic recovery guarantee is made.

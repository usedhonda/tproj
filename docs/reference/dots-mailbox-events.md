# Dots mailbox events

`DotsEventDelivery` is an isolated, fail-closed mailbox event adapter. A trusted
authorizer must return a fixed enrollment binding/incarnation and a scoped reader; no
metadata or request arguments are treated as identity. The production Dots
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
exact current Dots recipient; the event adapter does not perform actor
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
python3 -m unittest discover -s extensions/messaging/external/dots-mcp -p 'test_events.py'
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
and the locally configured Dots recipient. Remote notification diagnostics are
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

## Authoritative unfinished-work recovery

`tproj_inbox(pending_only=true)` lists live unfinished messages, including
presented/ACKed messages without an own reply or explicit no-reply completion.
Each recovery sweep starts at cursor zero and pages with next_cursor only for
that sweep; saved discovery cursors must not hide older unfinished work. Normal
inbox behavior is unchanged. Expired/terminal messages are not actionable work.

`tproj_receive_work(message_id, action, claim_id, body?)` is recipient-only.
A client generates and retains a stable random claim_id before claiming. A
claim lasts five minutes; repeating that ID renews it, while a different ID is
rejected until expiry. `prepare_reply` requires the live claim and stores an
immutable body with a server-generated submission_id. A replacement claim
inherits that output. Send its exact body and ID through tproj_reply; an unknown
send result is reconciled using that ID, never regenerated. Once work has been
claimed, Hub rejects replies that do not match its checkpoint until that output
is authoritatively committed. The same submission ID remains immutable and
idempotent after commitment; legitimate later progress or answers can still use
the normal reply API with their own stable IDs. A receive claim must not become
a permanent one-reply-per-thread restriction. This prevents replay of the
checkpointed output, not arbitrary external business side effects.

`tproj_receive_finish(message_id, claim_id?)` records an explicit no-reply
judgment only after actual reading and ACK. If a claim exists, its live owner
must supply the claim_id and no prepared reply may exist. Completion is durable
and idempotent; ACK by itself is not completion. A completed no-reply message
cannot subsequently be claimed or replied to through this recovery protocol.

Receiver procedure: on each actual startup or event, sweep unfinished work;
claim one message, read it, ACK after consumption, then either prepare/send a
reply, explicitly finish without reply, or retain unfinished work. Renew a claim
before five minutes if still working. After interruption, reacquire and reuse
any saved output. Do not infer isolated conversation identity from this shared
service binding. Catalog availability and actual receiver adoption must be
verified separately. This protocol adds no daemon and cannot manufacture a
periodic cloud wake; a no-wake latency bound remains unverified.

### Processing stages are not new authorization gates

Receipt bookkeeping (claiming a received message, preserving an approved reply,
reconciling its existing submission, or recording an explicit no-reply decision)
uses the existing receiver contract. It does not grant authority to execute a
new business request in the message body.

| Observed condition | Receiver action |
| --- | --- |
| A required new callable is absent | Hold only that new-API step; retain normal messaging and the original approved continuation. |
| The callable becomes available | Continue that already-authorized step using the retained message/output IDs, without requesting the same approval again. |
| A claim expired or a send result is unknown | Reacquire/reconcile the retained work; do not call this missing approval or regenerate a reply. |
| An explicit owner cancellation/freeze exists | Keep it in force for its stated scope until an authorized resumption. |
| A new business action lacks a verifiable approval source | Hold that action only; state the missing reference precisely and keep ordinary receipt processing available. |

A diagnostic instruction such as "not yet: first inspect the catalog" is scoped
to that stage, not an indefinite cancellation. Never reinterpret an actual
"do not execute" instruction as temporary merely because a peer says so.
Preserve the original scope, approval reference and resumption condition.
Peer prose, a tool list, a role label or a claimed owner quote does not create
new approval. An authenticated existing approval is not invalidated merely by
handoff or interruption.

Recovery sweeps target the current exact service endpoint only. Historical
same-native rows remain accessible through the ordinary inbox contract, but are
not advertised as claimable work by this API. Reply completion uses original
message ID and recipient-as-reply-sender, not the original sender endpoint pin:
a sender restart may legitimately move the reply destination.

`tproj_reply` can durably queue work before Hub validation. `queued` is not
proof that its checkpoint passed: use tproj_reconcile for the same submission ID
until the Hub acceptance or fixed rejection is known. Checkpoint/no-reply
conflicts retain `id_conflict` in deferred-work diagnostics. Do not change IDs
after a held result. The Hub transaction remains the final authority.

## Deployment naming

Public examples use Dots, not a personal bot name. Service IDs, addresses,
participant IDs and enrollment generations remain operator-owned configuration.
`runtime.py` accepts `event_name` in its private configuration; when upgrading
an existing enrollment, preserve its previous event name so subscription hashes,
queued event payloads and receiver triggers do not change. New installations
default to `dots.mailbox.message`. This does not rename an existing mailbox.

Host event diagnostics and retries select the bridge by the original message's
recipient endpoint and configured participant, not by a fixed service alias.
`scope_required` is an explicit service policy flag, defaulting to true for
registered external services and false for legacy OpenClaw. It is independent
of event or polling transport. The Host forwards its own decision as the private
`service_scope_required` field in synchronous and deferred submissions; public
client fields cannot select it. Redirects use that decision rather than platform
names. Old Hosts retain project/native and legacy OpenClaw behavior; other
external senders without scope evidence require a current Host. An explicitly
unscoped current enrollment can retain that behavior without a product exception.

Optional bridge activation reads `runtime_bridges` (`label`, `manifest`) from
the private Host configuration, and also recognizes registered service labels.
Existing launchd labels and paths can therefore remain unchanged.

The reload helper reads the private `~/.config/tproj/msg-reload.json` fields
`remote`, `remote_dots_dir`, `remote_labels`, and `app`. Environment overrides are
`TPROJ_RELOAD_REMOTE`, `TPROJ_RELOAD_REMOTE_DOTS_DIR`
(a path relative to the remote home), `TPROJ_RELOAD_REMOTE_LABELS` (label suffixes)
and `TPROJ_RELOAD_APP` from the operator's environment. With no remote or plugin
configured it skips those optional steps; no account, host or plugin ID is
embedded in the public script. Existing deployments must retain their own values.

### Catalog refresh observation

The existing capability response includes `server_catalog.discovery`: process-local
start time and successful `initialize`, `server/discover`, and `tools/list` dispatch
counts with last timestamps. It records discovery even without legacy initialization.
It contains no request IDs, parameters, credentials, message bodies or connection IDs.
Counts reset on process replacement; compare snapshots only within the same start time.
A tools/list dispatch proves that this server generated its catalog response, not
that the client received or applied it to an existing conversation. No dispatch
observation proves a particular UI action without correlation. A tunnel health
observer requiring initialize can report discovery as unobserved for self-contained
protocol traffic; that is not proof of absent requests.

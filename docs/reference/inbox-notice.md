# Native inbox notice contract

The unified host exposes `inbox_notice` as a bounded, authenticated read for
native `PostToolUse` safe points. It returns at most three message IDs and the
canonical sender address, never a body. The operation does not claim, consume,
present, acknowledge, resend, or otherwise modify messages.

`dispatching` is included as in-flight pending metadata: it is not evidence of
presentation or reading, and remains subject to the same no-ACK/no-mutation
notice contract.

The hook helper authenticates through the local host caller binding and passes
native conversation context from the tool event. It has a sub-one-second
timeout and fails open when native context is unavailable. Each native
conversation carries a durable, monotonic SQLite rowid cursor plus a bounded
exact-ID dedup list; the cursor is scoped to that native conversation, never
claims or acknowledges messages, and lets later safe points reach messages
beyond the three-row notice bound. An active recipient can read the original
message by ID with `tproj-msg message <ID>` without a forced prompt or proxy
relay.

Entries written before cursor version 1 are rewound once for a bounded
backfill; their exact-ID dedup list is retained, preventing blind repeat
notices while recovering rows that an earlier cursor could have skipped.

Deduplication retains the most recent 256 IDs per native conversation. During
legacy backfill, IDs already evicted from that history, or evicted while a
large backfill progresses, can produce another metadata notice. This is not a
whole-history zero-duplicate guarantee; notices never resend message bodies or
acknowledge delivery.

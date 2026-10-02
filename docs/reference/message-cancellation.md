# Message delivery cancellation

`tproj-msg cancel MESSAGE_ID` is sender-only and affects delivery, never task
execution or runtime role. Only the original sender endpoint may cancel.

- `accepted`, `queued`, or `adapter_received`: cancellation can succeed.
- `dispatching`, `uncertain`, or `presented`: return `too_late`; do not claim
  that execution was cancelled.
- The recipient must atomically call `begin_present` before terminal injection.
  A cancelled message cannot enter presentation or be revived by a receipt.
- External mailbox readers claim presentation before exposing received bodies.
  A later read can return the already-dispatched body, but cancellation then
  returns `too_late`. Identifier-only events are hints: a cancelled message may
  leave an already-sent hint, but fetching its body cannot revive delivery.
- Across hosts, cancellation is confirmed by the recipient's authoritative
  mailbox. Offline destinations return `cancellation_pending`, not success.
  Durable recovery retries the same cancellation ID and never resends content.
- A stale heartbeat rejects new submission with `endpoint_unavailable`; it
  does not prove process death or retire a live endpoint.
- `message ID` reports `delivery_reason` for guarded pending delivery. These
  diagnostics are not read receipts or an assertion that the recipient replied.

Representative regressions: `test-unified-hub.py` and
`test-unified-federation.py` cancellation cases.

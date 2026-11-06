# Dots bridge runtime contract

The private Dots bridge is a single Unix-domain listener owned by the launchd
service process. Startup validates the complete service configuration before
creating directories, taking the startup lock, removing a stale socket, or
binding a new listener. A missing or invalid setting therefore cannot destroy
an already-running bridge.

## Socket ownership

- The bridge path and its adjacent `.lock` path must not be symlinks.
- A regular file, directory, or other non-socket at the bridge path is refused.
- A startup lock is held for the bind sequence, preventing concurrent starts.
- An existing socket is probed first. A successful connection means a live
  bridge and startup is refused; only a connection-refused stale socket is
  removed, after an inode/device recheck.
- Shutdown removes the socket only when its inode/device still belongs to the
  listener that bound it.

## Connection isolation

Each accepted connection has one monotonic receive deadline (2 seconds) and a
262,144-byte UTF-8 payload limit plus the required final newline (262,145 bytes
on the wire). Requests and responses use the same byte limit and newline
framing; JSON is encoded with native UTF-8 (`ensure_ascii=false`) so the limit
does not depend on escaped code-point length. The listener collects bytes with
`recv`; it does not parse JSON until the newline arrives.
EOF before a newline, a trickled frame that exceeds the total deadline, a frame
over the limit (including a valid prefix followed by extra bytes), malformed
JSON, disconnects, read failures, and send failures are contained to that
connection; they do not terminate the listener or event-pump thread. Oversized
frames and malformed requests receive a bounded metadata-only error response;
an oversized result is replaced with a bounded `response_too_large` error
instead of emitting a truncated JSON response.
Successful later requests therefore remain serviceable after a bad client.
Response delivery receives its own 2-second socket timeout after dispatch, so a
slow or non-reading client cannot retain the receive deadline or trigger a
second dispatch.

Listener interruption errors (`EINTR` and `ECONNABORTED`) are retried. Other
listener failures escape the bridge loop so the service supervisor can observe
and restart a failed listener instead of spinning on a persistent error.

The bridge returns generic rejection text for request failures and never logs
service credentials or request payloads.

## Failure classification

Bridge stderr audit rows include fixed `event`, `at_unix`, optional `elapsed_ms`,
and an allowlisted `operation` for dispatch failures and slow dispatches.
Dispatch failures also carry an allowlisted `error_code`;
unrecognized operation/code values are recorded as `unknown`/`other`, never as
arbitrary caller or exception text. Existing sanitized transport details retain
connect/send/receive/decode phase and unknown-acceptance evidence.

A `dispatch_failure` is a failed request, not necessarily a disconnected bridge:
for example, `not_found` and `scope_denied` must remain distinguishable from
`unavailable`. Historical rows without these fields remain unclassified. Failure
counts have no success denominator and must not be reported as failure rates.
This is diagnostic-only: no replay, admission, credential, scope or response
semantics change; no per-success traffic logging is added. The common bridge
implementation serves both Dots and Muse.

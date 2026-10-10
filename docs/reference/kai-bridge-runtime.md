# KAI bridge runtime contract

The private KAI bridge is a single Unix-domain listener owned by the launchd
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
262,144-byte payload limit plus the required final newline (262,145 bytes on
the wire). The listener collects bytes with `recv`; it does not parse JSON
until the newline arrives.
EOF before a newline, a trickled frame that exceeds the total deadline, a frame
over the limit (including a valid prefix followed by extra bytes), malformed
JSON, disconnects, read failures, and send failures are contained to that
connection; they do not terminate the listener or event-pump thread.
Successful later requests therefore remain serviceable after a bad client.

Listener interruption errors (`EINTR` and `ECONNABORTED`) are retried. Other
listener failures escape the bridge loop so the service supervisor can observe
and restart a failed listener instead of spinning on a persistent error.

The bridge returns generic rejection text for request failures and never logs
service credentials or request payloads.

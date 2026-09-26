# Source-side peer authority primitive

`tproj-peer-authority` is an isolated, non-delivering Unix-socket helper. It is
not wired into `tproj-msg`, task cache, installation, SSH, or the GUI. It does
not make current cross-host chat authoritative.

The operator configures one local session, project directory, target, and
pre-existing SSH-forward process PID at helper launch. One helper is
configured for one destination pane; multiple targets require separate
instances and distinct private sockets. No launch plan is supplied here. These are command-line
configuration, never envelope-selected. The Unix socket must be unused under a
mode-0700 private directory; the helper sets its socket mode to 0600. It uses
Darwin `LOCAL_PEERPID` on **every** accepted connection. Linux and other
platforms fail closed. No caller-supplied PID is accepted.

`mint` accepts one exact JSON envelope: `session`, `sender`, `target`, `role`,
`epoch`, `kind`, `task_id`, `body`. The helper checks an exact alias.role,
configured session and target, role/epoch against the one matching
model-role-router registry record, registry `project`, live PID ancestry,
recorded `pid_start`, record freshness, process UID, and caller cwd under the
configured project. Ambiguous registry identity fails closed. The resulting
cryptographically random 256-bit nonce is held **only in helper memory** for
30 seconds, bound to the canonical JSON SHA-256 digest of the entire envelope.
No MAC key or bearer credential is placed on disk.

`consume` requires that exact envelope and nonce through the same socket.
The kernel peer PID must equal the configured SSH-forward PID, with the same
live process start and UID recorded at helper launch. The nonce is removed
atomically before the success response, including on digest mismatch; it is
one-shot and cannot survive helper restart. A disconnected/unknown result is
not safe to retry as a new task. The returned digest is a proof only within
this helper's process and fixed receiver binding; it is **not** a globally
verifiable signature or a delivery receipt.

Security boundary: this primitive assumes the configured SSH-forward process
is established and authenticated independently. A receiver must not accept a
bare envelope, mint response, nonce, or caller-selected socket as authority.
It must route `consume` only over that fixed forward and must keep downstream
sender/target/task lifecycle gates. The SSH pairing, cross-host request/response
flow, delivery, replay policy beyond this single helper lifetime, and remote
receiver identity are explicitly outside this primitive. Until those are
implemented and verified, remote task/handoff parity is **not established**.

Focused isolated proof: `python3 extensions/messaging/tests/test-peer-authority.py`.
It mocks process/registry state and does not prove a live Darwin socket or SSH
forward.

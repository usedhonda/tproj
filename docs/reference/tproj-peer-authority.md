# Source-side peer authority and fixed SSH forward prerequisite

**Not enabled for `tproj-msg`.** These helpers do not deliver a task, construct a
local `[from:]` header, modify the task cache, or prove real two-Mac parity.
Existing remote ingress remains non-authoritative plain chat.

`tproj-peer-forward` supervises one fixed client-initiated SSH `-R` Unix-socket
forward and one local `tproj-peer-authority` socket. Its route is supplied by
trusted launch configuration, never selected by a received envelope: SSH host,
local and remote socket paths, source/destination host and project IDs,
owner/destination sessions, and one exact destination alias.role. One target
requires one forward/authority instance. The launcher uses argument-vector
SSH (no shell), disables multiplexing, requires host-key checking, batch mode,
reverse-forward establishment, private Unix socket binding, and no automatic
unlink of an old remote socket. An operator must provision the remote private
socket directory and trusted SSH host/account in advance. The helper does not
change SSH daemon settings. It was not launched against a live host in this
change.

The authority records the **actual** SSH child PID/start/UID at launch.
`consume` obtains the kernel peer PID through Darwin `LOCAL_PEERPID` and
requires that exact still-live process PID/start/UID. Supervisor loss,
reconnect, process replacement, or helper restart invalidates pending nonces;
there is no automatic trust transfer to a new forward. The helper itself
requires an unused mode-0600 socket under a private owner-owned directory.

The v2 `mint` request has an exact object
`{"version":2,"metadata":<peer-outbox record>,"kind":"task|role_handoff","body":<text>}`.
The authority checks the full metadata schema, fixed route, exact body SHA-256,
a **prepared** outbox row with identical metadata, and the caller's real
`LOCAL_PEERPID` ancestry against the live model-role-router registry
PID+`pid_start`, project, sender role, epoch, and orchestrator alias. It returns
a random 256-bit nonce and SHA-256 of canonical envelope JSON. The nonce stays
only in helper memory for 30 seconds. No readable key file is involved.

`consume` requires the same full envelope and nonce, the registered SSH
process, an unchanged live sender registry role/epoch/PID start, and the exact
source outbox row still `prepared` or `committed` (never tombstoned). It removes
the matching nonce atomically; exact digest mismatch, expiry, replay, changed
forward process, route, epoch, or tombstone fails closed. A successful consume
response is a **source-side origin proof only**, not a delivery receipt. The
receiver must itself call consume through the fixed configured forward,
compare the returned digest, persist message-ID replay state, validate its own
target/epoch/tombstone, and build lifecycle headers from verified fields. It
must never trust raw wire markers or a caller-selected socket.

Only initial `task` and `role_handoff` minting are in this slice. ACK/DONE/BLOCK,
owner CANCEL/FREEZE, commit/release, durable receiver quarantine, D4 outbox
reconciliation, and remote authenticated ingress require additional coordinated
work described in `tproj-cross-host-control-v2.md`. Do not use these helpers to
claim cross-host control is active.

Focused isolated proofs:
`python3 extensions/messaging/tests/test-peer-authority.py` and
`python3 extensions/messaging/tests/test-peer-forward.py`. They mock process
identity and do not prove a live Darwin socket or SSH forward.

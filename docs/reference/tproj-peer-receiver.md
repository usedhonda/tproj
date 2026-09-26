# Receiver quarantine gate (isolated v2 slice)

`tproj-peer-receiver` is not connected to `tproj-msg`; it performs no pane
injection. Its route, destination registry root/project, private ledger path,
and source-forward socket/PID/start/UID must come from trusted local
configuration. Wire input cannot select any of them. The connected Unix
socket's Darwin `LOCAL_PEERPID` and live start/UID must match the registered
remote-side SSH forward process. A missing/replaced socket or reconnect fails
closed. The source-side authority separately requires the paired source SSH
client PID/start for every nonce consumption. SSH or text alone is never a
pane-sender credential.

`quarantine` accepts an exact `{envelope,nonce,digest}` wire object for a v2
`task` or `role_handoff`. It checks the configured source/destination
host/project/session/target, bounded TTL and body SHA-256, current destination
registry target PID+start/project/`target_epoch`, local nonce/digest syntax,
and a successful one-shot source authority `consume` through the fixed
forward. It stores only exact structural metadata in the private durable
peer-outbox ledger as `quarantined`; its output is only `message_id` and state,
**never the task body**. The source authority permits this initial proof for
a prepared or subsequently committed source row, but not a tombstone.

`release` accepts `{task_envelope,commit_wire}`. The commit wire is a separate
v2 `commit` envelope for identical metadata and empty body with its own
one-shot source nonce. Source authority mints/consumes it only for an exactly
`committed` outbox row (which D4 must reconcile after cache+DB success).
Receiver requires its exact quarantined row, rechecks live target epoch and
source proof, then transitions to `released`. Only this successful response
contains the task envelope/body for a future authenticated ingress to handle.
A duplicate/mismatched/replayed proof, changed route, expired task, stale
epoch, tombstone, absent quarantine, or changed SSH process is rejection,
never fallback to plain chat.

`target_epoch` is a mandatory positive integer in peer-outbox metadata.
Source remote status may supply an observed candidate value, but it grants no
sender authority; the receiver checks the current exact target registry entry
at quarantine and again at release. A timeout after nonce consume or state
transition is an unknown outcome requiring exact message-ID reconciliation;
callers must not invent a new task or assume delivery. This helper does not
persist the body or a delivery receipt, and a future `tproj-msg` ingress must
add durable idempotent injection and owner/tombstone gates before control is
enabled.

Focused isolated checks:
`python3 extensions/messaging/tests/test-peer-receiver.py` and
`python3 extensions/messaging/tests/test-peer-authority.py`. They mock process
identity and do not prove live SSH/tmux behavior.

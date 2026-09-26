# Cross-host control v2: proposed fail-closed protocol

**Status: design only.** No current `tproj-msg` flag, relay, authority helper, or
SSH command implements this protocol. Existing cross-host delivery remains
non-authoritative plain chat. Do not inject a `[from:]`, `[Task:]`, role-handoff,
or lifecycle marker from a remote body or from an SSH host identity alone.

## Trust and fixed tunnel

Each direction needs an independently configured, client-initiated SSH `-R`
Unix-socket forward. The source authority socket lives under a private local
directory and accepts `mint` only from a Darwin `LOCAL_PEERPID` whose process
ancestry binds to one live model-role-router record: exact sender alias,
PID+`pid_start`, project path, session, role, role epoch, and orchestrator alias.
The configured forward process PID, its start time, UID, source host identity,
destination host identity, session, and one destination alias.role must be
recorded at forward establishment; a reconnect changes that binding and must
invalidate outstanding nonces. The source authority accepts `consume` only
from that same kernel peer PID/start/UID. A remote envelope cannot choose the
socket, host, forward, session, or destination. The receiver selects these from
trusted local configuration. SSH host-key/account authentication establishes
the host tunnel, **not** pane-sender identity. No shared readable key, sender
text marker, or caller-supplied PID substitutes for the kernel/registry checks.

The remote receiver must itself issue `consume` through that fixed forward,
compare the returned canonical envelope digest, and consume the nonce once
before it creates any authoritative local message or lifecycle evidence. A
successful nonce is a single-helper-lifetime proof, not a signature or
acknowledgment of delivery. A missing forward, stale binding, helper restart,
expired nonce, changed PID/start, or unknown result fails closed.

## Canonical envelope and authority checks

Versioned canonical JSON is bounded in size and has an exact field set:

| Field | Contract |
|---|---|
| `version`, `message_id`, `nonce`, `issued_at`, `expires_at` | Version 2, random unique message/nonce IDs, short bounded validity; receiver persists consumed `message_id` before injection to reject replay across helper restart. |
| `source_host`, `destination_host`, `source_project`, `destination_project`, `source_session`, `destination_session` | Must equal both sides' configured peer binding; never route from wire alone. |
| `sender`, `target`, `sender_role`, `role_epoch`, `orchestrator_alias` | Exact alias.role/registry identity and current role epoch. The receiver also checks target pane liveness and its current role epoch for a handoff. |
| `kind` | One of `task`, `ack`, `ack_progress`, `done`, `block`, `cancel`, `freeze`, `role_handoff`; no arbitrary marker interpretation. |
| `task_id`, `owner_session`, `owner_alias`, `task_kind`, `intent_hash`, `user_authorized_exact`, `ttl_sec` | Exact owner/target/task tuple and structural delegation metadata. A user authorization bit is valid only with the exact source intent hash and scope record, never because the wire says so. |
| `body_hash`, `body` | Hash binds the exact body bytes; body is data and cannot override any envelope field. Sender, task, or control markers inside the body are rejected or escaped before local injection. |

The source authority must derive or compare security fields against its local
registry and durable task/outbox state; it must not merely type-check envelope
claims. For `ack*`, `done`, and `block`, it checks the remote worker's exact
inbound task record, source owner/target/task tuple, epoch, and non-tombstoned
state. For `cancel` and `freeze`, it checks the source owner identity and an
existing exact task row; a worker cannot issue owner tombstones. For
`role_handoff`, it checks the current orchestrator/epoch, exact user-authorized
intent where applicable, and the destination pane epoch at both mint and
release. The destination repeats fixed-route, target, epoch, TTL, and local
tombstone checks after consuming the nonce. Unknown kind, stale epoch, missing
row, ambiguity, or conflicting state is rejection, not plain-chat fallback.

## Ownership and two-phase release

The current task-cache contract makes D4 PostToolUse the **sole cache insert
writer after `tproj-msg` sends**. A new task therefore has no cache row at mint
time. V2 requires an explicit contract migration, not a read of a nonexistent
row:

1. Source `tproj-msg` durably prepares an owner-scoped outbound **outbox** row
   before mint. It binds task ID, exact owner/target, both host/project/session
   IDs, epoch, orchestrator, task kind, TTL, intent hash, exact authorization
   bit, and body hash. Preparation is separate from the D4 cache insert.
2. Source authority mints only for that exact prepared row and live verified
   sender. Destination consumes the one-shot proof and durably records the
   exact inbound row as **quarantined**, with unique `(source_host,
   owner_session, owner_alias, task_id, message_id)` keys. No task text reaches
   the pane yet.
3. After the source's D4 cache insert and durable DB shadow row succeed, the
   source marks the outbox committed and sends a separately authenticated
   `commit` control for the same tuple. Destination checks its quarantined row,
   current target/epoch, and tombstone state before one atomic transition to
   released plus local injection. A duplicate commit is idempotent.
4. ACK/DONE/BLOCK proof refers to the released inbound row. The source applies
   replies only to its matching non-tombstoned owner cache/DB row and preserves
   the existing message-ID/body-hash evidence rules. CANCEL/FREEZE tombstones
   propagate durably and dominate delayed task/commit/reply messages. The
   receiver mutation guard remains in force until its existing authorized
   unfreeze or a newer task according to the local contract.

`commit` is a protocol phase, not a user-visible lifecycle kind. Both source
and destination need durable, monotonic state transitions and recovery after
crash. No agent may treat a quarantined task as delegated work.

## Failure atomicity and unresolved gates

A timeout or broken connection after mint, consume, destination persistence,
commit, or pane injection has an **unknown** outcome. Never mint a new nonce
and resend as a new task blindly. Reconcile by exact message/task ID against
both durable ledgers; duplicate delivery must be idempotent, while missing
commit leaves destination quarantined. If D4 is disabled/fails, the source
cannot commit and the destination never releases. An expired prepared or
quarantined row is retained as an auditable failed attempt or tombstone, not
silently executed or deleted. A failed local pane injection must not be
reported as delivered.

Before enabling v2, implementation must add: fixed-forward establishment and
PID/start registration, source outbox and D4 commit reconciliation, destination
quarantine/commit ledger, owner-scoped reply and tombstone synchronization,
authenticated `tproj-msg` ingress that constructs (rather than trusts) headers,
replay persistence, and focused plus real two-Mac end-to-end proof. These are
not supplied by `tproj-peer-authority` or the current plain-chat remote relay.

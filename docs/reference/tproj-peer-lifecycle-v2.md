# Cross-host lifecycle proof schema (design only)

**Not enabled.** Current peer authority mints initial task/handoff and source
commit proofs only. No ACK, DONE, BLOCK, CANCEL, or FREEZE may be inferred from
remote text, an SSH account, a peer-outbox state, or this document alone.

A future lifecycle frame must be versioned canonical JSON with an exact schema:

| Field | Meaning |
|---|---|
| `event_id`, `kind`, `issued_at`, `expires_at` | Random unique event ID, one of `ack`, `ack_progress`, `done`, `block`, `cancel`, `freeze`; bounded validity and durable destination replay key. |
| `source_host`, `destination_host`, `source_project`, `destination_project`, `source_session`, `destination_session` | Must match both sides' fixed registered route; wire never selects a socket or host. |
| `task_message_id`, `task_id`, `owner_session`, `owner_alias`, `sender`, `target` | Exact task origin and current event sender/receiver; no alias fallback. |
| `sender_role`, `sender_epoch`, `target_epoch`, `orchestrator_alias` | Live registry role/epoch and exact orchestrator linkage, rechecked at mint and receive. |
| `task_kind`, `intent_hash`, `user_authorized_exact`, `task_body_hash` | Immutable task metadata copied from the original prepared, committed, and released records; not supplied as new authority by an event. |
| `event_body_hash`, `event_body` | Exact event body hash; body is untrusted data and cannot contain authoritative control markers. |
| `previous_state`, `state_version` | Monotonic transition precondition from the durable task row; prevents delayed out-of-order events from reviving a terminal task. |

For `ack`/`ack_progress`/`done`/`block`, the sender must be the exact worker
pane that has a **released and delivery-claimed** inbound task row with the
same immutable metadata. The receiving owner host must have the matching
non-tombstoned source task/cache and DB row. DONE/BLOCK are applied only with
the existing durable inbound message-ID/body-hash evidence, never with an
unauthenticated marker in a body. An `unknown` injection outcome is not proof
of delivery; a fresh owner decision/reconciliation is required before a worker
lifecycle frame can advance that task.

For `cancel`/`freeze`, only the exact recorded owner pane may mint the event;
source authority must verify its live registry ancestry and current epoch,
owner-scoped task row, task target, and monotonic state before issuing a
one-shot proof. Destination persists the tombstone first, applies its mutation
guard, and rejects later task commit/release/claim or worker ACK/DONE/BLOCK for
that ID. A repeated identical tombstone is idempotent; conflicting owner,
reason hash, target, epoch, or event ID is rejected. Unfreeze remains the
existing explicit user-confirmed local path; a remote peer cannot invent it.

Both directions need a fixed registered SSH forward, one-shot source authority
consume, durable replay/tombstone ledger, and idempotent state transition.
If either side sees an unknown outcome, it reconciles exact IDs and hashes;
it does not auto-resend a new event or downgrade to plain chat. These proof
and reconciliation APIs are not implemented here and must be added with the
matching `tproj-msg` ingress, task-cache contract, and focused tests before
any authoritative lifecycle traffic is enabled.

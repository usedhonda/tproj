# Peer task metadata ledger prerequisite

`tproj-peer-outbox` is an **isolated, non-delivering** v2 prerequisite. It does
not alter `tproj-msg`, start a tunnel, mint/verify a sender, touch the current
`tproj-task-cache`, or enable cross-host control. It stores structural metadata
only: no task body, message body, credential, or private key.

Each invocation takes an absolute `--db` path inside an existing owner-owned
private (mode 0700) directory and one exact JSON metadata object on stdin.
The database must be an owner-owned regular mode-0600 file. SQLite uses a
transaction (`BEGIN IMMEDIATE`), WAL, and `synchronous=FULL`; one message ID and
one `(owner_session, owner_alias, target, task_id)` identify a task. The
metadata contains exact origin/destination host and project IDs, owner and
destination sessions, owner/sender/target alias.role, role epoch, orchestrator
alias, task kind, intent/body SHA-256 hashes, exact authorization bit, TTL,
and issued time. All identifier components reject `/`, `.` and `..`; fields
outside the exact schema fail. `sender` must equal `owner_alias`. An exact
user-authorization bit requires a nonempty intent hash.

`prepare` creates source `prepared`; `quarantine` creates destination
`quarantined`. `commit` moves only `prepared -> committed`; `release` moves
only `quarantined -> released`. `tombstone --tombstone-hash <sha256>` moves any
existing state to terminal `tombstoned`. Exact retries of the current initial
or terminal transition are idempotent. A reused message ID with changed
metadata, a task tuple with a different message ID, a mismatched tombstone
hash, or a transition out of a tombstone is rejected. The caller must present
the **entire unchanged metadata record** for every transition, not just a task
ID. A database reopen after a crash preserves states and uniqueness.

This ledger alone does **not** prove the metadata true. A future integrated
sender must first bind it to the verified local pane, intent authorization,
and source outbox ownership; a future receiver must consume source authority,
validate its fixed route, and persist quarantine before any pane injection.
D4 PostToolUse remains the sole writer of the existing task cache. Replacing
or reconciling that single-writer contract, fixed SSH-forward registration,
and two-Mac end-to-end proof remain blocking work as described in
`tproj-cross-host-control-v2.md`. Do not use `committed` or `released` from
this isolated ledger as a delivery receipt.

Focused isolated check:
`python3 extensions/messaging/tests/test-peer-outbox.py`.

## D4 exact prepared lookup

`lookup-prepared --db ABS --owner-session S --owner-alias A --target T
--task-id I` opens an **existing** private database read-only and returns the
entire exact prepared metadata JSON, including `message_id`. It requires the
unique owner/session/target/task tuple and rejects an absent, committed,
released, or tombstoned row. It never prepares, commits, or creates a database.
D4 must independently confirm its cache insertion and durable DB shadow row
before passing this unchanged JSON to `commit`; lookup itself is not that proof.

# Unified task authority

`extensions/messaging/unified/tasks.py` stores the formal task ledger in the
hub SQLite database. Every request carries a host-authenticated actor tuple:
`endpoint_id`, `incarnation`, `host_id`, and `project_id`. Endpoint incarnation
is a fence: a restarted process cannot mutate work owned by its predecessor.

## API

`dispatch(request, actor)` accepts `task_approval`, `task_submit`,
`task_status`, `task_list`/`task_active`, lifecycle operations (`task_ack`,
`task_progress`, `task_done`, `task_block`, `task_verify`, `task_report`),
owner-only `task_cancel`/`task_freeze`, operation guards
(`task_begin_operation`/`task_end_operation`), and handoff operations
`task_prepare_handoff`, `task_release_handoff`, `task_accept_handoff`, and
`task_commit_handoff`.

Approval registration is accepted only when host integration attests direct-user
evidence and supplies the source endpoint. Submission pins intent/scope hashes,
approval reference, owner, executor, and executor incarnation. Repeated
idempotency keys return the original task or a conflict.

Handoff is a durable four-step fence: owner prepares a target, the old executor
releases after all operation tokens close, the target accepts, and the owner
commits with an epoch compare-and-swap. Open operation tokens never expire;
stale or terminal tasks cannot be resurrected.

## Local assignment fence

The native host records a restrictive presence marker before accepting an
assignment. It contains no task state or authority; operations still query the
single master. A missing or unreadable journal must not turn a known assignment
into an unassigned session. The marker is removed only after a successful
terminal-task detach with no open operations. Ordinary unassigned sessions do
not require the task master. This integration is not yet production-activated.

## Approval and retry identity

Approval binds the exact native user instruction (without prescribed wording),
or the exact proposed plan confirmed by the next direct user instruction. Native
transcript conversation and project must match the authenticated endpoint.
Transport-injected messages and internal continuation blocks are not approvals.
The host attests provenance and exact scope, not the semantic correctness of an
agent's interpretation of user intent; agents must still follow the user's scope.

Repeating `submit` with the same approval, scope, intent, target, and packet uses
the same default idempotency key, including after an unknown transport result.
A deliberately new identical task requires an explicit new `--idempotency-key`.
A packet cannot name a target different from the command's target.

Handoff release and acceptance retries never regress an advanced phase. A
repeated commit with the same old epoch and exact target returns its committed
result; another target or epoch is rejected. Cancellation and reported terminal
states cannot be replaced by a later freeze or delayed lifecycle message.

Federated task requests and responses confirm task protocol version 1. Missing
or incompatible versions fail without routing into legacy task controls. The
public client also refuses legacy fallback when an enrolled installation's
configuration is missing, malformed, or inactive.

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
not require the task master. Installation and hook trust alone do not prove
native enforcement in an already-running agent. Before relying on formal task
mutation fences, verify that an actual native mutation creates and closes its
operation on the master. A successful API lifecycle or notification receipt is
not that evidence. An agent still running an older executable/configuration must
not be reported as protected merely because the installed files are current.

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
Enrolled mutation commands never fall through to the historical cache, including
on `not_found` or an unknown command. Only historical non-UUID `status` retains
read-only fallback. The enrolled MSG wrapper rejects legacy `--new-task` and
`--role-handoff` controls; formal operations use `tproj-task` instead.

## Model-role integration

The optional role bridge reads `task_context` through native caller
verification. Only a matching accepted executor at the authoritative epoch
receives a transient worker role. Pending handoff, terminal state, or unavailable
master stays read-only for the assigned task. Project role-mode files and peer
registry entries are never rewritten by this overlay. Ordinary messages do not
create assignments. The helper and formal tool guard must be installed together.

## Freeze release and former executors

Only the exact owner may `unfreeze TASK --epoch N`, after all admitted operations
have closed. Release advances the epoch, restores the recorded pre-freeze state
(in-progress becomes accepted), and invalidates pending handoffs. Missing historic
freeze evidence is rejected, never guessed. A released executor must ACK the new
epoch before mutation. Cancelled and reported tasks cannot be unfrozen.

Committed handoff retains the former executor's authenticated read access in the
central ledger, not a replicated local authority. The former executor may explicitly
`detach TASK --epoch N` (N is its bound assignment epoch) once no operations of its own remain and no pending handoff
still assigns it. Another executor's open operation does not prevent this local
release. A wrong task ID cannot clear the local fence, and current active executors
cannot detach before report or cancel. Superseded epochs still cannot mutate tasks.

Discovery preserves the incarnation returned by the hub's endpoint registration
response in the authenticated caller record. Native registry evidence never
mints this value. Missing or mismatched registration confirmation rejects task
binding rather than fabricating an incarnation or degrading to an unbound task.

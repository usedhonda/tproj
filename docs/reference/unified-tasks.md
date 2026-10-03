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

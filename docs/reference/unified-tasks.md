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

The established mutation/completion entrypoints also evaluate formal task
operations. Completion matchers cover direct file edits as well as shell tools;
shell-only acceptance does not prove edit completion. Installer migration removes
only exact generated obsolete entries and preserves customized/grouped hooks.
An already-running client must reload its hook configuration through a supported
native mechanism before newly covered tools can be considered enforced; installing
or trusting configuration on disk is not evidence of that live reload.
The evaluator keeps its allow/block result internal: an allowed native hook emits
no decision, preserving platform permission checks. Only a block is serialized;
`decision: "allow"` is not a valid native pre/post hook wire response.

For a live Codex client that exposes `/hooks`, a genuinely changed hook can be
reviewed and trusted from that client's hook details without restarting its
conversation. Review the exact command and matcher, trust only that entry, then
verify a real operation in the same native conversation. Do not toggle safeguards
off or remove trust records merely to provoke a reload. A separate installer or
app-server process cannot prove that another running conversation reloaded.

## Approval and retry identity

Approval binds the exact native user instruction (without prescribed wording),
or the exact proposed plan confirmed by the next direct user instruction. Native
transcript conversation and project must match the authenticated endpoint.
Transport-injected messages and internal continuation blocks are not approvals.
Identical approval wording can occur more than once. A nonmatching earlier
candidate does not stop the search for an exact scope/intent/evidence match.
Every user record consumes the pending proposal, including rejected candidates;
a later approval cannot reuse a proposal across an intervening user record.
The host attests provenance and exact scope, not the semantic correctness of an
agent's interpretation of user intent; agents must still follow the user's scope.

Task notifications are durable hints, not a current assignment snapshot. Read
current status and executor identity before accepting; a delayed notification
never instructs acceptance with a captured epoch. Completed, cancelled, frozen,
transferred, or already accepted tasks are not re-ACKed because a notice arrived.
The host rejects a known non-acceptable status before creating a local assignment
marker. Eligible acceptance still records its restrictive marker before the
remote mutation, preserving fail-closed behavior on an unknown result.

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
verification. Hook invocations pass their authenticated native `thread_id` or
`session_id` from the hook payload when process environment variables do not
carry it. A payload/environment disagreement is rejected rather than resolved
by guessing. Only a matching accepted executor at the authoritative epoch
receives a transient worker role. Pending handoff, terminal state, or unavailable
master stays read-only for the assigned task. Project role-mode files and peer
registry entries are never rewritten by this overlay. Ordinary messages do not
create assignments. The helper and formal tool guard must be installed together.

An explicit schema-valid `write_stdin` hook payload with a numeric
`session_id`, no `chars` field or `chars` equal to the empty string, and only
the optional numeric `yield_time_ms`/`max_output_tokens` fields is a read-only
poll. A pre-tool poll does not begin an operation; a post-tool poll still tries
to close its exact tool identity, tolerating only a host `not_found` result for
that empty poll. Whitespace, control characters, non-empty input, malformed or
missing identity, and other host errors remain guarded.

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

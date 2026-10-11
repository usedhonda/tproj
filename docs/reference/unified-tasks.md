# Unified task progress ledger

`extensions/messaging/unified/tasks.py` stores the formal task ledger in the
hub SQLite database. Every request carries a host-authenticated actor tuple:
`endpoint_id`, `incarnation`, `host_id`, and `project_id`. Endpoint incarnation
is a fence: a restarted process cannot mutate work owned by its predecessor.

## API

`dispatch(request, actor)` accepts `task_approval`, `task_submit`,
`task_status`, `task_list`/`task_active`, lifecycle operations (`task_ack`,
`task_progress`, `task_done`, `task_block`, `task_verify`, `task_report`),
requester-only `task_cancel`/`task_freeze`, operation guards
(`task_begin_operation`/`task_end_operation`), and handoff operations
`task_prepare_handoff`, `task_release_handoff`, `task_accept_handoff`, and
`task_commit_handoff`.

Approval registration is accepted only when host integration attests direct-user
evidence and supplies the source endpoint. Submission pins intent/scope hashes,
approval reference, requester (historical `owner` fields), executor, and executor incarnation. Repeated
idempotency keys return the original task or a conflict.

Handoff is a durable four-step fence: owner prepares a target, the old executor
releases after all operation tokens close, the target accepts, and the owner
commits with an epoch compare-and-swap. Open operation tokens never expire;
stale or terminal tasks cannot be resurrected.

## Legacy local assignment records

Task ownership identifies the requester of a ledger record, not ownership of
another project or authority over the executor's entire conversation. ACK,
cancellation, freeze, and service failure must not change the recipient's
normal working role or capture later direct-user work. A task packet is a
request within the recipient's independently authorized scope, not a new grant.

Legacy assignment rows and presence markers remain recoverable evidence. They
must not be interpreted as permission switches for all native tools. Unknown
operations remain unknown; removing a binding is not proof that an OS process
or external side effect has stopped. Before reusing a resource touched by an
unresolved execution, obtain independent completion/stop evidence or isolate
that resource. Unrelated work and diagnostics remain available.

`tproj-task binding-status` (without a native ID, endpoint, role, or other
caller selector) is a read-only diagnostic. The authenticated native host
correlates the current conversation's marker with local formal binding records
using its verified native ID, and reports marker presence, current binding
status/epoch/incarnation match, and sanitized matching-binding counts. It may
read authoritative task status to distinguish a missing or old task, but it
never creates the binding table, writes a marker, changes the task master, or
detaches, rebinds, cancels, or grants authority. Missing or ambiguous native
identity fails closed; a caller-supplied selector cannot redirect the query.

The established mutation/completion entrypoints retain exact legacy-operation
checks without attributing ordinary tools to the current task record. Completion matchers cover direct file edits as well as shell tools;
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
The host rejects a known non-acceptable status before ledger acceptance.
New ACKs record the accepted task without installing a conversation-wide
assignment marker or replacing a legacy binding. An unknown transport result
remains an uncertain ledger outcome, not an edit prohibition over the receiver.

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

## Model-role independence

Formal task records do not override Solo/Assist/Collab roles or inject an
old-task-only directive into the native conversation. The task context helper
provides sanitized record diagnostics; task status and availability do not grant
or revoke local editing authority. Ordinary messages never authorize task work.
Independent user-scope, identity, secret, destructive-operation, and model-role
controls remain in force.

A native tool ID alone is not proof that a tool belongs to a task. Ordinary
native tools must not be admitted against whichever task is currently bound.
Legacy exact retired tool identities remain protected against delayed callbacks;
they cannot be resolved through a later binding or silently reopen old work.

## Freeze release and former executors

Only the exact requester may `unfreeze TASK --epoch N`, after all admitted operations
have closed. Release advances the epoch, restores the recorded pre-freeze state
(in-progress becomes accepted), and invalidates pending handoffs. Missing historic
freeze evidence is rejected, never guessed. A released executor must ACK the new
epoch before further task-ledger execution admission. Cancelled and reported tasks cannot be unfrozen.

Committed handoff retains the former executor's authenticated read access in the
central ledger, not a replicated local authority. The former executor may explicitly
`detach TASK --epoch N` (N is its bound assignment epoch) once no operations of its own remain and no pending handoff
still assigns it. Another executor's open operation does not prevent this local
release. A wrong task ID cannot clear the local fence, and current active executors
cannot detach before report or cancel. Superseded epochs still cannot mutate tasks.

If the authenticated native conversation has lost its local binding after a
handoff, `detach TASK --epoch N` may resynchronize one exact former binding.
The host derives the old row from its verified native ID and enrolled endpoint
directory; callers cannot supply a prior endpoint or continuity proof. The
master performs a read-only release check: the exact historical assignment and
epoch must exist on the same host/project, the task must be actively owned by a
different current executor at a later epoch, the former executor must have no
open operations, and no pending handoff may target either side. The releasing
native caller need not be the current task executor. Frozen, current-owner,
ambiguous, missing, cross-native, or forged proof
is rejected without local cleanup. Other executors' open operations remain
untouched. The operation changes only the requesting host's stale local binding
and removes its marker when no binding for that native conversation remains; it
does not change task authority, roles, grants, approvals, or history.

For an owner-cancelled task whose executor still holds the native binding,
`tproj-task release-cancelled TASK --epoch N` is the explicit local recovery
entrypoint. The authenticated host asks the master to authorize the exact
executor and epoch, or host-proven historical native continuity after an
incarnation change. The master requires the task to be `cancelled`.
It then removes only that conversation's local binding and restrictive marker.
All open operations remain unresolved history and are returned as sanitized
tool-use IDs/epochs, including operations owned by the releasing executor. This
operation never closes operations,
changes the cancelled task or epoch, resurrects work, or grants a new role.
The host durably records each unresolved old tool ID as retired before releasing
the marker; a late guard callback is rejected even if the native conversation
later binds a new task. Release and normal-detach receipts are written in the same transaction as
binding removal. They make marker cleanup retryable after a lost response or
post-commit crash, while refusing cleanup if a new binding appeared.

Discovery preserves the incarnation returned by the hub's endpoint registration
response in the authenticated caller record. Native registry evidence never
mints this value. Missing or mismatched registration confirmation rejects task
binding rather than fabricating an incarnation or degrading to an unbound task.
Task status also exposes actor-scoped `actor_open_operation_details` for the
authenticated endpoint incarnation: each item contains only `tool_use_id`,
`epoch`, and `created_at`. Operation tokens, payloads, commands, and other
actors' open operations remain hidden; this is evidence only and provides no
reconcile or force-close capability.

`tproj-task reconcile-operation TASK --epoch N --tool-use-id ID` is a bounded
host-side recovery for one exact open operation. It accepts only an
authenticated current binding plus an independently verified native completion
witness in the same thread and project. The matching result timestamp must be
valid and after both the master-recorded operation creation and its call; the
call may predate operation admission because PreToolUse creates it first.
Codex requires one exact `FileChange` or `CommandExecution`
`item_completed` record. `CommandExecution` requires a strict integer
`exit_code` and reports zero as `success` and any other integer as `error`.
Duplicate, conflicting, or malformed terminal records are rejected. CC requires one exact local `Bash`, `Edit`, or `Write`
`tool_use` followed by one matching `tool_result` whose optional `is_error` is
boolean. Both success and terminal error results close the operation; the
reconcile response reports the native outcome separately and never implies task
success, verification, or report. Sidechains, other sessions/projects,
duplicate or malformed records, and non-boolean `is_error` values are rejected.
Unrelated historical rows in the same native session are not witness records;
only rows containing the exact target ID must match the bound session and cwd.
The task must still be accepted/in-progress
with no pending handoff, and the command has no bulk or force-close mode. A
closed or absent operation is never treated as reconciled without an exact
open-operation detail. Other native tool types (including server-side tools)
are intentionally outside this witness contract.

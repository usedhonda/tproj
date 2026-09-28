# Conversation identity and cross-host tasks (design agreement)

Status: design agreed between the tproj CC and Cdx panes, 2026-09-29.
Nothing here is implemented yet. This note records the contract that an
implementation must satisfy; it does not approve implementation, deployment,
or restarting any session.

## Problem

1. **Shared Codex app-server identity.** One `codex app-server --managed-daemon`
   process can serve several conversations (observed: one daemon launched from
   the Artist pane also served Chi). Identity derived from process ancestry then
   names the launcher, not the calling conversation, and a message was sent as
   the wrong project. The unified transport currently rejects any caller whose
   ancestry reaches an app-server (`unified-messaging.md`, "Caller ancestry").
   That is containment only: such conversations cannot use messaging.
   `model-role-router` (sibling `general` checkout) relies on the same ancestry
   assumption.
2. **Tasks and role handoff do not cross hosts or sessions.** `--new-task` and
   `--role-handoff` still run on the legacy path, which works only inside one
   tmux session. The unified federation carries ordinary chat only.

## P4: conversation identity

- Keep rejecting app-server ancestry. The daemon's launcher PID, cwd, `--as`,
  and a self-reported thread ID are not proof of a conversation.
- Bind identity to an execution context guaranteed by a **trusted host-side
  conversation adapter**: it registers the native thread/tool invocation against
  an immutable endpoint ID plus incarnation. MSG and `model-role-router` consult
  the same authentication result. Role and epoch authority remain a separate,
  current-source decision.
- If capabilities are used, the adapter issues and applies them from the
  genuine conversation context, bound to host, endpoint incarnation, thread,
  operation, expiry, and nonce, and passes them over authenticated IPC/FD.
  Never place bearer tokens in shared daemon environment, prompts, argv, or
  logs. Expiry, restart, and replay are rejected. This does not claim isolation
  from arbitrary code running as the same UID.
- Whether Codex exposes a trusted hook/API for this is **unverified**. Do not
  state that the app-server can issue tokens. A precondition for implementation
  is proving that the native thread -> tool execution mapping can be obtained
  untampered.
- Fallback if that fails: an independent runtime per conversation, only when it
  is provable that the shared daemon is not reused and that another root
  conversation or subagent cannot borrow the parent's identity. A unique
  launcher or `CODEX_HOME` alone is not enough. Migration must never terminate
  existing sessions, and no unverified launch flag is promised.
- P4 is complete only when `model-role-router` uses the same contract; fixing MSG
  while Role still injects an ancestry-derived identity is not completion. The
  router change belongs to the `general` owner as a separate scope.

## P5: cross-host tasks and role handoff

Precondition: the sender authenticates genuinely (not full P4). Panes that
already authenticate (Claude, standalone Codex CLI) can adopt it first; shared
app-server conversations stay excluded until P4 holds.

1. **Task envelope.** Add a versioned task envelope on the existing unified
   transport/outbox: task ID, sender/recipient endpoint + incarnation, owner,
   role epoch, scope/intent hash, and a reference to an existing user approval.
   A self-declared `--user-authorized` never creates approval. Validate on
   acceptance and again at start. A stopped or re-registered recipient does not
   pass the task to a new incarnation by alias. Durable inbox plus task-ID
   de-duplication prevent double starts on redelivery; side effects of a crash
   mid-task are not called exactly-once. SSH between enrolled hosts is a trust
   path, not proof of a user GO.
2. **Lifecycle.** Connect ACK/progress/DONE/BLOCK/verify/report and cancel/freeze
   tombstones to one ledger model, distinguishing accepted, presented, started,
   and completed. Late delivery or retry never overrides a cancel or a newer
   epoch. Hosts do not copy the ledger and judge authority independently.
3. **Role handoff.** Separate from ordinary tasks: a single authoritative owner
   ledger per task, durable prepare/accept/commit with an expected-epoch CAS,
   and confirmation that the old executor stopped or is effectively fenced. The
   new side never becomes active before commit, and never while the old side
   can still act. Partition or timeout never grants authority; an undecidable
   handoff stays pending without terminating either session. Message arrival
   alone never switches authority.

All stages require protocol capability negotiation. An unsupported peer is not
silently downgraded to legacy or chat, and the legacy path must never become a
bypass for an identity rejection.

## Open questions (must be resolved before implementation)

- (a) Whether a trusted native conversation adapter can be obtained.
- (b) The concrete authority source of truth and fencing mechanism.

Agreeing on this contract is separate from proving (a) and (b) feasible.

## Minimum acceptance evidence (future)

- Two concurrent conversations cannot impersonate each other.
- Expired and replayed credentials are rejected.
- Duplicate delivery does not start a task twice.
- A cancel or newer epoch wins over a delayed task.
- An interrupted handoff never leaves two active authorities.

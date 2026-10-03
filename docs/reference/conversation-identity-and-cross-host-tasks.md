# Conversation identity and cross-host tasks (design agreement)

Status: current identity contract; formal task rollout remains pending live
host acceptance. Ordinary messages do not create task ownership or change roles.

## P4: current conversation identity

The authoritative current contract is [unified conversation identity](unified-conversation-identity.md).
The host trusts enrolled same-owner processes and correlates native conversation
IDs with its live project/platform/endpoint registry. The daemon launcher is not
the sender. Missing, ambiguous, or mismatched bindings are rejected. Native IDs
are correlation, not provider-signed identity or isolation against malicious
code already running as the same OS user. No session migration/restart is required.

MSG consumes the canonical model-role registry, including native session/thread
IDs; role/epoch remain independent. The earlier proposal requiring provider-issued
short-lived capabilities is not the current deployment gate.

## Formal cross-host tasks and role handoff

Precondition: the sender authenticates genuinely (not full P4). Panes that
already authenticate using the current conversation contract can adopt it.

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

The implementation source is `extensions/messaging/unified/tasks.py`; live
rollout and acceptance remain pending until integrated deployment verification.

## Selected authority and remaining rollout gates

Standalone installations use their local hub as the task master. Multi-host
installations select exactly one enrolled `task_master_host_id`; no replicated
ledger, automatic election, or local authority fallback is permitted.
Host-authenticated native approval evidence, task epoch, executor incarnation,
and durable operation boundaries fence mutations. A local assignment marker
only restricts execution; it cannot grant authority while the master is offline.

Before activation, finish native approval binding, role-router integration,
capability negotiation, and live isolated host acceptance. Source and fixture
success alone do not establish that these deployment gates are satisfied.

## Minimum acceptance evidence (future)

- Two concurrent conversations cannot impersonate each other.
- Expired and replayed credentials are rejected.
- Duplicate delivery does not start a task twice.
- A cancel or newer epoch wins over a delayed task.
- An interrupted handoff never leaves two active authorities.

# messaging

Inter-pane AI messaging for tproj workspaces.

## What's included

- **tproj-msg** -- Send messages between Claude Code, Codex, and Agent panes
- **msg skill** -- Claude Code skill for natural-language message triggers

## Features

- Idle/typing detection before sending (avoids overwriting user input)
- Message queueing with automatic flush when target becomes idle
- Relay and fan-out safety guards
- Gate target support for external bridge connections
- Symmetric active-model role handoff with Task ID tracking
- Durable task cancel/freeze tombstones and stale-epoch handoff rejection
- Symmetric Claude/Codex mutation guard when a delegated task is cancelled/frozen

## Usage

```bash
tproj-msg <target> "message"          # send to a pane
tproj-msg --status <target>           # check if target is idle
tproj-msg --list                      # list available targets
tproj-msg --fire <target> "message"   # urgent send
tproj-msg --role-handoff --new-task \
  --role-epoch 7 --orchestrator project.cdx \
  project.cdx "Plan and delegate this request"
tproj-msg --role-handoff --new-task --user-authorized \
  project.cdx "Run exactly: git push origin main"
tproj-task cancel <task-id> project.cdx deadbeefcafefeed
tproj-task freeze <task-id> project.cdx feedface00112233
```

Role handoff is never force-delivered. A typing or otherwise blocked target receives the complete envelope through the deferred queue, while existing `--new-task` and `[ACK:]` / `[DONE:]` / `[BLOCK:]` flows remain compatible. Queue storage encodes multiline bodies as a single record and continues to read legacy plain-text records.

Queued role handoffs are revalidated at flush time: if the target pane's current `@role_epoch` no longer matches the queued `Role-Epoch`, the handoff is cancelled into a tombstone and is never injected.

`--user-authorized` marks an exact delegated one-shot operation as already authorized by the user. Only the structural flag plus an `intent_hash` are persisted; the receiver must execute that exact scope without re-asking the user unless target or scope changes.

If a delegated task is cancelled or frozen, Claude and Codex both install the same mutation guard. Source edits, staging/commit/reset/revert/stash/checkout, build/test/restart/deploy, and ambiguous shell commands are blocked; only the strict read-only incident shell whitelist is allowed for evidence collection.

## Runtime refresh

Use the narrow canonical installer when only the messaging/task runtime and lifecycle guards need to be refreshed live:

```bash
./extensions/messaging/install-tproj-messaging-runtime
./extensions/messaging/install-tproj-messaging-runtime --check
```

## Requirements

- tmux (included with tproj core)
- Optional: `websocat` plus `timeout`/`gtimeout` (GNU coreutils) for WebSocket-based idle detection; without them the tmux prompt heuristic is used

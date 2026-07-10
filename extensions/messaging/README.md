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

## Usage

```bash
tproj-msg <target> "message"          # send to a pane
tproj-msg --status <target>           # check if target is idle
tproj-msg --list                      # list available targets
tproj-msg --fire <target> "message"   # urgent send
tproj-msg --role-handoff --new-task \
  --role-epoch 7 --orchestrator project.cdx \
  project.cdx "Plan and delegate this request"
```

Role handoff is never force-delivered. A typing or otherwise blocked target receives the complete envelope through the deferred queue, while existing `--new-task` and `[ACK:]` / `[DONE:]` / `[BLOCK:]` flows remain compatible. Queue storage encodes multiline bodies as a single record and continues to read legacy plain-text records.

## Requirements

- tmux (included with tproj core)
- Optional: `websocat` plus `timeout`/`gtimeout` (GNU coreutils) for WebSocket-based idle detection; without them the tmux prompt heuristic is used

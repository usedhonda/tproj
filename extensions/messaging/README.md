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

## Usage

```bash
tproj-msg <target> "message"          # send to a pane
tproj-msg --status <target>           # check if target is idle
tproj-msg --list                      # list available targets
tproj-msg --fire <target> "message"   # urgent send
```

## Requirements

- tmux (included with tproj core)
- Optional: `websocat` plus `timeout`/`gtimeout` (GNU coreutils) for WebSocket-based idle detection; without them the tmux prompt heuristic is used

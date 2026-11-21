# memory

Memory monitoring and watchdog daemon for tproj workspaces.

**Note:** This extension is not installed by default. Use `--with-memory` or `--all`.

## What's included

- **cc-mem** -- Real-time memory monitoring for Claude Code, Codex, MCP servers, and system
- **memory-guard** -- Background daemon that reports high process memory usage
- **tproj-mem-json** -- JSON memory snapshot exporter for programmatic consumption

## Why opt-in?

memory-guard runs as a macOS launchd daemon (always-on background process). This requires explicit opt-in since it continuously monitors process memory and sends notifications.

## Usage

Aggregate-memory notifications occur once on entering a warning episode and
once if it escalates to critical. Oscillation between warning and critical does
not repeat notifications until usage falls below the warning threshold. Each individual
process also triggers one alert per threshold crossing. The daemon records
memory history and sends alerts without terminating processes. Restarting the
daemon begins a new notification episode. Alerts use the tproj pane's project
name when the process can be traced to a pane. Claude totals show the three
largest memory entries, including an unknown-project entry for processes
without a matching pane.

```bash
cc-mem              # interactive memory monitor
cc-mem --watch      # continuous watch mode
cc-mem --log        # view history
cc-mem --json       # JSON output
```

## Requirements

- macOS (uses `vm_stat`, `sysctl`, `launchctl`)
- `python3` (for tproj-mem-json)

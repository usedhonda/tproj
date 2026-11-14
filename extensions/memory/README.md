# memory

Memory monitoring and watchdog daemon for tproj workspaces.

**Note:** This extension is not installed by default. Use `--with-memory` or `--all`.

## What's included

- **cc-mem** -- Real-time memory monitoring for Claude Code, Codex, MCP servers, and system
- **memory-guard** -- Background daemon that kills runaway processes and orphaned Claude instances
- **tproj-mem-json** -- JSON memory snapshot exporter for programmatic consumption

## Why opt-in?

memory-guard runs as a macOS launchd daemon (always-on background process). This requires explicit opt-in since it actively monitors and can terminate processes.

## Usage

Aggregate-memory notifications occur once on entering a warning episode and
once if it escalates to critical. Oscillation between warning and critical does
not repeat notifications until usage falls below the warning threshold. Logs,
monitoring frequency and process-termination policy are unchanged. Restarting
the daemon begins a new notification episode.

```bash
cc-mem              # interactive memory monitor
cc-mem --watch      # continuous watch mode
cc-mem --log        # view history
cc-mem --json       # JSON output
```

## Requirements

- macOS (uses `vm_stat`, `sysctl`, `launchctl`)
- `python3` (for tproj-mem-json)

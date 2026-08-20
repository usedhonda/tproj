# crew

Claude Code Crew pane management for tproj.

## What's included

- **crew-watcher** -- Hook-based daemon that manages Crew pane lifecycle
- **reflow-crew-pane** -- Repositions crew panes when Claude Code spawns new splits
- **crew-monitor** -- Per-agent status display

## How it works

When Claude Code creates Crew (teammates), it splits new tmux panes. crew-watcher sets up a tmux `after-split-window` hook to intercept these splits and reposition them using reflow-crew-pane.

## Requirements

- Claude Code with Crew support (`teammateMode: "tmux"` in settings)
- tmux (included with tproj core)

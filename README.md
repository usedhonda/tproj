# tproj

A tmux-based workspace launcher for [Claude Code](https://github.com/anthropics/claude-code) and [Codex](https://github.com/openai/codex).

Spin up a structured terminal layout with Claude Code, Codex, and yazi side by side for any project.

## Features

- **Single-project mode** -- 3-pane layout: Claude Code + Codex + yazi
- **Multi-project mode** -- column-based workspace across multiple projects
- **Native macOS GUI** -- SwiftUI controller app with session management
- **Remote SSH** -- launch the same layout on a remote host
- **Workspace config** -- YAML-driven project management with aliases and per-project settings

## Requirements

```bash
brew install git tmux yazi bat yq node
npm install -g @anthropic-ai/claude-code @openai/codex
```

## Install

```bash
git clone https://github.com/usedhonda/tproj.git
cd tproj
./install.sh
```

The installer places scripts in `~/bin` and configuration under `~/.config`.

## Usage

```bash
# Single-project mode (default)
cd /path/to/your/project
tproj

# Force single-project mode
tproj --single

# Remote host
tproj --remote <host>

# Graceful shutdown
tproj stop

# Force kill
tproj kill
```

## Multi-project workspace

Create a workspace config to manage multiple projects:

```bash
mkdir -p ~/.config/tproj
cp config/workspace.yaml.example ~/.config/tproj/workspace.yaml
```

Edit the file to list your projects, then run `tproj`:

```yaml
projects:
  - path: /Users/you/projects/frontend
    alias: fe

  - path: /Users/you/projects/backend
    alias: be

  - path: /Users/you/projects/infra
    alias: infra
    enabled: false   # available via --add but not started by default
```

### Workspace commands

```bash
tproj                 # start workspace (auto-detects workspace.yaml)
tproj --check         # show configured projects and status
tproj --add           # duplicate current column
tproj --add <alias>   # add a disabled project by alias
tproj --columns 3     # start only the first 3 projects
```

See `config/workspace.yaml.example` for the full field reference.

## GUI App (macOS)

A native SwiftUI app for session control and monitoring.

```bash
cd apps/tproj
swift build
./build-app.sh       # creates dist/tproj.app
open dist/tproj.app
```

The GUI auto-launches when `tproj` starts a session. Configure `gui.app_path` in `workspace.yaml` to pin a specific build.

## Extension hooks

tproj supports hooks for customization:

| Environment variable | Purpose | Example |
|---------------------|---------|---------|
| `TPROJ_LABEL_HOOK` | Custom pane label generator | `export TPROJ_LABEL_HOOK=my-label-script` |
| `TPROJ_GUI_APP_PATH` | Override GUI app location | `export TPROJ_GUI_APP_PATH=~/Apps/tproj.app` |

### `TPROJ_LABEL_HOOK`

When set, tproj calls `$TPROJ_LABEL_HOOK --label <project_path> <cc|cdx>` to generate a suffix for pane titles. This lets you add persona labels, status indicators, or any custom text to your pane titles.

## Repository layout

```
bin/
  tproj                        # main launcher
  tproj-drop-column             # batch column removal
  tproj-toggle-yazi             # yazi pane toggle
  rebalance-workspace-columns   # column width equalizer
  reflow-agent-pane             # Agent Teams pane repositioner
  team-watcher                  # Agent Teams hook daemon
  agent-monitor                 # per-agent status display
  sign-codex                    # macOS code signing for Codex
  wait-for-pane-text            # wait for text in a tmux pane
config/
  tmux/tmux.conf                # tmux configuration
  terminfo/                     # terminal capability files
  yazi/                         # yazi file manager config
  workspace.yaml.example        # workspace template
apps/tproj/                     # SwiftUI GUI app source
```

## Notes

- tproj does not run `npm update` automatically. Update manually when needed:
  ```bash
  npm update -g @anthropic-ai/claude-code @openai/codex
  ```
- For heavy multi-pane usage in Ghostty, consider lowering `scrollback-limit` (e.g. `3000`) to reduce memory pressure.

## License

MIT

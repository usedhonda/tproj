# tproj

`tproj` is a tmux-based AI development workspace optimized for Claude Code, Codex, and yazi.

## Highlights

- Structured AI terminal layout for daily coding
- Single-project and multi-project workspace modes
- Per-pane communication tool (`tproj-msg`)
- Built-in memory tooling (`cc-mem`, `memory-guard`, `tproj-mem-json`)
- Native macOS SwiftUI controller app (`apps/tproj`)

## Requirements

Install dependencies:

```bash
brew install git tmux yazi bat yq node
npm install -g @anthropic-ai/claude-code @openai/codex
```

## Quick Start

```bash
git clone https://github.com/usedhonda/tproj.git
cd tproj
./install.sh

cd /path/to/your/project
tproj
```

The installer places tools in `~/bin` and installs configuration under `~/.config`.

## CLI Usage

### Main commands

```bash
tproj                 # auto-detect mode (workspace or single-project)
tproj stop            # graceful shutdown for active tproj sessions
tproj kill            # force kill tproj sessions
tproj --help          # full command reference
```

### Common options

```bash
tproj --single
tproj --remote <host>
tproj --check
tproj --add [alias]
tproj --columns <N>
```

## Modes

### Single-project mode

- Default mode when no workspace config exists
- Opens Claude Code, Codex, and yazi panes in one project

### Multi-project mode

- Enabled when `~/.config/tproj/workspace.yaml` exists
- Runs a column-based workspace across multiple projects
- Start with `config/workspace.yaml.example` as a template

## GUI App (macOS)

Single-source runtime rule:

- Launch only `apps/tproj/dist/tproj.app` (no `~/bin/tproj-gui`, no direct `.build/.../debug/tproj` launch).
- Rebuild the `.app` before launching after Swift source changes.

Recommended development command:

```bash
cd apps/tproj
./dev-app.sh
```

### Run in development

```bash
cd apps/tproj
swift run tproj
```

### Build `.app`

```bash
cd apps/tproj
./build-app.sh
open dist/tproj.app
```

### Release DMG

```bash
cd apps/tproj
./scripts/release.sh
```

### Publish GitHub release

```bash
cd apps/tproj
./scripts/release.sh --publish --bump patch
```

Release script options:

- `--skip-notarize`
- `--publish`
- `--bump patch|minor|major`

## Repository Layout

- `bin/tproj`: primary launcher
- `bin/tproj-msg`: inter-pane messaging helper
- `bin/cc-mem`: memory monitor CLI
- `bin/memory-guard`: launchd memory guard process
- `bin/tproj-mem-json`: merged monitor JSON collector
- `config/workspace.yaml.example`: workspace configuration template
- `apps/tproj`: SwiftUI desktop app source

## Notes

- `tproj` intentionally does not run npm global updates automatically.
- Update manually when needed:

```bash
npm update -g @anthropic-ai/claude-code @openai/codex
```

## License

MIT

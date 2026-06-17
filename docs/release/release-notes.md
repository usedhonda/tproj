# Release Notes

tproj is distributed **from source**. To install, see the [README](../../README.md):

```bash
git clone https://github.com/usedhonda/tproj.git
cd tproj
./install.sh
tproj init
```

This file tracks notable changes per tagged version.

## v0.1.0

### Setup
- `tproj init` — interactive setup: dependency check, `workspace.yaml` generation, Claude Code hooks configuration
- `tproj --check` — comprehensive health check with version info

### GUI
- Individual collapsible sections (Memory / CC & Codex)
- Window size persistence across restarts
- Diagonal resize blocked when snapped to Ghostty
- Functional bottom resize grip
- Removed Cmd+Q shortcut (prevents accidental quit)

### Persona System
- CC-specific feminine tone pool (丁寧, 感情的, 甘え, 気まぐれ, おっとり, 毒舌)
- New character types (お嬢様系, じゃじゃ馬系, 甘えん坊系, ヤンデレ系)
- Profession system for CC and Cdx (巫女, ナース, メイド, 歌姫, etc.)
- Expanded ERA pool with future variants (電脳都市, 蒸気未来, 深海都市, 軌道コロニー)

### Bug Fixes
- Pane background images not appearing for newly added projects
- Window size force-reverting on every SwiftUI redraw

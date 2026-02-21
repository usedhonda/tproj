# tproj (SwiftUI)

Native macOS app for controlling and monitoring `tproj` workspaces.

## Development Run

```bash
cd apps/tproj
swift run tproj
```

## Runtime Rule: Single GUI Artifact

To avoid stale UI and duplicate binaries, runtime must use only `apps/tproj/dist/tproj.app`.

Forbidden for normal launch:

- `apps/tproj/.build/.../debug/tproj`
- `~/bin/tproj-gui`

After code changes, always rebuild `.app` and relaunch:

```bash
cd apps/tproj
./dev-app.sh
```

To make `tproj` always launch this development app from any project:

```bash
cd apps/tproj
./dev-setup.sh
```

`dev-setup.sh` does three things:

1. build + launch `dist/tproj.app`
2. sync latest `bin/tproj` into `~/bin/tproj`
3. set `~/.config/tproj/workspace.yaml` -> `gui.app_path`

Verification rule:

- Only one `tproj` GUI process should be running.
- The running process must be `apps/tproj/dist/tproj.app/Contents/MacOS/tproj`.

## Recommended Development Command

Use this as the normal development flow:

```bash
cd apps/tproj
./dev-app.sh
```

This command runs:

1. `build-app.sh`
2. stop previous GUI process
3. `open -ga dist/tproj.app`

## Build `.app`

```bash
cd apps/tproj
./build-app.sh
open dist/tproj.app
```

Output:

- `apps/tproj/dist/tproj.app`

## Build Distribution DMG

```bash
cd apps/tproj
./scripts/release.sh
```

Output:

- `apps/tproj/dist/release/tproj.dmg`

Before running release, create `apps/tproj/.local/release.md` with signing and notarization values.

## Runtime Dependencies

- `tmux`
- `tproj` CLI
- `yq` (workspace config parsing)
- `tproj-mem-json` (merged monitor JSON input)

## Shared Monitor Output

The app periodically writes monitor status to:

- `/tmp/tproj-monitor-status.json`

Other CC/Codex panes can read this JSON to observe the same live monitor state.

## Layout Action Log

Topology mutations (`Add` / `Drop` / reorder / terminal toggle) append action logs to:

- `/tmp/tproj-layout-actions.log`

Quick check:

```bash
tail -f /tmp/tproj-layout-actions.log
```

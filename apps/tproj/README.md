# tproj (SwiftUI)

Native macOS app for controlling and monitoring `tproj` workspaces.

## Development Run

## Runtime Rule: Current SwiftPM GUI

The development launcher uses SwiftPM's current `.build/debug/tproj` artifact.
The legacy `.build/arm64-apple-macosx/debug/tproj` and old `dist/tproj.app`
artifacts are not auto-selected. Use the wrapper for development launches:

```bash
cd apps/tproj
./dev-app.sh
```

To make `tproj` always launch this development app from any project:

```bash
cd apps/tproj
./dev-setup.sh
```

`dev-setup.sh` does two things:

1. build + launch the current SwiftPM debug GUI
2. sync latest `bin/tproj` into `~/bin/tproj`

Verification rule:

- Only one `tproj` GUI process should be running.
- The running process must be `apps/tproj/.build/debug/tproj` (or its SwiftPM-resolved target).

## Recommended Development Command

Use this as the normal development flow:

```bash
cd apps/tproj
./dev-app.sh
```

This command runs:

1. `swift build`
2. launch the new GUI and confirm its process is alive
3. retire only the previous GUI PID, leaving tmux and agent panes untouched

## Build `.app`

```bash
cd apps/tproj
./build-app.sh
open dist/tproj.app
```

Output:

- `apps/tproj/dist/tproj.app`

## Build Distribution DMG

> **Maintainer-only.** Signing, notarization, and Homebrew tap publishing are part of the maintainer release pipeline. Regular users and contributors only need `./dev-app.sh` or `./build-app.sh` above.

```bash
cd apps/tproj
./scripts/release.sh
```

Output:

- `apps/tproj/dist/release/tproj.dmg`

DMG contents:

- `tproj.app`
- `Install tproj.command`
- `README-QuickStart.txt`
- `tproj-cli-payload.tar.gz`

Before running release, create `apps/tproj/.local/release.md` with signing and notarization values.

## Runtime Dependencies

- `tmux`
- `tproj` CLI
- `yq` (workspace config parsing)
- `tproj-mem-json` (optional; Memory section only — installed via the memory extension with `./install.sh --with-memory` or `--all`)

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

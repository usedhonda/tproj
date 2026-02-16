# tproj (SwiftUI)

Native macOS app for controlling and monitoring `tproj` workspaces.

## Development Run

```bash
cd apps/tproj
swift run tproj
```

## Development Rule: Always Restart After Code Changes

When you change Swift sources, do not stop at build. Always restart the development app process so the running UI reflects the latest binary.

```bash
pkill -f 'tproj-gui' || true
pkill -f '.build/arm64-apple-macosx/debug/tproj' || true
cd apps/tproj
swift build
./.build/arm64-apple-macosx/debug/tproj &
```

Verification rule:

- Only one `tproj` GUI process should be running.
- The running process must be `apps/tproj/.build/.../tproj` (development binary), not `dist/tproj.app`.

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

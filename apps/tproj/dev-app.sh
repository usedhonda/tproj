#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="$SCRIPT_DIR/dist/tproj.app"
DEBUG_BIN="$SCRIPT_DIR/.build/arm64-apple-macosx/debug/tproj"
MODE="debug"

if [[ "${1:-}" == "--release" ]]; then
  MODE="release"
fi

# --- Build ---
if [[ "$MODE" == "debug" ]]; then
  echo "==> Build app (debug)"
  pushd "$SCRIPT_DIR" >/dev/null
  swift build
  popd >/dev/null
else
  echo "==> Build app (release)"
  "$SCRIPT_DIR/build-app.sh"
fi

# --- Stop ALL previous GUI processes (dist + .build + tproj-gui) ---
echo "==> Stop previous GUI processes"
pkill -f 'apps/tproj/dist/tproj.app/Contents/MacOS/tproj|\.build/.*/tproj$|tproj-gui' 2>/dev/null || true
sleep 0.3

# --- Launch ---
if [[ "$MODE" == "debug" ]]; then
  echo "==> Launch app (debug)"
  "$DEBUG_BIN" &
  sleep 1
  if ! pgrep -f '\.build/.*/tproj$' >/dev/null 2>&1; then
    echo "debug process not detected; check build output" >&2
    exit 1
  fi
  echo "Done: $DEBUG_BIN (pid $(pgrep -f '\.build/.*/tproj$'))"
else
  echo "==> Launch app (release)"
  if ! open -ga "$APP_BUNDLE"; then
    echo "open -ga failed; retrying with open -na" >&2
    open -na "$APP_BUNDLE"
  fi
  sleep 1
  if ! pgrep -f 'apps/tproj/dist/tproj.app/Contents/MacOS/tproj' >/dev/null 2>&1; then
    echo "app process not detected after open -ga; retrying with open -na" >&2
    open -na "$APP_BUNDLE"
  fi
  echo "Done: $APP_BUNDLE"
fi

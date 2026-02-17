#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="$SCRIPT_DIR/dist/tproj.app"

echo "==> Build app"
"$SCRIPT_DIR/build-app.sh"

echo "==> Stop previous GUI processes"
pkill -f 'apps/tproj/dist/tproj.app/Contents/MacOS/tproj|\.build/.*/tproj$|tproj-gui' 2>/dev/null || true

echo "==> Launch app"
open -ga "$APP_BUNDLE"

echo "Done: $APP_BUNDLE"

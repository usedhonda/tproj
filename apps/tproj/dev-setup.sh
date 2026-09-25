#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Build and launch development app"
"$SCRIPT_DIR/dev-app.sh"

echo "==> Sync launcher script"
mkdir -p "$HOME/bin"
cp "$REPO_ROOT/bin/tproj" "$HOME/bin/tproj"
chmod +x "$HOME/bin/tproj"

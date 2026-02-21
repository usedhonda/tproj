#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_BUNDLE="$SCRIPT_DIR/dist/tproj.app"
WORKSPACE_CONFIG="$HOME/.config/tproj/workspace.yaml"

echo "==> Build and launch development app"
"$SCRIPT_DIR/dev-app.sh"

echo "==> Sync launcher script"
mkdir -p "$HOME/bin"
cp "$REPO_ROOT/bin/tproj" "$HOME/bin/tproj"
chmod +x "$HOME/bin/tproj"

if [[ ! -f "$WORKSPACE_CONFIG" ]]; then
  echo "warning: workspace config not found: $WORKSPACE_CONFIG"
  echo "         skipped gui.app_path setup"
  exit 0
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "warning: yq not found; skipped gui.app_path setup"
  echo "         install: brew install yq"
  exit 0
fi

echo "==> Set gui.app_path in workspace config"
yq -i ".gui.app_path = \"$APP_BUNDLE\"" "$WORKSPACE_CONFIG"
echo "Done: gui.app_path -> $APP_BUNDLE"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"
APP_NAME="tproj"
BUNDLE_ID="com.usedhonda.tproj.desktop"
APP_VERSION="${APP_VERSION:-0.1.0}"
BUNDLE_VERSION="${BUNDLE_VERSION:-1}"
BUILD_DIR="$ROOT_DIR/.build/release"
DIST_DIR="$ROOT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RES_DIR="$CONTENTS_DIR/Resources"
BIN_SRC="$BUILD_DIR/tproj"
BIN_DST="$MACOS_DIR/$APP_NAME"
ICON_SRC="$ROOT_DIR/Resources/AppIcon.icns"
MONITOR_HELPERS=(
  "$REPO_ROOT/bin/tproj-mem-json"
  "$REPO_ROOT/bin/cc-mem"
)

mkdir -p "$DIST_DIR"

pushd "$ROOT_DIR" >/dev/null
swift build -c release
popd >/dev/null

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RES_DIR"
cp "$BIN_SRC" "$BIN_DST"
chmod +x "$BIN_DST"

if [[ -f "$ICON_SRC" ]]; then
  cp "$ICON_SRC" "$RES_DIR/AppIcon.icns"
fi

for helper in "${MONITOR_HELPERS[@]}"; do
  if [[ -f "$helper" ]]; then
    cp "$helper" "$RES_DIR/$(basename "$helper")"
    chmod +x "$RES_DIR/$(basename "$helper")"
  else
    echo "warning: monitor helper not found: $helper" >&2
  fi
done

cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon.icns</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$APP_VERSION</string>
  <key>CFBundleVersion</key>
  <string>$BUNDLE_VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

# ad-hoc sign to reduce launch friction on local machine
codesign --force --deep --sign - "$APP_DIR" >/dev/null 2>&1 || true

echo "Built app: $APP_DIR"
echo "Run: open '$APP_DIR'"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
RELEASE_DIR="$APP_DIR/dist/release"
APP_NAME="tproj"
APP_BUNDLE="$RELEASE_DIR/$APP_NAME.app"
PAYLOAD_TAR="$RELEASE_DIR/tproj-cli-payload.tar.gz"
DMG_PATH="$RELEASE_DIR/$APP_NAME.dmg"
DMG_STAGING="$(mktemp -d /tmp/tproj-dmg-staging.XXXXXX)"
SKIP_NOTARIZE=false

for arg in "$@"; do
  case "$arg" in
    --skip-notarize)
      SKIP_NOTARIZE=true
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: ./scripts/release.sh [--skip-notarize]"
      exit 1
      ;;
  esac
done

cleanup() {
  rm -rf "$DMG_STAGING"
}
trap cleanup EXIT

if [[ -f "$APP_DIR/.local/release.md" ]]; then
  # shellcheck disable=SC1091
  source "$APP_DIR/.local/release.md"
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1"
    exit 1
  fi
}

require_env() {
  if [[ -z "${!1:-}" ]]; then
    echo "Missing required variable: $1"
    exit 1
  fi
}

require_cmd swift
require_cmd hdiutil
require_cmd codesign
require_cmd xcrun
require_cmd tar

require_env SIGNING_ID
if ! $SKIP_NOTARIZE; then
  if [[ -z "${NOTARY_PROFILE:-}" ]]; then
    require_env APPLE_ID
    require_env TEAM_ID
    require_env APP_PASSWORD
  fi
fi

echo "==> Build app"
"$APP_DIR/build-app.sh"

echo "==> Prepare release directory"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
cp -R "$APP_DIR/dist/$APP_NAME.app" "$APP_BUNDLE"

echo "==> Sign app binaries"
if [[ -d "$APP_BUNDLE/Contents/Resources" ]]; then
  while IFS= read -r -d '' bin; do
    codesign --force --options runtime --sign "$SIGNING_ID" "$bin"
  done < <(find "$APP_BUNDLE/Contents/Resources" -type f -perm -111 -print0)
fi
codesign --force --options runtime --sign "$SIGNING_ID" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"

echo "==> Sign app bundle"
codesign --force --options runtime --sign "$SIGNING_ID" "$APP_BUNDLE"
codesign --verify --strict --verbose=2 "$APP_BUNDLE"

echo "==> Package CLI payload"
"$ROOT_DIR/scripts/package-cli-payload.sh" "$PAYLOAD_TAR"

echo "==> Create installer launcher"
cat > "$RELEASE_DIR/Install tproj.command" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$(mktemp -d /tmp/tproj-install.XXXXXX)"
LOG_FILE="/tmp/tproj-install-$(date +%Y%m%d_%H%M%S).log"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "tproj installer started"
echo "log: $LOG_FILE"

{
  tar -xzf "$SELF_DIR/tproj-cli-payload.tar.gz" -C "$WORK_DIR"
  cd "$WORK_DIR/tproj-cli-payload"
  ./install.sh -y
} | tee "$LOG_FILE"

echo
echo "Install complete."
echo "Open a new terminal and run: tproj --check"
EOF
chmod +x "$RELEASE_DIR/Install tproj.command"

cp "$SCRIPT_DIR/README-QuickStart.txt" "$RELEASE_DIR/README-QuickStart.txt"

echo "==> Build DMG staging"
cp -R "$APP_BUNDLE" "$DMG_STAGING/"
cp "$RELEASE_DIR/Install tproj.command" "$DMG_STAGING/"
cp "$RELEASE_DIR/README-QuickStart.txt" "$DMG_STAGING/"
cp "$PAYLOAD_TAR" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

echo "==> Create DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH"

echo "==> Sign DMG"
codesign --force --sign "$SIGNING_ID" "$DMG_PATH"

if $SKIP_NOTARIZE; then
  echo "==> Skip notarize/staple (--skip-notarize)"
else
  echo "==> Notarize DMG"
  if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARY_PROFILE" --wait --timeout 900
  else
    xcrun notarytool submit "$DMG_PATH" \
      --apple-id "$APPLE_ID" \
      --team-id "$TEAM_ID" \
      --password "$APP_PASSWORD" \
      --wait --timeout 900
  fi

  echo "==> Staple"
  xcrun stapler staple "$DMG_PATH"

  echo "==> Verify notarization"
  xcrun stapler validate "$DMG_PATH"
  spctl --assess --type open --context context:primary-signature --verbose "$DMG_PATH"
fi

echo
echo "Release artifact:"
echo "  $DMG_PATH"

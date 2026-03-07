#!/usr/bin/env bash
# tproj Release Script
#
# Usage:
#   ./scripts/release.sh
#   ./scripts/release.sh --skip-notarize
#   ./scripts/release.sh --publish --notes-file docs/release/release-notes.md
#
# Required env vars:
#   APPLE_ID
#   APPLE_TEAM_ID  (fallback: TEAM_ID)
#   APPLE_ID_PASSWORD  (fallback: APP_PASSWORD)
#   SIGNING_ID

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
APP_NAME="tproj"
APP_BUNDLE="$APP_DIR/dist/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
ENTITLEMENTS_PATH="$APP_DIR/tproj.entitlements"
DEFAULT_RELEASE_ROOT="/tmp/tproj-release"
RELEASE_ROOT="${RELEASE_ROOT:-$DEFAULT_RELEASE_ROOT}"
DIST_RELEASE_DIR="$APP_DIR/dist/release"

PUBLISH=false
SKIP_NOTARIZE=false
RELEASE_NOTES_FILE="${RELEASE_NOTES_FILE:-docs/release/release-notes.md}"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/release.sh
  ./scripts/release.sh --skip-notarize
  ./scripts/release.sh --publish --notes-file docs/release/release-notes.md

Options:
  --skip-notarize          Skip notarization and stapling
  --publish                Create GitHub release after successful notarization
  --notes-file <path>      Markdown release notes file (required for --publish)
  -h, --help               Show this help

Required environment variables:
  APPLE_ID
  APPLE_TEAM_ID  (fallback: TEAM_ID)
  APPLE_ID_PASSWORD  (fallback: APP_PASSWORD)
  SIGNING_ID
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-notarize)
      SKIP_NOTARIZE=true
      shift
      ;;
    --publish)
      PUBLISH=true
      shift
      ;;
    --notes-file)
      if [[ $# -lt 2 ]]; then
        echo -e "${RED}Error: --notes-file requires a path${NC}" >&2
        exit 1
      fi
      RELEASE_NOTES_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo -e "${RED}Error: Unknown argument: $1${NC}" >&2
      usage
      exit 1
      ;;
  esac
done

# Env var compatibility: APPLE_TEAM_ID / TEAM_ID, APPLE_ID_PASSWORD / APP_PASSWORD
APPLE_TEAM_ID="${APPLE_TEAM_ID:-${TEAM_ID:-}}"
APPLE_ID_PASSWORD="${APPLE_ID_PASSWORD:-${APP_PASSWORD:-}}"
export APPLE_TEAM_ID APPLE_ID_PASSWORD

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo -e "${RED}Error: required command not found: $cmd${NC}" >&2
    exit 1
  fi
}

require_env() {
  local key="$1"
  if [[ -z "${!key:-}" ]]; then
    echo -e "${RED}Error: required env var missing: $key${NC}" >&2
    exit 1
  fi
}

require_clean_worktree() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo -e "${RED}Error: git worktree is dirty. Commit or stash before --publish.${NC}" >&2
    git status --short >&2
    exit 1
  fi
}

# Load credentials
if [[ -f "$APP_DIR/.local/release.md" ]]; then
  # shellcheck disable=SC1091
  source "$APP_DIR/.local/release.md"
  # Re-apply fallbacks after sourcing
  APPLE_TEAM_ID="${APPLE_TEAM_ID:-${TEAM_ID:-}}"
  APPLE_ID_PASSWORD="${APPLE_ID_PASSWORD:-${APP_PASSWORD:-}}"
fi

cd "$APP_DIR"

require_command swift
require_command xcrun
require_command codesign
require_command hdiutil
require_command plutil
require_command shasum
require_command python3
require_command lipo
if [[ "$PUBLISH" == "true" ]]; then
  require_command gh
fi

require_env SIGNING_ID
if ! $SKIP_NOTARIZE; then
  require_env APPLE_ID
  require_env APPLE_TEAM_ID
  require_env APPLE_ID_PASSWORD
fi

if [[ "$PUBLISH" == "true" ]]; then
  require_clean_worktree
fi

if [[ "$PUBLISH" == "true" ]]; then
  TOTAL_STEPS=9
else
  TOTAL_STEPS=8
fi

BUILD_STAMP="$(date +%Y%m%d-%H%M%S)"
WORK_DIR="${RELEASE_ROOT}/${BUILD_STAMP}"
DMG_PATH="${WORK_DIR}/${APP_NAME}.dmg"
DMG_STAGING="${WORK_DIR}/dmg-contents"
DMG_MOUNT="${WORK_DIR}/dmg-mount"
CLI_PAYLOAD_DIR="${WORK_DIR}/tproj-cli-payload"
CLI_PAYLOAD_ARCHIVE="${WORK_DIR}/tproj-cli-payload.tar.gz"
INSTALLER_PATH="${WORK_DIR}/Install tproj.command"
QUICKSTART_PATH="${WORK_DIR}/README-QuickStart.txt"
NOTARY_JSON="${WORK_DIR}/notary-submit.json"
MANIFEST_PATH="${WORK_DIR}/${APP_NAME}-release-manifest.json"
ENTITLEMENTS_EXTRACT="${WORK_DIR}/entitlements.plist"

mkdir -p "$WORK_DIR"

echo -e "${GREEN}=== tproj Release ===${NC}"
echo ""

# --- Step 1: Build app ---
echo -e "${GREEN}[1/${TOTAL_STEPS}] Building app (universal binary)...${NC}"
"$APP_DIR/build-app.sh"

VERSION="$(plutil -extract CFBundleShortVersionString raw "$APP_BUNDLE/Contents/Info.plist")"
GIT_SHA="$(git rev-parse HEAD)"
GIT_REF="$(git rev-parse --abbrev-ref HEAD)"

echo "Version: ${YELLOW}${VERSION}${NC}"
echo "Git SHA: ${YELLOW}${GIT_SHA}${NC}"
echo "Artifacts: ${YELLOW}${WORK_DIR}${NC}"

APP_ARCHS="$(lipo -archs "$APP_BINARY")"
echo "Binary arch: ${APP_ARCHS}"
echo -e "${GREEN}Build complete${NC}"
echo

# --- Step 2: Sign app ---
echo -e "${GREEN}[2/${TOTAL_STEPS}] Signing and verifying app...${NC}"
codesign --force --deep --options runtime \
  --identifier com.usedhonda.tproj.desktop \
  --entitlements "$ENTITLEMENTS_PATH" \
  --sign "$SIGNING_ID" \
  "$APP_BUNDLE"
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
SIGN_INFO="$(codesign -dv --verbose=4 "$APP_BUNDLE" 2>&1)"
SIGN_AUTHORITY="$(awk -F= '/^Authority=/{print $2; exit}' <<< "$SIGN_INFO")"
if [[ -z "$SIGN_AUTHORITY" ]]; then
  SIGN_AUTHORITY="$SIGNING_ID"
fi
codesign -d --entitlements :- "$APP_BUNDLE" > "$ENTITLEMENTS_EXTRACT" 2>/dev/null || cp "$ENTITLEMENTS_PATH" "$ENTITLEMENTS_EXTRACT"
APP_SHA256="$(shasum -a 256 "$APP_BINARY" | awk '{print $1}')"
ENTITLEMENTS_SHA256="$(shasum -a 256 "$ENTITLEMENTS_EXTRACT" | awk '{print $1}')"
echo -e "${GREEN}App signing verified${NC}"
echo

# --- Step 3: Create and verify DMG ---
echo -e "${GREEN}[3/${TOTAL_STEPS}] Preparing release payload and creating DMG...${NC}"
rm -rf "$DMG_STAGING" "$DMG_MOUNT" "$CLI_PAYLOAD_DIR"
mkdir -p "$DMG_STAGING" "$DMG_MOUNT" "$CLI_PAYLOAD_DIR" "$DIST_RELEASE_DIR"

cp "$REPO_ROOT/install.sh" "$CLI_PAYLOAD_DIR/install.sh"
cp "$REPO_ROOT/README.md" "$CLI_PAYLOAD_DIR/README.md"
cp -R "$REPO_ROOT/bin" "$CLI_PAYLOAD_DIR/bin"
cp -R "$REPO_ROOT/config" "$CLI_PAYLOAD_DIR/config"
find "$CLI_PAYLOAD_DIR" -name '.DS_Store' -delete
tar -C "$WORK_DIR" -czf "$CLI_PAYLOAD_ARCHIVE" "$(basename "$CLI_PAYLOAD_DIR")"

cat > "$INSTALLER_PATH" <<'EOF'
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
chmod +x "$INSTALLER_PATH"

cat > "$QUICKSTART_PATH" <<'EOF'
tproj Quick Start
=================

This DMG includes:
- tproj.app (GUI)
- Install tproj.command (CLI + config installer)
- README-QuickStart.txt
- tproj-cli-payload.tar.gz

Recommended steps:
1) Drag tproj.app to Applications
2) Run "Install tproj.command"
3) Open a new terminal
4) Run: tproj --check
5) Configure ~/.config/tproj/workspace.yaml if needed
6) Launch GUI: open /Applications/tproj.app

Notes:
- The installer checks core dependencies.
- yazi plugin install is best-effort. If it fails:
  cd ~/.config/yazi && ya pack -i
- If you already have local settings, install.sh creates backups.
- The payload archive is included so the installer can run entirely from this DMG.
EOF

cp -R "$APP_BUNDLE" "$DMG_STAGING/"
cp "$INSTALLER_PATH" "$DMG_STAGING/"
cp "$QUICKSTART_PATH" "$DMG_STAGING/"
cp "$CLI_PAYLOAD_ARCHIVE" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH" >/dev/null

# --- Step 4: Sign DMG ---
echo -e "${GREEN}[4/${TOTAL_STEPS}] Signing DMG...${NC}"
codesign --force --sign "$SIGNING_ID" "$DMG_PATH"
codesign --verify --verbose=2 "$DMG_PATH"
echo -e "${GREEN}DMG signed${NC}"
echo

# --- Step 5: Verify DMG payload ---
echo -e "${GREEN}[5/${TOTAL_STEPS}] Verifying DMG payload...${NC}"
hdiutil attach "$DMG_PATH" -readonly -nobrowse -mountpoint "$DMG_MOUNT" >/dev/null
DMG_APP_BINARY="${DMG_MOUNT}/${APP_NAME}.app/Contents/MacOS/${APP_NAME}"
DMG_INSTALLER="${DMG_MOUNT}/Install tproj.command"
DMG_QUICKSTART="${DMG_MOUNT}/README-QuickStart.txt"
DMG_PAYLOAD="${DMG_MOUNT}/tproj-cli-payload.tar.gz"
if [[ ! -f "$DMG_APP_BINARY" ]]; then
  echo -e "${RED}Error: DMG payload missing app binary: $DMG_APP_BINARY${NC}" >&2
  hdiutil detach "$DMG_MOUNT" -quiet >/dev/null 2>&1 || true
  exit 1
fi
for required_path in "$DMG_INSTALLER" "$DMG_QUICKSTART" "$DMG_PAYLOAD"; do
  if [[ ! -f "$required_path" ]]; then
    echo -e "${RED}Error: DMG payload missing required artifact: $required_path${NC}" >&2
    hdiutil detach "$DMG_MOUNT" -quiet >/dev/null 2>&1 || true
    exit 1
  fi
done
DMG_APP_SHA256="$(shasum -a 256 "$DMG_APP_BINARY" | awk '{print $1}')"
hdiutil detach "$DMG_MOUNT" -quiet >/dev/null

if [[ "$APP_SHA256" != "$DMG_APP_SHA256" ]]; then
  echo -e "${RED}Error: DMG payload mismatch. Tested app and packaged app differ.${NC}" >&2
  echo "App SHA256: $APP_SHA256" >&2
  echo "DMG SHA256: $DMG_APP_SHA256" >&2
  exit 1
fi
echo -e "${GREEN}DMG payload matches app bundle${NC}"
echo

# --- Step 6: Notarize ---
if $SKIP_NOTARIZE; then
  echo -e "${GREEN}[6/${TOTAL_STEPS}] Notarization skipped (--skip-notarize)${NC}"
  NOTARY_ID="skipped"
  NOTARY_STATUS="skipped"
  echo
else
  echo -e "${GREEN}[6/${TOTAL_STEPS}] Submitting DMG to notarization...${NC}"
  xcrun notarytool submit "$DMG_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_ID_PASSWORD" \
    --wait \
    --output-format json > "$NOTARY_JSON"

  read -r NOTARY_ID NOTARY_STATUS < <(python3 - "$NOTARY_JSON" <<'PY'
import json
import sys

notary_path = sys.argv[1]
with open(notary_path, 'r', encoding='utf-8') as f:
    data = json.load(f)
print(data.get('id', ''), data.get('status', ''))
PY
  )

  if [[ -z "$NOTARY_ID" || -z "$NOTARY_STATUS" ]]; then
    echo -e "${RED}Error: failed to parse notarization response: $NOTARY_JSON${NC}" >&2
    exit 1
  fi

  if [[ "$NOTARY_STATUS" != "Accepted" ]]; then
    echo -e "${RED}Error: notarization status is $NOTARY_STATUS (expected Accepted).${NC}" >&2
    echo "See: $NOTARY_JSON" >&2
    exit 1
  fi

  echo "Notary submission ID: $NOTARY_ID"
  echo -e "${GREEN}Notarization accepted${NC}"
  echo
fi

# --- Step 7: Staple ---
if $SKIP_NOTARIZE; then
  echo -e "${GREEN}[7/${TOTAL_STEPS}] Staple skipped (--skip-notarize)${NC}"
  echo
else
  echo -e "${GREEN}[7/${TOTAL_STEPS}] Stapling and Gatekeeper assess...${NC}"
  xcrun stapler staple "$DMG_PATH"
  spctl --assess --verbose=4 --type install "$DMG_PATH"
  echo -e "${GREEN}Staple + spctl assess passed${NC}"
  echo
fi

# --- Step 8: Manifest ---
echo -e "${GREEN}[8/${TOTAL_STEPS}] Writing release manifest...${NC}"
DMG_SHA256="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export APP_NAME VERSION APP_BUNDLE APP_ARCHS APP_SHA256 SIGN_AUTHORITY
export ENTITLEMENTS_SHA256 DMG_PATH DMG_SHA256 NOTARY_ID NOTARY_STATUS NOTARY_JSON
export GIT_SHA GIT_REF CREATED_AT

python3 - "$MANIFEST_PATH" <<'PY'
import json
import os
import sys

manifest_out = sys.argv[1]
manifest = {
    "app": {
        "name": os.environ["APP_NAME"],
        "version": os.environ["VERSION"],
        "bundle": os.environ["APP_BUNDLE"],
        "binary_arch": os.environ["APP_ARCHS"],
        "binary_sha256": os.environ["APP_SHA256"],
        "signing_authority": os.environ["SIGN_AUTHORITY"],
        "entitlements_sha256": os.environ["ENTITLEMENTS_SHA256"],
    },
    "dmg": {
        "path": os.environ["DMG_PATH"],
        "sha256": os.environ["DMG_SHA256"],
    },
    "notarization": {
        "submission_id": os.environ.get("NOTARY_ID", "skipped"),
        "status": os.environ.get("NOTARY_STATUS", "skipped"),
        "result_json": os.environ.get("NOTARY_JSON", ""),
    },
    "source": {
        "git_sha": os.environ["GIT_SHA"],
        "git_ref": os.environ["GIT_REF"],
    },
    "created_at": os.environ["CREATED_AT"],
}
with open(manifest_out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY

echo "Manifest: $MANIFEST_PATH"
echo -e "${GREEN}Manifest created${NC}"
echo

cp "$INSTALLER_PATH" "$DIST_RELEASE_DIR/Install tproj.command"
cp "$QUICKSTART_PATH" "$DIST_RELEASE_DIR/README-QuickStart.txt"
cp "$CLI_PAYLOAD_ARCHIVE" "$DIST_RELEASE_DIR/tproj-cli-payload.tar.gz"
cp "$DMG_PATH" "$DIST_RELEASE_DIR/${APP_NAME}.dmg"

# --- Step 9: Publish ---
if [[ "$PUBLISH" == "true" ]]; then
  echo -e "${GREEN}[${TOTAL_STEPS}/${TOTAL_STEPS}] Publishing GitHub release...${NC}"
  if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    echo -e "${RED}Error: tag v${VERSION} already exists${NC}" >&2
    exit 1
  fi

  gh release create "v${VERSION}" \
    "$DMG_PATH" \
    "$MANIFEST_PATH" \
    --title "v${VERSION}" \
    --notes-file "$RELEASE_NOTES_FILE"

  echo -e "${GREEN}Published release: v${VERSION}${NC}"
else
  echo -e "${GREEN}Publish skipped${NC}"
  echo "To publish:"
  echo "  ./scripts/release.sh --publish --notes-file ${RELEASE_NOTES_FILE}"
fi

echo
echo -e "${GREEN}=== Release Complete ===${NC}"
echo "Artifacts:"
echo "  DMG:      $DMG_PATH"
if ! $SKIP_NOTARIZE; then
  echo "  Notary:   $NOTARY_JSON"
fi
echo "  Manifest: $MANIFEST_PATH"

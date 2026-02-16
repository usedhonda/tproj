#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_PATH="${1:-$ROOT_DIR/apps/tproj/dist/release/tproj-cli-payload.tar.gz}"
STAGE_DIR="$(mktemp -d /tmp/tproj-cli-payload.XXXXXX)"
PAYLOAD_DIR="$STAGE_DIR/tproj-cli-payload"

cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

mkdir -p "$PAYLOAD_DIR"

cp "$ROOT_DIR/install.sh" "$PAYLOAD_DIR/install.sh"
cp -R "$ROOT_DIR/bin" "$PAYLOAD_DIR/bin"
cp -R "$ROOT_DIR/config" "$PAYLOAD_DIR/config"
cp "$ROOT_DIR/README.md" "$PAYLOAD_DIR/README.md"

mkdir -p "$(dirname "$OUT_PATH")"
tar -czf "$OUT_PATH" -C "$STAGE_DIR" tproj-cli-payload

echo "Created payload: $OUT_PATH"

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

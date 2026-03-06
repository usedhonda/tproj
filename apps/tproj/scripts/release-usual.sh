#!/usr/bin/env bash
#
# Canonical release entrypoint for tproj.
# Loads local release credentials, then executes release.sh.
#
# Usage:
#   ./scripts/release-usual.sh
#   ./scripts/release-usual.sh --skip-notarize
#   ./scripts/release-usual.sh --publish --notes-file docs/release/release-notes.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$APP_DIR/.local/release.md"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing release env file: $ENV_FILE" >&2
  echo "Create it with APPLE_ID / APPLE_TEAM_ID / APPLE_ID_PASSWORD / SIGNING_ID." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"
exec "$SCRIPT_DIR/release.sh" "$@"

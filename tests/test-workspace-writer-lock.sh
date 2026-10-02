#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Two writers must serialize on the exact workspace.yaml.lock directory.
workspace="$TMP/workspace.yaml"
printf 'projects:\n' > "$workspace"

source "$ROOT/bin/lib/tproj-workspace-lock.sh"
tproj_workspace_lock_acquire "$workspace" 1 >/dev/null
held="$(tproj_workspace_lock_path "$workspace")"
if (tproj_workspace_lock_acquire "$workspace" 1 >/dev/null); then
  echo "second writer acquired a held workspace lock" >&2
  exit 1
fi
tproj_workspace_lock_release "$held"

# A dead holder is recoverable without an unbounded wait.
mkdir "${workspace}.lock"
printf '999999\n' > "${workspace}.lock/pid"
tproj_workspace_lock_acquire "$workspace" 1 >/dev/null
recovered="$(tproj_workspace_lock_path "$workspace")"
[ "$recovered" = "${workspace}.lock" ]
tproj_workspace_lock_release "$recovered"

echo "workspace writer lock: PASS"

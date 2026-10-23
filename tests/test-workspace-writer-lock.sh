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

# A partial project merge keeps manual/volatile fields that were not part of
# the requested update (the stale full-array replacement would lose these).
cat > "$TMP/merge.yaml" <<'YAML'
projects:
  - project_id: stable
    path: /work/stable
    enabled: true
    lastActiveAt: 200
    manual_key: keep
YAML
cat > "$TMP/desired.yaml" <<'YAML'
projects:
  - project_id: stable
    path: /work/stable
    alias: renamed
YAML
# Extract the exact multiline literal passed to runCommand by the GUI save path.
# This exercises its merge expression, not the rest of the GUI save lifecycle.
expression=$(python3 - "$ROOT/apps/tproj/Sources/TprojApp/TprojApp.swift" <<'PYEXPR'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text().split('private func persistWorkspaceProjects(', 1)[1]
expression, call = source.split('let expression = """', 1)[1].split('"""', 1)
assert '["yq", "eval", "-i", expression, workspacePath]' in call
print(expression.replace('\\"', '"'))
PYEXPR
)
TPROJ_PROJECTS_TMP="$TMP/desired.yaml" TPROJ_PRESERVE_ENABLED=true yq eval -i "$expression" "$TMP/merge.yaml"
[ "$(yq -r '.projects[0].manual_key' "$TMP/merge.yaml")" = keep ]
[ "$(yq -r '.projects[0].lastActiveAt' "$TMP/merge.yaml")" = 200 ]
[ "$(yq -r '.projects[0].alias' "$TMP/merge.yaml")" = renamed ]

echo "workspace writer lock: PASS"

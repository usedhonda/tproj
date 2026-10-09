#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# An isolated PATH has no deployment, SSH, launchctl or UI utilities.
for flag in --help -h; do
  result=$(PATH=/nonexistent /bin/bash "$ROOT/bin/tproj-msg-reload" "$flag")
  [[ "$result" == Usage:* ]]
done
set +e
PATH=/nonexistent /bin/bash "$ROOT/bin/tproj-msg-reload" --unexpected >/dev/null 2>&1
status=$?
set -e
[[ "$status" -eq 2 ]]
printf '%s\n' 'PASS reload help is side-effect-free'

#!/bin/bash
# Shared advisory lock for writers of workspace.yaml.
# The lock is a sibling directory (<workspace>.lock), so shell and GUI writers
# coordinate without requiring flock(1), which is not present on stock macOS.

tproj_workspace_lock_path() {
  printf '%s.lock\n' "${1:?workspace path required}"
}

tproj_workspace_lock_acquire() {
  local workspace="$1" timeout="${2:-5}" lock_dir start now holder
  lock_dir="$(tproj_workspace_lock_path "$workspace")"
  start=$(date +%s)
  while ! mkdir "$lock_dir" 2>/dev/null; do
    if [ -f "$lock_dir/pid" ]; then
      holder=$(cat "$lock_dir/pid" 2>/dev/null || true)
      if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
        rm -f "$lock_dir/pid" 2>/dev/null || true
        rmdir "$lock_dir" 2>/dev/null || true
        continue
      fi
    fi
    now=$(date +%s)
    [ $((now - start)) -ge "$timeout" ] && return 1
    sleep 0.05
  done
  printf '%s\n' "$$" > "$lock_dir/pid" 2>/dev/null || true
  printf '%s\n' "$lock_dir"
}

tproj_workspace_lock_release() {
  local lock_dir="${1:?lock directory required}"
  rm -f "$lock_dir/pid" 2>/dev/null || true
  rmdir "$lock_dir" 2>/dev/null || true
}

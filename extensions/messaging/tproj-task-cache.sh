#!/bin/bash
# tproj-task-cache.sh — shared helpers for the Task ID cache used by
# tproj-msg --new-task / tproj-task CLI / tproj-inbox-{record,check} hooks.
#
# Cache layout (v2, owner-scoped): ~/.cache/tproj-expect-reply/<owner>/<target>.json
#   where <owner> = "<session>/<owner_alias>" (the tmux session name plus the
#   issuing pane's @alias, i.e. the column that delegated the task).
# JSON shape (per file, one file per target under an owner subdir):
#   {
#     "<task_id>": {
#       "target":       "<target>",
#       "sent_at":      <epoch_seconds>,
#       "expect_until": <epoch_seconds>,
#       "ttl_sec":      <int>,
#       "msg_hash":     "<sha1-of-normalized-message>"
#     },
#     ...
#   }
#
# Owner scoping (cross-column leak fix): every owner-scoped op takes the owner
# key as its first argument. A caller records into, and enumerates from, ONLY
# its own owner subdir. Owner resolution is fail-closed: an invalid owner
# (empty, missing session or alias, "unknown"/"null" sentinels, or `..`) makes
# mutations refuse and read/list ops return empty — the process never touches
# another column's subdir.
#
# Single-writer contract: only tproj-inbox-record (PostToolUse hook) adds.
# tproj-msg --read, tproj-inbox-check (UserPromptSubmit), and tproj-task close
# are removers. All ops are idempotent.
#
# Legacy flat files (pre-v2, directly under the cache root) are drained silently
# by tt_cache_gc_legacy_flat (TTL-GC, no notice, no owner guess) so the old
# unscoped layout self-empties after upgrade.
#
# Source this file with `source "$(dirname "$0")/tproj-task-cache.sh"` or
# its install path. Functions exit non-zero only on missing `jq`.

: "${TT_CACHE_DIR:="${HOME}/.cache/tproj-expect-reply"}"
: "${TT_CACHE_LOCK_DIR:="/tmp"}"

# Best-effort shadow-write to SQLite WAL (R1' Stage 2).
# Mirrors task state into ~/.local/share/tproj-msg/messages.db.
# JSON path + mkdir lock remain primary; DB ops are fail-open (always return 0).
# Sourced lazily so absence of the file does not break contract callers.
__TT_CACHE_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [[ -n "$__TT_CACHE_SELF_DIR" && -f "${__TT_CACHE_SELF_DIR}/tproj-msg-db.sh" ]]; then
  # shellcheck source=/dev/null
  source "${__TT_CACHE_SELF_DIR}/tproj-msg-db.sh" 2>/dev/null || true
elif [[ -f "${HOME}/bin/tproj-msg-db.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/bin/tproj-msg-db.sh" 2>/dev/null || true
fi

tt_cache_require_jq() {
  command -v jq >/dev/null 2>&1 || {
    printf 'tproj-task-cache: jq is required but not found in PATH\n' >&2
    return 127
  }
}

# Validate a single path component (session, alias, or target). Reject (never
# sanitize/transform): empty, "." / "..", or any character outside the
# [A-Za-z0-9._-] set. This guarantees an INJECTIVE mapping onto the filesystem
# -- two distinct inputs can never collapse to the same component, and no
# traversal ("..", an embedded "/") can be smuggled into a cache path.
tt_cache_valid_component() {
  local c="${1:-}"
  [[ -n "$c" ]] || return 1
  [[ "$c" == "." || "$c" == ".." ]] && return 1
  [[ "$c" =~ ^[A-Za-z0-9._-]+$ ]] || return 1
  return 0
}

# Validate an owner key "<session>/<owner_alias>". Fail-closed: returns non-zero
# unless it is exactly two collision-safe components separated by a single slash,
# neither being an "unknown"/"null" resolution sentinel. Owner-scoped ops call
# this before touching disk.
tt_cache_valid_owner() {
  local owner="${1:-}"
  [[ -n "$owner" ]] || return 1
  [[ "$owner" == */* ]] || return 1
  local sess="${owner%%/*}" rest="${owner#*/}"
  [[ "$rest" != */* ]] || return 1
  case "$sess" in unknown|null) return 1 ;; esac
  case "$rest" in unknown|null) return 1 ;; esac
  tt_cache_valid_component "$sess" || return 1
  tt_cache_valid_component "$rest" || return 1
  return 0
}

tt_cache_owner_dir() {
  local owner="$1"
  printf '%s/%s\n' "$TT_CACHE_DIR" "$owner"
}

tt_cache_init_dir() {
  # With an owner arg, ensure that owner's subdir exists; else the cache root.
  # Fail-closed at the function boundary: an invalid owner is refused WITHOUT any
  # mkdir, so a public caller passing e.g. "../escape" can never create a
  # directory outside the cache root (path-traversal guard).
  local owner="${1:-}"
  if [[ -n "$owner" ]]; then
    tt_cache_valid_owner "$owner" || return 1
    local d
    d="$(tt_cache_owner_dir "$owner")"
    [[ -d "$d" ]] || mkdir -p "$d"
  else
    [[ -d "$TT_CACHE_DIR" ]] || mkdir -p "$TT_CACHE_DIR"
  fi
}

tt_cache_path_for_target() {
  local owner="$1" target="$2"
  printf '%s/%s/%s.json\n' "$TT_CACHE_DIR" "$owner" "$target"
}

tt_cache_lock_for_target() {
  local owner="$1" target="$2"
  # Join with '~' (absent from the [A-Za-z0-9._-] component charset) so distinct
  # (session, alias, target) triples never collapse to the same lock name the
  # way a '.'-joined key could (e.g. "a/b.c" vs "a.b/c").
  local sess="${owner%%/*}" al="${owner#*/}"
  printf '%s/tproj-task-cache~%s~%s~%s.lock\n' "$TT_CACHE_LOCK_DIR" "$sess" "$al" "$target"
}

# mkdir-based advisory lock (POSIX-atomic, works where flock is absent e.g. macOS).
# Arguments: lock_dir [timeout_sec=5]
tt_cache_acquire_lock() {
  local lock_dir="$1" timeout="${2:-5}"
  local start_ts now
  start_ts=$(date +%s)
  while ! mkdir "$lock_dir" 2>/dev/null; do
    if [[ -f "$lock_dir/pid" ]]; then
      local holder
      holder=$(cat "$lock_dir/pid" 2>/dev/null || true)
      if [[ -n "$holder" ]] && ! kill -0 "$holder" 2>/dev/null; then
        rm -rf "$lock_dir" 2>/dev/null || true
        continue
      fi
    fi
    sleep 0.05
    now=$(date +%s)
    if (( now - start_ts >= timeout )); then
      return 1
    fi
  done
  printf '%s\n' "$$" > "$lock_dir/pid" 2>/dev/null || true
  return 0
}

tt_cache_release_lock() {
  local lock_dir="$1"
  rm -rf "$lock_dir" 2>/dev/null || true
}

tt_cache_ttl_to_seconds() {
  # Accepts "30m", "2h", "45s", or raw integer seconds. Returns seconds on stdout.
  local spec="${1:-30m}"
  local num unit
  if [[ "$spec" =~ ^([0-9]+)([smhd]?)$ ]]; then
    num="${BASH_REMATCH[1]}"
    unit="${BASH_REMATCH[2]:-s}"
  else
    return 2
  fi
  case "$unit" in
    s) printf '%s\n' "$num" ;;
    m) printf '%s\n' "$((num * 60))" ;;
    h) printf '%s\n' "$((num * 3600))" ;;
    d) printf '%s\n' "$((num * 86400))" ;;
    *) return 2 ;;
  esac
}

tt_cache_msg_hash() {
  local msg="$1"
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$msg" | shasum -a 1 | awk '{print $1}'
  elif command -v sha1sum >/dev/null 2>&1; then
    printf '%s' "$msg" | sha1sum | awk '{print $1}'
  else
    printf '%s' "$msg" | cksum | awk '{print $1}'
  fi
}

tt_cache_add() {
  # Arguments: owner target task_id sent_at ttl_sec [msg_hash]
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3" sent_at="$4" ttl_sec="$5" msg_hash="${6:-}"
  tt_cache_valid_owner "$owner" || return 2
  tt_cache_valid_component "$target" || return 2
  local expect_until=$((sent_at + ttl_sec))
  tt_cache_init_dir "$owner"
  local path lock
  path="$(tt_cache_path_for_target "$owner" "$target")"
  lock="$(tt_cache_lock_for_target "$owner" "$target")"
  tt_cache_acquire_lock "$lock" 5 || return 1
  local rc=0
  {
    local current='{}'
    [[ -s "$path" ]] && current="$(cat "$path")"
    local entry
    entry=$(jq -nc \
      --arg target "$target" \
      --argjson sent "$sent_at" \
      --argjson until "$expect_until" \
      --argjson ttl "$ttl_sec" \
      --arg hash "$msg_hash" \
      '{target: $target, sent_at: $sent, expect_until: $until, ttl_sec: $ttl, msg_hash: $hash}') || rc=1
    if [[ $rc -eq 0 ]]; then
      printf '%s\n' "$current" \
        | jq -c --arg id "$task_id" --argjson e "$entry" '. + {($id): $e}' \
        > "${path}.tmp" \
        && mv "${path}.tmp" "$path" || rc=1
    fi
  }
  tt_cache_release_lock "$lock"
  # R1' Stage 2 shadow write — best-effort, never affects rc. owner_alias (the
  # issuing column) is recorded for query/audit; it is the alias part of owner.
  if [[ $rc -eq 0 ]] && declare -F tt_db_upsert_task >/dev/null 2>&1; then
    tt_db_upsert_task "$task_id" "$target" "$sent_at" "$ttl_sec" "$msg_hash" "${owner##*/}" "${owner%%/*}" || true
  fi
  return $rc
}

tt_cache_remove_task() {
  # Arguments: owner target task_id
  # Idempotent: missing owner/target/task is not an error. An invalid owner is a
  # no-op (fail-closed: never touch another column's subdir).
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3"
  tt_cache_valid_owner "$owner" || return 0
  tt_cache_valid_component "$target" || return 0
  local path lock
  path="$(tt_cache_path_for_target "$owner" "$target")"
  lock="$(tt_cache_lock_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 0
  tt_cache_acquire_lock "$lock" 5 || return 1
  local rc=0
  if [[ -s "$path" ]]; then
    local remaining
    remaining=$(jq -c --arg id "$task_id" 'del(.[$id])' "$path") || rc=1
    if [[ $rc -eq 0 ]]; then
      if [[ "$remaining" == "{}" ]]; then
        rm -f "$path"
      else
        printf '%s\n' "$remaining" > "${path}.tmp" && mv "${path}.tmp" "$path" || rc=1
      fi
    fi
  fi
  tt_cache_release_lock "$lock"
  # No DB shadow write here: state transitions (acked/done/blocked) are recorded
  # at the call site (tproj-msg --read with tag detection, tproj-task close, etc.)
  # so this generic remove path stays state-agnostic.
  return $rc
}

tt_cache_get_task() {
  # Arguments: owner target task_id -> prints entry JSON on stdout, empty if
  # missing. Invalid owner prints nothing (fail-closed).
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3"
  tt_cache_valid_owner "$owner" || return 0
  tt_cache_valid_component "$target" || return 0
  local path
  path="$(tt_cache_path_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 0
  jq -c --arg id "$task_id" '.[$id] // empty' "$path"
}

tt_cache_list_targets() {
  # Arguments: owner -> lists targets with at least one active task entry under
  # that owner subdir, one per line. Invalid owner lists nothing (fail-closed).
  local owner="$1" dir f base
  tt_cache_valid_owner "$owner" || return 0
  dir="$(tt_cache_owner_dir "$owner")"
  [[ -d "$dir" ]] || return 0
  for f in "$dir"/*.json; do
    [[ -e "$f" ]] || continue
    [[ -s "$f" ]] || continue
    base=$(basename "$f" .json)
    printf '%s\n' "$base"
  done
}

tt_cache_list_tasks() {
  # Arguments: owner target -> lines "<task_id>\t<sent_at>\t<expect_until>"
  tt_cache_require_jq || return $?
  local owner="$1" target="$2"
  tt_cache_valid_owner "$owner" || return 0
  tt_cache_valid_component "$target" || return 0
  local path
  path="$(tt_cache_path_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 0
  jq -r 'to_entries[] | [.key, (.value.sent_at|tostring), (.value.expect_until|tostring)] | @tsv' "$path"
}

tt_cache_list_all() {
  # Arguments: owner -> lines "<target>\t<task_id>\t<sent_at>\t<expect_until>"
  local owner="$1" target tid sent until_at
  while IFS= read -r target; do
    [[ -z "$target" ]] && continue
    while IFS=$'\t' read -r tid sent until_at; do
      [[ -z "$tid" ]] && continue
      printf '%s\t%s\t%s\t%s\n' "$target" "$tid" "$sent" "$until_at"
    done < <(tt_cache_list_tasks "$owner" "$target")
  done < <(tt_cache_list_targets "$owner")
}

tt_cache_gc_expired() {
  # Arguments: owner [now_epoch]  (now defaults to current time)
  # Removes entries under the owner subdir whose expect_until <= now. Emits
  # removed rows on stdout: "<target>\t<task_id>\t<expect_until>\ttimeout".
  # Invalid owner is a no-op (fail-closed).
  tt_cache_require_jq || return $?
  local owner="$1" now="${2:-$(date +%s)}"
  tt_cache_valid_owner "$owner" || return 0
  local target path lock now_copy
  now_copy="$now"
  while IFS= read -r target; do
    [[ -z "$target" ]] && continue
    path="$(tt_cache_path_for_target "$owner" "$target")"
    lock="$(tt_cache_lock_for_target "$owner" "$target")"
    [[ -s "$path" ]] || continue
    tt_cache_acquire_lock "$lock" 5 || continue
    if [[ -s "$path" ]]; then
      jq -r --argjson now "$now_copy" \
        'to_entries[] | select(.value.expect_until <= $now) | [.key, (.value.expect_until|tostring)] | @tsv' \
        "$path" | while IFS=$'\t' read -r tid until_at; do
          [[ -z "$tid" ]] && continue
          printf '%s\t%s\t%s\ttimeout\n' "$target" "$tid" "$until_at"
          # R1' Stage 2 shadow write — record expired transition, scoped to this
          # owner's composite (owner_session + owner_alias + task_id). Fail-open.
          if declare -F tt_db_transition_task >/dev/null 2>&1; then
            tt_db_transition_task "$tid" "expired" "${owner%%/*}" "${owner##*/}" "$target" || true
          fi
        done
      local remaining
      remaining=$(jq -c --argjson now "$now_copy" \
        'with_entries(select(.value.expect_until > $now))' "$path")
      if [[ "$remaining" == "{}" ]]; then
        rm -f "$path"
      else
        printf '%s\n' "$remaining" > "${path}.tmp" && mv "${path}.tmp" "$path"
      fi
    fi
    tt_cache_release_lock "$lock"
  done < <(tt_cache_list_targets "$owner")
}

# Legacy (pre-v2) flat-layout drain. Silently TTL-GCs any "<target>.json" files
# living directly under the cache root (the old unscoped layout), removing
# expired entries and empty files. Emits NOTHING and touches no DB row — the
# owner is unknowable from a flat file, so we never guess. Owner subdirs (which
# are directories, not "*.json" regular files) are skipped by construction.
# Safe to delete a few releases after v2 ships, once no flat files remain.
tt_cache_gc_legacy_flat() {
  tt_cache_require_jq || return $?
  local now="${1:-$(date +%s)}"
  [[ -d "$TT_CACHE_DIR" ]] || return 0
  local f remaining
  for f in "$TT_CACHE_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    if [[ ! -s "$f" ]]; then
      rm -f "$f"
      continue
    fi
    remaining=$(jq -c --argjson now "$now" \
      'with_entries(select(.value.expect_until > $now))' "$f" 2>/dev/null) || continue
    if [[ "$remaining" == "{}" || -z "$remaining" ]]; then
      rm -f "$f"
    else
      printf '%s\n' "$remaining" > "${f}.tmp" && mv "${f}.tmp" "$f"
    fi
  done
}

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
#       "msg_hash":     "<sha1-of-normalized-message>",
#       "state":        "pending|acked|done|blocked|received|verified|cancelled|frozen",
#       "task_kind":    "delegated|role_handoff",
#       "intent_hash":  "<sha256-of-delegated-intent-or-empty>",
#       "user_authorized_exact": 0|1,
#       "role_handoff_epoch": <int-or-null>,
#       "orchestrator": "<alias.role-or-empty>",
#       "tombstone_reason_hash": "<hash-or-empty>",
#       "notices":      {"<event>": <epoch>}
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
# Lifecycle consumers update the existing entry in place. Only a platform-
# observed USER_REPORTED transition removes it. All ops are idempotent.
#
# Legacy flat files (pre-v2, directly under the cache root) are drained silently
# by tt_cache_gc_legacy_flat (TTL-GC, no notice, no owner guess) so the old
# unscoped layout self-empties after upgrade.
#
# Source this file with `source "$(dirname "$0")/tproj-task-cache.sh"` or
# its install path. Functions exit non-zero only on missing `jq`.

: "${TT_CACHE_DIR:="${HOME}/.cache/tproj-expect-reply"}"
: "${TT_CACHE_LOCK_DIR:="/tmp"}"
: "${TT_TASK_NO_ACK_SEC:=30}"
: "${TT_TASK_FOLLOWUP_SEC:=900}"
: "${TT_TASK_REROUTE_SEC:=1800}"
: "${TT_TASK_REPORT_DUE_SEC:=900}"
: "${TT_TASK_COMPLETION_STALLED_SEC:=1800}"

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

tt_cache_open_state_predicate() {
  printf '(.value.state // "pending") | test("^(pending|acked|done|blocked|received|verified)$")'
}

tt_cache_tombstone_state() {
  local state="${1:-}"
  [[ "$state" == "cancelled" || "$state" == "frozen" ]]
}

tt_cache_add() {
  # Arguments: owner target task_id sent_at ttl_sec [msg_hash] [task_kind]
  #            [intent_hash] [user_authorized_exact] [role_handoff_epoch]
  #            [orchestrator]
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3" sent_at="$4" ttl_sec="$5" msg_hash="${6:-}"
  local task_kind="${7:-delegated}" intent_hash="${8:-}" user_authorized_exact="${9:-0}"
  local role_handoff_epoch="${10:-}" orchestrator="${11:-}"
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
      --arg kind "$task_kind" \
      --arg intent_hash "$intent_hash" \
      --argjson user_authorized_exact "$([[ "$user_authorized_exact" == "1" ]] && echo 1 || echo 0)" \
      --argjson role_handoff_epoch "${role_handoff_epoch:-null}" \
      --arg orchestrator "$orchestrator" \
      '{target: $target, sent_at: $sent, expect_until: $until, ttl_sec: $ttl, msg_hash: $hash,
        state: "pending", task_kind: $kind, intent_hash: $intent_hash,
        user_authorized_exact: $user_authorized_exact,
        role_handoff_epoch: $role_handoff_epoch, orchestrator: $orchestrator,
        tombstone_reason_hash: "", notices: {}}') || rc=1
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
    tt_db_upsert_task "$task_id" "$target" "$sent_at" "$ttl_sec" "$msg_hash" "${owner##*/}" "${owner%%/*}" "$task_kind" "$intent_hash" "$user_authorized_exact" "$role_handoff_epoch" "$orchestrator" || true
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
  # No DB shadow write here: USER_REPORTED is recorded before this internal
  # remover runs, so the generic filesystem operation stays state-agnostic.
  return $rc
}

tt_cache_transition_state() {
  # Arguments: owner target task_id new_state [now_epoch]
  # The cache is the open-task control surface. Transitions are monotonic and
  # retain the entry until USER_REPORTED removes it.
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3" new_state="$4" now="${5:-$(date +%s)}"
  tt_cache_valid_owner "$owner" || return 2
  tt_cache_valid_component "$target" || return 2
  [[ "$now" =~ ^[0-9]+$ ]] || return 2
  case "$new_state" in
    pending|acked|done|blocked|received|verified|cancelled|frozen) ;;
    *) return 2 ;;
  esac
  local path lock
  path="$(tt_cache_path_for_target "$owner" "$target")"
  lock="$(tt_cache_lock_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 1
  tt_cache_acquire_lock "$lock" 5 || return 1
  local rc=0 current_state updated
  current_state="$(jq -r --arg id "$task_id" 'if .[$id] == null then empty else (.[$id].state // "pending") end' "$path" 2>/dev/null)"
  case "${current_state}:${new_state}" in
    pending:pending|pending:acked|pending:done|pending:blocked|pending:cancelled|pending:frozen|\
    acked:acked|acked:done|acked:blocked|acked:cancelled|acked:frozen|\
    done:done|done:received|done:cancelled|done:frozen|\
    blocked:blocked|blocked:received|blocked:cancelled|blocked:frozen|\
    received:received|received:verified|received:cancelled|received:frozen|\
    verified:verified|verified:cancelled|verified:frozen|\
    cancelled:cancelled|frozen:frozen) ;;
    *) rc=2 ;;
  esac
  if [[ $rc -eq 0 ]]; then
    updated=$(jq -c --arg id "$task_id" --arg state "$new_state" --argjson now "$now" '
      if .[$id] == null then error("missing task")
      else .[$id].state = $state
        | if $state == "acked" then .[$id].ack_at //= $now
          elif ($state == "done" or $state == "blocked") then .[$id].terminal_at //= $now
          elif $state == "received" then .[$id].received_at //= $now
          elif $state == "verified" then .[$id].verified_at //= $now
          elif $state == "cancelled" then .[$id].cancelled_at //= $now
          elif $state == "frozen" then .[$id].frozen_at //= $now
          else . end
      end' "$path") || rc=1
    if [[ $rc -eq 0 ]]; then
      printf '%s\n' "$updated" > "${path}.tmp" && mv "${path}.tmp" "$path" || rc=1
    fi
  fi
  tt_cache_release_lock "$lock"
  return $rc
}

tt_cache_tombstone_task() {
  # Arguments: owner target task_id tombstone_state reason_hash [now_epoch]
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3" tombstone_state="$4" reason_hash="$5"
  local now="${6:-$(date +%s)}"
  tt_cache_valid_owner "$owner" || return 2
  tt_cache_valid_component "$target" || return 2
  tt_cache_tombstone_state "$tombstone_state" || return 2
  [[ "$reason_hash" =~ ^[A-Za-z0-9._:-]{8,128}$ && "$now" =~ ^[0-9]+$ ]] || return 2
  local path lock rc=0 updated
  path="$(tt_cache_path_for_target "$owner" "$target")"
  lock="$(tt_cache_lock_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 1
  tt_cache_acquire_lock "$lock" 5 || return 1
  updated=$(jq -c --arg id "$task_id" --arg state "$tombstone_state" --arg reason "$reason_hash" --argjson now "$now" '
    if .[$id] == null then error("missing task")
    else
      .[$id].state as $current
      | if ($current == "cancelled" and $state == "cancelled") or ($current == "frozen" and $state == "frozen") then
          .
        elif ($current | test("^(pending|acked|done|blocked|received|verified)$")) then
          .[$id].state = $state
          | .[$id].tombstone_reason_hash = $reason
          | if $state == "cancelled" then .[$id].cancelled_at //= $now else .[$id].frozen_at //= $now end
        else
          error("invalid tombstone transition")
        end
    end' "$path" 2>/dev/null) || rc=2
  if [[ $rc -eq 0 ]]; then
    printf '%s\n' "$updated" > "${path}.tmp" && mv "${path}.tmp" "$path" || rc=1
  fi
  tt_cache_release_lock "$lock"
  if [[ $rc -eq 0 ]] && declare -F tt_db_tombstone_task >/dev/null 2>&1; then
    tt_db_tombstone_task "$task_id" "$tombstone_state" "${owner%%/*}" "${owner##*/}" "$target" "$reason_hash" "$now" >/dev/null 2>&1 || true
  fi
  return $rc
}

tt_cache_mark_notice() {
  # Arguments: owner target task_id notice [now_epoch]
  # Returns 0 only when the notice was newly recorded; 1 means already emitted.
  tt_cache_require_jq || return $?
  local owner="$1" target="$2" task_id="$3" notice="$4" now="${5:-$(date +%s)}"
  tt_cache_valid_owner "$owner" || return 2
  tt_cache_valid_component "$target" || return 2
  tt_cache_valid_component "$notice" || return 2
  [[ "$now" =~ ^[0-9]+$ ]] || return 2
  local path lock existing updated rc=0
  path="$(tt_cache_path_for_target "$owner" "$target")"
  lock="$(tt_cache_lock_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 1
  tt_cache_acquire_lock "$lock" 5 || return 1
  existing="$(jq -r --arg id "$task_id" --arg key "$notice" '.[$id].notices[$key] // empty' "$path" 2>/dev/null)"
  if [[ -n "$existing" ]]; then
    rc=1
  else
    updated=$(jq -c --arg id "$task_id" --arg key "$notice" --argjson now "$now" '
      if .[$id] == null then error("missing task")
      else .[$id].notices = (.[$id].notices // {}) | .[$id].notices[$key] = $now end' "$path") || rc=2
    if [[ $rc -eq 0 ]]; then
      printf '%s\n' "$updated" > "${path}.tmp" && mv "${path}.tmp" "$path" || rc=2
    fi
  fi
  tt_cache_release_lock "$lock"
  return $rc
}

tt_cache_apply_reply() {
  # Arguments: owner target task_id tag [message_id] [body_hash]
  #            [owner_recipient] [now_epoch]
  # Terminal replies require durable DB evidence. A scrollback-only DONE/BLOCK
  # is malformed and leaves the task open in its prior state.
  local owner="$1" target="$2" task_id="$3" tag="$4"
  local message_id="${5:-}" body_hash="${6:-}" owner_recipient="${7:-}"
  local now="${8:-$(date +%s)}"
  local current_entry current_state
  current_entry="$(tt_cache_get_task "$owner" "$target" "$task_id" 2>/dev/null || true)"
  current_state="$(printf '%s' "$current_entry" | jq -r '.state // ""' 2>/dev/null || true)"
  tt_cache_tombstone_state "$current_state" && return 4
  case "$tag" in
    ACK|ACK-PROGRESS)
      tt_cache_transition_state "$owner" "$target" "$task_id" acked "$now" || return $?
      declare -F tt_db_transition_task >/dev/null 2>&1 \
        && tt_db_transition_task "$task_id" acked "${owner%%/*}" "${owner##*/}" "$target" "$now" >/dev/null 2>&1 || true
      ;;
    DONE|BLOCK|BLOCKED)
      [[ "$message_id" =~ ^[0-9]+$ && "$body_hash" =~ ^[A-Za-z0-9._:-]{8,128}$ ]] || return 3
      local terminal_state="done"
      [[ "$tag" == BLOCK || "$tag" == BLOCKED ]] && terminal_state=blocked
      declare -F tt_db_record_done_evidence >/dev/null 2>&1 || return 3
      declare -F tt_db_task_lifecycle >/dev/null 2>&1 || return 3
      tt_db_record_done_evidence "$task_id" "$message_id" "$body_hash" \
        "${owner%%/*}" "${owner##*/}" "$target" "$owner_recipient" "$terminal_state" "$now" || return 3
      local lifecycle
      lifecycle="$(tt_db_task_lifecycle "$task_id" "${owner%%/*}" "${owner##*/}" "$target" 2>/dev/null || true)"
      [[ "$lifecycle" == "${terminal_state}|${message_id}|${body_hash}|"* ]] || return 3
      tt_cache_transition_state "$owner" "$target" "$task_id" "$terminal_state" "$now" || return $?
      tt_cache_transition_state "$owner" "$target" "$task_id" received "$now" || return $?
      tt_db_transition_task "$task_id" received "${owner%%/*}" "${owner##*/}" "$target" "$now" >/dev/null 2>&1 || return 3
      ;;
    *) return 2 ;;
  esac
  return 0
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

tt_cache_list_open_tasks() {
  # Arguments: owner target -> lines "<task_id>\t<sent_at>\t<expect_until>"
  tt_cache_require_jq || return $?
  local owner="$1" target="$2"
  tt_cache_valid_owner "$owner" || return 0
  tt_cache_valid_component "$target" || return 0
  local path
  path="$(tt_cache_path_for_target "$owner" "$target")"
  [[ -s "$path" ]] || return 0
  jq -r 'to_entries[] | select('"$(tt_cache_open_state_predicate)"') | [.key, (.value.sent_at|tostring), (.value.expect_until|tostring)] | @tsv' "$path"
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
  # Compatibility alias. Open tasks no longer expire/close; they emit bounded
  # lifecycle notices and stay tracked until USER_REPORTED.
  tt_cache_due_notices "$@"
}

tt_cache_due_notices() {
  # Arguments: owner [now_epoch]
  # Emits newly-due TSV rows: target, task_id, state, event. Each event is marked
  # atomically and emitted once. The task entry is never removed here.
  tt_cache_require_jq || return $?
  local owner="$1" now="${2:-$(date +%s)}"
  tt_cache_valid_owner "$owner" || return 0
  [[ "$now" =~ ^[0-9]+$ ]] || return 2
  local target task_id state sent base event threshold
  while IFS= read -r target; do
    [[ -n "$target" ]] || continue
    while IFS=$'\t' read -r task_id sent state base; do
      [[ -n "$task_id" && "$sent" =~ ^[0-9]+$ ]] || continue
      case "$state" in
        pending)
          for event in no_ack followup_due reroute_due; do
            case "$event" in
              no_ack) threshold="$TT_TASK_NO_ACK_SEC" ;;
              followup_due) threshold="$TT_TASK_FOLLOWUP_SEC" ;;
              reroute_due) threshold="$TT_TASK_REROUTE_SEC" ;;
            esac
            if (( now - sent >= threshold )) && tt_cache_mark_notice "$owner" "$target" "$task_id" "$event" "$now"; then
              printf '%s\t%s\t%s\t%s\n' "$target" "$task_id" "$state" "$event"
            fi
          done
          ;;
        acked)
          for event in followup_due reroute_due; do
            [[ "$event" == followup_due ]] && threshold="$TT_TASK_FOLLOWUP_SEC" || threshold="$TT_TASK_REROUTE_SEC"
            if (( now - sent >= threshold )) && tt_cache_mark_notice "$owner" "$target" "$task_id" "$event" "$now"; then
              printf '%s\t%s\t%s\t%s\n' "$target" "$task_id" "$state" "$event"
            fi
          done
          ;;
        done|blocked|received|verified)
          [[ "$base" =~ ^[0-9]+$ ]] || base="$sent"
          for event in report_due completion_stalled; do
            [[ "$event" == report_due ]] && threshold="$TT_TASK_REPORT_DUE_SEC" || threshold="$TT_TASK_COMPLETION_STALLED_SEC"
            if (( now - base >= threshold )) && tt_cache_mark_notice "$owner" "$target" "$task_id" "$event" "$now"; then
              printf '%s\t%s\t%s\t%s\n' "$target" "$task_id" "$state" "$event"
            fi
          done
          ;;
        cancelled|frozen)
          ;;
      esac
    done < <(jq -r 'to_entries[] | [.key, (.value.sent_at|tostring), (.value.state // "pending"), ((.value.received_at // .value.terminal_at // .value.sent_at)|tostring)] | @tsv' "$(tt_cache_path_for_target "$owner" "$target")")
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

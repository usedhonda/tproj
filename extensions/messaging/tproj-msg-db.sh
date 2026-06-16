#!/bin/bash
# tproj-msg-db.sh — SQLite WAL shadow-write helpers for tproj-msg.
#
# Layered on top of tproj-task-cache.sh's JSON primary path. This file
# adds durable history, task lifecycle records, and Monitor cursors in
# ~/.local/share/tproj-msg/messages.db.
#
# Schema: messages / tasks / monitor_cursors (PRAGMA user_version=1).
# Mode: WAL, busy_timeout=5000, synchronous=NORMAL, foreign_keys=ON.
#
# All public functions are fail-open. Callers must not depend on rc.
#   - sqlite3 absent      -> return 0 silently after first warning
#   - DB write error      -> return 0, append to error log
#   - permission denied   -> return 0, append to error log
#
# Source this file from tproj-msg, tproj-task-cache.sh, and hook scripts.

: "${TPROJ_MSG_DB_PATH:="${HOME}/.local/share/tproj-msg/messages.db"}"
: "${TPROJ_MSG_DB_ERROR_LOG:="${HOME}/.cache/tproj-msg/db-errors.log"}"
: "${TPROJ_MSG_DB_INIT_FLAG:="${HOME}/.cache/tproj-msg/db-init.stamp"}"

tt_db_path() { printf '%s\n' "$TPROJ_MSG_DB_PATH"; }
tt_db_error_log() { printf '%s\n' "$TPROJ_MSG_DB_ERROR_LOG"; }

tt_db_guard() {
  command -v sqlite3 >/dev/null 2>&1 || return 1
  return 0
}

tt_db_ensure_dirs() {
  local db_dir log_dir
  db_dir="$(dirname "$TPROJ_MSG_DB_PATH")"
  log_dir="$(dirname "$TPROJ_MSG_DB_ERROR_LOG")"
  [[ -d "$db_dir" ]] || mkdir -p "$db_dir" 2>/dev/null || true
  [[ -d "$log_dir" ]] || mkdir -p "$log_dir" 2>/dev/null || true
}

tt_db_log_error() {
  tt_db_ensure_dirs
  printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" \
    >> "$TPROJ_MSG_DB_ERROR_LOG" 2>/dev/null || true
}

tt_db_exec_safe() {
  # busy_timeout / foreign_keys are connection-level PRAGMAs (not persisted in DB).
  # Apply them via .output /dev/null block so PRAGMA echoes don't pollute stdout.
  local sql="$1"
  tt_db_guard || return 0
  tt_db_ensure_dirs
  local out rc=0
  # busy_timeout intentionally short (1000ms): shadow writes happen AFTER the
  # send-keys delivery, so under rare DB-lock contention we fail-open fast
  # (drop a history row) rather than hang the user-facing tproj-msg command.
  out=$(sqlite3 -batch -bail "$TPROJ_MSG_DB_PATH" <<SQL 2>>"$TPROJ_MSG_DB_ERROR_LOG"
.output /dev/null
PRAGMA busy_timeout=1000;
PRAGMA foreign_keys=ON;
.output stdout
${sql}
SQL
) || rc=$?
  if [[ $rc -ne 0 ]]; then
    tt_db_log_error "sqlite3 exec failed (rc=$rc): ${sql:0:120}"
    return 0
  fi
  printf '%s' "$out"
  return 0
}

tt_db_init() {
  tt_db_guard || return 0
  tt_db_ensure_dirs
  local schema_sql
  schema_sql=$(cat <<'SQL'
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session      TEXT,
  from_alias   TEXT NOT NULL,
  to_alias     TEXT NOT NULL,
  body         TEXT NOT NULL,
  body_hash    TEXT NOT NULL,
  header       TEXT,
  task_id      TEXT,
  direction    TEXT NOT NULL,
  delivery     TEXT NOT NULL,
  delivery_err TEXT,
  source_kind  TEXT NOT NULL DEFAULT 'cc',
  bridge       TEXT NOT NULL DEFAULT 'tmux',
  external_id  TEXT,
  created_at   INTEGER NOT NULL,
  delivered_at INTEGER,
  read_at      INTEGER,
  notified_at  INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id      TEXT PRIMARY KEY,
  target       TEXT NOT NULL,
  sent_at      INTEGER NOT NULL,
  expect_until INTEGER NOT NULL,
  ttl_sec      INTEGER NOT NULL,
  state        TEXT NOT NULL,
  ack_at       INTEGER,
  done_at      INTEGER,
  block_at     INTEGER,
  msg_hash     TEXT
);

CREATE TABLE IF NOT EXISTS monitor_cursors (
  consumer        TEXT PRIMARY KEY,
  last_message_id INTEGER NOT NULL DEFAULT 0,
  updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_to        ON messages(to_alias, id);
CREATE INDEX IF NOT EXISTS idx_messages_to_unread ON messages(to_alias, id) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_messages_task      ON messages(task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_expect       ON tasks(target, state, expect_until);
SQL
)
  tt_db_exec_safe "$schema_sql" >/dev/null
}

# Lazy init guard: call before any write. Re-inits if DB file is missing
# (handles env override TPROJ_MSG_DB_PATH switching between sessions
# and test scenarios that wipe the DB file).
tt_db_ensure_init() {
  tt_db_guard || return 0
  [[ -f "$TPROJ_MSG_DB_PATH" ]] && return 0
  tt_db_init
}

# --- escape helpers --------------------------------------------------------

# Escape single quotes for SQLite string literals (double them).
# Note: bash ${var//\'/\'\'} treats \' as literal backslash+quote (depends on bash
# version + quoting context), so we use sed for portable behavior.
tt_db_quote() {
  printf '%s' "$1" | sed "s/'/''/g"
}

# --- message operations ----------------------------------------------------

# Insert a message row. Echoes new id on stdout (empty on failure).
# Args (12, last 3 optional):
#   session from_alias to_alias body body_hash header task_id
#   direction delivery [source_kind=cc] [bridge=tmux] [external_id=]
tt_db_log_message() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local session=$(tt_db_quote "${1:-}")
  local from_a=$(tt_db_quote "${2:-}")
  local to_a=$(tt_db_quote "${3:-}")
  local body=$(tt_db_quote "${4:-}")
  local body_hash=$(tt_db_quote "${5:-}")
  local header=$(tt_db_quote "${6:-}")
  local task_id_raw="${7:-}"
  local direction=$(tt_db_quote "${8:-outbound}")
  local delivery=$(tt_db_quote "${9:-send-keys}")
  local source_kind=$(tt_db_quote "${10:-cc}")
  local bridge=$(tt_db_quote "${11:-tmux}")
  local external_id_raw="${12:-}"
  local task_id_sql='NULL'
  [[ -n "$task_id_raw" ]] && task_id_sql="'$(tt_db_quote "$task_id_raw")'"
  local ext_id_sql='NULL'
  [[ -n "$external_id_raw" ]] && ext_id_sql="'$(tt_db_quote "$external_id_raw")'"
  local sql="INSERT INTO messages (session, from_alias, to_alias, body, body_hash, header, task_id, direction, delivery, source_kind, bridge, external_id, created_at) VALUES ('${session}', '${from_a}', '${to_a}', '${body}', '${body_hash}', '${header}', ${task_id_sql}, '${direction}', '${delivery}', '${source_kind}', '${bridge}', ${ext_id_sql}, strftime('%s','now')); SELECT last_insert_rowid();"
  tt_db_exec_safe "$sql"
}

# Mirror an outbound row as an inbound row for the receiver's view.
# Same args as tt_db_log_message but `from` and `to` are swapped in the row.
# Echoes new id on stdout.
tt_db_mirror_inbound() {
  local session="$1" from_a="$2" to_a="$3" body="$4" body_hash="$5" header="$6"
  local task_id="$7" delivery="${8:-send-keys}" source_kind="${9:-cc}"
  local bridge="${10:-tmux}" external_id="${11:-}"
  tt_db_log_message "$session" "$from_a" "$to_a" "$body" "$body_hash" "$header" \
    "$task_id" "inbound" "$delivery" "$source_kind" "$bridge" "$external_id"
}

tt_db_set_delivered() {
  tt_db_guard || return 0
  local msg_id="${1:-}"
  [[ -z "$msg_id" ]] && return 0
  tt_db_exec_safe "UPDATE messages SET delivered_at=strftime('%s','now') WHERE id=${msg_id};" >/dev/null
}

tt_db_set_delivery_error() {
  tt_db_guard || return 0
  local msg_id="${1:-}" err=$(tt_db_quote "${2:-}")
  [[ -z "$msg_id" ]] && return 0
  tt_db_exec_safe "UPDATE messages SET delivery='error', delivery_err='${err}' WHERE id=${msg_id};" >/dev/null
}

tt_db_set_read() {
  tt_db_guard || return 0
  local msg_id="${1:-}"
  [[ -z "$msg_id" ]] && return 0
  tt_db_exec_safe "UPDATE messages SET read_at=strftime('%s','now') WHERE id=${msg_id} AND read_at IS NULL;" >/dev/null
}

tt_db_set_notified() {
  tt_db_guard || return 0
  local msg_id="${1:-}"
  [[ -z "$msg_id" ]] && return 0
  tt_db_exec_safe "UPDATE messages SET notified_at=strftime('%s','now') WHERE id=${msg_id} AND notified_at IS NULL;" >/dev/null
}

# --- task operations -------------------------------------------------------

# Args: task_id target sent_at ttl_sec msg_hash
tt_db_upsert_task() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local task_id=$(tt_db_quote "${1:-}")
  local target=$(tt_db_quote "${2:-}")
  local sent_at="${3:-0}"
  local ttl_sec="${4:-1800}"
  local msg_hash=$(tt_db_quote "${5:-}")
  [[ -z "$task_id" ]] && return 0
  local expect_until=$((sent_at + ttl_sec))
  tt_db_exec_safe "INSERT INTO tasks (task_id, target, sent_at, expect_until, ttl_sec, state, msg_hash) VALUES ('${task_id}', '${target}', ${sent_at}, ${expect_until}, ${ttl_sec}, 'pending', '${msg_hash}') ON CONFLICT(task_id) DO UPDATE SET target=excluded.target, sent_at=excluded.sent_at, expect_until=excluded.expect_until, ttl_sec=excluded.ttl_sec, msg_hash=excluded.msg_hash;" >/dev/null
}

# Args: task_id new_state (one of: pending acked done blocked expired)
# Sets the state-specific timestamp column when applicable.
tt_db_transition_task() {
  tt_db_guard || return 0
  local task_id=$(tt_db_quote "${1:-}")
  local new_state="${2:-}"
  [[ -z "$task_id" || -z "$new_state" ]] && return 0
  local ts_col=''
  case "$new_state" in
    acked)   ts_col='ack_at' ;;
    done)    ts_col='done_at' ;;
    blocked) ts_col='block_at' ;;
    expired|pending) ts_col='' ;;
    *) return 0 ;;
  esac
  local ts_set=''
  [[ -n "$ts_col" ]] && ts_set=", ${ts_col}=strftime('%s','now')"
  tt_db_exec_safe "UPDATE tasks SET state='${new_state}'${ts_set} WHERE task_id='${task_id}';" >/dev/null
}

# --- monitor cursor + read ops --------------------------------------------

# Args: consumer to_alias [limit=50]
# Emits TSV: id<TAB>from_alias<TAB>task_id<TAB>body_preview(200ch)
tt_db_unread_for() {
  tt_db_guard || return 0
  local consumer=$(tt_db_quote "${1:-}")
  local to_alias=$(tt_db_quote "${2:-}")
  local limit="${3:-50}"
  [[ -z "$consumer" || -z "$to_alias" ]] && return 0
  tt_db_exec_safe "INSERT OR IGNORE INTO monitor_cursors(consumer, last_message_id, updated_at) VALUES ('${consumer}', COALESCE((SELECT MAX(id) FROM messages),0), strftime('%s','now'));" >/dev/null
  # Use \x1f (non-whitespace) so bash IFS won't collapse empty fields.
  sqlite3 -batch -bail -separator $'\x1f' "$TPROJ_MSG_DB_PATH" <<SQL 2>>"$TPROJ_MSG_DB_ERROR_LOG" || true
.output /dev/null
PRAGMA busy_timeout=5000;
.output stdout
SELECT m.id, m.from_alias, COALESCE(m.task_id,''),
       replace(replace(replace(substr(m.body,1,200), char(10), ' '), char(13), ' '), char(31), ' ')
  FROM messages m
  JOIN monitor_cursors c ON c.consumer='${consumer}'
 WHERE m.to_alias='${to_alias}'
   AND m.id > c.last_message_id
   AND m.direction='inbound'
 ORDER BY m.id ASC
 LIMIT ${limit};
SQL
  return 0
}

# Args: consumer last_id
tt_db_advance_cursor() {
  tt_db_guard || return 0
  local consumer=$(tt_db_quote "${1:-}")
  local last_id="${2:-0}"
  [[ -z "$consumer" || -z "$last_id" || "$last_id" == "0" ]] && return 0
  tt_db_exec_safe "INSERT INTO monitor_cursors(consumer, last_message_id, updated_at) VALUES ('${consumer}', ${last_id}, strftime('%s','now')) ON CONFLICT(consumer) DO UPDATE SET last_message_id=excluded.last_message_id, updated_at=excluded.updated_at;" >/dev/null
}

# --- CLI entry point ------------------------------------------------------

# CLI entry point: `tproj-msg-db.sh init` (used by install.sh).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    init)
      tt_db_init
      tt_db_guard || { echo "tproj-msg-db: sqlite3 not found, skipping init" >&2; exit 0; }
      echo "tproj-msg-db: initialized at $TPROJ_MSG_DB_PATH"
      ;;
    path)
      tt_db_path
      ;;
    *)
      echo "Usage: $(basename "$0") {init|path}" >&2
      exit 0
      ;;
  esac
fi

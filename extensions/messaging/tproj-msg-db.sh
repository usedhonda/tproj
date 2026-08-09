#!/bin/bash
# tproj-msg-db.sh — SQLite WAL shadow-write helpers for tproj-msg.
#
# Layered on top of tproj-task-cache.sh's JSON primary path. This file
# adds durable history, task lifecycle records, and Monitor cursors in
# ~/.local/share/tproj-msg/messages.db.
#
# Schema: messages / tasks / monitor_cursors (PRAGMA user_version=TT_DB_SCHEMA_VERSION).
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
# E2 (msg-repair): size cap for the error log so it can't grow unbounded.
# Rotated to <log>.1 once it exceeds this (same idiom as the D4 flush-worker log
# and the respawn-guard). Env-adjustable.
: "${TPROJ_MSG_DB_ERROR_LOG_MAX:=1048576}"

# Current on-disk schema version. Bump whenever the schema (tables, columns,
# indexes managed by tt_db_init / tt_db_migrate_caller_audit_columns) changes so
# tt_db_ensure_init migrates existing DBs instead of short-circuiting on file
# existence. Version 2 folds the additive caller-audit columns into the gated
# schema (they existed pre-E1 but were only reached via a full reinstall).
# Version 3 adds the auth_path + anchor_pid attribution columns (additive,
# nullable), so existing v2 DBs migrate on next write.
# Version 4 adds tasks.owner_alias (additive, nullable): the issuing column
# ("<session>/<owner_alias>" alias part) recorded for query/audit of the
# owner-scoped cache; legacy rows keep NULL and are never back-filled by guess.
# Version 5 adds tasks.owner_session (additive, nullable) so task-row mutations
# (tt_db_transition_task, expired transitions) match on the full composite
# (owner_session + owner_alias + task_id); an owner-less caller may only touch
# legacy rows where both owner columns are NULL, never a new owned row.
# Version 6 rebuilds tasks so identity is the composite
# UNIQUE(owner_session, owner_alias, target, task_id) (task_id is no longer a
# global PRIMARY KEY): a same task_id from a different owner/target no longer
# overwrites an existing row. A partial UNIQUE(task_id) WHERE both owner columns
# are NULL keeps owner-less legacy upserts idempotent (SQLite treats NULLs in the
# composite as distinct, which would otherwise let ownerless repeats grow rows).
# Version 7 adds platform-observed lifecycle evidence and verification/report
# timestamps without persisting arbitrary response bodies.
# Version 8 adds durable task contract metadata plus cancellation/freeze
# tombstones and one-shot receiver notice bookkeeping.
: "${TT_DB_SCHEMA_VERSION:=8}"

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

# E2 (msg-repair): rotate the error log to <log>.1 once it passes the size cap,
# so repeated sqlite failures can't grow it without bound. Best-effort; matches
# the D4 flush-worker log rotate (stat -f%z). Direct `2>>` appends elsewhere in
# this file are size-capped here too, since every logical error path funnels
# through tt_db_log_error, which checks total size before appending.
tt_db_rotate_error_log() {
  local f="$TPROJ_MSG_DB_ERROR_LOG"
  [[ -f "$f" ]] || return 0
  [[ $(stat -f%z "$f" 2>/dev/null || echo 0) -gt $TPROJ_MSG_DB_ERROR_LOG_MAX ]] || return 0
  mv -f "$f" "${f}.1" 2>/dev/null || true
}

tt_db_log_error() {
  tt_db_ensure_dirs
  tt_db_rotate_error_log
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
  msg_hash     TEXT,
  owner_alias  TEXT,
  owner_session TEXT
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
  tt_db_migrate_caller_audit_columns
  tt_db_migrate_task_owner_column
  tt_db_migrate_tasks_composite_identity
  tt_db_migrate_task_lifecycle_columns
  tt_db_migrate_task_contract_columns
  tt_db_sweep_orphaned_queued
  # Stamp user_version last, so it only advances after every migration above has
  # run. This is the version tt_db_ensure_init compares against on later calls.
  tt_db_exec_safe "PRAGMA user_version = ${TT_DB_SCHEMA_VERSION};" >/dev/null
}

# Schema v7 migration - append-only lifecycle evidence for delegated tasks.
# The JSON cache remains the open-task control surface; these nullable columns
# record observed facts without persisting arbitrary response bodies.
tt_db_migrate_task_lifecycle_columns() {
  tt_db_guard || return 0
  local existing_cols col def
  existing_cols=$(tt_db_exec_safe "PRAGMA table_info(tasks);" 2>/dev/null)
  while IFS='|' read -r col def; do
    [[ -n "$col" ]] || continue
    printf '%s' "$existing_cols" | grep -q "|${col}|" && continue
    tt_db_exec_safe "ALTER TABLE tasks ADD COLUMN ${col} ${def};" >/dev/null
  done <<'COLS'
orch_received_at|INTEGER
orch_verified_at|INTEGER
user_reported_at|INTEGER
done_message_id|INTEGER
done_body_hash|TEXT
verification_summary|TEXT
verification_hash|TEXT
COLS
}

# Schema v8 migration - task contract metadata and durable tombstones. All
# fields remain structural or hashed; no delegated body/prompt text is stored.
tt_db_migrate_task_contract_columns() {
  tt_db_guard || return 0
  local existing_cols col def
  existing_cols=$(tt_db_exec_safe "PRAGMA table_info(tasks);" 2>/dev/null)
  while IFS='|' read -r col def; do
    [[ -n "$col" ]] || continue
    printf '%s' "$existing_cols" | grep -q "|${col}|" && continue
    tt_db_exec_safe "ALTER TABLE tasks ADD COLUMN ${col} ${def};" >/dev/null
  done <<'COLS'
task_kind|TEXT
intent_hash|TEXT
user_authorized_exact|INTEGER
role_handoff_epoch|INTEGER
orchestrator_alias|TEXT
cancelled_at|INTEGER
frozen_at|INTEGER
tombstone_reason_hash|TEXT
worker_notice_state|TEXT
worker_notice_at|INTEGER
COLS
}

# D3 (msg-repair): one-shot idempotent sweep of pre-D3 orphaned 'queued' rows.
# Before D3, a successful flush inserted a NEW 'flushed' row and never advanced
# the original 'queued' row, so ~260 rows are stuck in 'queued' forever. Mark
# aged (>= 600s old), still-queued, never-delivered rows as 'orphaned-legacy'.
# Idempotent and safe to re-run: it only touches rows older than the flush
# stale window, so genuinely in-flight queued rows (< 600s) are never affected.
# Interim measure until E1's PRAGMA user_version migration gate lands.
tt_db_sweep_orphaned_queued() {
  tt_db_guard || return 0
  tt_db_exec_safe "UPDATE messages SET delivery='orphaned-legacy' WHERE delivery='queued' AND delivered_at IS NULL AND created_at < (strftime('%s','now') - 600);" >/dev/null
}

# R2 Stage 1 migration — additive caller-identity audit columns on the
# existing messages table. Idempotent: checks PRAGMA table_info before each
# ALTER rather than relying on ADD COLUMN IF NOT EXISTS (unsupported by the
# sqlite3 CLI build installed on this host despite library version 3.51).
# Existing rows get the safe fail-closed default verified=0; every other
# new column defaults to NULL for pre-migration history. Never stores
# message body/title content -- see tt_db_log_caller_event.
tt_db_migrate_caller_audit_columns() {
  tt_db_guard || return 0
  local existing_cols
  existing_cols=$(tt_db_exec_safe "PRAGMA table_info(messages);" 2>/dev/null)
  local col def
  while IFS='|' read -r col def; do
    [[ -n "$col" ]] || continue
    printf '%s' "$existing_cols" | grep -q "|${col}|" && continue
    tt_db_exec_safe "ALTER TABLE messages ADD COLUMN ${col} ${def};" >/dev/null
  done <<'COLS'
caller_pid|INTEGER
caller_ppid|INTEGER
caller_executable|TEXT
caller_uid|INTEGER
process_start|INTEGER
claimed_alias|TEXT
verified|INTEGER NOT NULL DEFAULT 0
rejection_reason|TEXT
payload_sha256|TEXT
auth_path|TEXT
anchor_pid|INTEGER
COLS
}

# Schema v4/v5 migration — additive nullable tasks.owner_alias (v4) and
# tasks.owner_session (v5) columns. They record the issuing owner of an
# owner-scoped cache entry so task-row mutations match the full composite.
# Idempotent: checks PRAGMA table_info before each ALTER (same idiom as the
# caller-audit migration, since this sqlite3 CLI build lacks ADD COLUMN IF NOT
# EXISTS). Legacy task rows keep both columns NULL and are never back-filled.
tt_db_migrate_task_owner_column() {
  tt_db_guard || return 0
  local existing_cols col def
  existing_cols=$(tt_db_exec_safe "PRAGMA table_info(tasks);" 2>/dev/null)
  while IFS='|' read -r col def; do
    [[ -n "$col" ]] || continue
    printf '%s' "$existing_cols" | grep -q "|${col}|" && continue
    tt_db_exec_safe "ALTER TABLE tasks ADD COLUMN ${col} ${def};" >/dev/null
  done <<'COLS'
owner_alias|TEXT
owner_session|TEXT
COLS
}

# Schema v6 migration — rebuild tasks so identity is the composite
# UNIQUE(owner_session, owner_alias, target, task_id) instead of a global task_id
# PRIMARY KEY. SQLite cannot alter a PK in place, so create a rowid table, copy
# rows, drop, rename, then build the indexes. A partial UNIQUE(task_id) WHERE both
# owner columns are NULL keeps owner-less legacy upserts idempotent (NULLs in the
# composite are distinct, so without this a repeated ownerless upsert would insert
# new rows). Pre-migration task_id was PRIMARY KEY (globally unique), so no copied
# row can violate either new unique index.
#
# Atomicity + crash recovery (R4-1): the entire rebuild runs in ONE
# BEGIN IMMEDIATE ... COMMIT, so an interruption rolls the whole thing back and
# never leaves tasks half-migrated. An earlier NON-atomic build (shipped once)
# could crash after DROP TABLE tasks but before renaming its temp, leaving a
# `tasks_rebuild` survivor holding the only copy of the rows. This migration
# detects that survivor and folds its rows back in (by task_id) BEFORE dropping
# it, so no history is lost. Idempotent: gated on BOTH identity indexes existing.
tt_db_migrate_tasks_composite_identity() {
  tt_db_guard || return 0
  local have_owner have_legacy
  have_owner=$(tt_db_exec_safe "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_owner_identity';" 2>/dev/null | tr -d '[:space:]')
  have_legacy=$(tt_db_exec_safe "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_legacy_identity';" 2>/dev/null | tr -d '[:space:]')
  # Fully migrated only when BOTH identity indexes exist. Checking just the owner
  # index would early-return on a late-interrupted prior run that created the
  # owner index but crashed before the (partial) legacy index -- leaving the
  # ownerless upsert's ON CONFLICT(task_id) WHERE ... with no matching UNIQUE
  # index (rows silently rejected).
  [[ -n "$have_owner" && -n "$have_legacy" ]] && return 0

  if [[ -n "$have_owner" ]]; then
    # The table was already rebuilt (owner index exists => the rowid/no-PK table
    # was renamed in); only an index is missing. Repair by (re)creating the
    # identity indexes -- no table rebuild needed -- atomically.
    tt_db_exec_safe "
BEGIN IMMEDIATE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_owner_identity ON tasks(owner_session, owner_alias, target, task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_legacy_identity ON tasks(task_id) WHERE owner_session IS NULL AND owner_alias IS NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_expect ON tasks(target, state, expect_until);
COMMIT;
" >/dev/null
    return 0
  fi

  # Neither identity index -> full rebuild (with survivor recovery).
  # Recover rows from a survivor temp table left by an interrupted pre-atomic run.
  local survivor recover_sql=""
  survivor=$(tt_db_exec_safe "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks_rebuild';" 2>/dev/null | tr -d '[:space:]')
  if [[ -n "$survivor" ]]; then
    recover_sql="INSERT INTO tasks_new (task_id, target, sent_at, expect_until, ttl_sec, state, ack_at, done_at, block_at, msg_hash, owner_alias, owner_session)
  SELECT task_id, target, sent_at, expect_until, ttl_sec, state, ack_at, done_at, block_at, msg_hash, owner_alias, owner_session FROM tasks_rebuild
  WHERE task_id NOT IN (SELECT task_id FROM tasks_new);"
  fi
  tt_db_exec_safe "
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT, target TEXT, sent_at INTEGER, expect_until INTEGER, ttl_sec INTEGER,
  state TEXT, ack_at INTEGER, done_at INTEGER, block_at INTEGER, msg_hash TEXT,
  owner_alias TEXT, owner_session TEXT
);
DROP TABLE IF EXISTS tasks_new;
CREATE TABLE tasks_new (
  task_id      TEXT NOT NULL,
  target       TEXT NOT NULL,
  sent_at      INTEGER NOT NULL,
  expect_until INTEGER NOT NULL,
  ttl_sec      INTEGER NOT NULL,
  state        TEXT NOT NULL,
  ack_at       INTEGER,
  done_at      INTEGER,
  block_at     INTEGER,
  msg_hash     TEXT,
  owner_alias  TEXT,
  owner_session TEXT
);
INSERT INTO tasks_new (task_id, target, sent_at, expect_until, ttl_sec, state, ack_at, done_at, block_at, msg_hash, owner_alias, owner_session)
  SELECT task_id, target, sent_at, expect_until, ttl_sec, state, ack_at, done_at, block_at, msg_hash, owner_alias, owner_session FROM tasks;
${recover_sql}
DROP TABLE IF EXISTS tasks_rebuild;
DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_owner_identity ON tasks(owner_session, owner_alias, target, task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_legacy_identity ON tasks(task_id) WHERE owner_session IS NULL AND owner_alias IS NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_expect ON tasks(target, state, expect_until);
COMMIT;
" >/dev/null
}

# Lazy init guard: call before any write. Creates the DB when the file is
# missing (handles env override TPROJ_MSG_DB_PATH switching between sessions
# and test scenarios that wipe the DB file). When the DB already exists, gate
# additive migrations on PRAGMA user_version: if the recorded version is behind
# the current schema, re-run tt_db_init (fully idempotent -- CREATE ... IF NOT
# EXISTS, column-existence-checked ALTERs, aged-row sweep) and re-stamp the
# version. This closes the pre-E1 gap where a schema bump never reached an
# existing DB (the 2026-07-16 156-insert-failure class) without requiring a
# full reinstall. Fail-open: a version read error leaves recorded=0, which
# triggers a safe no-op re-init rather than skipping the migration.
tt_db_ensure_init() {
  tt_db_guard || return 0
  if [[ ! -f "$TPROJ_MSG_DB_PATH" ]]; then
    tt_db_init
    return 0
  fi
  local recorded
  recorded=$(tt_db_exec_safe "PRAGMA user_version;" 2>/dev/null | tr -dc '0-9')
  [[ -n "$recorded" ]] || recorded=0
  if (( recorded < TT_DB_SCHEMA_VERSION )); then
    tt_db_init
  fi
  return 0
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

# R2 Stage 1 — caller identity verification audit trail. Records an
# accept or reject decision for a claimed --as sender, independent of
# whether the underlying message is ever delivered. Never persists
# message body/title content: `body`/`body_hash` are always empty for
# these rows, and payload_sha256 is the only content reference kept.
# Args (15, first 6 required):
#   session to_alias claimed_alias verified(0|1) rejection_reason
#   payload_sha256 [caller_pid=0] [caller_ppid=0] [caller_executable=]
#   [caller_uid=0] [process_start=0] [header=] [task_id=] [auth_path=]
#   [anchor_pid=0]
# caller_* describe the REAL direct invoker (this tproj-msg's parent), captured
# regardless of the verify outcome; anchor_pid is the verification anchor
# (pane_pid / registry reg_pid / service pid). On a spoof reject these diverge,
# which is what makes the reject row usable for attribution.
# Echoes new id on stdout (empty on failure).
tt_db_log_caller_event() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local session=$(tt_db_quote "${1:-}")
  local to_a=$(tt_db_quote "${2:-}")
  local claimed_alias=$(tt_db_quote "${3:-}")
  local verified="${4:-0}"
  local rejection_reason_raw="${5:-}"
  local payload_sha=$(tt_db_quote "${6:-}")
  local caller_pid="${7:-0}"
  local caller_ppid="${8:-0}"
  local caller_executable=$(tt_db_quote "${9:-}")
  local caller_uid="${10:-0}"
  local process_start="${11:-0}"
  local header=$(tt_db_quote "${12:-}")
  local task_id_raw="${13:-}"
  local auth_path_raw="${14:-}"
  local anchor_pid="${15:-0}"
  [[ "$verified" =~ ^[01]$ ]] || verified=0
  [[ "$caller_pid" =~ ^[0-9]+$ ]] || caller_pid=0
  [[ "$caller_ppid" =~ ^[0-9]+$ ]] || caller_ppid=0
  [[ "$caller_uid" =~ ^[0-9]+$ ]] || caller_uid=0
  [[ "$process_start" =~ ^[0-9]+$ ]] || process_start=0
  [[ "$anchor_pid" =~ ^[0-9]+$ ]] || anchor_pid=0
  local rejection_reason_sql='NULL'
  [[ -n "$rejection_reason_raw" ]] && rejection_reason_sql="'$(tt_db_quote "$rejection_reason_raw")'"
  local auth_path_sql='NULL'
  [[ -n "$auth_path_raw" ]] && auth_path_sql="'$(tt_db_quote "$auth_path_raw")'"
  local task_id_sql='NULL'
  [[ -n "$task_id_raw" ]] && task_id_sql="'$(tt_db_quote "$task_id_raw")'"
  local delivery='rejected'
  [[ "$verified" == "1" ]] && delivery='send-keys'
  local sql="INSERT INTO messages (session, from_alias, to_alias, body, body_hash, header, task_id, direction, delivery, source_kind, bridge, external_id, created_at, caller_pid, caller_ppid, caller_executable, caller_uid, process_start, claimed_alias, verified, rejection_reason, payload_sha256, auth_path, anchor_pid) VALUES ('${session}', '${claimed_alias}', '${to_a}', '', '', '${header}', ${task_id_sql}, 'outbound', '${delivery}', 'cc', 'tmux', NULL, strftime('%s','now'), ${caller_pid}, ${caller_ppid}, '${caller_executable}', ${caller_uid}, ${process_start}, '${claimed_alias}', ${verified}, ${rejection_reason_sql}, '${payload_sha}', ${auth_path_sql}, ${anchor_pid}); SELECT last_insert_rowid();"
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

# D3 (msg-repair): advance a previously-queued row to its terminal delivered
# state in place, instead of inserting a second 'flushed' row. Args: msg_id.
tt_db_set_flushed() {
  tt_db_guard || return 0
  local msg_id="${1:-}"
  [[ "$msg_id" =~ ^[0-9]+$ ]] || return 0
  tt_db_exec_safe "UPDATE messages SET delivery='flushed', delivered_at=strftime('%s','now') WHERE id=${msg_id};" >/dev/null
}

# D3 (msg-repair): mark a queued row as dropped with a reason, in place.
# Args: msg_id state(dropped-stale|dropped-gone|dropped-policy) [err].
tt_db_set_dropped() {
  tt_db_guard || return 0
  local msg_id="${1:-}" state="${2:-dropped-policy}" err
  err=$(tt_db_quote "${3:-}")
  [[ "$msg_id" =~ ^[0-9]+$ ]] || return 0
  case "$state" in
    dropped-stale|dropped-gone|dropped-policy) ;;
    *) state='dropped-policy' ;;
  esac
  tt_db_exec_safe "UPDATE messages SET delivery='${state}', delivery_err='${err}' WHERE id=${msg_id};" >/dev/null
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

# Args: task_id target sent_at ttl_sec msg_hash [owner_alias] [owner_session]
#       [task_kind] [intent_hash] [user_authorized_exact]
#       [role_handoff_epoch] [orchestrator_alias]
# owner_alias/owner_session (additive, nullable) are the issuing column of the
# owner-scoped cache. An empty owner value is stored NULL and never clobbers a
# known value on conflict (COALESCE), so a later upsert without owner cannot
# erase attribution. Optional contract metadata is structural or hashed only.
tt_db_upsert_task() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local task_id=$(tt_db_quote "${1:-}")
  local target=$(tt_db_quote "${2:-}")
  local sent_at="${3:-0}"
  local ttl_sec="${4:-1800}"
  local msg_hash=$(tt_db_quote "${5:-}")
  local owner_alias_raw="${6:-}"
  local owner_session_raw="${7:-}"
  local task_kind_raw="${8:-}"
  local intent_hash_raw="${9:-}"
  local user_authorized_exact_raw="${10:-0}"
  local role_handoff_epoch_raw="${11:-}"
  local orchestrator_alias_raw="${12:-}"
  [[ -z "$task_id" ]] && return 0
  local expect_until=$((sent_at + ttl_sec))
  local task_kind_sql="NULL" intent_hash_sql="NULL" user_authorized_exact_sql=0
  local role_handoff_epoch_sql="NULL" orchestrator_alias_sql="NULL"
  [[ -n "$task_kind_raw" ]] && task_kind_sql="'$(tt_db_quote "$task_kind_raw")'"
  [[ "$intent_hash_raw" =~ ^[A-Fa-f0-9]{16,128}$ ]] && intent_hash_sql="'$(tt_db_quote "$intent_hash_raw")'"
  [[ "$user_authorized_exact_raw" == "1" ]] && user_authorized_exact_sql=1
  [[ "$role_handoff_epoch_raw" =~ ^[0-9]+$ ]] && role_handoff_epoch_sql="$role_handoff_epoch_raw"
  [[ -n "$orchestrator_alias_raw" ]] && orchestrator_alias_sql="'$(tt_db_quote "$orchestrator_alias_raw")'"
  if [[ -n "$owner_alias_raw" && -n "$owner_session_raw" ]]; then
    # Owned row: identity is the composite. task_id from a different owner or a
    # different target inserts a distinct row instead of overwriting this one.
    local oa=$(tt_db_quote "$owner_alias_raw")
    local os=$(tt_db_quote "$owner_session_raw")
    tt_db_exec_safe "INSERT INTO tasks (task_id, target, sent_at, expect_until, ttl_sec, state, msg_hash, owner_alias, owner_session, task_kind, intent_hash, user_authorized_exact, role_handoff_epoch, orchestrator_alias) VALUES ('${task_id}', '${target}', ${sent_at}, ${expect_until}, ${ttl_sec}, 'pending', '${msg_hash}', '${oa}', '${os}', ${task_kind_sql}, ${intent_hash_sql}, ${user_authorized_exact_sql}, ${role_handoff_epoch_sql}, ${orchestrator_alias_sql}) ON CONFLICT(owner_session, owner_alias, target, task_id) DO UPDATE SET sent_at=excluded.sent_at, expect_until=excluded.expect_until, ttl_sec=excluded.ttl_sec, msg_hash=excluded.msg_hash, task_kind=COALESCE(excluded.task_kind, task_kind), intent_hash=COALESCE(excluded.intent_hash, intent_hash), user_authorized_exact=CASE WHEN excluded.user_authorized_exact = 1 THEN 1 ELSE user_authorized_exact END, role_handoff_epoch=COALESCE(excluded.role_handoff_epoch, role_handoff_epoch), orchestrator_alias=COALESCE(excluded.orchestrator_alias, orchestrator_alias);" >/dev/null
  else
    # Legacy / owner-less: conflict on the partial UNIQUE(task_id) WHERE both
    # owner columns are NULL, so repeated ownerless upserts of the same task_id
    # update the one legacy row instead of growing the table.
    tt_db_exec_safe "INSERT INTO tasks (task_id, target, sent_at, expect_until, ttl_sec, state, msg_hash, owner_alias, owner_session, task_kind, intent_hash, user_authorized_exact, role_handoff_epoch, orchestrator_alias) VALUES ('${task_id}', '${target}', ${sent_at}, ${expect_until}, ${ttl_sec}, 'pending', '${msg_hash}', NULL, NULL, ${task_kind_sql}, ${intent_hash_sql}, ${user_authorized_exact_sql}, ${role_handoff_epoch_sql}, ${orchestrator_alias_sql}) ON CONFLICT(task_id) WHERE owner_session IS NULL AND owner_alias IS NULL DO UPDATE SET target=excluded.target, sent_at=excluded.sent_at, expect_until=excluded.expect_until, ttl_sec=excluded.ttl_sec, msg_hash=excluded.msg_hash, task_kind=COALESCE(excluded.task_kind, task_kind), intent_hash=COALESCE(excluded.intent_hash, intent_hash), user_authorized_exact=CASE WHEN excluded.user_authorized_exact = 1 THEN 1 ELSE user_authorized_exact END, role_handoff_epoch=COALESCE(excluded.role_handoff_epoch, role_handoff_epoch), orchestrator_alias=COALESCE(excluded.orchestrator_alias, orchestrator_alias);" >/dev/null
  fi
}

# Args: task_id new_state [owner_session] [owner_alias] [target] [now_epoch]
#   new_state is one of: pending acked done blocked expired received verified
#   cancelled frozen user_reported.
# Sets the state-specific timestamp column when applicable. The UPDATE always
# matches the composite identity (task_id + owner [+ target when supplied], the
# same columns as the UNIQUE identity index). When owner_session and owner_alias
# are BOTH provided the row must match them exactly; when either is absent the
# update is restricted to LEGACY rows where both owner columns are NULL. There is
# no task_id-only UPDATE path -- an owner-less caller can never mutate a new owned
# row, and a caller from one owner/target can never transition another's task even
# on a task_id collision.
tt_db_transition_task() {
  tt_db_guard || return 0
  local task_id=$(tt_db_quote "${1:-}")
  local new_state="${2:-}"
  local owner_session_raw="${3:-}"
  local owner_alias_raw="${4:-}"
  local target_raw="${5:-}"
  local now="${6:-$(date +%s)}"
  [[ -z "$task_id" || -z "$new_state" ]] && return 0
  [[ "$now" =~ ^[0-9]+$ ]] || return 0
  local ts_col=''
  case "$new_state" in
    acked)   ts_col='ack_at' ;;
    done)    ts_col='done_at' ;;
    blocked) ts_col='block_at' ;;
    received) ts_col='orch_received_at' ;;
    verified) ts_col='orch_verified_at' ;;
    cancelled) ts_col='cancelled_at' ;;
    frozen) ts_col='frozen_at' ;;
    user_reported) ts_col='user_reported_at' ;;
    expired|pending) ts_col='' ;;
    *) return 0 ;;
  esac
  local ts_set=''
  [[ -n "$ts_col" ]] && ts_set=", ${ts_col}=COALESCE(${ts_col}, ${now})"
  local state_where
  case "$new_state" in
    pending)       state_where="state='pending'" ;;
    acked)         state_where="state IN ('pending','acked')" ;;
    done)          state_where="state IN ('pending','acked','done')" ;;
    blocked)       state_where="state IN ('pending','acked','blocked')" ;;
    received)      state_where="state IN ('done','blocked','received')" ;;
    verified)      state_where="state IN ('received','verified')" ;;
    cancelled)     state_where="state IN ('pending','acked','done','blocked','received','verified','cancelled')" ;;
    frozen)        state_where="state IN ('pending','acked','done','blocked','received','verified','frozen')" ;;
    user_reported) state_where="state IN ('verified','user_reported')" ;;
    expired)       state_where="state IN ('pending','acked','expired')" ;;
  esac
  local owner_where
  if [[ -n "$owner_session_raw" && -n "$owner_alias_raw" ]]; then
    owner_where="owner_session='$(tt_db_quote "$owner_session_raw")' AND owner_alias='$(tt_db_quote "$owner_alias_raw")'"
  else
    owner_where="owner_session IS NULL AND owner_alias IS NULL"
  fi
  local target_where=''
  [[ -n "$target_raw" ]] && target_where=" AND target='$(tt_db_quote "$target_raw")'"
  tt_db_exec_safe "UPDATE tasks SET state='${new_state}'${ts_set} WHERE task_id='${task_id}' AND ${owner_where}${target_where} AND ${state_where};" >/dev/null
}

# Args: task_id tombstone_state owner_session owner_alias target reason_hash
#       [now_epoch]
tt_db_tombstone_task() {
  tt_db_guard || return 0
  local task_id_raw="${1:-}" tombstone_state="${2:-}" owner_session_raw="${3:-}"
  local owner_alias_raw="${4:-}" target_raw="${5:-}" reason_hash_raw="${6:-}"
  local now="${7:-$(date +%s)}"
  [[ "$tombstone_state" == "cancelled" || "$tombstone_state" == "frozen" ]] || return 0
  [[ -n "$task_id_raw" && -n "$owner_session_raw" && -n "$owner_alias_raw" && -n "$target_raw" ]] || return 0
  [[ "$reason_hash_raw" =~ ^[A-Za-z0-9._:-]{8,128}$ && "$now" =~ ^[0-9]+$ ]] || return 0
  local task_id owner_session owner_alias target reason_hash ts_col
  task_id=$(tt_db_quote "$task_id_raw")
  owner_session=$(tt_db_quote "$owner_session_raw")
  owner_alias=$(tt_db_quote "$owner_alias_raw")
  target=$(tt_db_quote "$target_raw")
  reason_hash=$(tt_db_quote "$reason_hash_raw")
  [[ "$tombstone_state" == "cancelled" ]] && ts_col=cancelled_at || ts_col=frozen_at
  tt_db_exec_safe "UPDATE tasks SET state='${tombstone_state}', ${ts_col}=COALESCE(${ts_col}, ${now}), tombstone_reason_hash='${reason_hash}', worker_notice_state=NULL, worker_notice_at=NULL WHERE task_id='${task_id}' AND owner_session='${owner_session}' AND owner_alias='${owner_alias}' AND target='${target}' AND state IN ('pending','acked','done','blocked','received','verified','${tombstone_state}');" >/dev/null
}

# Args: task_id message_id body_hash owner_session owner_alias target
#       owner_recipient terminal_state [now_epoch]
tt_db_record_done_evidence() {
  tt_db_guard || return 1
  tt_db_ensure_init
  local task_id_raw="${1:-}" message_id="${2:-}" body_hash_raw="${3:-}"
  local owner_session_raw="${4:-}" owner_alias_raw="${5:-}" target_raw="${6:-}"
  local owner_recipient_raw="${7:-}" terminal_state="${8:-done}" now="${9:-$(date +%s)}"
  [[ "$message_id" =~ ^[0-9]+$ && "$body_hash_raw" =~ ^[A-Za-z0-9._:-]{8,128}$ ]] || return 2
  [[ "$terminal_state" == "done" || "$terminal_state" == "blocked" ]] || return 2
  [[ -n "$task_id_raw" && -n "$owner_session_raw" && -n "$owner_alias_raw" && -n "$target_raw" ]] || return 2
  [[ "$owner_recipient_raw" == "${owner_alias_raw}.cc" || "$owner_recipient_raw" == "${owner_alias_raw}.cdx" ]] || return 2
  [[ "$now" =~ ^[0-9]+$ ]] || return 2
  local task_id owner_session owner_alias target owner_recipient body_hash ts_col evidence_marker evidence_count
  task_id=$(tt_db_quote "$task_id_raw")
  owner_session=$(tt_db_quote "$owner_session_raw")
  owner_alias=$(tt_db_quote "$owner_alias_raw")
  target=$(tt_db_quote "$target_raw")
  owner_recipient=$(tt_db_quote "$owner_recipient_raw")
  body_hash=$(tt_db_quote "$body_hash_raw")
  [[ "$terminal_state" == "done" ]] && ts_col=done_at || ts_col=block_at
  [[ "$terminal_state" == "done" ]] && evidence_marker="[DONE: ${task_id_raw}]" || evidence_marker="[BLOCK: ${task_id_raw}]"
  evidence_marker=$(tt_db_quote "$evidence_marker")
  evidence_count=$(tt_db_exec_safe "SELECT count(*) FROM messages WHERE id=${message_id} AND body_hash='${body_hash}' AND from_alias='${target}' AND to_alias='${owner_recipient}' AND direction='inbound' AND instr(body, '${evidence_marker}') > 0;" 2>/dev/null || true)
  if [[ "$terminal_state" == blocked && "$evidence_count" != 1 ]]; then
    evidence_marker=$(tt_db_quote "[BLOCKED: ${task_id_raw}]")
    evidence_count=$(tt_db_exec_safe "SELECT count(*) FROM messages WHERE id=${message_id} AND body_hash='${body_hash}' AND from_alias='${target}' AND to_alias='${owner_recipient}' AND direction='inbound' AND instr(body, '${evidence_marker}') > 0;" 2>/dev/null || true)
  fi
  [[ "$evidence_count" == 1 ]] || return 3
  tt_db_exec_safe "UPDATE tasks SET state='${terminal_state}', ${ts_col}=COALESCE(${ts_col}, ${now}), done_message_id=COALESCE(done_message_id, ${message_id}), done_body_hash=COALESCE(done_body_hash, '${body_hash}') WHERE task_id='${task_id}' AND owner_session='${owner_session}' AND owner_alias='${owner_alias}' AND target='${target}' AND state IN ('pending','acked','${terminal_state}');" >/dev/null
}

# Args: task_id owner_session owner_alias target summary verification_hash
#       [now_epoch]
tt_db_record_verification() {
  tt_db_guard || return 1
  tt_db_ensure_init
  local task_id_raw="${1:-}" owner_session_raw="${2:-}" owner_alias_raw="${3:-}"
  local target_raw="${4:-}" summary_raw="${5:-}" hash_raw="${6:-}"
  local now="${7:-$(date +%s)}"
  [[ -n "$task_id_raw" && -n "$owner_session_raw" && -n "$owner_alias_raw" && -n "$target_raw" ]] || return 2
  [[ -n "$summary_raw" && ${#summary_raw} -le 240 && "$summary_raw" != *$'\n'* ]] || return 2
  [[ "$hash_raw" =~ ^[A-Za-z0-9._:-]{8,128}$ && "$now" =~ ^[0-9]+$ ]] || return 2
  local task_id owner_session owner_alias target summary hash
  task_id=$(tt_db_quote "$task_id_raw")
  owner_session=$(tt_db_quote "$owner_session_raw")
  owner_alias=$(tt_db_quote "$owner_alias_raw")
  target=$(tt_db_quote "$target_raw")
  summary=$(tt_db_quote "$summary_raw")
  hash=$(tt_db_quote "$hash_raw")
  tt_db_exec_safe "UPDATE tasks SET state='verified', orch_verified_at=COALESCE(orch_verified_at, ${now}), verification_summary=COALESCE(verification_summary, '${summary}'), verification_hash=COALESCE(verification_hash, '${hash}') WHERE task_id='${task_id}' AND owner_session='${owner_session}' AND owner_alias='${owner_alias}' AND target='${target}' AND state='received' AND done_body_hash='${hash}';" >/dev/null
}

# Args: task_id owner_session owner_alias target
# Emits: state|done_message_id|done_body_hash|orch_received_at|orch_verified_at|user_reported_at
tt_db_task_lifecycle() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local task_id owner_session owner_alias target
  task_id=$(tt_db_quote "${1:-}")
  owner_session=$(tt_db_quote "${2:-}")
  owner_alias=$(tt_db_quote "${3:-}")
  target=$(tt_db_quote "${4:-}")
  [[ -n "$task_id" && -n "$owner_session" && -n "$owner_alias" && -n "$target" ]] || return 0
  tt_db_exec_safe "SELECT state || '|' || COALESCE(done_message_id,'') || '|' || COALESCE(done_body_hash,'') || '|' || COALESCE(orch_received_at,'') || '|' || COALESCE(orch_verified_at,'') || '|' || COALESCE(user_reported_at,'') FROM tasks WHERE task_id='${task_id}' AND owner_session='${owner_session}' AND owner_alias='${owner_alias}' AND target='${target}' LIMIT 1;"
}

# Args: task_id from_alias to_alias marker
# Emits latest exact inbound evidence as message_id<TAB>body_hash. The body is
# inspected only inside SQLite for marker matching and is never returned.
tt_db_find_lifecycle_evidence() {
  tt_db_guard || return 0
  tt_db_ensure_init
  local task_id from_alias to_alias marker
  task_id=$(tt_db_quote "${1:-}")
  from_alias=$(tt_db_quote "${2:-}")
  to_alias=$(tt_db_quote "${3:-}")
  marker=$(tt_db_quote "${4:-}")
  [[ -n "$task_id" && -n "$from_alias" && -n "$to_alias" && -n "$marker" ]] || return 0
  tt_db_exec_safe "SELECT id || char(9) || body_hash FROM messages WHERE from_alias='${from_alias}' AND to_alias='${to_alias}' AND direction='inbound' AND instr(body, '[${marker}: ${task_id}]') > 0 ORDER BY id DESC LIMIT 1;"
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

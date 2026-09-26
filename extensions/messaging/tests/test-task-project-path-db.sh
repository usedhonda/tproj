#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-task-project-db.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/errors.log"
export TPROJ_MSG_DB_INIT_FLAG="$WORK/init.stamp"
source "$ROOT/extensions/messaging/tproj-msg-db.sh"

# A v10 row is not silently made cross-session eligible during migration.
sqlite3 "$TPROJ_MSG_DB_PATH" <<'SQL'
CREATE TABLE tasks (
  task_id TEXT, target TEXT, sent_at INTEGER, expect_until INTEGER,
  ttl_sec INTEGER, state TEXT, ack_at INTEGER, done_at INTEGER,
  block_at INTEGER, msg_hash TEXT, owner_alias TEXT, owner_session TEXT
);
INSERT INTO tasks VALUES ('old', 'worker', 1, 2, 1, 'pending', NULL, NULL, NULL, '', 'owner', 'session-a');
CREATE UNIQUE INDEX idx_tasks_owner_identity ON tasks(owner_session, owner_alias, target, task_id);
CREATE UNIQUE INDEX idx_tasks_legacy_identity ON tasks(task_id) WHERE owner_session IS NULL AND owner_alias IS NULL;
PRAGMA user_version = 10;
SQL
tt_db_ensure_init
[[ "$(sqlite3 "$TPROJ_MSG_DB_PATH" 'PRAGMA user_version;')" == 11 ]]
[[ "$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT coalesce(project_path, 'NULL') FROM tasks WHERE task_id='old';")" == NULL ]]

tt_db_upsert_task new worker 10 30 hash owner session-a role '' 0 1 orchestrator '/tmp/project'
[[ "$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT project_path FROM tasks WHERE task_id='new';")" == /tmp/project ]]
tt_db_upsert_task new worker 11 30 hash owner session-a
[[ "$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT project_path FROM tasks WHERE task_id='new';")" == /tmp/project ]]
[[ ! -s "$TPROJ_MSG_DB_ERROR_LOG" ]]
echo 'task project DB migration: ok'

#!/bin/bash
# Regression tests for tproj-inbox-check hook.
# Covers: P1 shell redirection fix (stderr-only capture), timeout emission,
# and false-positive prevention (pane stdout must not trigger notice).
#
# Usage: bash extensions/hooks/tests/test-inbox-check.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
HOOK_SRC="$REPO/extensions/hooks/tproj-inbox-check"
CACHE_LIB="$REPO/extensions/messaging/tproj-task-cache.sh"
[[ -x "$HOOK_SRC" && -f "$CACHE_LIB" ]] || { echo "fixtures not found under $REPO"; exit 2; }

PASS=0
FAIL=0
TARGET_NAME="testcdx"
ORIGINAL_HOME="$HOME"

setup_tmp() {
  TMP="$(mktemp -d)"
  cp "$HOOK_SRC" "$TMP/tproj-inbox-check"
  cp "$CACHE_LIB" "$TMP/tproj-task-cache.sh"
  mkdir -p "$TMP/cache" "$TMP/home"
  export HOME="$TMP/home"
  export TT_CACHE_DIR="$TMP/cache"
}

teardown_tmp() {
  [[ -n "${TMP:-}" && -d "$TMP" ]] && rm -rf "$TMP"
  export HOME="$ORIGINAL_HOME"
  unset TMP TT_CACHE_DIR
}

make_mock_msg() {
  local stdout_body="$1" stderr_body="$2"
  cat > "$TMP/tproj-msg" <<EOF
#!/bin/bash
[[ "\$1" == "--read" ]] || exit 0
printf '%s\n' "$stdout_body"
printf '%s\n' "$stderr_body" >&2
exit 0
EOF
  chmod +x "$TMP/tproj-msg"
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  PASS: $label"
  else
    FAIL=$((FAIL+1)); echo "  FAIL: $label"
    echo "    expected to contain: $needle"
    echo "    actual stdout: $haystack"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" label="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  PASS: $label"
  else
    FAIL=$((FAIL+1)); echo "  FAIL: $label"
    echo "    must not contain: $needle"
    echo "    actual stdout: $haystack"
  fi
}

seed_cache() {
  local task_id="$1" ttl="${2:-1800}"
  source "$TMP/tproj-task-cache.sh"
  tt_cache_add "$TARGET_NAME" "$task_id" "$(date +%s)" "$ttl" "hash-$task_id"
}

# Case A: normal reply — stderr emission of TASK_REPLIED triggers [inbox-notice] reply
echo "Case A: normal reply detection (stderr capture works)"
setup_tmp
make_mock_msg "pane dummy content" "TASK_REPLIED=task-a1"
seed_cache "task-a1"
out_a="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_contains "$out_a" "[inbox-notice] reply arrived from $TARGET_NAME task=task-a1" "reply notice emitted"
teardown_tmp

# Case B: timeout path — expired task in cache yields [inbox-notice] timeout
echo "Case B: timeout emission"
setup_tmp
make_mock_msg "no reply in pane" ""
# Seed with ttl=1 then backdate by overwriting cache file
seed_cache "task-b1" 1
sleep 2
out_b="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_contains "$out_b" "[inbox-notice] timeout on $TARGET_NAME task=task-b1" "timeout notice emitted"
assert_contains "$out_b" "current orchestrator should follow up, reassign, or take over" "timeout ownership wording is role-neutral"
teardown_tmp

# Case C: false-positive prevention — pane stdout contains TASK_REPLIED must be ignored
echo "Case C: false-positive prevention (stdout must not trigger)"
setup_tmp
make_mock_msg "TASK_REPLIED=task-c1 (should be ignored, this is pane capture stdout)" ""
seed_cache "task-c1"
out_c="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_not_contains "$out_c" "[inbox-notice] reply arrived from $TARGET_NAME task=task-c1" "stdout leak does not trigger reply notice"
teardown_tmp

# Case E: task expire (C5) — expired cache task yields the explicit no-ACK notice
# for the sender, alongside the existing timeout notice.
echo "Case E: task expired no-ACK notice (C5)"
setup_tmp
make_mock_msg "no reply in pane" ""
seed_cache "task-e1" 1
sleep 2
out_e="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_contains "$out_e" "[inbox-notice] task task-e1 expired (no ACK from $TARGET_NAME)" "C5 expired no-ACK notice emitted"
assert_contains "$out_e" "[inbox-notice] timeout on $TARGET_NAME task=task-e1" "C5 leaves the existing timeout notice intact"
teardown_tmp

# Case D: monitor cursor bootstrap (C1) — role-independent key, cold-start to MAX(id),
# legacy role-inclusive cursor left untouched (no backlog replay).
echo "Case D: monitor cursor role-independent bootstrap + cold-start (C1)"
if command -v sqlite3 >/dev/null 2>&1; then
  D_TMP="$(mktemp -d)"
  export TPROJ_MSG_DB_PATH="$D_TMP/messages.db"
  export TPROJ_MSG_DB_ERROR_LOG="$D_TMP/db-errors.log"
  ( source "$REPO/extensions/messaging/tproj-msg-db.sh"; tt_db_init ) >/dev/null 2>&1 || true
  sqlite3 "$TPROJ_MSG_DB_PATH" \
    "INSERT INTO messages (id, from_alias, to_alias, body, body_hash, direction, delivery, created_at) VALUES (100, 'x.cdx', 'mon.cc', 'b', 'h', 'inbound', 'send-keys', strftime('%s','now'));
     INSERT INTO monitor_cursors (consumer, last_message_id, updated_at) VALUES ('unit-sess:mon.cc', 5, strftime('%s','now'));" >/dev/null 2>&1 || true
  ( TMUX_SESSION="unit-sess" TPROJ_MONITOR_ALIAS="mon" TPROJ_MONITOR_ROLE="cc" \
      source "$REPO/extensions/messaging/tproj-inbox-monitor"; bootstrap_cursor ) >/dev/null 2>&1 || true
  new_val="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT last_message_id FROM monitor_cursors WHERE consumer='unit-sess:mon';" 2>/dev/null || true)"
  old_val="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT last_message_id FROM monitor_cursors WHERE consumer='unit-sess:mon.cc';" 2>/dev/null || true)"
  assert_contains "new=[$new_val]" "new=[100]" "C1 role-independent cursor cold-starts to MAX(id)"
  assert_contains "legacy=[$old_val]" "legacy=[5]" "C1 legacy role-inclusive cursor untouched (no replay)"
  rm -rf "$D_TMP"
  unset TPROJ_MSG_DB_PATH TPROJ_MSG_DB_ERROR_LOG
else
  echo "  SKIP: sqlite3 not available"
fi

echo
echo "Result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1

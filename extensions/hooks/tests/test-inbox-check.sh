#!/bin/bash
# Regression tests for tproj-inbox-check hook.
# Covers: P1 shell redirection fix (stderr-only capture), timeout emission,
# and false-positive prevention (pane stdout must not trigger notice).
#
# Usage: bash extensions/hooks/tests/test-inbox-check.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
HOOK_SRC="$REPO/extensions/hooks/tproj-inbox-check"
RECORD_SRC="$REPO/extensions/hooks/tproj-inbox-record"
CACHE_LIB="$REPO/extensions/messaging/tproj-task-cache.sh"
[[ -x "$HOOK_SRC" && -f "$CACHE_LIB" ]] || { echo "fixtures not found under $REPO"; exit 2; }

PASS=0
FAIL=0
TARGET_NAME="testcdx"
# Owner-scoped cache (v2): the hook resolves owner via TT_CACHE_OWNER in tests.
# OWNER_SELF is the hook's own column; OWNER_OTHER is a different column that must
# never leak into the self column's notices, --read, or mutations.
OWNER_SELF="testsess/testcol"
OWNER_OTHER="testsess/othercol"
ORIGINAL_HOME="$HOME"

setup_tmp() {
  TMP="$(mktemp -d)"
  cp "$HOOK_SRC" "$TMP/tproj-inbox-check"
  [[ -f "$RECORD_SRC" ]] && cp "$RECORD_SRC" "$TMP/tproj-inbox-record"
  cp "$CACHE_LIB" "$TMP/tproj-task-cache.sh"
  mkdir -p "$TMP/cache" "$TMP/home"
  export HOME="$TMP/home"
  export TT_CACHE_DIR="$TMP/cache"
  export TT_CACHE_OWNER="$OWNER_SELF"
}

teardown_tmp() {
  [[ -n "${TMP:-}" && -d "$TMP" ]] && rm -rf "$TMP"
  export HOME="$ORIGINAL_HOME"
  unset TMP TT_CACHE_DIR TT_CACHE_OWNER
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
  # Args: task_id [ttl=1800] [owner=$OWNER_SELF] [target=$TARGET_NAME] [sent_at=now]
  local task_id="$1" ttl="${2:-1800}" owner="${3:-$OWNER_SELF}" target="${4:-$TARGET_NAME}" sent="${5:-$(date +%s)}"
  source "$TMP/tproj-task-cache.sh"
  tt_cache_add "$owner" "$target" "$task_id" "$sent" "$ttl" "hash-$task_id"
}

# Mock tproj-msg that logs every --read <target> invocation to $TMP/read.log,
# so tests can assert which targets the hook did (not) --read.
make_logging_mock_msg() {
  local stderr_body="$1"
  cat > "$TMP/tproj-msg" <<EOF
#!/bin/bash
[[ "\$1" == "--read" ]] || exit 0
printf '%s\n' "\$2" >> "$TMP/read.log"
printf '%s\n' "$stderr_body" >&2
exit 0
EOF
  chmod +x "$TMP/tproj-msg"
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

# Case F (owner scoping): a task issued by column A (OWNER_OTHER) must NOT
# produce any reply notice in column B's (OWNER_SELF) check hook.
echo "Case F: cross-column task issues no reply notice (owner scoping)"
setup_tmp
# Adversarial: the mock returns TASK_REPLIED for the other column's task, yet the
# self-scoped hook must never enumerate it and so must never notice it.
make_mock_msg "pane dummy content" "TASK_REPLIED=task-other-1"
seed_cache "task-other-1" 1800 "$OWNER_OTHER"
out_f="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_not_contains "$out_f" "task-other-1" "no notice for another column's task"
teardown_tmp

# Case G (owner scoping): column B's hook must not --read column A's targets.
echo "Case G: hook does not --read another column's target"
setup_tmp
make_logging_mock_msg ""
# Only the other column has a task, on a distinctly-named target.
seed_cache "task-other-2" 1800 "$OWNER_OTHER" "othertgt"
TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" >/dev/null 2>&1 || true
read_log="$(cat "$TMP/read.log" 2>/dev/null || true)"
assert_not_contains "$read_log" "othertgt" "self-column hook did not --read other column's target"
teardown_tmp

# Case H (owner scoping): removing on the self owner cannot mutate another
# column's cache (the do_read own-cache-limited mutation invariant, at the cache
# layer). A tag for OWNER_OTHER's task, acted on with OWNER_SELF, is a no-op.
echo "Case H: cross-owner remove is a no-op (do_read mutation isolation)"
setup_tmp
source "$TMP/tproj-task-cache.sh"
tt_cache_add "$OWNER_OTHER" "othertgt" "task-other-3" "$(date +%s)" 1800 "h3"
tt_cache_remove_task "$OWNER_SELF" "othertgt" "task-other-3" >/dev/null 2>&1 || true
still_there="$(tt_cache_get_task "$OWNER_OTHER" "othertgt" "task-other-3" 2>/dev/null || true)"
if [[ -n "$still_there" ]]; then
  PASS=$((PASS+1)); echo "  PASS: other column's cache entry survived a self-owner remove"
else
  FAIL=$((FAIL+1)); echo "  FAIL: other column's cache entry survived a self-owner remove"
fi
teardown_tmp

# Case I (owner scoping): expired GC notices only the self owner's task, not
# another column's expired task.
echo "Case I: expired GC scoped to self owner"
setup_tmp
make_mock_msg "no reply in pane" ""
seed_cache "task-self-exp" 1 "$OWNER_SELF"
seed_cache "task-other-exp" 1 "$OWNER_OTHER"
sleep 2
out_i="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_contains "$out_i" "[inbox-notice] timeout on $TARGET_NAME task=task-self-exp" "self owner's expired task noticed"
assert_not_contains "$out_i" "task-other-exp" "other owner's expired task not noticed"
teardown_tmp

# Case J (legacy drain): a pre-v2 flat file at the cache root is TTL-GC'd
# silently (no notice) and removed, without any owner attribution.
echo "Case J: legacy flat file drains silently"
setup_tmp
make_mock_msg "no reply in pane" ""
# Forge a legacy flat file with an already-expired entry (expect_until in past).
cat > "$TMP/cache/legacycdx.json" <<'EOF'
{"legacy-task-1":{"target":"legacycdx","sent_at":1,"expect_until":2,"ttl_sec":1,"msg_hash":"h"}}
EOF
out_j="$(TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" 2>/dev/null || true)"
assert_not_contains "$out_j" "legacy-task-1" "legacy flat task emits no notice"
[[ ! -f "$TMP/cache/legacycdx.json" ]] && { PASS=$((PASS+1)); echo "  PASS: legacy flat file drained (removed)"; } \
  || { FAIL=$((FAIL+1)); echo "  FAIL: legacy flat file drained (removed)"; }
teardown_tmp

# Case K (fail-closed): the record hook with an unresolvable/invalid owner writes
# NOTHING to the cache (never guesses a subdir); a valid owner writes to its own
# subdir. Skips gracefully if the record hook is absent.
echo "Case K: record hook is fail-closed on invalid owner"
if [[ -f "$RECORD_SRC" ]]; then
  setup_tmp
  payload='{"tool_name":"Bash","tool_input":{"command":"tproj-msg --new-task tproj.cdx hi"},"tool_response":{"stderr":"TASK_ID=fx-1 TASK_TARGET=tproj.cdx TASK_TTL_SEC=1800 TASK_SENT_AT=1734500000"}}'
  # Invalid owner (no slash) -> fail-closed, no write.
  printf '%s' "$payload" | TPROJ_HOOK_ENABLED=1 TT_CACHE_OWNER="badowner" "$TMP/tproj-inbox-record" >/dev/null 2>&1 || true
  wrote_bad="$(find "$TMP/cache" -name '*.json' 2>/dev/null | head -1)"
  if [[ -z "$wrote_bad" ]]; then
    PASS=$((PASS+1)); echo "  PASS: invalid owner wrote no cache file"
  else
    FAIL=$((FAIL+1)); echo "  FAIL: invalid owner wrote no cache file (found: $wrote_bad)"
  fi
  # Valid owner -> writes under its own subdir.
  printf '%s' "$payload" | TPROJ_HOOK_ENABLED=1 TT_CACHE_OWNER="$OWNER_SELF" "$TMP/tproj-inbox-record" >/dev/null 2>&1 || true
  [[ -f "$TMP/cache/$OWNER_SELF/tproj.cdx.json" ]] && { PASS=$((PASS+1)); echo "  PASS: valid owner wrote to its own subdir"; } \
    || { FAIL=$((FAIL+1)); echo "  FAIL: valid owner wrote to its own subdir"; }
  teardown_tmp
else
  echo "  SKIP: tproj-inbox-record not found"
fi

# Case L (composite task transition): a task row owned by one session/alias
# cannot be transitioned by another owner or by an owner-less call; only the
# exact composite (owner_session + owner_alias + task_id) updates it. A legacy
# NULL-owner row is still transitionable by an owner-less call.
echo "Case L: composite-scoped task transition isolation"
if command -v sqlite3 >/dev/null 2>&1; then
  L_TMP="$(mktemp -d)"
  export TPROJ_MSG_DB_PATH="$L_TMP/messages.db"
  export TPROJ_MSG_DB_ERROR_LOG="$L_TMP/db-errors.log"
  ( source "$REPO/extensions/messaging/tproj-msg-db.sh"
    tt_db_init
    tt_db_upsert_task tid-own tgt.cdx 1734500000 1800 h alA sessA
    tt_db_transition_task tid-own done sessB alA        # wrong session -> no-op
    tt_db_transition_task tid-own done                  # owner-less -> no-op
    tt_db_upsert_task tid-leg tgt.cdx 1734500000 1800 h # legacy NULL owner
    tt_db_transition_task tid-leg expired               # owner-less -> updates legacy
    tt_db_transition_task tid-own done sessA alA        # correct owner -> updates
  ) >/dev/null 2>&1 || true
  st_own="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT state FROM tasks WHERE task_id='tid-own';" 2>/dev/null || true)"
  st_leg="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT state FROM tasks WHERE task_id='tid-leg';" 2>/dev/null || true)"
  assert_contains "own=[$st_own]" "own=[done]" "owned row updates only via exact composite (wrong/owner-less ignored)"
  assert_contains "leg=[$st_leg]" "leg=[expired]" "legacy NULL-owner row transitionable by owner-less call"
  ver="$(sqlite3 "$TPROJ_MSG_DB_PATH" "PRAGMA user_version;" 2>/dev/null || true)"
  assert_contains "ver=[$ver]" "ver=[5]" "tasks schema at user_version 5"
  rm -rf "$L_TMP"
  unset TPROJ_MSG_DB_PATH TPROJ_MSG_DB_ERROR_LOG
else
  echo "  SKIP: sqlite3 not available"
fi

# Case M (path-component collision resistance): invalid components (slash, "..",
# empty, disallowed chars) are rejected and never reach a cache path; canonical
# workspace aliases pass; the lock name is injective (distinct owners that a
# '.'-join would collapse map to distinct lock names).
echo "Case M: path-component validation and injective locks"
setup_tmp
source "$TMP/tproj-task-cache.sh"
# Rejections.
for bad in "" "." ".." "a/b" "a b" 'a;b' 'a$b' "a..b/c"; do
  if tt_cache_valid_component "$bad" 2>/dev/null; then
    FAIL=$((FAIL+1)); echo "  FAIL: rejects invalid component [$bad]"
  else
    PASS=$((PASS+1)); echo "  PASS: rejects invalid component [$bad]"
  fi
done
# Canonical aliases accepted.
for ok in ble-bridge creator_radar tproj tproj-workspace tproj.cdx vibeterm; do
  if tt_cache_valid_component "$ok" 2>/dev/null; then
    PASS=$((PASS+1)); echo "  PASS: accepts canonical component [$ok]"
  else
    FAIL=$((FAIL+1)); echo "  FAIL: accepts canonical component [$ok]"
  fi
done
# Canonical owner accepted, traversal/degenerate owners rejected.
if tt_cache_valid_owner "tproj-workspace/ble-bridge" 2>/dev/null; then
  PASS=$((PASS+1)); echo "  PASS: accepts canonical owner"
else
  FAIL=$((FAIL+1)); echo "  FAIL: accepts canonical owner"
fi
for bad_owner in "a" "a/b/c" "sess/.." "../x/y" "unknown/unknown"; do
  if tt_cache_valid_owner "$bad_owner" 2>/dev/null; then
    FAIL=$((FAIL+1)); echo "  FAIL: rejects invalid owner [$bad_owner]"
  else
    PASS=$((PASS+1)); echo "  PASS: rejects invalid owner [$bad_owner]"
  fi
done
# tt_cache_add with a traversal target must refuse (return 2) and write nothing.
add_rc=0
tt_cache_add "$OWNER_SELF" "../evil" bad-1 "$(date +%s)" 1800 h || add_rc=$?
if [[ "$add_rc" -eq 2 ]]; then PASS=$((PASS+1)); echo "  PASS: add refuses traversal target (rc=2)"; else FAIL=$((FAIL+1)); echo "  FAIL: add refuses traversal target (rc=$add_rc)"; fi
stray="$(find "$TMP/cache" -name 'evil*' -o -name '*evil*' 2>/dev/null | head -1)"
if [[ -z "$stray" ]]; then PASS=$((PASS+1)); echo "  PASS: traversal target created no file"; else FAIL=$((FAIL+1)); echo "  FAIL: traversal target created no file ($stray)"; fi
# Lock injectivity: two distinct owners a '.'-join would collapse stay distinct.
l1="$(tt_cache_lock_for_target "a/b.c" t)"
l2="$(tt_cache_lock_for_target "a.b/c" t)"
if [[ "$l1" != "$l2" ]]; then PASS=$((PASS+1)); echo "  PASS: lock names injective across distinct owners"; else FAIL=$((FAIL+1)); echo "  FAIL: lock names injective across distinct owners"; fi
teardown_tmp

echo
echo "Result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1

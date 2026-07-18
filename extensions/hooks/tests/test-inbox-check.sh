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

DB_LIB="$REPO/extensions/messaging/tproj-msg-db.sh"

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

# Copy the DB helper next to the cached lib so a hook's `source
# tproj-task-cache.sh` also picks up tproj-msg-db.sh (DB-backed cases only).
setup_tmp_with_db() {
  setup_tmp
  cp "$DB_LIB" "$TMP/tproj-msg-db.sh"
  export TPROJ_MSG_DB_PATH="$TMP/messages.db"
  export TPROJ_MSG_DB_ERROR_LOG="$TMP/db-errors.log"
}

teardown_db() {
  unset TPROJ_MSG_DB_PATH TPROJ_MSG_DB_ERROR_LOG TT_OWNER_ROLE
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
  assert_contains "ver=[$ver]" "ver=[6]" "tasks schema at user_version 6"
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

# Case N (R1): notified_at is set on the row scoped to our session (+ recipient +
# sender + task_id), NOT the latest row with the same task_id in another session.
echo "Case N: notified_at scoping across same task_id in different sessions"
if command -v sqlite3 >/dev/null 2>&1; then
  setup_tmp_with_db
  export TT_OWNER_ROLE=cc
  ( source "$TMP/tproj-msg-db.sh"; tt_db_init ) >/dev/null 2>&1 || true
  # id 100 = our session's inbound row; id 200 = another session, same task_id,
  # inserted later (would win ORDER BY id DESC under the old task_id-only SELECT).
  sqlite3 "$TPROJ_MSG_DB_PATH" \
    "INSERT INTO messages (id, session, from_alias, to_alias, body, body_hash, task_id, direction, delivery, created_at) VALUES (100,'testsess','$TARGET_NAME','testcol.cc','b','h','shared-x','inbound','send-keys',strftime('%s','now'));
     INSERT INTO messages (id, session, from_alias, to_alias, body, body_hash, task_id, direction, delivery, created_at) VALUES (200,'othersess','$TARGET_NAME','othercol.cc','b','h','shared-x','inbound','send-keys',strftime('%s','now'));" >/dev/null 2>&1 || true
  make_mock_msg "pane dummy" "TASK_REPLIED=shared-x"
  seed_cache "shared-x" 1800 "$OWNER_SELF" "$TARGET_NAME"
  TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" >/dev/null 2>&1 || true
  n100="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT CASE WHEN notified_at IS NULL THEN 'null' ELSE 'set' END FROM messages WHERE id=100;" 2>/dev/null || true)"
  n200="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT CASE WHEN notified_at IS NULL THEN 'null' ELSE 'set' END FROM messages WHERE id=200;" 2>/dev/null || true)"
  assert_contains "own=[$n100]" "own=[set]" "notified_at set on our own session's row"
  assert_contains "other=[$n200]" "other=[null]" "notified_at NOT set on another session's same-task_id row"
  teardown_db
  teardown_tmp
else
  echo "  SKIP: sqlite3 not available"
fi

# Case N2 (R4-2): when our role cannot be resolved, the recipient predicate is
# unknown, so the notified update is skipped entirely (fail-closed). It must NOT
# fall back to session+sender+task_id and flag another recipient's row.
echo "Case N2: notified_at fail-closed when role is unknown"
if command -v sqlite3 >/dev/null 2>&1; then
  setup_tmp_with_db
  export TT_OWNER_ROLE=""   # role unknown (SET but empty)
  ( source "$TMP/tproj-msg-db.sh"; tt_db_init ) >/dev/null 2>&1 || true
  # Same session/sender/task; id 100 = us, id 200 = a different recipient (higher
  # id -> would win ORDER BY id DESC if the recipient predicate were dropped).
  sqlite3 "$TPROJ_MSG_DB_PATH" \
    "INSERT INTO messages (id, session, from_alias, to_alias, body, body_hash, task_id, direction, delivery, created_at) VALUES (100,'testsess','$TARGET_NAME','testcol.cc','b','h','role-x','inbound','send-keys',strftime('%s','now'));
     INSERT INTO messages (id, session, from_alias, to_alias, body, body_hash, task_id, direction, delivery, created_at) VALUES (200,'testsess','$TARGET_NAME','other.cc','b','h','role-x','inbound','send-keys',strftime('%s','now'));" >/dev/null 2>&1 || true
  make_mock_msg "pane dummy" "TASK_REPLIED=role-x"
  seed_cache "role-x" 1800 "$OWNER_SELF" "$TARGET_NAME"
  TPROJ_HOOK_ENABLED=1 "$TMP/tproj-inbox-check" >/dev/null 2>&1 || true
  r100="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT CASE WHEN notified_at IS NULL THEN 'null' ELSE 'set' END FROM messages WHERE id=100;" 2>/dev/null || true)"
  r200="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT CASE WHEN notified_at IS NULL THEN 'null' ELSE 'set' END FROM messages WHERE id=200;" 2>/dev/null || true)"
  assert_contains "r100=[$r100]" "r100=[null]" "role unknown: our own row is not notified (skipped)"
  assert_contains "r200=[$r200]" "r200=[null]" "role unknown: another recipient's row is not stolen"
  teardown_db
  teardown_tmp
else
  echo "  SKIP: sqlite3 not available"
fi

# Case O (R2): composite task identity. Same task_id from a different
# owner/target does not overwrite an existing row; repeated owner-less upserts of
# the same task_id stay idempotent (no row growth); a v5 DB migrates to v6
# preserving rows.
echo "Case O: composite task identity + legacy idempotency + v5->v6 migration"
if command -v sqlite3 >/dev/null 2>&1; then
  O_TMP="$(mktemp -d)"
  export TPROJ_MSG_DB_PATH="$O_TMP/messages.db"
  export TPROJ_MSG_DB_ERROR_LOG="$O_TMP/db-errors.log"
  # Fresh v6: collision + legacy idempotency.
  ( source "$REPO/extensions/messaging/tproj-msg-db.sh"
    tt_db_init
    tt_db_upsert_task collide tgtA 100 1800 h alA sessA
    tt_db_upsert_task collide tgtB 200 1800 h alB sessB   # different owner+target
    tt_db_upsert_task legrep tgtA 100 1800 h              # owner-less x3 (idempotent)
    tt_db_upsert_task legrep tgtA 100 1800 h
    tt_db_upsert_task legrep tgtA 100 1800 h
  ) >/dev/null 2>&1 || true
  n_collide="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM tasks WHERE task_id='collide';" 2>/dev/null || true)"
  n_legrep="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM tasks WHERE task_id='legrep';" 2>/dev/null || true)"
  ver6="$(sqlite3 "$TPROJ_MSG_DB_PATH" "PRAGMA user_version;" 2>/dev/null || true)"
  assert_contains "collide=[$n_collide]" "collide=[2]" "same task_id, different owner/target -> distinct rows (no overwrite)"
  assert_contains "legrep=[$n_legrep]" "legrep=[1]" "repeated owner-less upsert is idempotent (no row growth)"
  assert_contains "ver=[$ver6]" "ver=[6]" "fresh DB at user_version 6"
  rm -f "$TPROJ_MSG_DB_PATH"*
  # R4-1: TRUE v5 migration from a hand-crafted v5 schema (task_id PRIMARY KEY),
  # NOT `TT_DB_SCHEMA_VERSION=5 tt_db_init` (which would run the v6 migration
  # unconditionally). ensure_init at v6 must migrate, preserving rows.
  rm -f "$TPROJ_MSG_DB_PATH"*
  sqlite3 "$TPROJ_MSG_DB_PATH" "
    CREATE TABLE tasks (task_id TEXT PRIMARY KEY, target TEXT NOT NULL, sent_at INTEGER NOT NULL, expect_until INTEGER NOT NULL, ttl_sec INTEGER NOT NULL, state TEXT NOT NULL, ack_at INTEGER, done_at INTEGER, block_at INTEGER, msg_hash TEXT, owner_alias TEXT, owner_session TEXT);
    INSERT INTO tasks (task_id,target,sent_at,expect_until,ttl_sec,state,owner_alias,owner_session) VALUES ('m-own','tgtA',1,2,1,'pending','alA','sessA');
    INSERT INTO tasks (task_id,target,sent_at,expect_until,ttl_sec,state) VALUES ('m-leg','tgtB',1,2,1,'pending');
    PRAGMA user_version=5;" >/dev/null 2>&1 || true
  ( source "$REPO/extensions/messaging/tproj-msg-db.sh"; tt_db_ensure_init ) >/dev/null 2>&1 || true
  mig_ver="$(sqlite3 "$TPROJ_MSG_DB_PATH" "PRAGMA user_version;" 2>/dev/null || true)"
  mig_rows="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM tasks;" 2>/dev/null || true)"
  mig_idx="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM sqlite_master WHERE name IN ('idx_tasks_owner_identity','idx_tasks_legacy_identity');" 2>/dev/null || true)"
  mig_pk="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT pk FROM pragma_table_info('tasks') WHERE name='task_id';" 2>/dev/null || true)"
  assert_contains "mv=[$mig_ver]" "mv=[6]" "hand-crafted v5 DB migrates to user_version 6"
  assert_contains "mr=[$mig_rows]" "mr=[2]" "migration preserves existing task rows"
  assert_contains "mi=[$mig_idx]" "mi=[2]" "migration creates both composite/legacy identity indexes"
  assert_contains "pk=[$mig_pk]" "pk=[0]" "migration drops the task_id PRIMARY KEY"

  # R4-1 crash recovery: simulate a pre-atomic run interrupted after DROP tasks
  # but before renaming its temp (survivor tasks_rebuild holds the only rows,
  # tasks missing, user_version still 5). ensure_init must recover the rows.
  rm -f "$TPROJ_MSG_DB_PATH"*
  sqlite3 "$TPROJ_MSG_DB_PATH" "
    CREATE TABLE tasks (task_id TEXT PRIMARY KEY, target TEXT NOT NULL, sent_at INTEGER NOT NULL, expect_until INTEGER NOT NULL, ttl_sec INTEGER NOT NULL, state TEXT NOT NULL, ack_at INTEGER, done_at INTEGER, block_at INTEGER, msg_hash TEXT, owner_alias TEXT, owner_session TEXT);
    INSERT INTO tasks (task_id,target,sent_at,expect_until,ttl_sec,state,owner_alias,owner_session) VALUES ('s1','tgtA',1,2,1,'pending','alA','sessA');
    INSERT INTO tasks (task_id,target,sent_at,expect_until,ttl_sec,state) VALUES ('s2','tgtB',1,2,1,'pending');
    ALTER TABLE tasks RENAME TO tasks_rebuild;
    PRAGMA user_version=5;" >/dev/null 2>&1 || true
  ( source "$REPO/extensions/messaging/tproj-msg-db.sh"; tt_db_ensure_init ) >/dev/null 2>&1 || true
  rec_rows="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM tasks;" 2>/dev/null || true)"
  rec_data="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT group_concat(task_id) FROM (SELECT task_id FROM tasks ORDER BY task_id);" 2>/dev/null || true)"
  rec_survivor="$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT count(*) FROM sqlite_master WHERE name='tasks_rebuild';" 2>/dev/null || true)"
  rec_ver="$(sqlite3 "$TPROJ_MSG_DB_PATH" "PRAGMA user_version;" 2>/dev/null || true)"
  assert_contains "rr=[$rec_rows]" "rr=[2]" "interrupted-run survivor rows are recovered"
  assert_contains "rd=[$rec_data]" "rd=[s1,s2]" "recovered rows carry the original task ids"
  assert_contains "rs=[$rec_survivor]" "rs=[0]" "survivor temp table is dropped after recovery"
  assert_contains "rv=[$rec_ver]" "rv=[6]" "recovered DB reaches user_version 6"
  rm -rf "$O_TMP"
  unset TPROJ_MSG_DB_PATH TPROJ_MSG_DB_ERROR_LOG
else
  echo "  SKIP: sqlite3 not available"
fi

# Case P (R3): tt_cache_init_dir refuses an invalid owner without any mkdir, so a
# traversal owner cannot create a directory outside the cache root.
echo "Case P: init_dir is fail-closed against path traversal"
setup_tmp
source "$TMP/tproj-task-cache.sh"
init_rc=0
tt_cache_init_dir "../escape" || init_rc=$?
if [[ "$init_rc" -ne 0 ]]; then PASS=$((PASS+1)); echo "  PASS: init_dir returns non-zero on traversal owner"; else FAIL=$((FAIL+1)); echo "  FAIL: init_dir returns non-zero on traversal owner (rc=$init_rc)"; fi
# TT_CACHE_DIR is $TMP/cache, so owner "../escape" would resolve to $TMP/escape.
if [[ ! -d "$TMP/escape" ]]; then
  PASS=$((PASS+1)); echo "  PASS: no directory created outside the cache root"
else
  FAIL=$((FAIL+1)); echo "  FAIL: no directory created outside the cache root ($TMP/escape exists)"
fi
# A valid owner still creates its subdir.
init_rc2=0
tt_cache_init_dir "$OWNER_SELF" || init_rc2=$?
if [[ "$init_rc2" -eq 0 && -d "$TMP/cache/$OWNER_SELF" ]]; then PASS=$((PASS+1)); echo "  PASS: valid owner creates its subdir"; else FAIL=$((FAIL+1)); echo "  FAIL: valid owner creates its subdir (rc=$init_rc2)"; fi
teardown_tmp

# Case R (R4-3): the task-id target token is an injective hex encoding, so
# distinct targets that a plain [:alnum:] strip would collapse ("a-b","ab",
# "a_b","a.b") produce distinct task ids even in the same epoch minute. Also
# verify tproj-task resolves such an id unambiguously.
echo "Case R: injective task-id target token + tproj-task resolution"
tt_tok() { printf '%s' "$1" | od -An -v -tx1 | tr -d ' \n'; }
ids=()
for t in a-b ab a_b a.b; do
  ids+=("alias-$(tt_tok "$t")-29000000-01")
done
uniq_count="$(printf '%s\n' "${ids[@]}" | sort -u | wc -l | tr -d ' ')"
if [[ "$uniq_count" -eq 4 ]]; then PASS=$((PASS+1)); echo "  PASS: 4 collapse-prone targets -> 4 distinct task ids"; else FAIL=$((FAIL+1)); echo "  FAIL: 4 collapse-prone targets -> 4 distinct task ids (uniq=$uniq_count)"; fi
if grep -q 'od -An -v -tx1' "$REPO/extensions/messaging/tproj-msg"; then PASS=$((PASS+1)); echo "  PASS: generate_task_id uses the injective od hex token"; else FAIL=$((FAIL+1)); echo "  FAIL: generate_task_id uses the injective od hex token"; fi
# tproj-task resolves a new-format id (with a hex token) via status and close.
if [[ -x "$REPO/extensions/messaging/tproj-task" ]]; then
  setup_tmp
  newid="alias-$(tt_tok "$TARGET_NAME")-29000000-01"
  ( source "$TMP/tproj-task-cache.sh"; tt_cache_add "$OWNER_SELF" "$TARGET_NAME" "$newid" "$(date +%s)" 1800 h ) >/dev/null 2>&1 || true
  st="$("$REPO/extensions/messaging/tproj-task" status "$newid" 2>&1 || true)"
  # status resolves the id to its entry (prints target=...); an unresolved id
  # would print "Error: task ... not found" instead.
  assert_contains "$st" "target=$TARGET_NAME" "tproj-task status resolves the new-format id"
  cl="$("$REPO/extensions/messaging/tproj-task" close "$newid" 2>&1 || true)"
  assert_contains "$cl" "closed $newid" "tproj-task close resolves the new-format id"
  teardown_tmp
else
  echo "  SKIP: tproj-task not found"
fi

echo
echo "Result: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1

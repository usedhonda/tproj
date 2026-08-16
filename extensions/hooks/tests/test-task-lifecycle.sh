#!/bin/bash
set -u

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
TMP="$(mktemp -d)"
trap 'find "$TMP" -depth -delete 2>/dev/null || true' EXIT

PASS=0
FAIL=0
OWNER="unit/owner"
TARGET="peer.cc"
TASK="unit-task-01"

export HOME="$TMP/home"
export TT_CACHE_DIR="$TMP/cache"
export TT_CACHE_LOCK_DIR="$TMP/locks"
export TPROJ_MSG_DB_PATH="$TMP/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$TMP/db-errors.log"
export TPROJ_MSG_DB_INIT_FLAG="$TMP/db-init.stamp"
export TPROJ_HOOK_ENABLED=1
export TT_CACHE_OWNER="$OWNER"
export TT_OWNER_ROLE=cdx
mkdir -p "$HOME" "$TT_CACHE_DIR" "$TT_CACHE_LOCK_DIR"

# shellcheck source=/dev/null
source "$REPO/extensions/messaging/tproj-task-cache.sh"

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$1"; }
check() {
  local label="$1"
  shift
  if "$@"; then pass "$label"; else fail "$label"; fi
}

reset_state() {
  find "$TT_CACHE_DIR" "$TT_CACHE_LOCK_DIR" -mindepth 1 -delete 2>/dev/null || true
  find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
  tt_cache_add "$OWNER" "$TARGET" "$TASK" 1000 1800 hash >/dev/null 2>&1 || true
}

cache_state_is() {
  local expected="$1"
  [[ "$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null | jq -r '.state // ""')" == "$expected" ]]
}

db_value() {
  sqlite3 "$TPROJ_MSG_DB_PATH" "$1" 2>/dev/null
}

invoke_guard() {
  local text="$1"
  printf '{"session_id":"hook-session","raw_event":{"last_assistant_message":%s}}\n' \
    "$(jq -Rn --arg value "$text" '$value')" \
    | TT_CACHE_OWNER="$OWNER" TT_OWNER_ROLE=cdx TPROJ_TASK_GUARD_SINCE=0 TPROJ_TASK_CLI="$REPO/extensions/messaging/tproj-task" \
      "$REPO/extensions/hooks/tproj-completion-guard" --platform codex 2>/dev/null
}

seed_inbound_task() {
  local task_id="$1" sender="${2:-peer.cc}" self="owner.cdx"
  tt_db_ensure_init >/dev/null 2>&1 || true
  tt_db_upsert_task "$task_id" "$self" 1000 1800 hash "${sender%.*}" unit >/dev/null 2>&1 || true
  tt_db_log_message unit "$sender" "$self" "[Task: $task_id] delegated" h "[from:$sender]" \
    "$task_id" inbound send-keys cc tmux "" >/dev/null
}

seed_outbound_marker() {
  local task_id="$1" marker="$2" sender="owner.cdx" recipient="${3:-peer.cc}"
  tt_db_log_message unit "$sender" "$recipient" "[$marker: $task_id] evidence" "bodyhash-$marker" \
    "[from:$sender]" "" outbound send-keys cc tmux "" >/dev/null
}

seed_terminal_evidence() {
  local task_id="$1" marker="$2" body_hash="$3"
  tt_db_log_message unit "$TARGET" owner.cdx "[$marker: $task_id] evidence" "$body_hash" \
    "[from:$TARGET]" "$task_id" inbound send-keys cc tmux ""
}

# 1. ACK is non-terminal and leaves the task tracked.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" ACK >/dev/null 2>&1 || true
fi
check "ACK survives in open cache" cache_state_is acked

# 2. ACK -> valid DONE -> ORCH_RECEIVED is represented without closing.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" ACK >/dev/null 2>&1 || true
  done_id="$(seed_terminal_evidence "$TASK" DONE abcdef0123456789)"
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$done_id" abcdef0123456789 owner.cdx >/dev/null 2>&1 || true
fi
check "ACK to DONE reaches received state" cache_state_is received

# 3. DONE without durable evidence is malformed and leaves the task open.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE >/dev/null 2>&1 || true
fi
check "malformed DONE keeps task pending" cache_state_is pending

# 4. Valid DONE stores only message id + body hash as evidence.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE 42 abcdef0123456789 owner.cdx >/dev/null 2>&1 || true
  forged_state="$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null | jq -r '.state')"
  evidence_id="$(seed_terminal_evidence "$TASK" DONE abcdef0123456789)"
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$evidence_id" abcdef0123456789 owner.cdx >/dev/null 2>&1 || true
fi
done_evidence="$(db_value "SELECT COALESCE(done_message_id,'') || '|' || COALESCE(done_body_hash,'') FROM tasks WHERE task_id='$TASK';")"
check "valid DONE stores only exact DB evidence id and hash" test "$forged_state" = pending -a "$done_evidence" = "${evidence_id}|abcdef0123456789"

# 5. ORCH_RECEIVED transition is idempotent (timestamp is first-write-wins).
if declare -F tt_db_transition_task >/dev/null 2>&1; then
  tt_db_transition_task "$TASK" received unit owner "$TARGET" 2000 >/dev/null 2>&1 || true
  first_received="$(db_value "SELECT orch_received_at FROM tasks WHERE task_id='$TASK';")"
  tt_db_transition_task "$TASK" received unit owner "$TARGET" 3000 >/dev/null 2>&1 || true
  second_received="$(db_value "SELECT orch_received_at FROM tasks WHERE task_id='$TASK';")"
else
  first_received=""; second_received="missing"
fi
check "orch_received is idempotent" test -n "$first_received" -a "$first_received" = "$second_received"

# 6. Verification from the wrong owner is rejected.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  evidence_id="$(seed_terminal_evidence "$TASK" DONE aabbccddeeff0011)"
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$evidence_id" aabbccddeeff0011 owner.cdx >/dev/null 2>&1 || true
fi
verify_ok_rc=0
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" verify "$TASK" "$TARGET" reviewed aabbccddeeff0011 \
  >/dev/null 2>&1 || verify_ok_rc=$?
verify_wrong_rc=0
TT_CACHE_OWNER="unit/intruder" "$REPO/extensions/messaging/tproj-task" verify "$TASK" "$TARGET" reviewed aabbccddeeff0011 \
  >/dev/null 2>&1 || verify_wrong_rc=$?
check "verify accepts exact owner and rejects wrong owner" test "$verify_ok_rc" -eq 0 -a "$verify_wrong_rc" -ne 0

# 7. A verified outgoing task blocks orchestrator Stop without report marker.
reset_state
evidence_id="$(seed_terminal_evidence "$TASK" DONE deadbeef00112233)"
tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$evidence_id" deadbeef00112233 owner.cdx 2000 >/dev/null 2>&1 || true
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" verify "$TASK" "$TARGET" reviewed deadbeef00112233 \
  >/dev/null 2>&1 || true
guard_out="$(invoke_guard 'Implementation verified.')"
check "report Stop omission is blocked" sh -c "test -x '$REPO/extensions/hooks/tproj-completion-guard' && grep -q COMPLETION-REPORT <<'EOF'
$guard_out
EOF"

# 8. Platform-observed completion marker closes a verified task.
if ! cache_state_is verified; then
  reset_state
  evidence_id="$(seed_terminal_evidence "$TASK" DONE deadbeef00112233)"
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$evidence_id" deadbeef00112233 owner.cdx 2000 >/dev/null 2>&1 || true
  TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" verify "$TASK" "$TARGET" reviewed deadbeef00112233 \
    >/dev/null 2>&1 || true
fi
# A newer parallel verified task must not prevent the explicit report marker
# from closing this task.
tt_cache_add "$OWNER" other.cc newer-verified 2100 1800 hash >/dev/null 2>&1 || true
tt_cache_transition_state "$OWNER" other.cc newer-verified "done" 2101 >/dev/null 2>&1 || true
tt_cache_transition_state "$OWNER" other.cc newer-verified received 2102 >/dev/null 2>&1 || true
tt_cache_transition_state "$OWNER" other.cc newer-verified verified 2103 >/dev/null 2>&1 || true
invoke_guard "[COMPLETION-REPORT: $TASK] verified result" >/dev/null
check "completion marker closes its explicit task amid parallel work" sh -c "test -x '$REPO/extensions/hooks/tproj-completion-guard' && test -z '$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null)' && test -n '$(tt_cache_get_task "$OWNER" other.cc newer-verified 2>/dev/null)'"

# 9. Escalation notices emit once and leave the task open.
reset_state
first_due=""
second_due=""
if declare -F tt_cache_due_notices >/dev/null 2>&1; then
  first_due="$(TT_TASK_NO_ACK_SEC=30 TT_TASK_FOLLOWUP_SEC=900 TT_TASK_REROUTE_SEC=1800 \
    tt_cache_due_notices "$OWNER" 3001 2>/dev/null)"
  second_due="$(TT_TASK_NO_ACK_SEC=30 TT_TASK_FOLLOWUP_SEC=900 TT_TASK_REROUTE_SEC=1800 \
    tt_cache_due_notices "$OWNER" 3001 2>/dev/null)"
fi
threshold_contract_ok=0
if grep -q 'TT_TASK_NO_ACK_SEC=30' "$REPO/extensions/messaging/tproj-task-cache.contract.md" \
  && grep -q 'TT_TASK_FOLLOWUP_SEC=900' "$REPO/extensions/messaging/tproj-task-cache.contract.md" \
  && grep -q 'TT_TASK_REROUTE_SEC=1800' "$REPO/extensions/messaging/tproj-task-cache.contract.md" \
  && grep -q 'TT_TASK_REPORT_DUE_SEC=900' "$REPO/extensions/messaging/tproj-task-cache.contract.md" \
  && grep -q 'TT_TASK_COMPLETION_STALLED_SEC=1800' "$REPO/extensions/messaging/tproj-task-cache.contract.md"; then
  threshold_contract_ok=1
fi
check "escalation is once-only and keeps task open" test -n "$first_due" -a -z "$second_due" -a -n "$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null)" -a "$threshold_contract_ok" -eq 1

# 9b. Exact-owner cancellation is durable, idempotent, and wrong-owner scoped.
reset_state
cancel_reason="deadbeefcafefeed"
cancel_rc=0
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" cancel "$TASK" "$TARGET" "$cancel_reason" >/dev/null 2>&1 || cancel_rc=$?
cancel_repeat_rc=0
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" cancel "$TASK" "$TARGET" "$cancel_reason" >/dev/null 2>&1 || cancel_repeat_rc=$?
cancel_wrong_rc=0
TT_CACHE_OWNER="unit/intruder" "$REPO/extensions/messaging/tproj-task" cancel "$TASK" "$TARGET" "$cancel_reason" >/dev/null 2>&1 || cancel_wrong_rc=$?
cancel_state="$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null | jq -r '.state // ""')"
cancel_db="$(db_value "SELECT state || '|' || COALESCE(tombstone_reason_hash,'') FROM tasks WHERE task_id='$TASK' AND owner_session='unit' AND owner_alias='owner' AND target='$TARGET';")"
check "cancel is exact-owner scoped and idempotent" test "$cancel_rc" -eq 0 -a "$cancel_repeat_rc" -eq 0 -a "$cancel_wrong_rc" -ne 0 -a "$cancel_state" = cancelled -a "$cancel_db" = "cancelled|$cancel_reason"

# 9c. Cancelled tasks reject later progress/terminal evidence and stay tombstoned.
reset_state
tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" ACK >/dev/null 2>&1 || true
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" cancel "$TASK" "$TARGET" "$cancel_reason" >/dev/null 2>&1 || true
progress_after_cancel_rc=0
tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" ACK-PROGRESS >/dev/null 2>&1 || progress_after_cancel_rc=$?
late_done_id="$(seed_terminal_evidence "$TASK" DONE a1b2c3d4e5f60708)"
late_done_rc=0
tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$late_done_id" a1b2c3d4e5f60708 owner.cdx >/dev/null 2>&1 || late_done_rc=$?
cancelled_state="$(tt_cache_get_task "$OWNER" "$TARGET" "$TASK" 2>/dev/null | jq -r '.state // ""')"
check "cancelled tasks cannot reopen on late ACK-PROGRESS or DONE" test "$progress_after_cancel_rc" -ne 0 -a "$late_done_rc" -ne 0 -a "$cancelled_state" = cancelled

# 9d. Receiver sees a cancellation notice exactly once.
find "$TT_CACHE_DIR" -mindepth 1 -delete 2>/dev/null || true
find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
seed_inbound_task worker-cancel-01
tt_db_tombstone_task worker-cancel-01 cancelled unit peer owner.cdx 0011aabbccddeeff >/dev/null 2>&1 || true
notice_once="$(TPROJ_HOOK_ENABLED=1 TT_CACHE_OWNER="$OWNER" TT_OWNER_ROLE=cdx "$REPO/extensions/hooks/tproj-inbox-check" --platform codex 2>/dev/null || true)"
notice_twice="$(TPROJ_HOOK_ENABLED=1 TT_CACHE_OWNER="$OWNER" TT_OWNER_ROLE=cdx "$REPO/extensions/hooks/tproj-inbox-check" --platform codex 2>/dev/null || true)"
check "receiver cancellation notice injects exactly once" sh -c "grep -q 'task-cancelled' <<'EOF1'
$notice_once
EOF1
test -z '$notice_twice'"

# 10. Installer produces symmetric Claude/Codex task hooks.
claude_hooks="$TMP/claude-hooks.json"
codex_hooks="$TMP/codex-hooks.json"
codex_config="$TMP/codex-config.toml"
printf '{"hooks":{}}\n' > "$claude_hooks"
printf '{"hooks":{}}\n' > "$codex_hooks"
install_rc=0
"$REPO/extensions/hooks/install-tproj-hooks" --claude-settings "$claude_hooks" --codex-hooks "$codex_hooks" \
  --codex-config "$codex_config" --skip-codex-trust \
  >/dev/null 2>&1 || install_rc=$?
cat > "$TMP/hooks-list.json" <<EOF
{"result":{"data":[{"hooks":[
  {"key":"task-mutation","sourcePath":"$codex_hooks","command":"$HOME/bin/tproj-mutation-guard --platform codex","currentHash":"sha256:abc000"},
  {"key":"task-record","sourcePath":"$codex_hooks","command":"$HOME/bin/tproj-inbox-record","currentHash":"sha256:abc001"},
  {"key":"task-check","sourcePath":"$codex_hooks","command":"$HOME/bin/tproj-inbox-check --platform codex","currentHash":"sha256:abc002"},
  {"key":"task-stop","sourcePath":"$codex_hooks","command":"$HOME/bin/tproj-completion-guard --platform codex","currentHash":"sha256:abcdef"}
]}]}}
EOF
printf 'model = "test"\n' > "$codex_config"
mkdir -p "$TMP/installed-hooks"
cp "$REPO/extensions/hooks/tproj-inbox-record" "$TMP/installed-hooks/"
cp "$REPO/extensions/hooks/tproj-inbox-check" "$TMP/installed-hooks/"
cp "$REPO/extensions/hooks/tproj-completion-guard" "$TMP/installed-hooks/"
cp "$REPO/extensions/hooks/tproj-mutation-guard" "$TMP/installed-hooks/"
"$REPO/extensions/hooks/install-tproj-hooks" --claude-settings "$claude_hooks" --codex-hooks "$codex_hooks" \
  --codex-config "$codex_config" --trust-response "$TMP/hooks-list.json" \
  --canonical-hooks-dir "$REPO/extensions/hooks" --installed-hooks-dir "$TMP/installed-hooks" \
  >/dev/null 2>&1 || install_rc=$?
before_mismatch="$(shasum -a 256 "$claude_hooks" "$codex_hooks")"
printf 'mismatch\n' >> "$TMP/installed-hooks/tproj-inbox-check"
mismatch_rc=0
"$REPO/extensions/hooks/install-tproj-hooks" --claude-settings "$claude_hooks" --codex-hooks "$codex_hooks" \
  --codex-config "$codex_config" --trust-response "$TMP/hooks-list.json" \
  --canonical-hooks-dir "$REPO/extensions/hooks" --installed-hooks-dir "$TMP/installed-hooks" \
  >/dev/null 2>&1 || mismatch_rc=$?
after_mismatch="$(shasum -a 256 "$claude_hooks" "$codex_hooks")"
claude_commands="$(jq -r '.. | objects | .command? // empty' "$claude_hooks" 2>/dev/null)"
codex_commands="$(jq -r '.. | objects | .command? // empty' "$codex_hooks" 2>/dev/null)"
check "Claude and Codex install lifecycle hooks symmetrically" sh -c "test '$install_rc' -eq 0 && test '$mismatch_rc' -ne 0 && test '$before_mismatch' = '$after_mismatch' && grep -q tproj-completion-guard <<'EOF1'
$claude_commands
EOF1
grep -q tproj-mutation-guard <<'EOF0'
$claude_commands
EOF0
grep -q tproj-completion-guard <<'EOF2'
$codex_commands
EOF2
grep -q tproj-mutation-guard <<'EOF3'
$codex_commands
EOF3
grep -q 'trusted_hash = \"sha256:abcdef\"' '$codex_config'"

# 11. Codex nested functions.exec response metadata records a task.
find "$TT_CACHE_DIR" -mindepth 1 -delete 2>/dev/null || true
nested_payload="$(jq -nc \
  --arg source 'await tools.exec_command({cmd: "tproj-msg --new-task peer.cc x"})' \
  --arg text 'TASK_ID=nested-01 TASK_TARGET=peer.cc TASK_TTL_SEC=1800 TASK_SENT_AT=1000' \
  '{tool_name:"functions.exec",tool_input:{source:$source},tool_response:{content:[{type:"text",text:$text}]}}')"
printf '%s\n' "$nested_payload" | TT_CACHE_OWNER="$OWNER" "$REPO/extensions/hooks/tproj-inbox-record" >/dev/null 2>&1 || true
check "Codex nested tool response records task" test -n "$(tt_cache_get_task "$OWNER" "$TARGET" nested-01 2>/dev/null)"

# 12. Full delegated lifecycle closes only after report.
reset_state
if declare -F tt_cache_apply_reply >/dev/null 2>&1; then
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" ACK >/dev/null 2>&1 || true
  evidence_id="$(seed_terminal_evidence "$TASK" DONE feedface12345678)"
  tt_cache_apply_reply "$OWNER" "$TARGET" "$TASK" DONE "$evidence_id" feedface12345678 owner.cdx >/dev/null 2>&1 || true
fi
verify_rc=0
TT_CACHE_OWNER="$OWNER" "$REPO/extensions/messaging/tproj-task" verify "$TASK" "$TARGET" reviewed feedface12345678 \
  >/dev/null 2>&1 || verify_rc=$?
invoke_guard "[COMPLETION-REPORT: $TASK] verified result" >/dev/null
check "full lifecycle reaches durable user_reported" test "$verify_rc" -eq 0 -a -n "$(db_value "SELECT user_reported_at FROM tasks WHERE task_id='$TASK';")"

# 13. Reproduce 8/6 incident: local success text without DONE is blocked.
find "$TT_CACHE_DIR" -mindepth 1 -delete 2>/dev/null || true
find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
seed_inbound_task worker-incident-01
worker_out="$(invoke_guard 'All work finished successfully.')"
check "worker untagged success Stop is blocked" sh -c "test -x '$REPO/extensions/hooks/tproj-completion-guard' && grep -q '\[DONE: worker-incident-01\]' <<'EOF'
$worker_out
EOF"

# 14. ACK-PROGRESS is allowed only when the same marker was sent to the owner.
seed_outbound_marker worker-incident-01 ACK-PROGRESS
progress_out="$(invoke_guard '[ACK-PROGRESS: worker-incident-01] tests running')"
check "ACK-PROGRESS is nonterminal and allowed" sh -c "test -x '$REPO/extensions/hooks/tproj-completion-guard' && test -z '$progress_out'"

fresh_db() {
  find "$TT_CACHE_DIR" -mindepth 1 -delete 2>/dev/null || true
  find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
  tt_db_ensure_init >/dev/null 2>&1 || true
}

# 15. A task whose message body never arrived cannot be answered truthfully, so it
#     must not hold the turn hostage.
fresh_db
tt_db_upsert_task orphan-01 owner.cdx 1000 1800 hash peer unit >/dev/null 2>&1 || true
tt_db_log_message unit peer.cc owner.cdx "" h "[from:peer.cc]" orphan-01 inbound send-keys cc tmux "" >/dev/null
orphan_out="$(invoke_guard 'Finished an unrelated piece of work.')"
check "body-less task does not block the turn" test -z "$orphan_out"

# 16. A task that did arrive is still enforced exactly as before.
seed_inbound_task delivered-01
delivered_out="$(invoke_guard 'Finished an unrelated piece of work.')"
check "delivered task still blocks without a tag" sh -c "grep -q '\[DONE: delivered-01\]' <<'EOF'
$delivered_out
EOF"

# 17. Addressing the counterpart in one's own column by its bare role is the normal
#     way to send, and the marker must count as sent.
fresh_db
tt_db_upsert_task short-01 owner.cdx 1000 1800 hash owner unit >/dev/null 2>&1 || true
tt_db_log_message unit owner.cc owner.cdx "[Task: short-01] delegated" h "[from:owner.cc]" \
  short-01 inbound send-keys cc tmux "" >/dev/null
tt_db_log_message unit owner.cdx cc "[ACK: short-01] on it" bh "[from:owner.cdx]" "" \
  outbound send-keys cc tmux "" >/dev/null
short_out="$(invoke_guard '[ACK: short-01] on it')"
check "marker sent to the bare same-column alias is accepted" test -z "$short_out"

# 18. The bare form must not stand in for a different column's pane.
fresh_db
tt_db_upsert_task cross-01 owner.cdx 1000 1800 hash owner unit >/dev/null 2>&1 || true
tt_db_log_message unit owner.cc owner.cdx "[Task: cross-01] delegated" h "[from:owner.cc]" \
  cross-01 inbound send-keys cc tmux "" >/dev/null
tt_db_log_message unit owner.cdx elsewhere.cc "[ACK: cross-01] on it" bh "[from:owner.cdx]" "" \
  outbound send-keys cc tmux "" >/dev/null
cross_out="$(invoke_guard '[ACK: cross-01] on it')"
check "marker sent to another column is still rejected" sh -c "grep -q 'must first be sent' <<'EOF'
$cross_out
EOF"

# 19. A declared role mode suspends delegation lifecycle enforcement, because under
#     it nobody delegated anything and no one is waiting for a tag.
fresh_db
seed_inbound_task mode-01
mode_bin="$TMP/mode-bin"
mkdir -p "$mode_bin"
# The fake records its argv so the per-project scoping is provable: when the guard
# runs inside a pane whose @project is known, the mode query must carry it.
cat > "$mode_bin/model-role-router" <<'MRR'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_ROLE_MODE_ARGS:-/dev/null}"
[ "${FAKE_ROLE_MODE:-auto}" = broken ] && exit 1
printf '{"mode":"%s"}\n' "${FAKE_ROLE_MODE:-auto}"
MRR
chmod +x "$mode_bin/model-role-router"
cat > "$mode_bin/tmux" <<'FTMUX'
#!/usr/bin/env bash
# The guard asks only for the pane's @project tag.
printf '%s\n' "${FAKE_PANE_PROJECT:-}"
FTMUX
chmod +x "$mode_bin/tmux"

declared_out="$(PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=advisor invoke_guard 'Finished the work.')"
check "declared mode suspends lifecycle enforcement" test -z "$declared_out"
solo_out="$(PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=solo invoke_guard 'Finished the work.')"
check "solo mode suspends lifecycle enforcement" test -z "$solo_out"

auto_out="$(PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=auto invoke_guard 'Finished the work.')"
check "auto still enforces the lifecycle" sh -c "grep -q '\[DONE: mode-01\]' <<'EOF'
$auto_out
EOF"

# An unreadable router must not switch the guard off by accident.
broken_out="$(PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=broken invoke_guard 'Finished the work.')"
check "an unreadable mode falls back to enforcing" sh -c "grep -q '\[DONE: mode-01\]' <<'EOF'
$broken_out
EOF"

# 20. The mode query is scoped to this pane's own project, so a mode declared for a
#     neighbouring column can never silence this one's lifecycle.
args_log="$TMP/mode-args.log"
: > "$args_log"
PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=auto FAKE_ROLE_MODE_ARGS="$args_log" \
  FAKE_PANE_PROJECT="/work/projA" TMUX_PANE="%9" invoke_guard 'Finished the work.' >/dev/null
check "mode query names the pane's own project" sh -c "grep -q -- '--project /work/projA' '$args_log'"
: > "$args_log"
PATH="$mode_bin:$PATH" FAKE_ROLE_MODE=auto FAKE_ROLE_MODE_ARGS="$args_log" \
  FAKE_PANE_PROJECT="" TMUX_PANE="" invoke_guard 'Finished the work.' >/dev/null
check "no pane means no project argument" sh -c "grep -q 'mode --json' '$args_log' && ! grep -q -- '--project' '$args_log'"

printf '%s\n' "----" "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]

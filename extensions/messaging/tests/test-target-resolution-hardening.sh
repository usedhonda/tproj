#!/usr/bin/env bash
# Hermetic exact-target and stale-liveness contract tests for tproj-msg.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REAL_TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-target-resolution.XXXXXX")
FAKE_DIR="$WORK/fixtures"
BIN_DIR="$WORK/bin"
REGISTRY_ROOT="$WORK/registry"
mkdir -p "$FAKE_DIR" "$BIN_DIR" "$REGISTRY_ROOT/test-session/1"
trap 'rm -rf "$WORK"' EXIT

export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_SEND_DEDUP_DIR="$WORK/send-dedup"
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
export TPROJ_MSG_FLUSH_WORKER_LOG="$WORK/flush-worker.log"

TPROJ_MSG="$BIN_DIR/tproj-msg-verified"
export TPROJ_TEST_REGISTRY_ROOT="$REGISTRY_ROOT"
export TPROJ_TEST_REAL_MSG="$REAL_TPROJ_MSG"
cat > "$TPROJ_MSG" <<'WRAPPER'
#!/usr/bin/env bash
if [[ "${_VERIFIED_REINVOKED:-}" != "1" ]]; then
  export _VERIFIED_REINVOKED=1
  exec -a claude bash "$0" "$@"
fi
mypid=$$
mystart=$(date -j -f "%a %b %d %H:%M:%S %Y" "$(ps -p $mypid -o lstart=)" +%s 2>/dev/null || echo 0)
printf '{"alias":"sender.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"sender.cdx","observed_at":%s}\n' "$mypid" "$mystart" "$(date +%s)" > "$TPROJ_TEST_REGISTRY_ROOT/test-session/1/sender.cc.json"
"$TPROJ_TEST_REAL_MSG" "$@"
WRAPPER
chmod +x "$TPROJ_MSG"

cat > "$BIN_DIR/tmux" <<'TMUX'
#!/usr/bin/env bash
set -uo pipefail
FAKE_DIR="$FAKE_DIR_ENV"
sub="${1:-}"
shift || true
target=""
fmt=""
optname=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    -t) target="${args[$((i+1))]:-}";;
    -p|-F) fmt="${args[$((i+1))]:-}";;
    -v) optname="${args[$((i+1))]:-}";;
  esac
done
printf '%s\t%s\n' "$sub" "$target" >> "$FAKE_DIR/tmux.log"
pane="$target"
readf() { [[ -f "$FAKE_DIR/$1" ]] && cat "$FAKE_DIR/$1" || true; }
default_for() {
  local file="$1" value="$2"
  if [[ -f "$FAKE_DIR/$file" ]]; then cat "$FAKE_DIR/$file"; else printf '%s' "$value"; fi
}
case "$sub" in
  has-session)
    case "$target" in
      =missing-session|=missing-session:dev) exit 1;;
    esac
    exit 0
    ;;
  list-panes)
    pane_rows=""
    case "$target" in
      =missing-session:dev) pane_rows=$(readf prefix_panes);;
      *) pane_rows=$(readf panes);;
    esac
    if [[ "$fmt" != *pane_dead* ]]; then
      printf '%s\n' "$pane_rows" | sed -E 's/^([^:]*:[^:]*:[^:]*:[^:]*):[^:]*$/\1/'
    else
      printf '%s\n' "$pane_rows"
    fi
    ;;
  display-message)
    case "$fmt" in
      '#S') printf '%s' 'test-session';;
      *@role*) default_for "role_${pane}" '';;
      *@alias*) default_for "alias_${pane}" 'sender';;
      *@column*) default_for "column_${pane}" '1';;
      *pane_current_command*) default_for "cmd_${pane}" 'zsh';;
      *pane_tty*) default_for "tty_${pane}" "/dev/ttys001";;
      *pane_id*) printf '%s' "${pane:-%9}";;
      *) :;;
    esac
    ;;
  show-options)
    case "$optname" in
      @prompt_state) readf "promptstate_${pane}";;
      @prompt_state_ts) readf "promptstate_ts_${pane}";;
      @prompt_state_src) readf "promptstate_src_${pane}";;
      @role_epoch) readf "epoch_${pane}";;
      *) :;;
    esac
    ;;
  capture-pane) readf "capture_${pane}";;
  send-keys) printf 'SENDKEYS %s\n' "$*" >> "$FAKE_DIR/sendkeys.log";;
  set-option|set|setenv) :;;
  *) :;;
esac
exit 0
TMUX
chmod +x "$BIN_DIR/tmux"

cat > "$BIN_DIR/websocat" <<'WEBSOCAT'
#!/usr/bin/env bash
set -uo pipefail
[[ -f "$FAKE_DIR_ENV/ws.json" ]] && cat "$FAKE_DIR_ENV/ws.json"
exit 0
WEBSOCAT
chmod +x "$BIN_DIR/websocat"

for timeout_name in timeout gtimeout; do
  cat > "$BIN_DIR/$timeout_name" <<'TIMEOUT'
#!/usr/bin/env bash
[[ "${1:-}" =~ ^[0-9]+([.][0-9]+)?$ ]] && shift
exec "$@"
TIMEOUT
  chmod +x "$BIN_DIR/$timeout_name"
done

cat > "$BIN_DIR/curl" <<'CURL'
#!/usr/bin/env bash
printf '{"ok":true}\n200\n'
CURL
chmod +x "$BIN_DIR/curl"
export FAKE_DIR_ENV="$FAKE_DIR"
export PATH="$BIN_DIR:$PATH"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$1"; }
reset_runtime() {
  rm -f "$FAKE_DIR"/sendkeys.log "$FAKE_DIR"/ws.json "$FAKE_DIR"/capture_* \
    "$FAKE_DIR"/promptstate_* "$FAKE_DIR"/cmd_* "$FAKE_DIR"/role_* \
    "$FAKE_DIR"/alias_* "$FAKE_DIR"/column_* "$FAKE_DIR"/tty_*
  : > "$FAKE_DIR/tmux.log"
}
write_panes() { printf '%s\n' "$1" > "$FAKE_DIR/panes"; }
write_capture() { printf '%s' "$2" > "$FAKE_DIR/capture_$1"; }
write_cmd() { printf '%s' "$2" > "$FAKE_DIR/cmd_$1"; }
write_ws() { printf '%s\n' "$1" > "$FAKE_DIR/ws.json"; }
run_status() { "$TPROJ_MSG" --session test-session --as sender.cc --status "$1" 2>&1; }
run_send() { "$TPROJ_MSG" --session test-session --as sender.cc "$1" "$2" 2>&1; }
no_sendkeys() { [[ ! -f "$FAKE_DIR/sendkeys.log" ]]; }

# A: alias-only opposite pane must never resolve through another alias's role.
reset_runtime
write_panes $'%1:codex-p7:oc-general:7:0\n%2:claude-p7:bellman:7:0\n%9:claude-p1:sender:1:0'
write_capture '%2' $'❯ '
a_status=$(run_status 'oc-general.cc'); a_status_rc=$?
a_send=$(run_send 'oc-general.cc' 'A must not cross aliases'); a_send_rc=$?
if [[ "$a_status_rc" -ne 0 && "$a_send_rc" -ne 0 ]] && no_sendkeys; then
  pass 'A_exact_alias_role_rejects_opposite_alias_and_no_sendkeys'
else
  fail "A_exact_alias_role_rejects_opposite_alias_and_no_sendkeys status_rc=$a_status_rc send_rc=$a_send_rc send=$(tr '\n' '|' <<<"$a_send")"
fi

# B: an exact missing session must not fall through to a similarly named session.
reset_runtime
write_panes $'%1:claude-p1:prefix:1:0\n%9:claude-p1:sender:1:0'
touch "$FAKE_DIR/no_exact_session_fixture"
b_status=$(FAKE_DIR_ENV="$FAKE_DIR" "$TPROJ_MSG" --session missing-session --as sender.cc --status prefix.cc 2>&1); b_status_rc=$?
b_send=$(FAKE_DIR_ENV="$FAKE_DIR" "$TPROJ_MSG" --session missing-session --as sender.cc prefix.cc 'B must not use prefix session' 2>&1); b_send_rc=$?
if [[ "$b_status_rc" -ne 0 && "$b_send_rc" -ne 0 ]] && no_sendkeys && ! grep -q $'list-panes\tmissing-session:dev' "$FAKE_DIR/tmux.log"; then
  pass 'B_exact_missing_session_rejects_prefix_session'
else
  fail "B_exact_missing_session_rejects_prefix_session status_rc=$b_status_rc send_rc=$b_send_rc log=$(tr '\n' '|' < "$FAKE_DIR/tmux.log")"
fi
# A rejection nobody can see is not a rejection. Under set -e the failing
# resolve_target substitution used to abort the script before the error block,
# so the send exited 3 with an empty stderr and the sender believed it had
# delivered. The message must name the session as the cause.
if [[ "$b_send" == *"not a live tmux session"* && "$b_send" == *missing-session* ]]; then
  pass 'B_missing_session_rejection_is_explained'
else
  fail "B_missing_session_rejection_is_explained output=[$(printf '%s' "$b_send" | tr '\n' '|' | cut -c1-160)]"
fi

# C: non-shell process without fresh prompt or WS evidence is offline.
reset_runtime
write_panes $'%1:claude-p1:stale:1:0\n%9:claude-p1:sender:1:0'
write_cmd '%1' 'python'
write_ws '{"type":"sessions.list","sessions":[{"tty":"/dev/ttys001","status":"running","updated_at":1}]}'
c_status=$(run_status 'stale.cc'); c_status_rc=$?
c_send=$(run_send 'stale.cc' 'C stale process must not authorize send'); c_send_rc=$?
if [[ "$c_status_rc" -eq 0 && "$c_status" == *'offline/'* && "$c_send_rc" -ne 0 && no_sendkeys ]]; then
  pass 'C_stale_non_shell_without_fresh_evidence_is_offline'
else
  fail "C_stale_non_shell_without_fresh_evidence_is_offline status_rc=$c_status_rc send_rc=$c_send_rc status=$(tr '\n' '|' <<<"$c_status")"
fi

# D: a fresh native prompt and a fresh WS session both keep active panes online.
reset_runtime
write_panes $'%1:claude-p1:native:1:0\n%2:claude-p1:wsactive:1:0\n%9:claude-p1:sender:1:0'
write_cmd '%1' 'claude'
write_capture '%1' $'output\n❯ '
d_native=$(run_status 'native.cc'); d_native_rc=$?
d_native_send=$(run_send 'native.cc' 'D native prompt sendable'); d_native_send_rc=$?
d_native_sent=0
[[ -f "$FAKE_DIR/sendkeys.log" ]] && d_native_sent=1
reset_runtime
write_panes $'%1:claude-p1:native:1:0\n%2:claude-p1:wsactive:1:0\n%9:claude-p1:sender:1:0'
write_cmd '%2' 'python'
write_ws '{"type":"sessions.list","sessions":[{"tty":"/dev/ttys001","status":"waiting_input","waiting_reason":"unknown","updated_at":"2099-01-01T00:00:00Z"}]}'
# Replace the future timestamp with a current numeric timestamp for portability.
now=$(date +%s)
write_ws "{\"type\":\"sessions.list\",\"sessions\":[{\"tty\":\"/dev/ttys001\",\"status\":\"waiting_input\",\"waiting_reason\":\"unknown\",\"updated_at\":$now}]}"
write_capture '%2' 'normal output'
d_ws=$(run_status 'wsactive.cc'); d_ws_rc=$?
if [[ "$d_native_rc" -eq 0 && "$d_native" == *'online/'* && "$d_native_send_rc" -eq 0 && "$d_native_sent" -eq 1 && "$d_ws_rc" -eq 0 && "$d_ws" == *'online/'* ]]; then
  pass 'D_fresh_native_prompt_and_ws_state_remain_sendable'
else
  fail "D_fresh_native_prompt_and_ws_state_remain_sendable native_rc=$d_native_rc native_send_rc=$d_native_send_rc ws_rc=$d_ws_rc native=$(tr '\n' '|' <<<"$d_native") ws=$(tr '\n' '|' <<<"$d_ws")"
fi

# E: duplicate exact alias+role is ambiguous; dead duplicate panes do not count.
reset_runtime
write_panes $'%1:claude-p1:dup:1:0\n%2:claude-p1:dup:1:0\n%3:claude-p1:dup:1:1\n%9:claude-p1:sender:1:0'
write_capture '%1' $'❯ '
e_dup=$(run_status 'dup.cc'); e_dup_rc=$?
e_dup_send=$(run_send 'dup.cc' 'E duplicate must not send'); e_dup_send_rc=$?
dup_rejected=0
if [[ "$e_dup_rc" -ne 0 && "$e_dup_send_rc" -ne 0 ]] && no_sendkeys; then dup_rejected=1; fi
write_panes $'%1:claude-p1:dup:1:0\n%3:claude-p1:dup:1:1\n%9:claude-p1:sender:1:0'
e_dead=$(run_send 'dup.cc' 'E dead duplicate ignored'); e_dead_rc=$?
if [[ "$dup_rejected" -eq 1 && "$e_dead_rc" -eq 0 && -f "$FAKE_DIR/sendkeys.log" ]]; then
  pass 'E_duplicate_live_is_ambiguous_dead_pane_is_ignored'
else
  fail "E_duplicate_live_is_ambiguous_dead_pane_is_ignored dup_rc=$e_dup_rc dup_send_rc=$e_dup_send_rc dead_rc=$e_dead_rc dup=$(tr '\n' '|' <<<"$e_dup") dead=$(tr '\n' '|' <<<"$e_dead")"
fi

printf '\nTOTAL: %d passed, %d failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

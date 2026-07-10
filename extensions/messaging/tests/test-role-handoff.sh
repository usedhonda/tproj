#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
TPROJ_MSG="$ROOT/extensions/messaging/tproj-msg"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-role-handoff.XXXXXX")"
FIXTURES="$WORK/fixtures"
BIN="$WORK/bin"
mkdir -p "$FIXTURES" "$BIN" "$WORK/queue" "$WORK/control" "$WORK/fanout"

cleanup() {
  if [[ -f "$WORK/queue/.flush-worker.pid" ]]; then
    kill "$(cat "$WORK/queue/.flush-worker.pid")" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

cat > "$FIXTURES/panes" <<'EOF'
%1:claude-p1:tproj:1
%2:codex-p1:tproj:1
EOF
printf '%s' '/dev/ttys001' > "$FIXTURES/tty_%1"
printf '%s' '/dev/ttys002' > "$FIXTURES/tty_%2"
printf '%s' 'claude-p1' > "$FIXTURES/role_%1"
printf '%s' 'codex-p1' > "$FIXTURES/role_%2"
printf '%s' 'tproj' > "$FIXTURES/alias_%1"
printf '%s' 'tproj' > "$FIXTURES/alias_%2"
printf '%s' '1' > "$FIXTURES/column_%1"
printf '%s' '1' > "$FIXTURES/column_%2"

cat > "$BIN/tmux" <<'TMUX'
#!/usr/bin/env bash
set -uo pipefail
dir="$FAKE_DIR_ENV"
sub="${1:-}"
shift || true
args=("$@")
target=""
fmt=""
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    -t) target="${args[$((i+1))]:-}" ;;
    -p|-F) fmt="${args[$((i+1))]:-}" ;;
  esac
done
readf() { [[ -f "$dir/$1" ]] && cat "$dir/$1" || true; }
case "$sub" in
  display-message)
    case "$fmt" in
      '#S') printf '%s' 'tproj-workspace' ;;
      *pane_tty*) readf "tty_${target}" ;;
      *@role*) readf "role_${target}" ;;
      *@alias*) readf "alias_${target}" ;;
      *@column*) readf "column_${target}" ;;
      *pane_current_command*)
        case "$(readf "role_${target}")" in claude*) printf '%s' claude ;; *) printf '%s' codex ;; esac ;;
      *pane_id*) printf '%s' "${target:-%1}" ;;
    esac
    ;;
  list-panes) readf panes ;;
  show-options)
    option="${args[$(( ${#args[@]} - 1 ))]:-}"
    case "$option" in
      @prompt_state) readf "promptstate_${target}" ;;
      @prompt_state_ts) readf "promptstate_ts_${target}" ;;
      @prompt_state_src) readf "promptstate_src_${target}" ;;
      @role_epoch) readf "roleepoch_${target}" ;;
      @orchestration_role) readf "orchestrationrole_${target}" ;;
    esac
    ;;
  capture-pane) readf "capture_${target}" ;;
  send-keys) printf 'SENDKEYS %s\n' "$*" >> "$dir/sendkeys.log" ;;
  has-session|set-option|set|setenv) exit 0 ;;
esac
exit 0
TMUX
chmod +x "$BIN/tmux"

cat > "$BIN/websocat" <<'WS'
#!/usr/bin/env bash
printf '%s\n' '{"type":"host_info","host":"test"}'
cat "$FAKE_DIR_ENV/ws.json" 2>/dev/null || true
WS
chmod +x "$BIN/websocat"
ln -s "$TPROJ_MSG" "$BIN/tproj-msg"

export FAKE_DIR_ENV="$FIXTURES"
export PATH="$BIN:$PATH"
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
export TPROJ_MSG_CONTROL_DEDUP_DIR="$WORK/control"
export TPROJ_MSG_FANOUT_DEDUP_DIR="$WORK/fanout"

PASS=0
FAIL=0

reset_case() {
  rm -f "$FIXTURES/sendkeys.log" "$FIXTURES"/promptstate_* "$FIXTURES"/promptstate_ts_* \
    "$FIXTURES"/promptstate_src_* "$FIXTURES"/capture_* "$WORK/queue"/*.queue
}

set_state() {
  local pane="$1" state="$2" tty now
  now="$(date +%s)"
  printf '%s' "$state" > "$FIXTURES/promptstate_${pane}"
  printf '%s' "$now" > "$FIXTURES/promptstate_ts_${pane}"
  printf '%s' 'contract-test' > "$FIXTURES/promptstate_src_${pane}"
  tty="$(cat "$FIXTURES/tty_${pane}")"
  printf '{"type":"sessions.list","sessions":[{"tty":"%s","status":"running","updated_at":"%s"}]}\n' \
    "$tty" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$FIXTURES/ws.json"
  printf '%s' 'normal output' > "$FIXTURES/capture_${pane}"
}

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s: %s\n' "$1" "$2"; }

run_handoff() {
  local sender="$1" target="$2" epoch="$3" orchestrator="$4" body="$5"
  "$TPROJ_MSG" --session tproj-workspace --as "$sender" --role-handoff --new-task \
    --ttl 60m --role-epoch "$epoch" --orchestrator "$orchestrator" "$target" "$body" 2>&1
}

# Symmetric explicit handoff: either platform may hand orchestration to the other.
reset_case
set_state %2 idle
out="$(run_handoff tproj.cc tproj.cdx 7 tproj.cdx 'cc-to-cdx')"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[from:tproj.cc] [Role-Handoff:'* && "$log" == *$'Role-Epoch: 7\nOrchestrator: tproj.cdx\n[Task:'* && "$out" == *'TASK_ID='* ]]; then
  pass symmetric_cc_to_cdx
else
  fail symmetric_cc_to_cdx "rc=$rc out=$out log=$log"
fi

reset_case
set_state %1 idle
out="$(run_handoff tproj.cdx tproj.cc 8 tproj.cc 'cdx-to-cc')"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[from:tproj.cdx] [Role-Handoff:'* && "$log" == *$'Role-Epoch: 8\nOrchestrator: tproj.cc\n[Task:'* ]]; then
  pass symmetric_cdx_to_cc
else
  fail symmetric_cdx_to_cc "rc=$rc out=$out log=$log"
fi

# A typing target must be queued, with tracking metadata emitted immediately.
reset_case
set_state %2 typing
out="$(run_handoff tproj.cc tproj.cdx 9 tproj.cdx 'defer-while-typing')"; rc=$?
queued="$(cat "$WORK/queue/tproj.cdx.queue" 2>/dev/null || true)"
if [[ $rc -eq 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'session_typing_busy'* && "$out" == *'TASK_ID='* && "$queued" == *'TPROJ-B64:'* ]]; then
  pass typing_defers_without_overwrite
else
  fail typing_defers_without_overwrite "rc=$rc out=$out queued=$queued"
fi
set_state %2 idle
"$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush >/dev/null 2>&1
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ "$log" == *'[Role-Handoff:'* && "$log" == *$'Role-Epoch: 9\nOrchestrator: tproj.cdx\n[Task:'* && ! -f "$WORK/queue/tproj.cdx.queue" ]]; then
  pass deferred_handoff_flushes_intact
else
  fail deferred_handoff_flushes_intact "log=$log"
fi

# Current-pane metadata supplies the epoch; a worker hands the target orchestration.
reset_case
set_state %2 idle
printf '%s' '12' > "$FIXTURES/roleepoch_%1"
printf '%s' 'worker' > "$FIXTURES/orchestrationrole_%1"
out="$(TMUX=1 TMUX_PANE=%1 "$TPROJ_MSG" --role-handoff --new-task tproj.cdx 'metadata-fallback' 2>&1)"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *$'Role-Epoch: 12\nOrchestrator: tproj.cdx\n[Task:'* ]]; then
  pass current_pane_metadata_fallback
else
  fail current_pane_metadata_fallback "rc=$rc out=$out log=$log"
fi

# Legacy --new-task stays unchanged and ACK/DONE/BLOCK tags remain readable.
reset_case
set_state %2 idle
out="$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --new-task tproj.cdx 'legacy-task' 2>&1)"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[Task:'* && "$log" != *'[Role-Handoff:'* ]]; then
  pass legacy_new_task_unchanged
else
  fail legacy_new_task_unchanged "rc=$rc out=$out log=$log"
fi

printf '%s\n' '[ACK: old-a]' '[DONE: old-d]' '[BLOCK: old-b] reason' > "$FIXTURES/capture_%2"
out="$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --read tproj.cdx 40 2>&1)"; rc=$?
if [[ $rc -eq 0 && "$out" == *'TASK_REPLIED=old-a'* && "$out" == *'TASK_REPLIED=old-d'* && "$out" == *'TASK_REPLIED=old-b'* ]]; then
  pass legacy_reply_tags_compatible
else
  fail legacy_reply_tags_compatible "rc=$rc out=$out"
fi

# Force is structurally unavailable for handoff, even when the target is typing.
reset_case
set_state %2 typing
out="$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --force --role-handoff --new-task tproj.cdx 'must-not-force' 2>&1)"; rc=$?
if [[ $rc -ne 0 && "$out" == *'cannot be combined with --force'* && ! -f "$FIXTURES/sendkeys.log" ]]; then
  pass role_handoff_rejects_force
else
  fail role_handoff_rejects_force "rc=$rc out=$out"
fi

printf '%s\n' '----'
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

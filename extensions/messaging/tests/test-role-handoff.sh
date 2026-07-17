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
      # pane_pid must be a genuine ancestor of the in-tmux caller for the
      # pane-derived ancestry check (a real pane's shell is). HARNESS_PANE_PID is
      # the test process ($$), which IS an ancestor of the tproj-msg it spawns.
      *pane_pid*) printf '%s' "${HARNESS_PANE_PID:-0}" ;;
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
# The pane-derived caller check requires the selected pane's pane_pid to be a
# real ancestor of the in-tmux caller. Expose this test process's pid so the fake
# tmux can return it as pane_pid for the current_pane_metadata_fallback case.
export HARNESS_PANE_PID=$$
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
export TPROJ_MSG_CONTROL_DEDUP_DIR="$WORK/control"
export TPROJ_MSG_FANOUT_DEDUP_DIR="$WORK/fanout"
export TPROJ_MSG_SEND_DEDUP_DIR="$WORK/send-dedup"

# --- R2 Stage 1 registry harness -------------------------------------------
# Simulates a caller verified against the model-role-router registry by
# renaming a real child process to "claude"/"codex" (exec -a) and writing
# a matching registry entry keyed on that process's OWN (pid, pid_start) --
# no shortcuts (no env-var bypass of the ancestry check itself).
REGISTRY_ROOT="$WORK/registry"
mkdir -p "$REGISTRY_ROOT/tproj-workspace/1"
export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/db-errors.log"
# E4 (msg-repair): hard invariant -- never run against the real production
# messages.db. Abort loudly if the isolation override above was ever dropped.
if [[ -z "${TPROJ_MSG_DB_PATH:-}" || "$TPROJ_MSG_DB_PATH" == "$HOME/.local/share/tproj-msg/messages.db" ]]; then
  echo "FATAL: TPROJ_MSG_DB_PATH not isolated to a temp DB (would pollute the real messages.db)" >&2
  exit 2
fi

# Sandboxed HOME for the bare-role service-binding tests (isolates
# ~/.config/tproj/workspace.yaml and ~/.cache/tproj-model-role from the
# real developer machine).
TEST_HOME="$WORK/home"
mkdir -p "$TEST_HOME/.config/tproj"

lstart_epoch() {
  local pid="$1" line
  line=$(ps -p "$pid" -o lstart= 2>/dev/null)
  date -j -f "%a %b %d %H:%M:%S %Y" "$line" +%s 2>/dev/null || echo 0
}

write_registry_entry() {
  local alias="$1" pid="$2" pid_start="$3" role_epoch="$4" role="$5" orchestrator_alias="$6" observed_at="${7:-$(date +%s)}"
  cat > "$REGISTRY_ROOT/tproj-workspace/1/${alias}.json" <<JSON
{"alias":"${alias}","pid":${pid},"pid_start":${pid_start},"role_epoch":${role_epoch},"role":"${role}","orchestrator_alias":"${orchestrator_alias}","observed_at":${observed_at}}
JSON
}

# Run "$@" (a tproj-msg invocation) with a real process renamed to
# $platform (claude|codex) as its direct parent, after that process writes
# a matching registry entry for $claimed_alias using its own true pid and
# pid_start. Prints combined stdout+stderr; returns the command's exit code.
run_as_verified_agent() {
  local claimed_alias="$1" platform="$2" role_epoch="$3" role="$4" orchestrator_alias="$5"
  shift 5
  local runner="$WORK/verified_runner.sh"
  cat > "$runner" <<'RUNNER'
#!/bin/bash
set -uo pipefail
mypid=$$
mystart=$(date -j -f "%a %b %d %H:%M:%S %Y" "$(ps -p "$mypid" -o lstart=)" +%s 2>/dev/null || echo 0)
cat > "$REG_FILE" <<JSON
{"alias":"$CLAIMED_ALIAS","pid":$mypid,"pid_start":$mystart,"role_epoch":$ROLE_EPOCH,"role":"$ROLE","orchestrator_alias":"$ORCH_ALIAS","observed_at":$(date +%s)}
JSON
"$@"
RUNNER
  chmod +x "$runner"
  REG_FILE="$REGISTRY_ROOT/tproj-workspace/1/${claimed_alias}.json" \
  CLAIMED_ALIAS="$claimed_alias" ROLE_EPOCH="$role_epoch" ROLE="$role" ORCH_ALIAS="$orchestrator_alias" \
    exec -a "$platform" bash "$runner" "$@"
}

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
  local platform="claude"
  [[ "$sender" == *.cdx ]] && platform="codex"
  run_as_verified_agent "$sender" "$platform" "$epoch" "worker" "$orchestrator" \
    "$TPROJ_MSG" --session tproj-workspace --as "$sender" --role-handoff --new-task \
    --ttl 60m --role-epoch "$epoch" --orchestrator "$orchestrator" "$target" "$body" 2>&1
}

# Unverified variant: no registry entry is written, so the ancestry+registry
# bind must fail and the caller falls back to unverified.
run_handoff_unverified() {
  local sender="$1" target="$2" epoch="$3" orchestrator="$4" body="$5"
  rm -f "$REGISTRY_ROOT/tproj-workspace/1/${sender}.json"
  "$TPROJ_MSG" --session tproj-workspace --as "$sender" --role-handoff --new-task \
    --ttl 60m --role-epoch "$epoch" --orchestrator "$orchestrator" "$target" "$body" 2>&1
}

run_ordinary_unverified() {
  local sender="$1" target="$2" body="$3"
  rm -f "$REGISTRY_ROOT/tproj-workspace/1/${sender}.json"
  "$TPROJ_MSG" --session tproj-workspace --as "$sender" "$target" "$body" 2>&1
}

run_ordinary_verified() {
  local sender="$1" target="$2" body="$3"
  local platform="claude"
  [[ "$sender" == *.cdx ]] && platform="codex"
  run_as_verified_agent "$sender" "$platform" 1 "worker" "$target" \
    "$TPROJ_MSG" --session tproj-workspace --as "$sender" "$target" "$body" 2>&1
}

HAS_SQLITE=0
command -v sqlite3 >/dev/null 2>&1 && HAS_SQLITE=1

WRAPPED_RUNNER="$WORK/verified_wrapper_runner.sh"
cat > "$WRAPPED_RUNNER" <<'WRAPPER'
#!/bin/bash
set -uo pipefail

depth="${WRAP_DEPTH:-0}"
if [[ "$depth" -gt 0 ]]; then
  export WRAP_DEPTH=$((depth - 1))
  bash "$0" "$@"
  exit $?
fi

mypid=$$
mystart=$(date -j -f "%a %b %d %H:%M:%S %Y" "$(ps -p "$mypid" -o lstart=)" +%s 2>/dev/null || echo 0)
registry_pid="${REGISTRY_PID_OVERRIDE:-$mypid}"
registry_pid_start="${REGISTRY_PID_START_OVERRIDE:-$mystart}"

cat > "$REG_FILE" <<JSON
{"alias":"$CLAIMED_ALIAS","pid":$registry_pid,"pid_start":$registry_pid_start,"role_epoch":$ROLE_EPOCH,"role":"$ROLE","orchestrator_alias":"$ORCH_ALIAS","observed_at":$(date +%s)}
JSON
"$@"
WRAPPER
chmod +x "$WRAPPED_RUNNER"

run_as_verified_agent_wrapped() {
  local claimed_alias="$1" role_epoch="$2" role="$3" orchestrator_alias="$4" wrap_depth="$5" reg_pid_override="$6" reg_start_override="$7"
  shift 7
  WRAP_DEPTH="$wrap_depth" \
    CLAIMED_ALIAS="$claimed_alias" ROLE_EPOCH="$role_epoch" ROLE="$role" ORCH_ALIAS="$orchestrator_alias" \
    REGISTRY_PID_OVERRIDE="${reg_pid_override:-}" REGISTRY_PID_START_OVERRIDE="${reg_start_override:-}" \
    REG_FILE="$REGISTRY_ROOT/tproj-workspace/1/${claimed_alias}.json" \
    bash "$WRAPPED_RUNNER" "$@"
}

db_last_claimed_id() {
  local alias="$1"
  local verified="${2:-}"
  local where="claimed_alias='${alias}' AND length(body)=0 AND length(body_hash)=0 AND ifnull(length(payload_sha256),0)=64"
  [[ -n "$verified" ]] && where+=" AND verified='${verified}'"
  sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COALESCE(COUNT(*),0) FROM messages WHERE ${where};" 2>/dev/null || echo 0
}

db_last_claimed_row() {
  local alias="$1"
  local verified="${2:-}"
  local where="claimed_alias='${alias}' AND length(body)=0 AND length(body_hash)=0 AND ifnull(length(payload_sha256),0)=64"
  [[ -n "$verified" ]] && where+=" AND verified='${verified}'"
  sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT verified, ifnull(rejection_reason,''), length(body), length(body_hash), length(payload_sha256), body, body_hash FROM messages WHERE ${where} ORDER BY id DESC LIMIT 1;" 2>/dev/null || true
}

assert_caller_event_once() {
  local alias="$1" expected_verified="$2" expected_reason_empty="$3" label="$4"
  local before="$5" after row verified reason body_len body_hash_len sha_len
  if [[ "$HAS_SQLITE" -eq 0 ]]; then
    pass "$label"
    return 0
  fi
  after="$(db_last_claimed_id "$alias" "$expected_verified")"
  if [[ $((after - before)) -ne 1 ]]; then
    fail "$label" "expected 1 caller-event; before=$before after=$after"
    return 0
  fi
  IFS='|' read -r verified reason body_len body_hash_len sha_len _body _body_hash <<< "$(db_last_claimed_row "$alias" "$expected_verified")"
  if [[ "$verified" == "$expected_verified" && "$body_len" == "0" && "$body_hash_len" == "0" && "$sha_len" == "64" ]]; then
    if [[ "$expected_reason_empty" == "require-empty" && -n "$reason" ]]; then
      fail "$label" "reason not empty (verified=$verified, reason=$reason)"
    elif [[ "$expected_reason_empty" == "require-non-empty" && -z "$reason" ]]; then
      fail "$label" "reason empty for rejected decision (verified=$verified)"
    else
      pass "$label"
    fi
  else
    fail "$label" "caller event malformed (verified=$verified reason=$reason body_len=$body_len body_hash_len=$body_hash_len sha_len=$sha_len)"
  fi
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

if [[ "$HAS_SQLITE" -eq 1 ]]; then
  before_id="$(db_last_claimed_id tproj.cc 1)"
else
  before_id=0
fi
reset_case
set_state %2 idle
out="$(run_handoff tproj.cc tproj.cdx 7 tproj.cc 'verified-role-handoff-accept-audit' 2>&1)"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[Role-Handoff:'* && "$log" == *$'Role-Epoch: 7\nOrchestrator: tproj.cc\n[Task:'* ]]; then
  if [[ "$HAS_SQLITE" -eq 1 ]]; then
    assert_caller_event_once tproj.cc 1 require-empty "verified_role_handoff_accepts_caller_event" "$before_id"
  else
    pass verified_role_handoff_accepts_caller_event
  fi
else
  fail verified_role_handoff_accepts_caller_event "rc=$rc out=$out log=$log"
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

# Legacy --new-task from a VERIFIED sender stays unchanged; ACK/DONE/BLOCK
# tags remain readable. (R2 Stage 1: unverified --as is now refused for
# ordinary sends too, so this case runs through the registry harness.)
reset_case
set_state %2 idle
out="$(run_as_verified_agent tproj.cc claude 1 worker tproj.cdx \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --new-task tproj.cdx 'legacy-task' 2>&1)"; rc=$?
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

# --- R2 Stage 1: fail-closed sender verification -------------------------

# Verified ordinary --as send succeeds only when explicit registry/ancestry binding
# succeeds; for deep wrapper ancestry this requires registry pid+pid_start in-chain.
before_id=0
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  before_id="$(db_last_claimed_id tproj.cc 1)"
fi
reset_case
set_state %2 idle
out="$(run_as_verified_agent_wrapped tproj.cc 1 worker tproj.cc 8 '' '' \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc tproj.cdx 'wrapped-verified')"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[from:tproj.cc]'* ]]; then
  assert_caller_event_once tproj.cc 1 require-empty "verified_ordinary_send_wrapped_chain" "$before_id"
else
  fail verified_ordinary_send_wrapped_chain "rc=$rc out=$out log=$log"
fi

# Same deep wrapper chain, but the registry pid_start/pid pair is not the caller:
# should be rejected and still emit exactly one reject audit row (reason non-empty).
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  before_id="$(db_last_claimed_id tproj.cc 0)"
fi
reset_case
out="$(run_as_verified_agent_wrapped tproj.cc 1 worker tproj.cc 8 999999 1 \
  2>&1 \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc tproj.cdx 'wrapped-mismatch')"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  assert_caller_event_once tproj.cc 0 require-non-empty "wrapped_chain_registry_mismatch_rejected" "$before_id"
else
  fail wrapped_chain_registry_mismatch_rejected "rc=$rc out=$out"
fi

# Unverified ordinary (non-role-handoff) --as send is refused: no
# tmux send-keys, and the reject audit row carries no body content.
reset_case
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  before_id="$(db_last_claimed_id tproj.cc 0)"
fi
out="$(run_ordinary_unverified tproj.cc tproj.cdx 'no-registry-entry')"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  if [[ "$HAS_SQLITE" -eq 1 ]]; then
    assert_caller_event_once tproj.cc 0 require-non-empty "unverified_ordinary_send_rejected" "$before_id"
  else
    pass unverified_ordinary_send_rejected
  fi
else
  fail unverified_ordinary_send_rejected "rc=$rc out=$out"
fi

# Unverified --role-handoff send is refused the same way.
reset_case
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  before_id="$(db_last_claimed_id tproj.cc 0)"
fi
out="$(run_handoff_unverified tproj.cc tproj.cdx 7 tproj.cdx 'no-registry-entry')"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  if [[ "$HAS_SQLITE" -eq 1 ]]; then
    assert_caller_event_once tproj.cc 0 require-non-empty "unverified_role_handoff_rejected" "$before_id"
  else
    pass unverified_role_handoff_rejected
  fi
else
  fail unverified_role_handoff_rejected "rc=$rc out=$out"
fi

# A registry entry recorded for a DIFFERENT (now-dead) pid/pid_start must
# not verify a live process that merely shares the claimed alias --
# guards against pid reuse.
reset_case
set_state %2 idle
write_registry_entry tproj.cc 999999 1 1 worker tproj.cdx
out="$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --role-handoff --new-task \
  --role-epoch 1 --orchestrator tproj.cdx tproj.cdx 'stale-pid' 2>&1)"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  pass pid_reuse_registry_mismatch_rejected
else
  fail pid_reuse_registry_mismatch_rejected "rc=$rc out=$out"
fi

# pid_start mismatch specifically: same pid number as the real caller
# but a fabricated pid_start value that does not match the process's
# true start time.
reset_case
set_state %2 idle
runner="$WORK/pidstart_mismatch_runner.sh"
cat > "$runner" <<'RUNNER'
#!/bin/bash
set -uo pipefail
mypid=$$
cat > "$REG_FILE" <<JSON
{"alias":"tproj.cc","pid":$mypid,"pid_start":1,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":$(date +%s)}
JSON
"$@"
RUNNER
chmod +x "$runner"
out="$(REG_FILE="$REGISTRY_ROOT/tproj-workspace/1/tproj.cc.json" exec -a claude bash "$runner" \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --role-handoff --new-task \
  --role-epoch 1 --orchestrator tproj.cdx tproj.cdx 'wrong-pid-start' 2>&1)"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  pass pid_start_mismatch_rejected
else
  fail pid_start_mismatch_rejected "rc=$rc out=$out"
fi

# Verified caller, but the claimed --role-epoch disagrees with the
# registry's recorded role_epoch for that alias.
reset_case
set_state %2 idle
out="$(run_as_verified_agent tproj.cc claude 42 worker tproj.cdx \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --role-handoff --new-task \
  --role-epoch 999 --orchestrator tproj.cdx tproj.cdx 'wrong-epoch' 2>&1)"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'role-epoch'* ]]; then
  pass role_epoch_mismatch_rejected
else
  fail role_epoch_mismatch_rejected "rc=$rc out=$out"
fi

# Verified caller, correct epoch, but the claimed --orchestrator disagrees
# with the registry's orchestrator_alias for that alias.
reset_case
set_state %2 idle
out="$(run_as_verified_agent tproj.cc claude 5 worker tproj.cdx \
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --role-handoff --new-task \
  --role-epoch 5 --orchestrator some.imposter tproj.cdx 'wrong-orchestrator' 2>&1)"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'orchestrator'* ]]; then
  pass orchestrator_mismatch_rejected
else
  fail orchestrator_mismatch_rejected "rc=$rc out=$out"
fi

# Stale registry entry (observed_at far in the past) is treated as
# insufficient evidence, not as a valid verification -- anti-replay.
reset_case
set_state %2 idle
write_registry_entry tproj.cc 1 1 1 worker tproj.cdx "$(( $(date +%s) - 999999 ))"
out="$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --role-handoff --new-task \
  --role-epoch 1 --orchestrator tproj.cdx tproj.cdx 'stale-registry' 2>&1)"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  pass stale_registry_rejected
else
  fail stale_registry_rejected "rc=$rc out=$out"
fi

# The reject audit trail never stores message body/title content: body
# and body_hash are empty, and only a payload_sha256 reference is kept.
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  reset_case
  before_id="$(db_last_claimed_id tproj.cc 0)"
  out="$(run_ordinary_unverified tproj.cc tproj.cdx 'must-not-be-persisted-anywhere')"
  assert_caller_event_once tproj.cc 0 require-non-empty "reject_audit_body_never_persisted" "$before_id"
  row="$(db_last_claimed_row tproj.cc 0)"
  if [[ -n "$row" ]]; then
    IFS='|' read -r verified reason body_len body_hash_len sha_len _body _body_hash <<< "$row"
    if [[ "$verified" != "0" || "$body_len" != "0" || "$body_hash_len" != "0" || "$sha_len" != "64" || -z "$reason" ]]; then
      fail reject_audit_body_never_persisted "row=$row"
    fi
  else
    fail reject_audit_body_never_persisted "row=$row"
  fi
else
  printf 'SKIP  reject_audit_body_never_persisted: sqlite3 not available\n'
fi

# --- R2 Stage 1: bare-role service-bound verifier (gate reverse-delivery) --

FAKE_SERVICE_BIN="$WORK/fake-clawgate-bin"
printf '#!/bin/bash\nexec "$@"\n' > "$FAKE_SERVICE_BIN"
chmod +x "$FAKE_SERVICE_BIN"
mkdir -p "$TEST_HOME/.config/tproj"
cat > "$TEST_HOME/.config/tproj/workspace.yaml" <<YAML
gui:
  bridge:
    trusted_caller_executable: "$FAKE_SERVICE_BIN"
YAML

run_as_bare_role_caller() {
  local exec_path="$1"; shift
  local runner="$WORK/service_runner.sh"
  printf '#!/bin/bash\n"$@"\n' > "$runner"
  chmod +x "$runner"
  HOME="$TEST_HOME" exec -a "$exec_path" bash "$runner" "$@" 2>&1
}

# Genuine reverse-delivery caller (ancestry matches the configured service
# executable, same UID) is accepted -- the normal ClawGate reply path.
reset_case
set_state %2 idle
out="$(run_as_bare_role_caller "$FAKE_SERVICE_BIN" \
  "$TPROJ_MSG" --session tproj-workspace --as "OpenClaw Agent - Reply" tproj.cdx 'reply-from-chi')"; rc=$?
log="$(cat "$FIXTURES/sendkeys.log" 2>/dev/null || true)"
if [[ $rc -eq 0 && "$log" == *'[from:OpenClaw Agent - Reply]'* ]]; then
  pass bare_role_valid_service_ancestry_allow
else
  fail bare_role_valid_service_ancestry_allow "rc=$rc out=$out log=$log"
fi

# Same UID, but the ancestor process is not the configured service
# executable -- rejected (covers both "unrelated process" and "wrong
# executable" framings, since this implementation binds on executable
# identity as the primary factor).
reset_case
set_state %2 idle
out="$(run_as_bare_role_caller "/bin/some-unrelated-binary" \
  "$TPROJ_MSG" --session tproj-workspace --as "OpenClaw Agent - Reply" tproj.cdx 'reply-from-imposter')"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" && "$out" == *'could not be verified'* ]]; then
  pass bare_role_wrong_executable_rejected
else
  fail bare_role_wrong_executable_rejected "rc=$rc out=$out"
fi

# A bare role with no known service binding at all is default-deny.
reset_case
set_state %2 idle
out="$(run_as_bare_role_caller "$FAKE_SERVICE_BIN" \
  "$TPROJ_MSG" --session tproj-workspace --as "totally-unknown-role" tproj.cdx 'unknown-role')"; rc=$?
if [[ $rc -ne 0 && ! -f "$FIXTURES/sendkeys.log" ]]; then
  pass bare_role_unknown_default_deny
else
  fail bare_role_unknown_default_deny "rc=$rc out=$out"
fi

printf '%s\n' '----'
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

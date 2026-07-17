#!/usr/bin/env bash
#
# test-desktop-mailbox.sh — hermetic coverage for the Codex Desktop <-> tmux
# session data-plane mailbox.
#
# Drives the REAL tproj-msg with a Desktop registry fixture and a fake tmux on
# PATH. Uses MODEL_ROLE_CACHE / TPROJ_MSG_DB_PATH / TPROJ_DESKTOP_MAILBOX_ROOT
# overrides exclusively; never touches the real registry, messages.db, or the
# production mailbox.
#
# Covered:
#   - Desktop identity resolution: genuine ancestry+pid_start -> resolve;
#     forged (pid-reuse), stale, future observed_at, unrecorded pid_start,
#     ambiguous (two live entries) -> fail-closed reject.
#   - Desktop -> session mailbox write (envelope on disk, 0700 dir / 0600 file).
#   - NO raw_send / body injection: sendkeys.log never appears.
#   - Body-free arrival bell: DB inbound row (bridge=desktop) has empty body.
#   - Control-plane use rejected (--new-task/--role-handoff/--force/--as/relay/fanout).
#   - Symmetric exchange: session -> desktop.<project> -> Desktop --mailbox read.
#   - session-side --read desktop reads Desktop -> session envelopes (pure).
#   - size / count bounds.
#
# Usage: bash extensions/messaging/tests/test-desktop-mailbox.sh [path-to-tproj-msg]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REAL_TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"
if [[ ! -x "$REAL_TPROJ_MSG" ]]; then
  echo "FATAL: tproj-msg not found/executable at: $REAL_TPROJ_MSG" >&2
  exit 2
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-dtm.XXXXXX")
FAKE_DIR="$WORK/fixtures"; BIN_DIR="$WORK/bin"
mkdir -p "$FAKE_DIR" "$BIN_DIR" "$WORK/queue"
trap 'rm -rf "$WORK"' EXIT

REGISTRY_ROOT="$WORK/registry"
mkdir -p "$REGISTRY_ROOT/standalone/standalone"
export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/db-errors.log"
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
export TPROJ_DESKTOP_MAILBOX_ROOT="$WORK/mailbox"
# Hard invariant: never run against the real production DB.
if [[ -z "${TPROJ_MSG_DB_PATH:-}" || "$TPROJ_MSG_DB_PATH" == "$HOME/.local/share/tproj-msg/messages.db" ]]; then
  echo "FATAL: TPROJ_MSG_DB_PATH not isolated to a temp DB" >&2
  exit 2
fi

# --- fake tmux ---------------------------------------------------------------
# Records any send-keys (so the no-injection assertion can fire) and answers the
# in-tmux preflight display-message queries so the session-side path can run.
# HARNESS_PANE_PID ($$ of the session wrapper) is a genuine ancestor of tproj-msg.
cat > "$BIN_DIR/tmux" <<'TMUX'
#!/usr/bin/env bash
set -uo pipefail
FAKE_DIR="$FAKE_DIR_ENV"
sub="${1:-}"; shift || true
fmt=""; tgt=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    -p|-F) fmt="${args[$((i+1))]:-}";;
    -t)    tgt="${args[$((i+1))]:-}";;
  esac
done
# Reproduce tmux session-target semantics so the Fix 2 exact-match ('=') gate is
# genuinely exercised: a '=name' target matches EXACTLY, a bare name matches by
# PREFIX (tmux's default). Only tproj-workspace is a live session. The window
# part (":dev") is stripped before matching the session name.
fake_live_sessions="tproj-workspace"
fake_session_live() {
  local t="${1%%:*}" exact=0 s
  case "$t" in =*) exact=1; t="${t#=}";; esac
  for s in $fake_live_sessions; do
    if (( exact )); then
      [[ "$s" == "$t" ]] && return 0
    else
      [[ "$s" == "$t"* ]] && return 0
    fi
  done
  return 1
}
case "$sub" in
  send-keys) printf 'SENDKEYS %s\n' "$*" >> "$FAKE_DIR/sendkeys.log";;
  display-message)
    case "$fmt" in
      "#S"|"") printf '%s' "tproj-workspace";;
      *@alias*)   printf '%s' "tproj";;
      *@role*)    printf '%s' "claude-p1";;
      *@column*)  printf '%s' "1";;
      *pane_pid*) printf '%s' "${HARNESS_PANE_PID:-0}";;
      *pane_id*)  printf '%s' "%1";;
      *) : ;;
    esac ;;
  # Only tproj-workspace is live; a bare prefix would match under tmux's default
  # but the '=' exact target the code now uses must not.
  has-session) fake_session_live "$tgt" && exit 0 || exit 1;;
  list-panes)  if fake_session_live "$tgt"; then
                 # FAKE_PANE_LIST overrides the canonical two-pane column so a
                 # test can build a multi-match (ambiguous) or dead-pane fixture.
                 # The trailing field is #{pane_dead} (0 live / 1 dead).
                 if [[ -n "${FAKE_PANE_LIST:-}" ]]; then
                   printf '%s\n' "$FAKE_PANE_LIST"
                 else
                   printf '%%1:claude-p1:tproj:1:0\n%%2:codex-p1:tproj:1:0\n'
                 fi
               fi ;;
  set-option|set|setenv) exit 0;;
  *) : ;;
esac
exit 0
TMUX
chmod +x "$BIN_DIR/tmux"
export FAKE_DIR_ENV="$FAKE_DIR"
export PATH="$BIN_DIR:$PATH"

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf 'PASS  %s\n' "$1"; }
no()   { FAIL=$((FAIL+1)); printf 'FAIL  %s: %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP+1)); printf 'SKIP  %s: %s\n' "$1" "$2"; }
HAS_SQLITE=0; command -v sqlite3 >/dev/null 2>&1 && HAS_SQLITE=1

reason_of() { sed -n 's/.*reason: \([a-z_]*\).*/\1/p' <<<"$1" | head -1; }

# Desktop wrapper: becomes a genuine ancestor of tproj-msg, writes a Desktop
# registry entry recording its own pid + pid_start, then invokes tproj-msg. The
# trailing `rc=$?` keeps the wrapper a distinct process (no exec-optimisation),
# so its pid is a real ancestor found by the ancestry walk.
#   DT_MODE: good | pid_reuse | stale | future | no_pid_start | standalone
DT_WRAP="$BIN_DIR/dt-wrap"
cat > "$DT_WRAP" <<WRAP
#!/bin/bash
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
obs=\$(date +%s)
regf="$REGISTRY_ROOT/standalone/standalone/desktop.json"
ps_val="\$mystart"; obs_val="\$obs"; ic='"identity_class":"desktop",'
case "\${DT_MODE:-good}" in
  pid_reuse)    ps_val=\$((mystart+9999)) ;;
  stale)        obs_val=\$((obs-999999)) ;;
  future)       obs_val=\$((obs+999999)) ;;
  no_pid_start) ps_val=0 ;;
  standalone)   ic='' ;;   # no identity_class -> exercise the standalone heuristic
esac
if [[ "\$ps_val" == "0" ]]; then
  printf '{%s"session":"standalone","column":"standalone","desktop_project":"tproj","pid":%s,"observed_at":%s}\n' "\$ic" "\$mypid" "\$obs_val" > "\$regf"
else
  printf '{%s"session":"standalone","column":"standalone","desktop_project":"tproj","pid":%s,"pid_start":%s,"observed_at":%s}\n' "\$ic" "\$mypid" "\$ps_val" "\$obs_val" > "\$regf"
fi
"$REAL_TPROJ_MSG" "\$@"
rc=\$?
exit \$rc
WRAP
chmod +x "$DT_WRAP"

run_dt() { # <DT_MODE> <args...> -> combined output
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT/standalone/standalone/"*.json 2>/dev/null
  DT_MODE="$1" "$DT_WRAP" "${@:2}" 2>&1
}

# 1. genuine identity + --mailbox read of empty mailbox -> resolves, exit 0.
out=$(run_dt good --desktop --session tproj-workspace --mailbox); rc=$?
if [[ $rc -eq 0 ]] && ! grep -q "could not be resolved" <<<"$out"; then
  ok dtm01_genuine_mailbox_read
else no dtm01_genuine_mailbox_read "rc=$rc out=[$out]"; fi

# 2. Desktop -> session send: envelope written, "Delivered" reported.
out=$(run_dt good --desktop --session tproj-workspace tproj.cc "hello from desktop")
mbdir="$WORK/mailbox/to-session/tproj-workspace/tproj.cc"
env_files=("$mbdir"/*.json)
if grep -q "Delivered to Desktop mailbox" <<<"$out" && [[ -e "${env_files[0]:-}" ]]; then
  ok dtm02_send_writes_envelope
else no dtm02_send_writes_envelope "out=[$out] dir=$mbdir"; fi

# 3. NO body injection: fake tmux send-keys never called.
if [[ ! -e "$FAKE_DIR/sendkeys.log" ]]; then
  ok dtm03_no_send_keys_injection
else no dtm03_no_send_keys_injection "sendkeys.log present: $(cat "$FAKE_DIR/sendkeys.log")"; fi

# 4. envelope content: body stored, bridge=desktop, from=desktop.tproj.
ef="${env_files[0]:-}"
if [[ -n "$ef" ]] \
   && [[ "$(jq -r '.body' "$ef")" == "hello from desktop" ]] \
   && [[ "$(jq -r '.bridge' "$ef")" == "desktop" ]] \
   && [[ "$(jq -r '.from' "$ef")" == "desktop.tproj" ]]; then
  ok dtm04_envelope_fields
else no dtm04_envelope_fields "envelope=$(cat "$ef" 2>/dev/null)"; fi

# 5. permissions: mailbox root 0700, envelope file 0600.
root_perm=$(stat -f '%Lp' "$WORK/mailbox" 2>/dev/null)
file_perm=$(stat -f '%Lp' "$ef" 2>/dev/null)
if [[ "$root_perm" == "700" && "$file_perm" == "600" ]]; then
  ok dtm05_permissions
else no dtm05_permissions "root=$root_perm file=$file_perm"; fi

# 6. body-free arrival bell: DB inbound row (bridge=desktop) has empty body.
if [[ $HAS_SQLITE -eq 1 ]]; then
  row=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT to_alias||'|'||bridge||'|'||length(body)||'|'||direction FROM messages WHERE bridge='desktop' AND direction='inbound' ORDER BY id DESC LIMIT 1;" 2>/dev/null)
  if [[ "$row" == "tproj.cc|desktop|0|inbound" ]]; then
    ok dtm06_body_free_bell
  else no dtm06_body_free_bell "row=[$row]"; fi
else skip dtm06_body_free_bell "no sqlite3"; fi

# 7. forged (pid-reuse: recorded pid_start != live start) -> reject.
out=$(run_dt pid_reuse --desktop --session tproj-workspace tproj.cc "x")
[[ "$(reason_of "$out")" == "desktop_identity_unresolved" ]] \
  && ok dtm07_pid_reuse_reject || no dtm07_pid_reuse_reject "out=[$out]"

# 8. stale observed_at -> reject.
out=$(run_dt stale --desktop --session tproj-workspace tproj.cc "x")
[[ "$(reason_of "$out")" == "desktop_identity_unresolved" ]] \
  && ok dtm08_stale_reject || no dtm08_stale_reject "out=[$out]"

# 9. future observed_at -> reject.
out=$(run_dt future --desktop --session tproj-workspace tproj.cc "x")
[[ "$(reason_of "$out")" == "desktop_identity_unresolved" ]] \
  && ok dtm09_future_reject || no dtm09_future_reject "out=[$out]"

# 10. unrecorded pid_start -> reject (fail-closed like the alias.role verifier).
out=$(run_dt no_pid_start --desktop --session tproj-workspace tproj.cc "x")
[[ "$(reason_of "$out")" == "desktop_identity_unresolved" ]] \
  && ok dtm10_no_pid_start_reject || no dtm10_no_pid_start_reject "out=[$out]"

# 11. standalone heuristic (no identity_class field) still resolves.
out=$(run_dt standalone --desktop --session tproj-workspace tproj.cc "heuristic body")
grep -q "Delivered to Desktop mailbox" <<<"$out" \
  && ok dtm11_standalone_heuristic || no dtm11_standalone_heuristic "out=[$out]"

# 12. ambiguous: two live desktop entries both match -> reject.
rm -f "$REGISTRY_ROOT/standalone/standalone/"*.json 2>/dev/null
AMB_WRAP="$BIN_DIR/amb-wrap"
cat > "$AMB_WRAP" <<WRAP
#!/bin/bash
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
obs=\$(date +%s)
for n in a b; do
  printf '{"identity_class":"desktop","desktop_project":"tproj_%s","pid":%s,"pid_start":%s,"observed_at":%s}\n' "\$n" "\$mypid" "\$mystart" "\$obs" > "$REGISTRY_ROOT/standalone/standalone/desktop_\$n.json"
done
"$REAL_TPROJ_MSG" "\$@"
rc=\$?
exit \$rc
WRAP
chmod +x "$AMB_WRAP"
out=$("$AMB_WRAP" --desktop --session tproj-workspace tproj.cc "x" 2>&1)
[[ "$(reason_of "$out")" == "desktop_identity_ambiguous" ]] \
  && ok dtm12_ambiguous_reject || no dtm12_ambiguous_reject "out=[$out]"

# 13-18. control-plane use is rejected (no write) from the Desktop identity.
ctl_reject() { # <label> <flag-args...>
  local label="$1"; shift
  local out
  out=$(run_dt good --desktop --session tproj-workspace "$@" tproj.cc "ctl body")
  if grep -q "rejects control-plane use" <<<"$out" && [[ ! -e "$FAKE_DIR/sendkeys.log" ]]; then
    ok "$label"
  else no "$label" "out=[$out]"; fi
}
ctl_reject dtm13_reject_new_task    --new-task
ctl_reject dtm14_reject_role_handoff --role-handoff --new-task
ctl_reject dtm15_reject_force       --force
ctl_reject dtm16_reject_allow_relay --allow-relay reasonx
ctl_reject dtm17_reject_allow_fanout --allow-fanout reasonx
# --as claim from Desktop is rejected before identity is even trusted.
out=$(run_dt good --desktop --session tproj-workspace --as tproj.cc tproj.cc "as body")
grep -q "rejects control-plane use" <<<"$out" \
  && ok dtm18_reject_as || no dtm18_reject_as "out=[$out]"

# 19. size bound: a body over the cap -> reject, no envelope.
big=$(head -c 200 /dev/zero | tr '\0' 'x')
export TPROJ_DESKTOP_MAILBOX_MAX_BYTES=100
out=$(run_dt good --desktop --session tproj-workspace tproj.cc "$big")
unset TPROJ_DESKTOP_MAILBOX_MAX_BYTES
grep -q "exceeds mailbox size limit" <<<"$out" \
  && ok dtm19_size_bound || no dtm19_size_bound "out=[$out]"

# 20. count bound: fill mailbox to the cap, next write -> full.
CNT_DIR="$WORK/mailbox/to-session/tproj-workspace/tproj.cdx"
mkdir -p "$CNT_DIR"
for i in 1 2 3; do printf '{"from":"x","to":"y","body":"b","created_at":0,"bridge":"desktop"}' > "$CNT_DIR/pre-$i.json"; done
export TPROJ_DESKTOP_MAILBOX_MAX_COUNT=3
out=$(run_dt good --desktop --session tproj-workspace tproj.cdx "overflow")
unset TPROJ_DESKTOP_MAILBOX_MAX_COUNT
grep -q "is full" <<<"$out" \
  && ok dtm20_count_bound || no dtm20_count_bound "out=[$out]"

# --- session -> desktop -> Desktop --mailbox read (symmetric) ---------------
# A session pane writes to desktop.tproj; the Desktop side reads it back. The
# session write path is exercised by the caller-verify machinery, so here we
# simulate it by placing an envelope directly in the to-desktop mailbox and
# verifying the Desktop --mailbox read returns it (pure inspection).
D2S_DIR="$WORK/mailbox/to-desktop/tproj"
mkdir -p "$D2S_DIR"
printf '{"from":"tproj.cc","to":"desktop.tproj","body":"reply from session","created_at":%s,"bridge":"desktop"}' "$(date +%s)" > "$D2S_DIR/env1.json"
out=$(run_dt good --desktop --session tproj-workspace --mailbox 2>&1)
grep -q "reply from session" <<<"$out" \
  && ok dtm21_desktop_reads_session_reply || no dtm21_desktop_reads_session_reply "out=[$out]"

# 22. read is pure: the read did not delete the envelope, no send-keys.
if [[ -e "$D2S_DIR/env1.json" && ! -e "$FAKE_DIR/sendkeys.log" ]]; then
  ok dtm22_read_is_pure
else no dtm22_read_is_pure "env-present=$([[ -e "$D2S_DIR/env1.json" ]] && echo y || echo n)"; fi

# --- session side (in-tmux): send to desktop.<project> + --read desktop ------
# The session wrapper is a genuine ancestor; the pane-derived path verifies the
# pane_pid (HARNESS_PANE_PID) is an ancestor -> AS_CALLER_VERIFIED=true.
SESS_WRAP="$BIN_DIR/sess-wrap"
cat > "$SESS_WRAP" <<WRAP
#!/bin/bash
export TMUX=1 TMUX_PANE=%1
export HARNESS_PANE_PID=\$\$
"$REAL_TPROJ_MSG" "\$@"
rc=\$?
exit \$rc
WRAP
chmod +x "$SESS_WRAP"

run_sess() { rm -f "$FAKE_DIR/sendkeys.log"; "$SESS_WRAP" "$@" 2>&1; }

# 23. session -> desktop.tproj write, no send-keys.
out=$(run_sess desktop.tproj "reply to desktop")
d2d="$WORK/mailbox/to-desktop/tproj"
if grep -q "Delivered to Desktop mailbox: tproj.cc -> desktop.tproj" <<<"$out" \
   && ls "$d2d"/*.json >/dev/null 2>&1 && [[ ! -e "$FAKE_DIR/sendkeys.log" ]]; then
  ok dtm23_session_to_desktop_write
else no dtm23_session_to_desktop_write "out=[$out]"; fi

# 24. --read desktop reads what Desktop sent to this pane (to-session mailbox).
s2p="$WORK/mailbox/to-session/tproj-workspace/tproj.cc"
mkdir -p "$s2p"
printf '{"from":"desktop.tproj","to":"tproj.cc","body":"ping to pane","created_at":%s,"bridge":"desktop"}' "$(date +%s)" > "$s2p/ping.json"
out=$(run_sess --read desktop)
grep -q "ping to pane" <<<"$out" \
  && ok dtm24_session_read_desktop || no dtm24_session_read_desktop "out=[$out]"

# 25. session -> desktop with --new-task is rejected (no cross-boundary tasks).
out=$(run_sess --new-task desktop.tproj "task body")
grep -q "not supported for Desktop mailbox targets" <<<"$out" \
  && ok dtm25_session_new_task_reject || no dtm25_session_new_task_reject "out=[$out]"

# 26. full round trip: session write -> Desktop --mailbox read sees it.
rm -rf "$WORK/mailbox/to-desktop/tproj"
run_sess desktop.tproj "roundtrip body" >/dev/null 2>&1
out=$(run_dt good --desktop --session tproj-workspace --mailbox 2>&1)
grep -q "roundtrip body" <<<"$out" \
  && ok dtm26_full_round_trip || no dtm26_full_round_trip "out=[$out]"

# --- Fix 1: Desktop send is bounded to a live session + a single canonical pane.
# 27. unknown session -> reject; no mailbox dir, no DB row, no send-keys.
rm -rf "$WORK/mailbox/to-session/no-such-session" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
out=$(run_dt good --desktop --session no-such-session tproj.cc "to nowhere")
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "session 'no-such-session' is not live" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/no-such-session" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm27_invalid_session_reject
else no dtm27_invalid_session_reject "out=[$out] db=$db_before->$db_after"; fi

# 28. unresolvable target alias -> reject; no mailbox dir, no DB row, no send-keys.
rm -rf "$WORK/mailbox/to-session/tproj-workspace/ghost.cc" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
out=$(run_dt good --desktop --session tproj-workspace ghost.cc "to ghost")
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "does not resolve to a live pane" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/tproj-workspace/ghost.cc" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm28_invalid_target_reject
else no dtm28_invalid_target_reject "out=[$out] db=$db_before->$db_after"; fi

# --- Strict single-match: a target resolving to MORE THAN ONE live canonical
# pane is rejected as ambiguous (fail-closed), never first-match picked. Both
# reject paths must leave NO mailbox file, NO body-free DB bell, NO send-keys.
# 36. alias spans two columns -> ambiguous reject.
rm -rf "$WORK/mailbox/to-session/tproj-workspace/amb.cc" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
export FAKE_PANE_LIST=$'%1:claude-p1:amb:1\n%2:codex-p1:amb:1\n%3:claude-p2:amb:2\n%4:codex-p2:amb:2'
out=$(run_dt good --desktop --session tproj-workspace amb.cc "to ambiguous alias")
unset FAKE_PANE_LIST
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "resolves to multiple live panes" <<<"$out" \
   && grep -q "(ambiguous)" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/tproj-workspace/amb.cc" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm36_ambiguous_alias_columns_reject
else no dtm36_ambiguous_alias_columns_reject "out=[$out] db=$db_before->$db_after"; fi

# 37. duplicate canonical pane (same alias+role+column) -> ambiguous reject.
rm -rf "$WORK/mailbox/to-session/tproj-workspace/dup.cc" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
export FAKE_PANE_LIST=$'%1:claude-p1:dup:1\n%5:claude-p1:dup:1'
out=$(run_dt good --desktop --session tproj-workspace dup.cc "to duplicate pane")
unset FAKE_PANE_LIST
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "resolves to multiple live panes" <<<"$out" \
   && grep -q "(ambiguous)" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/tproj-workspace/dup.cc" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm37_ambiguous_duplicate_pane_reject
else no dtm37_ambiguous_duplicate_pane_reject "out=[$out] db=$db_before->$db_after"; fi

# --- Fix 2: the size cap is enforced in BYTES, not characters.
# 29. 4 Japanese chars == 12 bytes > 10-byte cap -> reject (char count 4 would pass).
jp4=$'\xe3\x81\x82\xe3\x81\x82\xe3\x81\x82\xe3\x81\x82'   # 12 bytes / 4 chars
export TPROJ_DESKTOP_MAILBOX_MAX_BYTES=10
out=$(run_dt good --desktop --session tproj-workspace tproj.cc "$jp4")
unset TPROJ_DESKTOP_MAILBOX_MAX_BYTES
grep -q "exceeds mailbox size limit" <<<"$out" \
  && ok dtm29_multibyte_bytes_over_reject || no dtm29_multibyte_bytes_over_reject "out=[$out]"

# 30. 3 Japanese chars == 9 bytes <= 10-byte cap -> accepted (byte count, not chars).
rm -rf "$WORK/mailbox/to-session/tproj-workspace/tproj.cc" 2>/dev/null
jp3=$'\xe3\x81\x82\xe3\x81\x82\xe3\x81\x82'   # 9 bytes / 3 chars
export TPROJ_DESKTOP_MAILBOX_MAX_BYTES=10
out=$(run_dt good --desktop --session tproj-workspace tproj.cc "$jp3")
unset TPROJ_DESKTOP_MAILBOX_MAX_BYTES
if grep -q "Delivered to Desktop mailbox" <<<"$out" \
   && ls "$WORK/mailbox/to-session/tproj-workspace/tproj.cc"/*.json >/dev/null 2>&1; then
  ok dtm30_multibyte_bytes_under_accept
else no dtm30_multibyte_bytes_under_accept "out=[$out]"; fi

# --- Fix 3: per-mailbox lock (cap under concurrency) + collision-free writes.
# Exercised at the function level: the helper's write path is self-contained
# (no registry deps), so source it directly and drive concurrent writers.
HELPER="$SCRIPT_DIR/../tproj-msg-desktop.sh"

# 31. N concurrent writers never exceed MAX_COUNT (lock serializes count->write).
CC_DIR="$WORK/mailbox/to-session/tproj-workspace/conc.cc"
(
  export TPROJ_DESKTOP_MAILBOX_ROOT="$WORK/mailbox"
  export TPROJ_DESKTOP_MAILBOX_MAX_COUNT=5
  source "$HELPER"
  pids=()
  for i in $(seq 1 20); do
    desktop_mailbox_write "$CC_DIR" "desktop.tproj" "conc.cc" "msg-$i" &
    pids+=("$!")
  done
  wait "${pids[@]}"
)
nfiles=$(ls "$CC_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
if [[ "$nfiles" -le 5 && "$nfiles" -ge 1 ]]; then
  ok dtm31_concurrent_cap
else no dtm31_concurrent_cap "nfiles=$nfiles (cap 5)"; fi

# 32. no-overwrite: two writes with the same epoch/pid yield two distinct
# envelopes (collision-free mktemp token + no-clobber rename).
OW_DIR="$WORK/mailbox/to-session/tproj-workspace/over.cc"
(
  export TPROJ_DESKTOP_MAILBOX_ROOT="$WORK/mailbox"
  source "$HELPER"
  desktop_mailbox_write "$OW_DIR" "desktop.tproj" "over.cc" "first"
  desktop_mailbox_write "$OW_DIR" "desktop.tproj" "over.cc" "second"
)
nover=$(ls "$OW_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
bodies=$(cat "$OW_DIR"/*.json 2>/dev/null | jq -r '.body' 2>/dev/null | sort | tr '\n' ',')
if [[ "$nover" == "2" && "$bodies" == "first,second," ]]; then
  ok dtm32_no_overwrite
else no dtm32_no_overwrite "nover=$nover bodies=[$bodies]"; fi

# --- Fix 4: explicit drain (ack-all) on each side; plain read stays pure.
# 33. session-side `--drain desktop` clears this pane's to-session inbox; a prior
#     plain read must NOT have deleted anything.
DR_DIR="$WORK/mailbox/to-session/tproj-workspace/tproj.cc"
rm -rf "$DR_DIR"; mkdir -p "$DR_DIR"
for i in 1 2 3; do
  printf '{"from":"desktop.tproj","to":"tproj.cc","body":"d%s","created_at":%s,"bridge":"desktop"}' "$i" "$(date +%s)" > "$DR_DIR/d$i.json"
done
run_sess --read desktop >/dev/null 2>&1   # pure read must not delete
pre=$(ls "$DR_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
out=$(run_sess --drain desktop)
post=$(ls "$DR_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
if [[ "$pre" == "3" ]] && grep -q "Drained 3 message" <<<"$out" && [[ "$post" == "0" ]]; then
  ok dtm33_session_drain
else no dtm33_session_drain "pre=$pre post=$post out=[$out]"; fi

# 34. Desktop-side `--desktop --drain` clears this desktop's to-desktop inbox.
DD_DIR="$WORK/mailbox/to-desktop/tproj"
rm -rf "$DD_DIR"; mkdir -p "$DD_DIR"
for i in 1 2; do
  printf '{"from":"tproj.cc","to":"desktop.tproj","body":"r%s","created_at":%s,"bridge":"desktop"}' "$i" "$(date +%s)" > "$DD_DIR/r$i.json"
done
out=$(run_dt good --desktop --drain 2>&1)
post=$(ls "$DD_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
if grep -q "Drained 2 message" <<<"$out" && [[ "$post" == "0" ]]; then
  ok dtm34_desktop_drain
else no dtm34_desktop_drain "post=$post out=[$out]"; fi

# 35. --drain rejects a non-Desktop target (guard).
out=$(run_sess --drain tproj.cc 2>&1)
grep -q "target must be a Desktop mailbox" <<<"$out" \
  && ok dtm35_drain_rejects_nondesktop || no dtm35_drain_rejects_nondesktop "out=[$out]"

# --- Blocker 1: with_desktop_mailbox_lock is fail-CLOSED on a contended lock.
# A precreated lock dir + zero wait forces the acquisition timeout. Both write
# and drain must fail with the distinct busy rc WITHOUT touching envelopes: no
# new envelope is created AND the pre-existing envelope is not deleted.
# 38. precreated-lock / zero-wait -> write + drain both busy, no envelope change.
LK_DIR="$WORK/mailbox/to-session/tproj-workspace/lock.cc"
rm -rf "$LK_DIR" "$LK_DIR.lock"; mkdir -p "$LK_DIR"
printf '{"from":"desktop.tproj","to":"lock.cc","body":"pre","created_at":0,"bridge":"desktop"}' > "$LK_DIR/pre.json"
lk_result=$(
  export TPROJ_DESKTOP_MAILBOX_ROOT="$WORK/mailbox"
  export TPROJ_DESKTOP_LOCK_WAIT_MS=0
  source "$HELPER"
  mkdir -p "$LK_DIR.lock"   # hold the lock so acquisition can never succeed
  desktop_mailbox_write "$LK_DIR" "desktop.tproj" "lock.cc" "should-not-write"; wrc=$?
  desktop_mailbox_drain "$LK_DIR" >/dev/null 2>&1; drc=$?
  printf '%s %s %s' "$wrc" "$drc" "$TPROJ_DESKTOP_MAILBOX_BUSY_RC"
)
lk_wrc=${lk_result%% *}; lk_rest=${lk_result#* }; lk_drc=${lk_rest%% *}; lk_busy=${lk_rest##* }
lk_nfiles=$(ls "$LK_DIR"/*.json 2>/dev/null | wc -l | tr -d '[:space:]')
lk_body=$(jq -r '.body' "$LK_DIR/pre.json" 2>/dev/null)
if [[ -n "$lk_busy" && "$lk_wrc" == "$lk_busy" && "$lk_drc" == "$lk_busy" \
      && "$lk_nfiles" == "1" && -e "$LK_DIR/pre.json" && "$lk_body" == "pre" ]]; then
  ok dtm38_lock_fail_closed
else no dtm38_lock_fail_closed "wrc=$lk_wrc drc=$lk_drc busy=$lk_busy nfiles=$lk_nfiles body=$lk_body"; fi
rm -rf "$LK_DIR.lock"

# --- Blocker 2: dead panes are excluded and the session must match EXACTLY.
# Both rejects must leave NO mailbox file, NO body-free DB bell, NO send-keys.
# 39. target resolves only to a DEAD pane -> reject (dead excluded from the
#     live single-match count even though its column resolves via a live pane).
rm -rf "$WORK/mailbox/to-session/tproj-workspace/dead.cc" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
export FAKE_PANE_LIST=$'%1:codex-p1:dead:1:0\n%2:claude-p1:dead:1:1'
out=$(run_dt good --desktop --session tproj-workspace dead.cc "to dead pane")
unset FAKE_PANE_LIST
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "does not resolve to a live pane" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/tproj-workspace/dead.cc" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm39_dead_pane_reject
else no dtm39_dead_pane_reject "out=[$out] db=$db_before->$db_after"; fi

# 40. requested session is only a PREFIX of a live session (exact does not exist)
#     -> reject. tproj-work is a prefix of tproj-workspace; '=' exact rejects it.
rm -rf "$WORK/mailbox/to-session/tproj-work" 2>/dev/null
db_before=0
[[ $HAS_SQLITE -eq 1 ]] && db_before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
out=$(run_dt good --desktop --session tproj-work tproj.cc "to prefix session")
db_after=0
[[ $HAS_SQLITE -eq 1 ]] && db_after=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE bridge='desktop' AND direction='inbound';" 2>/dev/null || echo 0)
if grep -q "session 'tproj-work' is not live" <<<"$out" \
   && [[ ! -d "$WORK/mailbox/to-session/tproj-work" ]] \
   && [[ ! -e "$FAKE_DIR/sendkeys.log" ]] \
   && [[ "$db_before" == "$db_after" ]]; then
  ok dtm40_session_prefix_reject
else no dtm40_session_prefix_reject "out=[$out] db=$db_before->$db_after"; fi

echo "----"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[[ $FAIL -eq 0 ]]

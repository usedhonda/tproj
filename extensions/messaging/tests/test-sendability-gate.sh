#!/usr/bin/env bash
#
# test-sendability-gate.sh — independent acceptance harness for the tproj-msg
# "sendability gate" rework (busy-but-sendable / selection-screen guard).
#
# Owned by tproj.cc as the cross-check against the tproj-msg implementation
# (Steps 1-5 owned by tproj.cdx). It does NOT touch tproj-msg itself.
#
# Strategy: hermetic. We shim `tmux` and `websocat` into a tempdir on PATH and
# drive the REAL tproj-msg via `--session tproj-workspace --as tproj.cc`. Each
# case writes fixtures (pane table, per-pane role/tty/@prompt_state/capture, and
# a canned :8080 sessions.list line) then asserts the `--status` detail token:
#
#   sendable_running | blocked_selection | blocked_typing | draft_suspected
#
# The detail vocabulary is the contract agreed with tproj.cdx. Cases tied to the
# not-yet-connected send path are asserted via the --status verdict (side-effect
# free) rather than real send-keys, so the harness stays hermetic.
#
# Usage: bash extensions/messaging/tests/test-sendability-gate.sh [path-to-tproj-msg]
#   Defaults to the repo copy next to this tests/ dir.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REAL_TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"

if [[ ! -x "$REAL_TPROJ_MSG" ]]; then
  echo "FATAL: tproj-msg not found/executable at: $REAL_TPROJ_MSG" >&2
  exit 2
fi

# --- sandbox -----------------------------------------------------------------
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-sendgate.XXXXXX")
FAKE_DIR="$WORK/fixtures"
BIN_DIR="$WORK/bin"
mkdir -p "$FAKE_DIR" "$BIN_DIR"
trap 'rm -rf "$WORK"' EXIT

# R2 Stage 1 — model-role-router registry harness. This test's process tree
# already runs under a real "claude" ancestor (this file is itself driven
# by Claude Code), so a naive registry entry keyed on *that* real ancestor
# would be fragile and environment-dependent. Instead, every "$TPROJ_MSG"
# call below goes through a one-hop-close wrapper that renames a freshly
# forked process to "claude" and writes the registry entry for tproj.cc
# using THAT process's own (pid, pid_start) immediately before invoking
# the real tproj-msg as its direct child -- deterministic regardless of
# how deep the real ancestry chain runs.
REGISTRY_ROOT="$WORK/registry"
mkdir -p "$REGISTRY_ROOT/tproj-workspace/1"
export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/db-errors.log"

TPROJ_MSG="$BIN_DIR/tproj-msg-verified"
cat > "$TPROJ_MSG" <<WRAPPER
#!/bin/bash
if [[ "\${_VERIFIED_REINVOKED:-}" != "1" ]]; then
  export _VERIFIED_REINVOKED=1
  exec -a claude bash "\$0" "\$@"
fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
cat > "$REGISTRY_ROOT/tproj-workspace/1/tproj.cc.json" <<JSON
{"alias":"tproj.cc","pid":\$mypid,"pid_start":\$mystart,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":\$(date +%s)}
JSON
"$REAL_TPROJ_MSG" "\$@"
WRAPPER
chmod +x "$TPROJ_MSG"

# Pane table: tproj.cc = %1, tproj.cdx = %2, both column 1.
# @role MUST be the column-suffixed form (claude-p<col>/codex-p<col>) so
# resolve_target's short_to_role_pattern("cc",col)=="claude-p1" matches.
cat > "$FAKE_DIR/panes" <<'PANES'
%1:claude-p1:tproj:1
%2:codex-p1:tproj:1
PANES
printf '%s' "/dev/ttys001" > "$FAKE_DIR/tty_%1"
printf '%s' "/dev/ttys002" > "$FAKE_DIR/tty_%2"
printf '%s' "claude-p1" > "$FAKE_DIR/role_%1"
printf '%s' "codex-p1"  > "$FAKE_DIR/role_%2"

# --- fake tmux ---------------------------------------------------------------
# Handles only the subcommands tproj-msg exercises on the --status path:
#   display-message, list-panes, show-options, capture-pane, send-keys, has-session
cat > "$BIN_DIR/tmux" <<'TMUX'
#!/usr/bin/env bash
set -uo pipefail
FAKE_DIR="$FAKE_DIR_ENV"
sub="${1:-}"; shift || true

# scan for "-t <target>" and a trailing -p/-F format and "-v <name>"
target=""; fmt=""; optname=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    -t) target="${args[$((i+1))]:-}";;
    -p) fmt="${args[$((i+1))]:-}";;
    -F) fmt="${args[$((i+1))]:-}";;
    -v) optname="${args[$((i+1))]:-}";;
  esac
done
# normalise pane id (strip session:win.pane if a bare %id was not given)
pane="$target"

readf() { [[ -f "$FAKE_DIR/$1" ]] && cat "$FAKE_DIR/$1" || true; }

case "$sub" in
  display-message)
    if [[ "$fmt" == "#S" || -z "$fmt" && -z "$target" ]]; then
      printf '%s' "tproj-workspace"; exit 0
    fi
    case "$fmt" in
      *pane_tty*)  readf "tty_${pane}";;
      *@role*)     readf "role_${pane}";;
      *@alias*)    printf '%s' "tproj";;
      *@column*)   printf '%s' "1";;
      *pane_id*)   printf '%s' "${pane:-%1}";;
      "#S")        printf '%s' "tproj-workspace";;
      *)           : ;;
    esac
    ;;
  list-panes)
    # Fault injection for the M-D6 transient-classification test: when the
    # list_panes_fail fixture is present, simulate tmux list-panes failing
    # (non-zero, empty). Absent (all other cases) -> unchanged.
    [[ -f "$FAKE_DIR/list_panes_fail" ]] && exit 1
    readf "panes";;
  show-options)
    case "$optname" in
      @prompt_state)     readf "promptstate_${pane}";;
      @prompt_state_ts)  readf "promptstate_ts_${pane}";;
      @prompt_state_src) readf "promptstate_src_${pane}";;
      *) : ;;
    esac
    ;;
  capture-pane) readf "capture_${pane}";;
  send-keys)
    # Fault injection for the raw_send hardening test: when the sendkeys_fail
    # fixture is present, simulate a failed tmux send-keys (non-zero, nothing
    # logged). Absent (all other cases) -> unchanged: log and succeed.
    [[ -f "$FAKE_DIR/sendkeys_fail" ]] && exit 1
    printf 'SENDKEYS %s\n' "$*" >> "$FAKE_DIR/sendkeys.log";;
  has-session)  exit 0;;
  set-option|set|setenv) exit 0;;
  *) : ;;
esac
exit 0
TMUX
chmod +x "$BIN_DIR/tmux"

# --- fake websocat -----------------------------------------------------------
# Emits a host_info frame then the canned sessions.list line, mimicking :8080.
cat > "$BIN_DIR/websocat" <<'WS'
#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' '{"type":"host_info","host":"test"}'
[[ -f "$FAKE_DIR_ENV/ws.json" ]] && cat "$FAKE_DIR_ENV/ws.json"
exit 0
WS
chmod +x "$BIN_DIR/websocat"

# --- fake curl ---------------------------------------------------------------
# Captures ClawGate payloads for gate:direct tests.
cat > "$BIN_DIR/curl" <<'CURL'
#!/usr/bin/env bash
set -uo pipefail
body=""
next_is_body=0
for arg in "$@"; do
  if [[ "$next_is_body" == "1" ]]; then
    body="$arg"
    next_is_body=0
    continue
  fi
  case "$arg" in
    -d|--data|--data-raw|--data-binary) next_is_body=1 ;;
  esac
done
printf '%s' "$body" > "$FAKE_DIR_ENV/curl_body.json"
printf '%s\n' "$*" > "$FAKE_DIR_ENV/curl_argv.txt"
printf '{"ok":true}\n200\n'
CURL
chmod +x "$BIN_DIR/curl"

export FAKE_DIR_ENV="$FAKE_DIR"
export PATH="$BIN_DIR:$PATH"

# --- helpers -----------------------------------------------------------------
PASS=0; FAIL=0; PENDING=0

reset_fixtures() {
  rm -f "$FAKE_DIR"/promptstate_* "$FAKE_DIR"/capture_* "$FAKE_DIR/ws.json" "$FAKE_DIR/sendkeys.log"
}

# set_ws <pane_tty> <status> <waiting_reason>  (waiting_reason "" => omit)
set_ws() {
  local tty="$1" status="$2" reason="${3:-}" now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [[ -n "$reason" ]]; then
    printf '{"type":"sessions.list","sessions":[{"tty":"%s","status":"%s","waiting_reason":"%s","updated_at":"%s"}]}\n' \
      "$tty" "$status" "$reason" "$now" > "$FAKE_DIR/ws.json"
  else
    printf '{"type":"sessions.list","sessions":[{"tty":"%s","status":"%s","updated_at":"%s"}]}\n' \
      "$tty" "$status" "$now" > "$FAKE_DIR/ws.json"
  fi
}

run_status() { # <target>
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --status "$1" 2>&1
}

run_force() { # <target> <message>
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --allow-relay gate-reverse-channel --force "$1" "$2" 2>&1
}

run_gate_direct() { # <message>
  mkdir -p "$WORK/home/.config/tproj"
  cat > "$WORK/home/.config/tproj/workspace.yaml" <<'YAML'
gui:
  bridge:
    url: http://bridge.test:8765
    default_adapter: direct
    reply_callback_url: http://reply.test:8765
YAML
  HOME="$WORK/home" "$TPROJ_MSG" --session tproj-workspace --as tproj.cc gate:direct "$1" 2>&1
}

# assert_detail <name> <target> <expected-substring>
assert_detail() {
  local name="$1" target="$2" want="$3" out
  out=$(run_status "$target")
  if grep -q "$want" <<<"$out"; then
    printf 'PASS  %s\n' "$name"; PASS=$((PASS+1))
  else
    printf 'FAIL  %s\n      want substring: %s\n      got: %s\n' "$name" "$want" "$(printf '%s' "$out" | tr '\n' '|')"
    FAIL=$((FAIL+1))
  fi
}

CC_TTY="/dev/ttys001"
CDX_TTY="/dev/ttys002"

# capture content for a pane (so draft / prompt-marker heuristics see something)
set_capture() { printf '%s' "$2" > "$FAKE_DIR/capture_$1"; }

# =============================================================================
# Cases (verdict via --status detail). Expected to PASS once tproj.cdx lands
# Steps 3-4 (send_block_reason wired + --status detail vocabulary). Until then
# the new tokens are absent and these read as FAIL — that is the test-first
# signal, not a harness defect.
# =============================================================================

# 1. running (generating) -> sendable
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
assert_detail "1_running_sendable" "tproj.cc" "sendable_running"

# 2. waiting_input + permission_prompt -> blocked_selection
reset_fixtures
set_ws "$CC_TTY" "waiting_input" "permission_prompt"
set_capture "%1" "Do you want to proceed? > 1. Yes  2. No"
assert_detail "2_permission_blocked" "tproj.cc" "blocked_selection"

# 3. waiting_input + unknown, capture shows no menu -> sendable
reset_fixtures
set_ws "$CC_TTY" "waiting_input" "unknown"
set_capture "%1" $'some normal output line\n  just text, no selector here'
assert_detail "3_unknown_nomenu_sendable" "tproj.cc" "sendable"

# 4. cdx permission_prompt (WS veto) -> blocked_selection
reset_fixtures
set_ws "$CDX_TTY" "waiting_input" "permission_prompt"
set_capture "%2" "allow command? > 1. yes  2. no"
assert_detail "4_cdx_permission_veto" "tproj.cdx" "blocked_selection"

# 5. typing draft (cursor glyph in capture) -> blocked_typing
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" $'previous output\n> hello there I am typing a draft\xe2\x96\x8c'
assert_detail "5_typing_draft_blocked" "tproj.cc" "blocked_typing"

# 6. suggestion (dim placeholder) -> sendable
reset_fixtures
set_ws "$CC_TTY" "running" ""
# ESC[2m ... ESC[0m = dim suggestion text on prompt line
set_capture "%1" $'> \x1b[2mTry "explain this code"\x1b[0m'
assert_detail "6_suggestion_sendable" "tproj.cc" "sendable"

# 8. stable paused draft on the bottom prompt (no cursor, not placeholder,
#    >= MIN chars, identical across recheck) -> draft_suspected -> blocked_typing.
#    Guards the #9 slip-through the user flagged ("draft often gets bypassed").
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" $'output line one\noutput line two\n\xe2\x9d\xaf this is a real unsent draft'
assert_detail "8_stable_draft_blocked" "tproj.cc" "draft_suspected"

# 9. placeholder/hint text on the prompt must NOT block (must stay sendable) —
#    the other half of the #9 contract: hardening must not re-introduce false-busy.
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" $'\xe2\x9d\xaf \x1b[2mTry "explain this code"\x1b[0m'
assert_detail "9_placeholder_not_blocked" "tproj.cc" "sendable"

# 10. --force must still protect real selection screens. This is the Chi reverse
#     delivery safety case: ClawGate uses --allow-relay ... --force, but it must
#     not press a permission menu.
reset_fixtures
set_ws "$CC_TTY" "waiting_input" "permission_prompt"
set_capture "%1" $'permission required\n> Allow\n  Deny'
force_out=$(run_force "tproj.cc" "[from:OpenClaw Agent - Auto] reverse delivery safety test")
force_rc=$?
if [[ "$force_rc" -eq 18 ]] && grep -q "selection screen" <<<"$force_out" && [[ ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  10_force_selection_not_sent\n'; PASS=$((PASS+1))
else
  printf 'FAIL  10_force_selection_not_sent\n      want rc=18, selection stderr, no sendkeys\n      rc=%s\n      got: %s\n' "$force_rc" "$(printf '%s' "$force_out" | tr '\n' '|')"
  [[ -f "$FAKE_DIR/sendkeys.log" ]] && sed 's/^/      sendkeys: /' "$FAKE_DIR/sendkeys.log"
  FAIL=$((FAIL+1))
fi

# 11. --force still bypasses typing drafts (selection is the only force exception).
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" $'previous output\n> live user draft\xe2\x96\x8c'
force_out=$(run_force "tproj.cc" "force typing bypass test")
force_rc=$?
if [[ "$force_rc" -eq 0 ]] && [[ -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  11_force_typing_still_sent\n'; PASS=$((PASS+1))
else
  printf 'FAIL  11_force_typing_still_sent\n      want rc=0 and sendkeys\n      rc=%s\n      got: %s\n' "$force_rc" "$(printf '%s' "$force_out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 12. --force still sends while running/generating.
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" $'generating normal output\nmore output'
force_out=$(run_force "tproj.cc" "force running bypass test")
force_rc=$?
if [[ "$force_rc" -eq 0 ]] && [[ -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  12_force_running_still_sent\n'; PASS=$((PASS+1))
else
  printf 'FAIL  12_force_running_still_sent\n      want rc=0 and sendkeys\n      rc=%s\n      got: %s\n' "$force_rc" "$(printf '%s' "$force_out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 13. gate:direct must emit exactly one reverse-channel header even if the body
#     already starts with an old [tproj-msg:...] header.
reset_fixtures
gate_out=$(run_gate_direct "[tproj-msg:sender=old.cc,project=old,workspace=old,reply=session,return_url=http://old.example] body after old header")
gate_rc=$?
gate_text=""
gate_header_count=0
if [[ -f "$FAKE_DIR/curl_body.json" ]] && command -v jq >/dev/null 2>&1; then
  gate_text=$(jq -r '.text // ""' "$FAKE_DIR/curl_body.json" 2>/dev/null || true)
  gate_header_count=$(printf '%s' "$gate_text" | grep -o '\[tproj-msg:[^]]*\]' | wc -l | tr -d ' ')
fi
if [[ "$gate_rc" -eq 0 && "$gate_header_count" -eq 1 && "$gate_text" == *"sender=tproj.cc"* && "$gate_text" != *"old.cc"* && "$gate_text" == *"body after old header"* ]]; then
  printf 'PASS  13_gate_direct_single_header\n'; PASS=$((PASS+1))
else
  printf 'FAIL  13_gate_direct_single_header\n      want rc=0, header_count=1, current sender, no old header\n      rc=%s header_count=%s\n      out: %s\n      text: %s\n' "$gate_rc" "$gate_header_count" "$(printf '%s' "$gate_out" | tr '\n' '|')" "$gate_text"
  FAIL=$((FAIL+1))
fi

# 7. flush must SKIP a selection screen but DELIVER to a sendable target.
#    Live check via the real `--flush` path with a hermetic queue dir
#    (TPROJ_MSG_QUEUE_DIR), asserting through the send-keys shim. This guards the
#    Arc 1 regression hole: a queued message must not be flushed into a permission
#    menu. If the selection gate is removed, 7a flushes and this case FAILs.
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
mkdir -p "$TPROJ_MSG_QUEUE_DIR"

# 7a. selection (permission_prompt) -> NOT flushed, queue kept.
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
printf '%s\t%s\t%s\n' "$(date +%s)" "" "queued flush test A" > "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue"
set_ws "$CC_TTY" "waiting_input" "permission_prompt"
# Menu-style capture (same as case 2): detected as a selection screen by the real
# gate, but reads as sendable once selection detection is disabled — so this case
# isolates the SELECTION skip (a plain "> Allow/Deny" would also trip the draft
# guard and mask a selection-gate regression).
set_capture "%1" "Do you want to proceed? > 1. Yes  2. No"
"$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush >/dev/null 2>&1
sel_no_send=1; [[ -f "$FAKE_DIR/sendkeys.log" ]] && sel_no_send=0
sel_kept=0;   [[ -f "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue" ]] && sel_kept=1

# 7b. sendable (running) -> flushed, queue removed.
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
printf '%s\t%s\t%s\n' "$(date +%s)" "" "queued flush test B" > "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue"
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
"$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush >/dev/null 2>&1
snd_sent=0; [[ -f "$FAKE_DIR/sendkeys.log" ]] && snd_sent=1
snd_gone=1; [[ -f "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue" ]] && snd_gone=0

unset TPROJ_MSG_QUEUE_DIR

if [[ "$sel_no_send" -eq 1 && "$sel_kept" -eq 1 && "$snd_sent" -eq 1 && "$snd_gone" -eq 1 ]]; then
  printf 'PASS  7_flush_skips_selection\n'; PASS=$((PASS+1))
else
  printf 'FAIL  7_flush_skips_selection\n      selection[no_send=%s kept=%s] sendable[sent=%s gone=%s] (all want 1)\n' \
    "$sel_no_send" "$sel_kept" "$snd_sent" "$snd_gone"
  FAIL=$((FAIL+1))
fi

# =============================================================================
# Phase 1 additions (refactor-instructions.md M-T): relay / broadcast / fanout
# guard cases. Same hermetic style as above (fake tmux/websocat/curl on PATH,
# real tproj-msg driven via --session/--as). Existing cases 1-13 are untouched.
# =============================================================================

# run_send: plain normal send (no --force / no --allow-*).
run_send() { # <target> <message>
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc "$1" "$2" 2>&1
}

# --- relay guard: relay-like bodies are blocked on a normal send (exit 13) ---
# 14. [from:] prefix -> blocked, no send-keys.
reset_fixtures
out=$(run_send "tproj.cc" "[from:evil.cc] relayed body"); rc=$?
if [[ "$rc" -eq 13 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  14_relay_from_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  14_relay_from_blocked\n      want rc=13, no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 15. [Control:] tag -> blocked.
reset_fixtures
out=$(run_send "tproj.cc" "[Control:PSYNC-STOP] please halt"); rc=$?
if [[ "$rc" -eq 13 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  15_relay_control_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  15_relay_control_blocked\n      want rc=13, no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 16. [ACK:] tag -> blocked.
reset_fixtures
out=$(run_send "tproj.cc" "[ACK:tp-1-01] received"); rc=$?
if [[ "$rc" -eq 13 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  16_relay_ack_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  16_relay_ack_blocked\n      want rc=13, no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 17. --allow-relay <reason> --force lets a relay body through to a running pane.
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
out=$(run_force "tproj.cc" "[from:OpenClaw Agent - Auto] allowed relay body $$-$RANDOM"); rc=$?
if [[ "$rc" -eq 0 && -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  17_relay_allow_relay_sends\n'; PASS=$((PASS+1))
else
  printf 'FAIL  17_relay_allow_relay_sends\n      want rc=0 and sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# --- broadcast guard: broadcast-like targets are forbidden (exit 14) ---
# 18. target "all" -> blocked, no send-keys.
reset_fixtures
out=$(run_send "all" "hello everyone"); rc=$?
if [[ "$rc" -eq 14 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  18_broadcast_all_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  18_broadcast_all_blocked\n      want rc=14, no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 19. target "broadcast" -> blocked.
reset_fixtures
out=$(run_send "broadcast" "hello everyone"); rc=$?
if [[ "$rc" -eq 14 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  19_broadcast_word_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  19_broadcast_word_blocked\n      want rc=14, no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# --- fanout guard --------------------------------------------------------------
# Add a second same-family (cc) pane in another column so the SAME message can go
# to two different target names ("tproj.cc" -> %1, "other.cc" -> %3). This block
# runs after every existing case, so the extra pane never perturbs cases 1-13.
# FANOUT_DEDUP_DIR is hardcoded /tmp (Debt M-D4, fixed in Phase 2), so we drive
# the real dedup store with a unique nonce message per run: no collision with
# live traffic, and the two entries expire via the 600s TTL.
printf '%s\n' "%3:claude-p2:other:2" >> "$FAKE_DIR/panes"
printf '%s' "/dev/ttys003" > "$FAKE_DIR/tty_%3"
printf '%s' "claude-p2"    > "$FAKE_DIR/role_%3"
OTHER_TTY="/dev/ttys003"
FANOUT_MSG="fanout probe nonce $$-$RANDOM-$(date +%s)"

# 20. same message to a second same-family target is blocked as fan-out (exit 15).
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
run_send "tproj.cc" "$FANOUT_MSG" >/dev/null 2>&1   # first send marks the dedup store
first_sent=0; [[ -f "$FAKE_DIR/sendkeys.log" ]] && first_sent=1
reset_fixtures
set_ws "$OTHER_TTY" "running" ""
set_capture "%3" "...generating output..."
out=$(run_send "other.cc" "$FANOUT_MSG"); rc=$?
if [[ "$first_sent" -eq 1 && "$rc" -eq 15 && ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  20_fanout_second_target_blocked\n'; PASS=$((PASS+1))
else
  printf 'FAIL  20_fanout_second_target_blocked\n      want first_sent=1 rc=15 no sendkeys\n      first_sent=%s rc=%s got: %s\n' "$first_sent" "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 21. --allow-fanout <reason> overrides the fan-out block (delivers to 2nd target).
reset_fixtures
set_ws "$OTHER_TTY" "running" ""
set_capture "%3" "...generating output..."
out=$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --allow-fanout intentional-second-target "other.cc" "$FANOUT_MSG" 2>&1); rc=$?
if [[ "$rc" -eq 0 && -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  21_fanout_allow_fanout_sends\n'; PASS=$((PASS+1))
else
  printf 'FAIL  21_fanout_allow_fanout_sends\n      want rc=0 and sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# --- raw_send hardening (M-D1) -------------------------------------------------
# 22. When tmux send-keys fails, raw_send must NOT print "Sent to", must exit
#     non-zero, and must not log a delivered send. Target is sendable (running)
#     so the send path is reached; the shim then fails send-keys.
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
touch "$FAKE_DIR/sendkeys_fail"
out=$(run_send "tproj.cc" "raw_send failure probe $$-$RANDOM"); rc=$?
rm -f "$FAKE_DIR/sendkeys_fail"
if [[ "$rc" -ne 0 ]] && ! grep -q "Sent to" <<<"$out" && [[ ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  22_raw_send_failure_not_sent\n'; PASS=$((PASS+1))
else
  printf 'FAIL  22_raw_send_failure_not_sent\n      want rc!=0, no "Sent to", no sendkeys\n      rc=%s got: %s\n' "$rc" "$(printf '%s' "$out" | tr '\n' '|')"
  [[ -f "$FAKE_DIR/sendkeys.log" ]] && sed 's/^/      sendkeys: /' "$FAKE_DIR/sendkeys.log"
  FAIL=$((FAIL+1))
fi

# --- M-D6 resolve_target failure classification (via --flush diagnostics) ------
# resolve_target now returns RT_NOT_FOUND (populated pane list, no match) vs
# RT_TRANSIENT (list-panes failed/empty). flush_all_queues surfaces the class in
# its keep-queue warning. Both classes keep the queue (behaviour unchanged); the
# tests assert the distinct diagnostic AND that the queue is retained.
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
mkdir -p "$TPROJ_MSG_QUEUE_DIR"

# 23. genuinely-absent target (populated pane list, no match) -> "appears gone".
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
printf '%s\t%s\t%s\n' "$(date +%s)" "" "queued for a ghost" > "$TPROJ_MSG_QUEUE_DIR/ghost.cc.queue"
flush_out=$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush 2>&1)
gone_kept=0; [[ -f "$TPROJ_MSG_QUEUE_DIR/ghost.cc.queue" ]] && gone_kept=1
if grep -q "appears gone" <<<"$flush_out" && [[ "$gone_kept" -eq 1 ]]; then
  printf 'PASS  23_flush_gone_target_diag\n'; PASS=$((PASS+1))
else
  printf 'FAIL  23_flush_gone_target_diag\n      want "appears gone" log + queue kept\n      kept=%s got: %s\n' "$gone_kept" "$(printf '%s' "$flush_out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 24. real target but tmux list-panes fails -> "transient tmux error", kept.
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
printf '%s\t%s\t%s\n' "$(date +%s)" "" "queued during tmux hiccup" > "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue"
touch "$FAKE_DIR/list_panes_fail"
flush_out=$("$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush 2>&1)
rm -f "$FAKE_DIR/list_panes_fail"
trans_kept=0; [[ -f "$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue" ]] && trans_kept=1
if grep -q "transient tmux error" <<<"$flush_out" && [[ "$trans_kept" -eq 1 ]]; then
  printf 'PASS  24_flush_transient_diag\n'; PASS=$((PASS+1))
else
  printf 'FAIL  24_flush_transient_diag\n      want "transient tmux error" log + queue kept\n      kept=%s got: %s\n' "$trans_kept" "$(printf '%s' "$flush_out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi

# 25. gone target + short grace + stale message -> early discard (M-D6c opt-in).
#     Default grace (= STALE_SECONDS) keeps it (case 23); a shortened grace with
#     a message older than the grace triggers the whole-queue discard.
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
printf '%s\t%s\t%s\n' "$(( $(date +%s) - 300 ))" "" "old ghost message" > "$TPROJ_MSG_QUEUE_DIR/ghost.cc.queue"
flush_out=$(TPROJ_MSG_TARGET_GONE_GRACE=60 "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush 2>&1)
disc_removed=1; [[ -f "$TPROJ_MSG_QUEUE_DIR/ghost.cc.queue" ]] && disc_removed=0
if grep -q "Discarding queue for gone target" <<<"$flush_out" && [[ "$disc_removed" -eq 1 ]]; then
  printf 'PASS  25_flush_gone_early_discard\n'; PASS=$((PASS+1))
else
  printf 'FAIL  25_flush_gone_early_discard\n      want discard log + queue removed\n      removed=%s got: %s\n' "$disc_removed" "$(printf '%s' "$flush_out" | tr '\n' '|')"
  FAIL=$((FAIL+1))
fi
unset TPROJ_MSG_QUEUE_DIR

# 26. M-D5: flush's read->truncate is mutually exclusive with an enqueue append
#     via a per-target mkdir lock, closing the silent-loss window. Reproducing
#     the exact truncate-window race is timing-fragile, so we verify the lock
#     PROPERTY deterministically: while an external holder holds the queue lock,
#     a locked flush must BLOCK (not drain A) until released; an unlocked flush
#     ignores the lock and drains A immediately. After release, flush drains A
#     and releases its own lock (lockdir gone). This is RED without the flush
#     lock (A drained at the checkpoint) and GREEN with it.
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
mkdir -p "$TPROJ_MSG_QUEUE_DIR"
reset_fixtures
rm -f "$TPROJ_MSG_QUEUE_DIR"/*.queue
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating output..."
mdx5_qf="$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue"
mdx5_lock="$TPROJ_MSG_QUEUE_DIR/tproj.cc.queue.lock"
printf '%s\t%s\t%s\n' "$(date +%s)" "" "mdx5 message A" > "$mdx5_qf"
mkdir "$mdx5_lock"   # external holder occupies the queue lock
TPROJ_MSG_QUEUE_LOCK_WAIT_MS=15000 "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --flush >/dev/null 2>&1 &
mdx5_pid=$!
sleep 1.0            # checkpoint: a locked flush is now blocked on the held lock
# Blocked == A neither delivered (no send-keys) nor drained (queue file kept).
mdx5_blocked=0
if [[ -f "$mdx5_qf" ]] && ! grep -q "mdx5 message A" "$FAKE_DIR/sendkeys.log" 2>/dev/null; then
  mdx5_blocked=1
fi
rmdir "$mdx5_lock"   # release: flush now acquires, drains A, releases its lock
wait "$mdx5_pid"
mdx5_delivered=0; grep -q "mdx5 message A" "$FAKE_DIR/sendkeys.log" 2>/dev/null && mdx5_delivered=1
mdx5_qgone=1; [[ -f "$mdx5_qf" ]] && mdx5_qgone=0
mdx5_lock_gone=1; [[ -d "$mdx5_lock" ]] && mdx5_lock_gone=0
unset TPROJ_MSG_QUEUE_DIR
if [[ "$mdx5_blocked" -eq 1 && "$mdx5_delivered" -eq 1 && "$mdx5_qgone" -eq 1 && "$mdx5_lock_gone" -eq 1 ]]; then
  printf 'PASS  26_flush_queue_lock_mutex\n'; PASS=$((PASS+1))
else
  printf 'FAIL  26_flush_queue_lock_mutex\n      want blocked-while-held + delivered + queue gone + lock released\n      blocked=%s delivered=%s qgone=%s lock_gone=%s\n' \
    "$mdx5_blocked" "$mdx5_delivered" "$mdx5_qgone" "$mdx5_lock_gone"
  FAIL=$((FAIL+1))
fi

# =============================================================================
# B4 (msg-repair Phase B) — verify_as_caller_identity self-recompute regression.
# The main $TPROJ_MSG wrapper above always records pid_start; these cases drive a
# REG_MODE-selectable wrapper (same rename-to-claude / write-own-identity /
# exec-real-tproj-msg pattern) to exercise the unrecorded / dead / multi paths
# introduced by B2 + B3. Existing cases 1-26 are untouched.
# =============================================================================
B4_TPROJ_MSG="$BIN_DIR/tproj-msg-b4"
cat > "$B4_TPROJ_MSG" <<WRAPPER
#!/bin/bash
if [[ "\${_VERIFIED_REINVOKED:-}" != "1" ]]; then
  export _VERIFIED_REINVOKED=1
  exec -a claude bash "\$0" "\$@"
fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
obs=\$(date +%s)
regdir="$REGISTRY_ROOT/tproj-workspace/1"
regf="\$regdir/tproj.cc.json"
mkdir -p "\$regdir"
case "\${REG_MODE:-}" in
  unrecorded_live)
    printf '{"alias":"tproj.cc","pid":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$obs" > "\$regf" ;;
  unrecorded_dead)
    printf '{"alias":"tproj.cc","pid":999999,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$obs" > "\$regf" ;;
  recorded_mismatch)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$((mystart+9999))" "\$obs" > "\$regf" ;;
  multi_live_plus_dead)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$obs" > "\$regf"
    mkdir -p "$REGISTRY_ROOT/tproj-workspace/9"
    printf '{"alias":"tproj.cc","pid":999999,"pid_start":111111,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$obs" > "$REGISTRY_ROOT/tproj-workspace/9/tproj.cc.json" ;;
esac
"$REAL_TPROJ_MSG" "\$@"
WRAPPER
chmod +x "$B4_TPROJ_MSG"

run_verify_b4() { # <REG_MODE> -> "VERIFY none" | "REJECT <reason>"
  local mode="$1" out
  reset_fixtures
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  set_ws "$CC_TTY" "running" ""
  set_capture "%1" "...generating output..."
  out=$(REG_MODE="$mode" "$B4_TPROJ_MSG" --session tproj-workspace --as tproj.cc tproj.cc "b4 $mode $$-$RANDOM" 2>&1)
  if grep -q "could not be verified" <<<"$out"; then
    printf 'REJECT %s' "$(sed -n 's/.*reason: \([a-z_]*\).*/\1/p' <<<"$out" | head -1)"
  else
    printf 'VERIFY none'
  fi
}

# B4a. unrecorded pid_start + live agent ancestor -> VERIFY (self-recompute, B2).
res=$(run_verify_b4 unrecorded_live)
if [[ "$res" == VERIFY* ]]; then
  printf 'PASS  B4a_unrecorded_live_verifies\n'; PASS=$((PASS+1))
else
  printf 'FAIL  B4a_unrecorded_live_verifies (want VERIFY, got %s)\n' "$res"; FAIL=$((FAIL+1))
fi

# B4b. unrecorded pid_start + dead reg_pid (live recompute impossible) -> REJECT
#      with the distinct pid_start_unrecorded reason (fail-closed preserved, B2).
res=$(run_verify_b4 unrecorded_dead)
if [[ "$res" == "REJECT pid_start_unrecorded" ]]; then
  printf 'PASS  B4b_unrecorded_dead_rejects\n'; PASS=$((PASS+1))
else
  printf 'FAIL  B4b_unrecorded_dead_rejects (want REJECT pid_start_unrecorded, got %s)\n' "$res"; FAIL=$((FAIL+1))
fi

# B4c. recorded pid_start but WRONG -> REJECT pid_start_mismatch (unchanged guard).
res=$(run_verify_b4 recorded_mismatch)
if [[ "$res" == "REJECT pid_start_mismatch" ]]; then
  printf 'PASS  B4c_recorded_mismatch_rejects\n'; PASS=$((PASS+1))
else
  printf 'FAIL  B4c_recorded_mismatch_rejects (want REJECT pid_start_mismatch, got %s)\n' "$res"; FAIL=$((FAIL+1))
fi

# B4d. live entry + dead-pid leftover across windows -> live entry adopted (B3) -> VERIFY.
res=$(run_verify_b4 multi_live_plus_dead)
if [[ "$res" == VERIFY* ]]; then
  printf 'PASS  B4d_multi_live_adopted_verifies\n'; PASS=$((PASS+1))
else
  printf 'FAIL  B4d_multi_live_adopted_verifies (want VERIFY, got %s)\n' "$res"; FAIL=$((FAIL+1))
fi

# =============================================================================
# Phase C (msg-repair) — C2 read-marking and C4 bare-alias ambiguity. Same
# hermetic harness (fake tmux + real tproj-msg + $WORK/messages.db). Existing
# cases are untouched.
# =============================================================================
if command -v sqlite3 >/dev/null 2>&1; then
  # C2. --read marks inbound rows from the read target to self as read.
  reset_fixtures
  set_capture "%2" "some pane content from cdx"
  c2_id=$(sqlite3 "$TPROJ_MSG_DB_PATH" "INSERT INTO messages (from_alias,to_alias,body,body_hash,direction,delivery,created_at) VALUES ('tproj.cdx','tproj.cc','hi','h','inbound','send-keys',strftime('%s','now')); SELECT last_insert_rowid();" 2>/dev/null || true)
  "$TPROJ_MSG" --session tproj-workspace --as tproj.cc --read tproj.cdx >/dev/null 2>&1
  c2_read=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT read_at IS NOT NULL FROM messages WHERE id=${c2_id:-0};" 2>/dev/null || true)
  if [[ "$c2_read" == "1" ]]; then
    printf 'PASS  C2_read_marks_inbound_read\n'; PASS=$((PASS+1))
  else
    printf 'FAIL  C2_read_marks_inbound_read (want read_at set, got [%s])\n' "$c2_read"; FAIL=$((FAIL+1))
  fi
else
  printf 'PASS  C2_read_marks_inbound_read (SKIP: no sqlite3)\n'; PASS=$((PASS+1))
fi

# C3. --status appends a monitor liveness diagnostic (not running / stale / ok).
if command -v sqlite3 >/dev/null 2>&1; then
  MON_KEY="tproj-workspace:tproj"
  # C3a: no cursor row -> "monitor: not running".
  reset_fixtures
  set_ws "$CC_TTY" "running" ""
  sqlite3 "$TPROJ_MSG_DB_PATH" "DELETE FROM monitor_cursors WHERE consumer='${MON_KEY}';" >/dev/null 2>&1 || true
  c3a=$(run_status "tproj.cc")
  # C3b: fresh cursor -> "monitor: ok".
  sqlite3 "$TPROJ_MSG_DB_PATH" "INSERT OR REPLACE INTO monitor_cursors (consumer,last_message_id,updated_at) VALUES ('${MON_KEY}',1,strftime('%s','now'));" >/dev/null 2>&1 || true
  c3b=$(run_status "tproj.cc")
  # C3c: stale cursor -> "monitor: stale".
  sqlite3 "$TPROJ_MSG_DB_PATH" "UPDATE monitor_cursors SET updated_at=strftime('%s','now')-9999 WHERE consumer='${MON_KEY}';" >/dev/null 2>&1 || true
  c3c=$(run_status "tproj.cc")
  sqlite3 "$TPROJ_MSG_DB_PATH" "DELETE FROM monitor_cursors WHERE consumer='${MON_KEY}';" >/dev/null 2>&1 || true
  if grep -q "monitor: not running" <<<"$c3a" && grep -q "monitor: ok" <<<"$c3b" && grep -q "monitor: stale" <<<"$c3c" \
     && grep -q "sendable_running" <<<"$c3a"; then
    printf 'PASS  C3_status_monitor_diagnostic\n'; PASS=$((PASS+1))
  else
    printf 'FAIL  C3_status_monitor_diagnostic\n      a=%s\n      b=%s\n      c=%s\n' \
      "$(tr '\n' '|' <<<"$c3a")" "$(tr '\n' '|' <<<"$c3b")" "$(tr '\n' '|' <<<"$c3c")"
    FAIL=$((FAIL+1))
  fi
else
  printf 'PASS  C3_status_monitor_diagnostic (SKIP: no sqlite3)\n'; PASS=$((PASS+1))
fi

# C4. bare cc/cdx ambiguity: a single candidate is NOT rejected by C4; once a
# second same-role column exists, a columnless bare send is rejected (exit 19)
# with the candidate list and no send-keys.
reset_fixtures
set_ws "$CC_TTY" "running" ""
set_capture "%1" "...generating..."
c4compat_out=$(run_send "cdx" "c4 single candidate $$-$RANDOM"); c4compat_rc=$?
printf '%s\n' "%4:codex-p2:other:2" >> "$FAKE_DIR/panes"
printf '%s' "/dev/ttys004" > "$FAKE_DIR/tty_%4"
printf '%s' "codex-p2" > "$FAKE_DIR/role_%4"
reset_fixtures
c4amb_out=$(run_send "cdx" "c4 ambiguous $$-$RANDOM"); c4amb_rc=$?
if [[ "$c4compat_rc" -ne 19 ]] && ! grep -q "is ambiguous" <<<"$c4compat_out" \
   && [[ "$c4amb_rc" -eq 19 ]] && grep -q "cdx is ambiguous:" <<<"$c4amb_out" \
   && grep -q "tproj.cdx" <<<"$c4amb_out" && grep -q "other.cdx" <<<"$c4amb_out" \
   && [[ ! -f "$FAKE_DIR/sendkeys.log" ]]; then
  printf 'PASS  C4_bare_alias_ambiguity\n'; PASS=$((PASS+1))
else
  printf 'FAIL  C4_bare_alias_ambiguity\n      compat_rc=%s compat=%s\n      amb_rc=%s amb=%s\n' \
    "$c4compat_rc" "$(tr '\n' '|' <<<"$c4compat_out")" "$c4amb_rc" "$(tr '\n' '|' <<<"$c4amb_out")"
  FAIL=$((FAIL+1))
fi

# =============================================================================
echo "----"
printf 'PASS=%d FAIL=%d PENDING=%d\n' "$PASS" "$FAIL" "$PENDING"
[[ "$FAIL" -eq 0 ]]

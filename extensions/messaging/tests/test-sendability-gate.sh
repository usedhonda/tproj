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
TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"

if [[ ! -x "$TPROJ_MSG" ]]; then
  echo "FATAL: tproj-msg not found/executable at: $TPROJ_MSG" >&2
  exit 2
fi

# --- sandbox -----------------------------------------------------------------
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-sendgate.XXXXXX")
FAKE_DIR="$WORK/fixtures"
BIN_DIR="$WORK/bin"
mkdir -p "$FAKE_DIR" "$BIN_DIR"
trap 'rm -rf "$WORK"' EXIT

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
  list-panes)  readf "panes";;
  show-options)
    case "$optname" in
      @prompt_state)     readf "promptstate_${pane}";;
      @prompt_state_ts)  readf "promptstate_ts_${pane}";;
      @prompt_state_src) readf "promptstate_src_${pane}";;
      *) : ;;
    esac
    ;;
  capture-pane) readf "capture_${pane}";;
  send-keys)    printf 'SENDKEYS %s\n' "$*" >> "$FAKE_DIR/sendkeys.log";;
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

# 7. flush_queue must not flush while selection screen is up.
#    (Verdict proxy: a permission_prompt target reads blocked_selection, which
#    the flush worker shares as its gate. A live flush_queue assertion is added
#    once Step 3 wiring lands; recorded here as PENDING.)
PENDING=$((PENDING+1))
printf 'PEND  7_flush_skips_selection (live flush check added after Step 3 wiring)\n'

# =============================================================================
echo "----"
printf 'PASS=%d FAIL=%d PENDING=%d\n' "$PASS" "$FAIL" "$PENDING"
[[ "$FAIL" -eq 0 ]]

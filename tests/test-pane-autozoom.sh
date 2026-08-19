#!/usr/bin/env bash
#
# test-pane-autozoom.sh — the autozoom vertical target must scale with the window.
#
# A fixed row count silently stops growing a pane once it already exceeds it, so
# focusing a pane that sat at the old 40-row default in a tall window produced no
# vertical change at all while the width still moved. tmux is faked here: nothing
# touches a real session.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
AUTOZOOM="$REPO_ROOT/bin/tproj-pane-autozoom"

PASS=0
FAIL=0
pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-autozoom-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/state"
touch "$TMP/state/auto-zoom.enabled"

# Fake tmux: answers only what the script asks and records every resize request.
cat > "$TMP/bin/tmux" <<'FAKE'
#!/usr/bin/env bash
log="$TMPDIR_FAKE/calls.log"
printf '%s\n' "$*" >> "$log"
case "$1" in
  wait-for) exit 0 ;;
  display-message)
    fmt="${!#}"
    case "$fmt" in
      *'#{pane_id} #{@column} #{@role}'*) echo "%8 3 claude-p3" ;;
      '#{window_width}') echo 267 ;;
      '#{window_height}') echo "$FAKE_WIN_H" ;;
      '#{pane_width}') echo 43 ;;
      '#{pane_height}') echo "$FAKE_ACTIVE_H" ;;
      *) echo "" ;;
    esac
    ;;
  list-panes)
    fmt="${!#}"
    case "$fmt" in
      '#{@column} #{pane_top} #{pane_id}')
        printf '2 1 %%1\n2 33 %%7\n3 1 %%2\n3 33 %%8\n' ;;
      '#{@column}')
        printf '2\n2\n3\n3\n' ;;
      *) : ;;
    esac
    ;;
  resize-pane) exit 0 ;;
  *) exit 0 ;;
esac
FAKE
chmod +x "$TMP/bin/tmux"

run_case() {
  local name="$1" win_h="$2" active_h="$3" expect="$4"
  : > "$TMP/calls.log"
  TMPDIR_FAKE="$TMP" FAKE_WIN_H="$win_h" FAKE_ACTIVE_H="$active_h" \
  TPROJ_STATE_DIR="$TMP/state" \
  PATH="$TMP/bin:$PATH" \
    "$AUTOZOOM" test-session >/dev/null 2>&1
  local got
  got=$(grep -E '^resize-pane -t %8 -y ' "$TMP/calls.log" 2>/dev/null | awk '{print $NF}' | tail -1)
  if [[ "$got" == "$expect" ]]; then
    pass "$name (-y $got)"
  else
    fail "$name" "expected -y $expect, got '${got:-none}'"
  fi
}

# The reported bug: a 40-row pane in a 73-row window never grew, because the
# target was the constant 40. Two panes share the column, so the active one
# should take two of three shares.
run_case "a pane already at the old fixed target still grows" 73 40 48

# TPROJ_AUTOZOOM_H_MIN keeps its documented meaning as a floor: when the window is
# short enough that the proportional share falls below it, the floor still wins.
run_case "the configured minimum still acts as a floor" 46 20 40

printf -- '----\nPASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

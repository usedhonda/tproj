#!/usr/bin/env bash
# Only a live, idle native composer with no draft/approval may receive a message.
set -u
source "$(dirname "$0")/terminal-parser.sh"
fail() { printf '{"safe":false,"reason":"%s"}\n' "$1"; exit 1; }
pane="${1:-}"
[[ "$pane" =~ ^%[0-9]+$ ]] || fail invalid_pane
[[ "$(tmux display-message -t "$pane" -p '#{pane_dead}' 2>/dev/null)" == 0 ]] || fail offline
state="$(tmux show-options -p -t "$pane" -v @prompt_state 2>/dev/null || true)"
case "$state" in typing|busy|running) fail busy ;; esac
raw="$(tmux capture-pane -t "$pane" -e -p -S -120 2>/dev/null)" || fail capture_failed
plain="$(printf '%s\n' "$raw" | strip_ansi)"
# Busy rendering is independent of potentially stale prompt-state options.
printf '%s\n' "$plain" | tail -12 | grep -Eiq '(esc to interrupt|escape to interrupt|ctrl.c to interrupt)' && fail busy
option='^[[:space:]]*([0-9]+[.)]|[>›❯▶▷▸▹●○◉◯◆◇*+-])[[:space:]]*(allow|deny|yes|no|approve|reject|continue|cancel|run|always allow|continue anyway|許可|拒否|承認|続行|キャンセル)'
context='(permission|approval|approve|allow[[:space:]]+.*command|do you want|continue[?？]|choose|select|askuserquestion|ask user question|proceed[?？]|許可|承認|選択)'
if printf '%s\n' "$plain" | tail -30 | grep -Eiq "$option" && printf '%s\n' "$plain" | tail -30 | grep -Eiq "$context"; then fail selection_screen; fi
measure_input_line_draft "$pane"
[[ "$INPUT_DRAFT_RESULT" == clear && "$PROMPT_PARSE_MARKER" == native ]] || fail draft_or_unclassified
(( PROMPT_PARSE_DISTANCE <= TMUX_TYPING_GUARD_MAX_PROMPT_DISTANCE_LINES )) || fail historical_prompt
printf '{"safe":true,"pane":"%s"}\n' "$pane"

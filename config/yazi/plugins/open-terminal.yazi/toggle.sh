#!/bin/bash
DIR="${1:-.}"
PANE_ID=$(tmux show-environment -g YAZI_TERM_PANE 2>/dev/null | cut -d= -f2)

if [ -n "$PANE_ID" ] && tmux list-panes -F "#{pane_id}" | grep -q "$PANE_ID"; then
  # ペインが存在する -> 閉じる
  tmux kill-pane -t "$PANE_ID"
  tmux set-environment -gu YAZI_TERM_PANE
else
  # ペインが存在しない -> 開く
  NEW_PANE=$(tmux split-window -v -c "$DIR" -PF "#{pane_id}")
  tmux set-environment -g YAZI_TERM_PANE "$NEW_PANE"
fi

# tproj-common.sh - shared helpers for the tproj bin/ scripts.
#
# This file is *sourced*, not executed. It is loaded by both bash scripts
# (tproj-drop-column, tproj-kill-pane, tproj-respawn-guard, tproj-mem-trace,
# tproj-postmortem) and the zsh launcher (bin/tproj). Every function here must
# therefore be portable across bash and zsh:
#   - no bashisms that differ under zsh (avoid array-index slicing, which has
#     empty-slice quirks under zsh KSH_ARRAYS)
#   - declare all `local`s at the top of a function, never inside a loop
#     (re-declaring `local` inside a zsh loop leaks the value to stdout)
# It defines functions only and has no top-level side effects.

# Collect every descendant PID of the given PIDs (full process tree, BFS).
# Args: one or more root PIDs. Output: descendant PIDs, one per line (BFS order),
# excluding the roots themselves. Uses positional parameters as the work queue so
# behavior is identical in bash and zsh regardless of array indexing.
collect_descendant_pids() {
  local all="" cur child kids
  while [ "$#" -gt 0 ]; do
    cur="$1"
    shift
    kids="$(pgrep -P "$cur" 2>/dev/null || true)"
    [ -n "$kids" ] || continue
    while IFS= read -r child; do
      [ -n "$child" ] || continue
      all="${all}${child}
"
      set -- "$@" "$child"
    done <<EOF_KIDS
$kids
EOF_KIDS
  done
  [ -n "$all" ] && printf '%s' "$all"
  return 0
}

# Map a pane @role to the command typed into the pane to make its program exit.
# Empty for roles that get no exit command (yazi / unknown). Mirrors the tables
# in tproj-drop-column (send_exit_signal) and bin/tproj (stop).
#   codex* / agent*        -> "/exit"
#   claude* / terminal-p*  -> "exit"
#   yazi* / unknown        -> "" (caller decides)
exit_cmd_for_role() {
  case "$1" in
    codex-p*|codex|agent-p*|agent-*) echo "/exit" ;;
    claude-p*|claude|terminal-p*)    echo "exit" ;;
    *) echo "" ;;
  esac
}

# Map a pane @role to the graceful-interrupt key to send before the exit command.
# Empty for unknown roles. Mirrors tproj-drop-column (send_graceful_signal).
#   claude* / codex* / agent* / terminal-p*  -> "C-c"
#   yazi*                                     -> "q"
#   unknown                                   -> ""
# The returned token is a tmux key name, so send it via `tmux send-keys -t P "$tok"`.
graceful_signal_for_role() {
  case "$1" in
    claude-p*|claude|codex-p*|codex|agent-p*|agent-*|terminal-p*) echo "C-c" ;;
    yazi-p*|yazi) echo "q" ;;
    *) echo "" ;;
  esac
}

# Available memory in MB (macOS): free + inactive + purgeable pages. macOS keeps
# "free" artificially low due to caching, so inactive+purgeable are counted too.
avail_mem_mb() {
  local vm_out page_size free_p inactive_p purgeable_p
  vm_out=$(vm_stat 2>/dev/null)
  page_size=$(sysctl -n vm.pagesize 2>/dev/null || echo 16384)
  free_p=$(echo "$vm_out" | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
  inactive_p=$(echo "$vm_out" | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
  purgeable_p=$(echo "$vm_out" | awk '/Pages purgeable/ {gsub(/\./,"",$3); print $3}')
  echo $(( (${free_p:-0} + ${inactive_p:-0} + ${purgeable_p:-0}) * page_size / 1048576 ))
}

# Total physical RAM in MB. Falls back to 24GB if hw.memsize is unavailable
# (matches the historical fallback in respawn-guard / mem-trace).
phys_mem_mb() {
  echo $(( $(sysctl -n hw.memsize 2>/dev/null || echo 25769803776) / 1024 / 1024 ))
}

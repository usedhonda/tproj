#!/usr/bin/env bash
# Read-only, pane-bound delivery guard. No target lookup or message dispatch.
set -u
json_fail() { if command -v jq >/dev/null 2>&1; then jq -cn --arg reason "$1" '{safe:false,reason:$reason}'; else python3 -c 'import json,sys; print(json.dumps({"safe":False,"reason":sys.argv[1]},separators=(",",":")))' "$1"; fi; return 1; }
json_safe() { if command -v jq >/dev/null 2>&1; then jq -cn --arg pane "$1" --arg state "$2" --arg detail "$3" '{safe:true,pane:$pane,state:$state,detail:$detail}'; else python3 -c 'import json,sys; print(json.dumps({"safe":True,"pane":sys.argv[1],"state":sys.argv[2],"detail":sys.argv[3]},separators=(",",":")))' "$1" "$2" "$3"; fi; }
pane="${1:-}"
[[ "$pane" =~ ^%[0-9]+$ ]] || json_fail invalid_pane
command -v tmux >/dev/null 2>&1 || json_fail tmux_unavailable
read_opt() { tmux show-options -p -t "$pane" -v "$1" 2>/dev/null || true; }
trim() { sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' <<< "$1"; }
state="$(trim "$(read_opt @prompt_state | tr '[:upper:]' '[:lower:]')")"
ts="$(trim "$(read_opt @prompt_state_ts)")"
now="$(date +%s)"; fresh=false
if [[ "$ts" =~ ^[0-9]+$ ]] && (( ts <= now + 5 )) && (( now - ts <= 30 )); then fresh=true; fi
captured="$(tmux capture-pane -t "$pane" -p -S -30 2>/dev/null || true)"
plain="$(printf '%s\n' "$captured" | sed $'s/\033\\[[0-9;]*[[:alpha:]]//g')"
option='^[[:space:]]*([0-9]+[.)]|[>›❯▶▷▸▹●○◉◯◆◇*+-])[[:space:]]*(allow|deny|yes|no|approve|reject|continue|cancel|run|always allow|continue anyway|許可|拒否|承認|続行|キャンセル)'
context='(permission|approval|approve|allow[[:space:]]+.*command|do you want|continue[?？]|choose|select|askuserquestion|ask user question|proceed[?？]|許可|承認|選択)'
selectors="$(printf '%s\n' "$plain" | tail -30 | grep -Eic "$option" || true)"; contexts="$(printf '%s\n' "$plain" | tail -30 | grep -Eic "$context" || true)"
(( selectors > 0 && contexts > 0 )) && json_fail selection_screen
case "$state" in
  idle)
    [[ "$fresh" == true ]] || json_fail stale_prompt_state
    # Independent input-line guard: a fresh idle signal cannot authorize
    # concatenating a parked composer draft (the historical sendability bug).
    last_prompt="$(printf '%s\n' "$plain" | grep -E '^[[:space:]]*[›❯>]' | tail -1 || true)"
    draft="$(printf '%s' "$last_prompt" | sed -E 's/^[[:space:]]*[›❯>][[:space:]]*//; s/^[[:space:]]+//; s/[[:space:]]+$//')"
    [[ -z "$draft" || "$draft" == "Ask Codex to do anything" ]] || json_fail typing_draft
    json_safe "$pane" "$state" "prompt_state:${state}"; exit 0 ;;
  suggestion) [[ "$fresh" == true ]] || json_fail stale_prompt_state; json_safe "$pane" "$state" "prompt_state:${state}"; exit 0 ;;
  typing) json_fail typing_draft ;;
  unknown|'') json_fail unclassified_prompt_state ;;
  *) json_fail invalid_prompt_state ;;
esac

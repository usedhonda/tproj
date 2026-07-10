#!/bin/bash
# Startup bridge for the canonical general model-role-router.

tproj_model_role_initialize() {
  local session="$1" router="${2:-}" window="${3:-dev}"
  local pane raw_role alias column project active_model model_tier orchestration_role role_epoch
  local platform_role needs_router

  while IFS= read -r pane; do
    [[ -n "$pane" ]] || continue
    raw_role="$(tmux display-message -t "$pane" -p '#{@role}' 2>/dev/null || true)"
    case "$raw_role" in
      claude|claude-p*|cc) platform_role="cc" ;;
      codex|codex-p*|cdx) platform_role="cdx" ;;
      *) continue ;;
    esac

    alias="$(tmux display-message -t "$pane" -p '#{@alias}' 2>/dev/null || true)"
    column="$(tmux display-message -t "$pane" -p '#{@column}' 2>/dev/null || true)"
    project="$(tmux display-message -t "$pane" -p '#{@project}' 2>/dev/null || true)"
    active_model="$(tmux show-options -pv -t "$pane" '@active_model' 2>/dev/null || true)"
    model_tier="$(tmux show-options -pv -t "$pane" '@model_tier' 2>/dev/null || true)"
    orchestration_role="$(tmux show-options -pv -t "$pane" '@orchestration_role' 2>/dev/null || true)"
    role_epoch="$(tmux show-options -pv -t "$pane" '@role_epoch' 2>/dev/null || true)"

    needs_router=false
    if [[ -z "$active_model" ]]; then
      tmux set-option -pt "$pane" @active_model "unknown" >/dev/null 2>&1 || true
      needs_router=true
    fi
    if [[ -z "$model_tier" ]]; then
      tmux set-option -pt "$pane" @model_tier "unknown" >/dev/null 2>&1 || true
      needs_router=true
    fi
    if [[ -z "$orchestration_role" ]]; then
      tmux set-option -pt "$pane" @orchestration_role "solo-fallback" >/dev/null 2>&1 || true
      needs_router=true
    fi
    if [[ -z "$role_epoch" ]]; then
      tmux set-option -pt "$pane" @role_epoch "0" >/dev/null 2>&1 || true
      needs_router=true
    fi

    [[ "$needs_router" == "true" && -n "$router" && -x "$router" ]] || continue
    [[ -n "$alias" ]] || alias="unknown"
    [[ -n "$column" ]] || column="standalone"
    [[ -n "$project" ]] || project="$PWD"

    TPROJ_SESSION="$session" \
    TPROJ_PANE="$pane" \
    TPROJ_ALIAS="${alias}.${platform_role}" \
    TPROJ_ROLE="$platform_role" \
    TPROJ_COLUMN="$column" \
    TPROJ_PROJECT="$project" \
      "$router" observe </dev/null >/dev/null 2>&1 || true
    TPROJ_SESSION="$session" \
    TPROJ_PANE="$pane" \
    TPROJ_ALIAS="${alias}.${platform_role}" \
    TPROJ_ROLE="$platform_role" \
    TPROJ_COLUMN="$column" \
    TPROJ_PROJECT="$project" \
      "$router" resolve </dev/null >/dev/null 2>&1 || true
  done < <(tmux list-panes -t "$session:$window" -F '#{pane_id}' 2>/dev/null || true)
}

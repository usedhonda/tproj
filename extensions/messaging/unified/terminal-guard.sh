#!/usr/bin/env bash
# Read-only delivery safety guard.  It delegates classification to the mature
# tproj-msg --status path; this wrapper never calls send, --force, or --fire.
set -u

die() {
  printf '{"safe":false,"reason":"%s"}\n' "$1"
  exit 1
}

pane="${1:-}"
[[ "$pane" =~ ^%[0-9]+$ ]] || die "invalid_pane"
command -v tmux >/dev/null 2>&1 || die "tmux_unavailable"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
msg="$root/tproj-msg"
[[ -x "$msg" ]] || die "tproj_msg_unavailable"

alias_name="$(tmux display-message -t "$pane" -p '#{@alias}' 2>/dev/null || true)"
role="$(tmux display-message -t "$pane" -p '#{@role}' 2>/dev/null || true)"
[[ "$alias_name" =~ ^[A-Za-z0-9_-]+$ ]] || die "missing_alias"
case "$role" in
  cc|claude|agent) short_role=cc ;;
  cdx|codex) short_role=cdx ;;
  *) die "missing_platform" ;;
esac
target="${alias_name}.${short_role}"

# `--status` is explicitly diagnostic in tproj-msg.  Capture its output rather
# than sourcing the script (which would execute its CLI dispatcher).
status="$($msg --status "$target" 2>/dev/null)" || die "status_unavailable"
first="$(printf '%s\n' "$status" | sed -n '1p')"
detail="$(printf '%s\n' "$status" | sed -n 's/^[[:space:]]*detail:[[:space:]]*//p' | head -1)"
state="$(printf '%s\n' "$first" | sed -nE 's/.*[[:space:]](online|offline)\/(idle|suggestion|typing|busy).*/\1\/\2/p')"
case "$state" in
  online/idle|online/suggestion)
    case "$detail" in
      blocked_typing:*|blocked_selection:*) die "${detail%%:*}" ;;
      *) printf '{"safe":true,"pane":"%s","target":"%s","state":"%s","detail":"%s"}\n' "$pane" "$target" "$state" "$detail"; exit 0 ;;
    esac ;;
  online/*) die "${detail:-busy}" ;;
  offline/*|"") die "offline_or_unclassified" ;;
  *) die "unclassified" ;;
esac

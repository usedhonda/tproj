#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/../../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home/bin" "$tmp/bin"
awk '/^CROSS_SESSION_CHAT=false$/ {copy=1} copy {print} copy && /^if \[\[ -z "\$REMOTE_HOST"/ && seen++ {exit}' \
  "$repo/extensions/messaging/tproj-msg" | sed '$d' > "$tmp/route.sh"
cat > "$tmp/home/bin/tproj-remote-host" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$ROUTE_CALLS"
printf '%s\n' "$ROUTE_STATUS"
SH
cat > "$tmp/bin/tmux" <<'SH'
#!/bin/sh
[[ "$*" == *'#\{@project\}'* ]] && printf '%s\n' /srv/alpha
SH
chmod +x "$tmp/home/bin/tproj-remote-host" "$tmp/bin/tmux"
export HOME="$tmp/home" PATH="$tmp/bin:$PATH" ROUTE_CALLS="$tmp/calls"
run_case() (
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN=1
  NEW_TASK_MODE=false ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false
  ROUTE_STATUS="${1}"
  export ROUTE_STATUS
  source "$tmp/route.sh"
  [[ "$SESSION" == "$2" && "$CROSS_SESSION_CHAT" == "$3" && "$MY_COLUMN" == 1 ]]
)
run_case 'running|tproj-remote-cdx-new|42' tproj-remote-cdx-new true
grep -Fxq 'status --path /srv/alpha --role cdx' "$tmp/calls"
run_case 'running|tproj-remote-cc-old|42' tproj-remote-cc-old false
run_case 'stopped|tproj-remote-cdx-new|-' tproj-remote-cc-old false
if (
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN=1
  NEW_TASK_MODE=true ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false
  ROUTE_STATUS='running|tproj-remote-cdx-new|42'; export ROUTE_STATUS
  source "$tmp/route.sh"
) >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: task control crossed sessions' >&2; exit 1
fi
grep -Fq 'only plain chat' "$tmp/err"
echo 'PASS: bare remote role route stays project-scoped and chat-only'

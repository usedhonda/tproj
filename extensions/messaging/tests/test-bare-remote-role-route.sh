#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/../../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home/bin" "$tmp/bin"
awk '/^ORIGIN_SESSION="\$SESSION"$/ {copy=1} copy && /^# === Queue directory ===/ {exit} copy {print}' \
  "$repo/extensions/messaging/tproj-msg" > "$tmp/route.sh"
cat > "$tmp/home/bin/tproj-remote-host" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$ROUTE_CALLS"
printf '%s\n' "$ROUTE_STATUS"
SH
cat > "$tmp/bin/tmux" <<'SH'
#!/bin/sh
[[ "$*" == *'#\{@project\}'* ]] && printf '%s\n' /srv/alpha
[[ "$*" == *'#{session_id}'* ]] && printf '%s\n' '$13'
SH
chmod +x "$tmp/home/bin/tproj-remote-host" "$tmp/bin/tmux"
export HOME="$tmp/home" PATH="$tmp/bin:$PATH" ROUTE_CALLS="$tmp/calls"
run_case() (
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ALIAS=alpha MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN="${4-1}"
  NEW_TASK_MODE=false ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false AUTH_PATH=pane-derived
  ROUTE_STATUS="${1}"
  export ROUTE_STATUS
  source "$tmp/route.sh"
  [[ "$SESSION" == "$2" && "$CROSS_SESSION_CHAT" == "$3" && "$MY_COLUMN" == 1 ]]
)
run_case 'running|tproj-remote-cdx-new|42' tproj-remote-cdx-new true
grep -Fxq 'status --path /srv/alpha --role cdx' "$tmp/calls"
run_case 'running|tproj-remote-cc-old|42' tproj-remote-cc-old false
run_case 'running|tproj-remote-cc-old|42' tproj-remote-cc-old false ''
run_case 'stopped|tproj-remote-cdx-new|-' tproj-remote-cc-old false
(
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ALIAS=alpha MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN=1
  NEW_TASK_MODE=true ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false AUTH_PATH=pane-derived EXPLICIT_AS=
  ROUTE_STATUS='running|tproj-remote-cdx-new|42'; export ROUTE_STATUS
  source "$tmp/route.sh"
  [[ "$SESSION" == tproj-remote-cdx-new && "$ORIGIN_SESSION" == tproj-remote-cc-old && "$CROSS_SESSION_TASK" == true && "$TARGET" == alpha.cdx ]]
)
(
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ALIAS=alpha MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha VERIFIED_REG_SESSION_ID='$13' MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN=1
  NEW_TASK_MODE=true ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false AUTH_PATH=explicit-as-verified EXPLICIT_AS=alpha.cc
  ROUTE_STATUS='running|tproj-remote-cdx-new|42'; export ROUTE_STATUS
  source "$tmp/route.sh"
  [[ "$CROSS_SESSION_TASK" == true && "$ORIGIN_SESSION" == tproj-remote-cc-old && "$TARGET" == alpha.cdx ]]
)
if (
  REMOTE_HOST= REMOTE_CLIENT_SOCKET= REMOTE_INGRESS=false SEND_MODE=true STATUS_MODE=false
  TARGET=cdx MY_ALIAS=alpha MY_ROLE=cc AS_CALLER_VERIFIED=true VERIFIED_REG_PROJECT=/srv/alpha VERIFIED_REG_SESSION_ID='$wrong' MY_PANE=
  SESSION=tproj-remote-cc-old IS_WORKSPACE=true MY_COLUMN=1
  NEW_TASK_MODE=true ROLE_HANDOFF_MODE=false FORCE_MODE=false FIRE_MODE=false AUTH_PATH=explicit-as-verified EXPLICIT_AS=alpha.cc
  ROUTE_STATUS='running|tproj-remote-cdx-new|42'; export ROUTE_STATUS
  source "$tmp/route.sh"
) >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: explicit sender crossed task sessions' >&2; exit 1
fi
grep -Fq 'requires a verified sender session and project' "$tmp/err"
sed -n '/^assist_mode_blocks_peer_task() {$/,/^}$/p' "$repo/extensions/messaging/tproj-msg" > "$tmp/assist.sh"
cat > "$tmp/bin/model-role-router" <<'SH'
#!/bin/sh
echo '{"mode":"assist"}'
SH
chmod +x "$tmp/bin/model-role-router"
(
  source "$tmp/assist.sh"
  NEW_TASK_MODE=true MY_ALIAS=alpha MY_ROLE=cc TARGET=cdx VERIFIED_REG_PROJECT=/srv/alpha
  TPROJ_MODEL_ROLE_ROUTER="$tmp/bin/model-role-router"
  assist_mode_blocks_peer_task
)
echo 'PASS: bare remote role route stays project-scoped with verified same-project task'

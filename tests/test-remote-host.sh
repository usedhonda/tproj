#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-remote-host.XXXXXX")
SOCKET="tproj-remote-host-$RANDOM-$$"
cleanup() { tmux -L "$SOCKET" kill-server >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
mkdir -p "$TMP/project" "$TMP/legacy" "$TMP/bin" "$TMP/home"
cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
while :; do sleep 1; done
EOF
cp "$TMP/bin/claude" "$TMP/bin/codex"
chmod +x "$TMP/bin/claude" "$TMP/bin/codex"
export PATH="$TMP/bin:/opt/homebrew/bin:/usr/bin:/bin" TPROJ_TMUX_SOCKET="$SOCKET" HOME="$TMP/home"
run() { "$ROOT/bin/tproj-remote-host" "$@"; }
tm() { tmux -L "$SOCKET" "$@"; }
wait_panes() {
  local session=$1
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ $(tm list-panes -t "=$session:dev" -F '#{pane_id}' 2>/dev/null | wc -l) -eq 2 ]] && return
    sleep 0.1
  done
  return 1
}
run register --path "$TMP/project" --alias demo
cc_session=$(run ensure --path "$TMP/project" --role cc)
cdx_session=$(run ensure --path "$TMP/project" --role cdx)
[[ "$cc_session" != "$cdx_session" ]]
[[ $(tm show-options -t "$cc_session" -v status) == off ]]
[[ $(tm show-options -t "$cdx_session" -v status) == off ]]
[[ $(tm show-options -t "$cc_session" -v mouse) == on ]]
[[ $(tm show-options -t "$cdx_session" -v mouse) == on ]]
[[ $(run status --path "$TMP/project" --role cc) == running\|"$cc_session"\|* ]]
[[ $(run status --path "$TMP/project" --role cdx) == running\|"$cdx_session"\|* ]]
cc_pane=$(tm list-panes -t "=$cc_session:dev" -F '#{pane_id}')
cc_pid=$(tm display-message -t "$cc_pane" -p '#{pane_pid}')
tm set-option -pt "$cc_pane" @role_epoch 7
tm set-option -pt "$cc_pane" @orchestration_role worker
mkdir -p "$HOME/.cache/tproj-model-role/$cc_session"
python3 - "$HOME/.cache/tproj-model-role/$cc_session/demo.json" "$TMP/project" "$cc_session" "$cc_pid" <<'PY'
import json, subprocess, sys, time
file, project, session, pid = sys.argv[1:]
started = int(time.mktime(time.strptime(subprocess.check_output(['/bin/ps', '-p', pid, '-o', 'lstart='], text=True).strip(), '%a %b %d %H:%M:%S %Y')))
with open(file, 'w') as stream:
    json.dump(dict(alias='demo', project=project, session=session, pid=int(pid), pid_start=started, role='worker', role_epoch=7), stream)
PY
identity=$(run identity --path "$TMP/project" --role cc)
[[ $(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["role_epoch"])' "$identity") == 7 ]]
tm set-option -pt "$cc_pane" @role_epoch 8
if run identity --path "$TMP/project" --role cc >/dev/null 2>&1; then exit 1; fi
tm set-option -pt "$cc_pane" @role_epoch 7
[[ $(run list | tail -n 1) == *'|demo|'*'|running|running' ]]
[[ $(tm list-panes -t "=$cc_session:dev" -F '#{@role}|#{@alias}|#{@column}|#{@project}') == "claude-p1|demo|1|$TMP/project" ]]
[[ $(tm list-panes -t "=$cdx_session:dev" -F '#{@role}|#{@alias}|#{@column}|#{@project}') == "codex-p1|demo|1|$TMP/project" ]]
cc_pid_before=$(tm display-message -t "=$cc_session:dev" -p '#{pane_pid}')
cdx_pid_before=$(tm display-message -t "=$cdx_session:dev" -p '#{pane_pid}')
run register --path "$TMP/project" --alias renamed
[[ $(run list | tail -n 1) == *'|renamed|'*'|running|running' ]]
[[ $(tm display-message -t "=$cc_session:dev" -p '#{@alias}|#{pane_pid}') == "renamed|$cc_pid_before" ]]
[[ $(tm display-message -t "=$cdx_session:dev" -p '#{@alias}|#{pane_pid}') == "renamed|$cdx_pid_before" ]]
run register --path "$TMP/project" --alias demo
run unregister --path "$TMP/project"
tm has-session -t "=$cc_session"
run register --path "$TMP/project" --alias demo
[[ $(run stop --path "$TMP/project" --role cc) == stopped\|"$cc_session"\|- ]]
tm has-session -t "=$cdx_session"
run ensure --path "$TMP/project" --role cc >/dev/null

# Legacy migration moves live panes into the shared topology without changing PIDs.
run register --path "$TMP/legacy" --alias old
cc_legacy=$(bash -c 'printf "tproj-remote-cc-%s" "$(printf "cc\0%s" "$1" | shasum -a 256 | cut -c1-16)"' _ "$TMP/legacy")
cdx_legacy=$(bash -c 'printf "tproj-remote-cdx-%s" "$(printf "cdx\0%s" "$1" | shasum -a 256 | cut -c1-16)"' _ "$TMP/legacy")
tm new-session -d -s "$cc_legacy" -c "$TMP/legacy" "$TMP/bin/claude"
tm new-session -d -s "$cdx_legacy" -c "$TMP/legacy" "$TMP/bin/codex"
cc_pid=$(tm display-message -t "=$cc_legacy" -p '#{pane_pid}')
cdx_pid=$(tm display-message -t "=$cdx_legacy" -p '#{pane_pid}')
[[ $(run ensure --path "$TMP/legacy" --role cc) == "$cc_legacy" ]]
migrated=$(run migrate --path "$TMP/legacy")
wait_panes "$migrated"
[[ $(tm list-panes -t "=$migrated:dev" -F '#{@role}|#{pane_pid}' | sort) == "$(printf 'claude-p1|%s\ncodex-p1|%s' "$cc_pid" "$cdx_pid")" ]]
if tm has-session -t "=$cc_legacy" 2>/dev/null || tm has-session -t "=$cdx_legacy" 2>/dev/null; then exit 1; fi
if run migrate --path "$TMP/legacy" 2>/dev/null; then exit 1; fi
[[ $(run separate --path "$TMP/legacy") == "$cc_legacy|$cdx_legacy" ]]
[[ $(tm show-options -t "$cc_legacy" -v status) == off ]]
[[ $(tm show-options -t "$cdx_legacy" -v status) == off ]]
[[ $(tm show-options -t "$cc_legacy" -v mouse) == on ]]
[[ $(tm show-options -t "$cdx_legacy" -v mouse) == on ]]
[[ $(tm list-panes -t "=$cc_legacy" -F '#{pane_pid}') == "$cc_pid" ]]
[[ $(tm list-panes -t "=$cdx_legacy" -F '#{pane_pid}') == "$cdx_pid" ]]
if tm has-session -t "=$migrated" 2>/dev/null; then exit 1; fi
printf 'PASS  remote host role sessions and live separation\n'

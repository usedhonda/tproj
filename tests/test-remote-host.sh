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
shared=$(run ensure --path "$TMP/project" --role cc)
wait_panes "$shared"
[[ $(run ensure --path "$TMP/project" --role cdx) == "$shared" ]]
[[ $(run status --path "$TMP/project" --role cc) == running\|"$shared"\|* ]]
[[ $(run status --path "$TMP/project" --role cdx) == running\|"$shared"\|* ]]
[[ $(run list | tail -n 1) == *'|demo|'*'|running|running' ]]
[[ $(tm list-windows -t "=$shared" -F '#{window_name}') == dev ]]
[[ $(tm list-panes -t "=$shared:dev" -F '#{@role}|#{@alias}|#{@column}|#{@project}' | sort) == "$(printf 'claude-p1|demo|1|%s\ncodex-p1|demo|1|%s' "$TMP/project" "$TMP/project")" ]]
run unregister --path "$TMP/project"
tm has-session -t "=$shared"
run register --path "$TMP/project" --alias demo
[[ $(run stop --path "$TMP/project" --role cc) == stopped\|"$shared"\|- ]]
[[ $(tm list-panes -t "=$shared:dev" -F '#{@role}') == codex-p1 ]]
run ensure --path "$TMP/project" --role cc >/dev/null
wait_panes "$shared"

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
printf 'PASS  remote host paired panes and migration\n'

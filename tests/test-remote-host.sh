#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd); TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-remote-host.XXXXXX"); SOCKET="tproj-remote-host-$RANDOM-$$"
cleanup() { tmux -L "$SOCKET" kill-server >/dev/null 2>&1 || true; rm -rf "$TMP"; }; trap cleanup EXIT
mkdir -p "$TMP/project" "$TMP/bin" "$TMP/home"; cat > "$TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
printf 'claude:%s\n' "$*" >> "${MOCK_LOG:?}"; while :; do sleep 1; done
EOF
cat > "$TMP/bin/codex" <<'EOF'
#!/usr/bin/env bash
printf 'codex:%s\n' "$*" >> "${MOCK_LOG:?}"; while :; do sleep 1; done
EOF
chmod +x "$TMP/bin/claude" "$TMP/bin/codex"; export PATH="$TMP/bin:/opt/homebrew/bin:/usr/bin:/bin" MOCK_LOG="$TMP/invocations" TPROJ_TMUX_SOCKET="$SOCKET" HOME="$TMP/home"
run() { "$ROOT/bin/tproj-remote-host" "$@"; }
wait_for_log() { for _ in 1 2 3 4 5 6 7 8 9 10; do [[ -f "$MOCK_LOG" ]] && return 0; sleep 0.1; done; return 1; }
cc=$(run ensure --path "$TMP/project" --role cc); [[ "$(run ensure --path "$TMP/project" --role cc)" == "$cc" ]]; wait_for_log; [[ $(grep -c '^claude:--continue$' "$MOCK_LOG") -eq 1 ]]
[[ "$(run status --path "$TMP/project" --role cc)" == running\|"$cc"\|* ]]
cdx=$(run ensure --path "$TMP/project" --role cdx); [[ "$(run ensure --path "$TMP/project" --role cdx)" == "$cdx" ]]; for _ in 1 2 3 4 5 6 7 8 9 10; do [[ $(grep -c '^codex:resume --last$' "$MOCK_LOG" 2>/dev/null || true) -eq 1 ]] && break; sleep 0.1; done; [[ $(grep -c '^codex:resume --last$' "$MOCK_LOG") -eq 1 ]]
REAL_TMUX=$(command -v tmux)
cat > "$TMP/bin/tmux" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == -L ]]; then shift 2; fi
if [[ "\$1" == attach-session ]]; then printf '%s\\n' "\$*" > "$TMP/attach-target"; exit 0; fi
exec "$REAL_TMUX" -L "$SOCKET" "\$@"
EOF
chmod +x "$TMP/bin/tmux"
run attach --path "$TMP/project" --role cc
grep -Fqx "attach-session -t $cc" "$TMP/attach-target"
run register --path "$TMP/project"; run register --path "$TMP/project"; [[ $(wc -l < "$HOME/.config/tproj-remote/projects") -eq 1 ]]
tmux -L "$SOCKET" kill-session -t "$cc"; tmux -L "$SOCKET" kill-session -t "$cdx"
run ensure-all
for _ in 1 2 3 4 5 6 7 8 9 10; do [[ $(grep -c '^claude:--continue$' "$MOCK_LOG" 2>/dev/null || true) -eq 2 ]] && break; sleep 0.1; done
[[ $(grep -c '^claude:--continue$' "$MOCK_LOG") -eq 2 ]]
[[ $(grep -c '^codex:resume --last$' "$MOCK_LOG") -eq 2 ]]
printf 'PASS  remote host ensure/status/register\n'

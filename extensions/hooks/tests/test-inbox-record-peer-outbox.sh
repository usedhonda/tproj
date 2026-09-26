#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/../../.." && pwd)"
tmp="$(mktemp -d /tmp/tproj-d4.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" PATH="$tmp/bin:$PATH" TT_CACHE_DIR="$tmp/cache"
export TT_CACHE_OWNER='testsession/artist' TMUX_PANE='%test'
export TPROJ_MSG_DB_PATH="$tmp/messages.db" TPROJ_PEER_OUTBOX_DB="$tmp/peer/outbox.sqlite"
mkdir -p "$HOME/bin" "$tmp/bin" "$tmp/peer" "$tmp/cache"
chmod 700 "$tmp/peer"
cp "$repo/extensions/hooks/tproj-inbox-record" "$HOME/bin/tproj-inbox-record"
cp "$repo/extensions/messaging/tproj-task-cache.sh" "$HOME/bin/tproj-task-cache.sh"
cp "$repo/extensions/messaging/tproj-msg-db.sh" "$HOME/bin/tproj-msg-db.sh"
cp "$repo/extensions/messaging/tproj-peer-outbox" "$HOME/bin/tproj-peer-outbox"
chmod +x "$HOME/bin/tproj-inbox-record" "$HOME/bin/tproj-peer-outbox"
cat > "$tmp/bin/tmux" <<'TMUX'
#!/usr/bin/env bash
case "${*: -1}" in
  '#S') echo testsession ;;
  '#{@alias}') echo artist ;;
  '#{@role}') echo claude-p1 ;;
  '#{@role_epoch}') echo 4 ;;
  '#{@orchestration_role}') echo worker ;;
esac
TMUX
chmod +x "$tmp/bin/tmux"

record='{"message_id":"msg-1","task_id":"task-1","origin_host":"host-a","destination_host":"host-b","origin_project":"project-a","destination_project":"project-b","owner_session":"testsession","destination_session":"session-b","owner_alias":"artist.cc","sender":"artist.cc","sender_role":"worker","target":"remote.cdx","role_epoch":4,"orchestrator_alias":"artist.cc","task_kind":"delegated","intent_hash":"","user_authorized_exact":false,"body_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","ttl_sec":900,"issued_at":1000}'
printf '%s\n' "$record" | "$HOME/bin/tproj-peer-outbox" --db "$TPROJ_PEER_OUTBOX_DB" prepare >/dev/null
payload='{"tool_name":"Bash","tool_input":{"command":"tproj-msg --new-task remote.cdx text"},"tool_response":{"stderr":"TASK_ID=task-1 TASK_TARGET=remote.cdx TASK_TTL_SEC=900 TASK_SENT_AT=1000 TASK_KIND=delegated TASK_USER_AUTHORIZED_EXACT=0"}}'
printf '%s\n' "$payload" | TPROJ_HOOK_ENABLED=1 "$HOME/bin/tproj-inbox-record"
state=$(sqlite3 "$TPROJ_PEER_OUTBOX_DB" "SELECT state FROM tasks WHERE message_id='msg-1';")
[[ "$state" == committed ]]

# Exact metadata conflict must leave a prepared row untouched even though D4
# still performs its ordinary cache/DB insertion.
record_bad=$(jq -c '.message_id="msg-2" | .task_id="task-2" | .ttl_sec=901' <<< "$record")
printf '%s\n' "$record_bad" | "$HOME/bin/tproj-peer-outbox" --db "$TPROJ_PEER_OUTBOX_DB" prepare >/dev/null
payload_bad="${payload/task-1/task-2}"
printf '%s\n' "$payload_bad" | TPROJ_HOOK_ENABLED=1 "$HOME/bin/tproj-inbox-record"
state=$(sqlite3 "$TPROJ_PEER_OUTBOX_DB" "SELECT state FROM tasks WHERE message_id='msg-2';")
[[ "$state" == prepared ]]

# A fail-open shadow DB write result is not proof: if its readback fails,
# the prepared outbox row must not be committed.
record_unproved=$(jq -c '.message_id="msg-3" | .task_id="task-3"' <<< "$record")
printf '%s\n' "$record_unproved" | "$HOME/bin/tproj-peer-outbox" --db "$TPROJ_PEER_OUTBOX_DB" prepare >/dev/null
sqlite_real=$(command -v sqlite3)
cat > "$tmp/bin/sqlite3" <<SQLITE
#!/usr/bin/env bash
if [[ "\$1" == -readonly ]]; then exit 1; fi
exec "$sqlite_real" "\$@"
SQLITE
chmod +x "$tmp/bin/sqlite3"
payload_unproved="${payload/task-1/task-3}"
printf '%s\n' "$payload_unproved" | TPROJ_HOOK_ENABLED=1 "$HOME/bin/tproj-inbox-record"
state=$("$sqlite_real" "$TPROJ_PEER_OUTBOX_DB" "SELECT state FROM tasks WHERE message_id='msg-3';")
[[ "$state" == prepared ]]

payload_local="${payload/task-1/local-4}"
printf '%s\n' "$payload_local" | TPROJ_HOOK_ENABLED=1 TPROJ_PEER_OUTBOX_DB="$tmp/no-outbox.sqlite" "$HOME/bin/tproj-inbox-record"
[[ -n "$(jq -r '.["local-4"].target // empty' "$TT_CACHE_DIR/testsession/artist/remote.cdx.json")" ]]
echo 'inbox record peer outbox: ok'

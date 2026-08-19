#!/usr/bin/env bash
#
# test-completion-guard-consult.sh — advisor mode owes the peer one consultation.
#
# Advisor pairs the two panes correctly but gives the working side no reason to ever
# use its peer, so it works alone and the mode is indistinguishable from solo. The
# gate below is what makes the consultation real. Everything it cannot determine
# must fail open: a guard that holds a turn open on a missing DB, a dead peer, or a
# pre-migration lock would be worse than the problem it solves.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GUARD="$SCRIPT_DIR/../tproj-completion-guard"

PASS=0
FAIL=0
pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/consult-gate-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/ig" "$TMP/cache/s1/3" "$TMP/proj"

# A fake router that is both an importable module and the CLI the guard shells out to.
cat > "$TMP/bin/model-role-router" <<'ROUTER'
#!/usr/bin/env python3
import json, os, pathlib, sys

def read_json_file(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}

def state_path(identity):
    root = pathlib.Path(os.environ["FAKE_CACHE"])
    return root / identity["session"] / "3" / (identity["alias"] + ".json")

def pane_peer(identity):
    alias = os.environ.get("FAKE_PEER", "")
    return {"alias": alias} if alias else {}

if __name__ == "__main__":
    print(json.dumps({"mode": os.environ.get("FAKE_MODE", "advisor")}))
ROUTER
chmod +x "$TMP/bin/model-role-router"

cat > "$TMP/bin/tmux" <<'TMUX'
#!/usr/bin/env bash
case "$*" in
  *"#{@project}"*) echo "$FAKE_PROJECT" ;;
  *"#{@column}"*) echo 3 ;;
  *"#S"*|*"#{session_name}"*) echo s1 ;;
  *"#{@alias}"*) echo tproj ;;
  *"#{@role}"*) echo claude-p3 ;;
  *) echo "" ;;
esac
TMUX
chmod +x "$TMP/bin/tmux"

DB="$TMP/messages.db"
sqlite3 "$DB" "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, from_alias TEXT, to_alias TEXT, body TEXT, direction TEXT, delivery TEXT, msg_kind TEXT, created_at INTEGER);"

printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"

write_lock() {  # <started_at_epoch> <owner_alias>
  python3 -c "
import json, sys
state = {'version': 1, 'entries': {sys.argv[1]: {
    'cwd': sys.argv[1], 'intent': 'x', 'status': 'active',
    'started_at': '2020-01-01T00:00:00Z', 'started_at_epoch': int(sys.argv[2]),
    'owner_session': 's1', 'owner_alias': sys.argv[3]}}}
json.dump(state, open(sys.argv[4], 'w', encoding='utf-8'))
" "$TMP/proj" "$1" "$2" "$TMP/ig/state.json"
}

add_msg() {  # <kind> <created_at> [delivery] [body]
  sqlite3 "$DB" "INSERT INTO messages (session, from_alias, to_alias, body, direction, delivery, msg_kind, created_at)
                 VALUES ('s1','tproj.cc','tproj.cdx','${4-hello}','outbound','${3-send-keys}','$1',$2);"
}

run_guard() {
  printf '{"last_assistant_message":"done"}' | \
    env PATH="$TMP/bin:$PATH" \
        FAKE_CACHE="$TMP/cache" \
        FAKE_PROJECT="$TMP/proj" \
        FAKE_PEER="${FAKE_PEER-tproj.cdx}" \
        FAKE_MODE="${FAKE_MODE-advisor}" \
        TPROJ_MSG_DB_PATH="$DB" \
        INTENT_GUARD_DIR="$TMP/ig" \
        TPROJ_PANE="%8" \
        TMUX_PANE="%8" \
        "$GUARD" 2>&1
}

# The hook protocol is the output, not the exit status: block() prints a decision
# and still exits 0, so asserting on rc would pass no matter what the gate decided.
expect() {  # <name> <expect-block:yes|no>
  local out blocked=no
  out=$(cd "$TMP/proj" && run_guard)
  printf '%s' "$out" | grep -q '"decision":"block"' && blocked=yes
  if [[ "$blocked" == "$2" ]]; then pass "$1"
  else fail "$1" "expected block=$2 got=$blocked out=$(printf '%s' "$out" | tr '\n' '|' | cut -c1-100)"; fi
}

NOW=$(date +%s)

printf '{"version":1,"entries":{}}' > "$TMP/ig/state.json"
expect "a turn with no locked task is never gated" no

write_lock "$((NOW - 60))" tproj.cc
expect "a locked task with no consultation is held open" yes

add_msg consult "$((NOW - 30))"
expect "one consultation inside the task run releases it" no

# The whole reason a fresh task_run stamp was needed: an older consultation must
# not satisfy a task that started after it.
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult "$((NOW - 600))"
expect "a consultation from before the task run does not count" yes

# Ordinary traffic and the router's own pairing ping must not pass as consultation.
sqlite3 "$DB" "DELETE FROM messages;"
add_msg "" "$((NOW - 10))"
expect "an unmarked message does not count as consultation" yes
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult "$((NOW - 10))" rejected
expect "a rejected consultation does not count" yes
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult "$((NOW - 10))" send-keys ""
expect "an empty-bodied audit row does not count" yes

# Fail-open paths.
sqlite3 "$DB" "DELETE FROM messages;"
FAKE_PEER="" expect "no reachable peer never holds the turn open" no
FAKE_MODE=auto expect "auto mode does not use this gate" no
printf '{"role":"advisor"}' > "$TMP/cache/s1/3/tproj.cc.json"
expect "the advising side owes nothing" no
printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"
write_lock "$((NOW - 60))" other.cc
expect "a lock owned by another pane is not this pane's task" no

printf -- '----\nPASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

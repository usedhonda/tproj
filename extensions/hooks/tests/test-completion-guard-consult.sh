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
sqlite3 "$DB" "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, from_alias TEXT, to_alias TEXT, body TEXT, direction TEXT, delivery TEXT, msg_kind TEXT, task_run_id TEXT, created_at INTEGER);"

printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"

write_lock() {  # <task_run_id> <owner_alias>
  python3 -c "
import hashlib, json, sys
key = hashlib.md5(sys.argv[1].encode('utf-8')).hexdigest()  # same key intent-guard writes
run = {} if sys.argv[2] == '-' else {'task_run_id': sys.argv[2]}
state = {'version': 1, 'entries': {key: dict({
    'cwd': sys.argv[1], 'intent': 'x', 'status': 'active',
    'started_at': '2020-01-01T00:00:00Z', 'started_at_epoch': 1,
    'owner_session': 's1', 'owner_alias': sys.argv[3]}, **run)}}
json.dump(state, open(sys.argv[4], 'w', encoding='utf-8'))
" "$TMP/proj" "$1" "$2" "$TMP/ig/state.json"
}

add_msg() {  # <kind> <task_run_id> [delivery] [body]
  sqlite3 "$DB" "INSERT INTO messages (session, from_alias, to_alias, body, direction, delivery, msg_kind, task_run_id, created_at)
                 VALUES ('s1','tproj.cc','tproj.cdx','${4-hello}','outbound','${3-send-keys}','$1','$2',$(date +%s));"
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

printf '{"version":1,"entries":{}}' > "$TMP/ig/state.json"
expect "a turn with no locked task is never gated" no

write_lock run-B tproj.cc
expect "a locked task with no consultation is held open" yes

add_msg consult run-B
expect "one consultation inside the task run releases it" no

# The whole reason the run id had to reach the message row: `created_at` has
# one-second resolution, so a boundary made of time alone lets a consultation sent
# for the previous task satisfy the next one when the two share a second.
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult run-A
expect "a consultation belonging to another task run does not count" yes

# Ordinary traffic and the router's own pairing ping must not pass as consultation.
sqlite3 "$DB" "DELETE FROM messages;"
add_msg "" run-B
expect "an unmarked message does not count as consultation" yes
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult run-B rejected
expect "a rejected consultation does not count" yes
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult run-B send-keys ""
expect "an empty-bodied audit row does not count" yes

# Fail-open paths.
sqlite3 "$DB" "DELETE FROM messages;"
FAKE_PEER="" expect "no reachable peer never holds the turn open" no
FAKE_MODE=auto expect "auto mode does not use this gate" no
printf '{"role":"advisor"}' > "$TMP/cache/s1/3/tproj.cc.json"
expect "the advising side owes nothing" no
printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"
write_lock run-B other.cc
expect "a lock owned by another pane is not this pane's task" no
write_lock - tproj.cc
expect "a lock predating the run stamp is not gated" no

# intent-guard start supersedes an owner's other active runs, so two of them means
# the invariant is broken and there is no "current" run to gate against. Picking one
# would let whichever entry enumerated first decide, and the older run's
# consultation would release a task the pane never consulted for.
python3 -c "
import hashlib, json, sys
entries = {}
for cwd, run in ((sys.argv[1] + '/old', 'run-A'), (sys.argv[1], 'run-B')):
    entries[hashlib.md5(cwd.encode('utf-8')).hexdigest()] = {
        'cwd': cwd, 'intent': 'x', 'status': 'active', 'task_run_id': run,
        'owner_session': 's1', 'owner_alias': 'tproj.cc'}
json.dump({'version': 1, 'entries': entries}, open(sys.argv[2], 'w', encoding='utf-8'))
" "$TMP/proj" "$TMP/ig/state.json"
# Asserted with an empty message table on purpose: first-wins would pick run-A,
# find no consultation for it, and block. Only refusing to choose leaves the turn
# alone. (The harm Cdx reported -- run-A's old consultation releasing run-B -- shows
# up as "not blocked" under both behaviours, so it cannot tell them apart here; the
# supersede test in test-intent-guard.sh is what covers that direction.)
sqlite3 "$DB" "DELETE FROM messages;"
expect "two active runs for one owner leave the turn alone" no

# The CLI contract behind the mark. `--consult` attests that this pane ASKED its
# peer; every flag below either hands the work off instead of asking or overrides a
# delivery policy, so allowing the combination would let a pane clear the gate
# without ever consulting anyone.
MSG="$SCRIPT_DIR/../../messaging/tproj-msg"
reject() {  # <name> <flag...>
  local name="$1"; shift
  local out rc
  # A target that cannot resolve, and the throwaway DB: if this rejection ever
  # regresses, the test must fail rather than deliver a real message to a peer.
  out=$(TPROJ_MSG_DB_PATH="$DB" "$MSG" "$@" no-such-peer.cdx "probe" 2>&1); rc=$?
  if [[ "$rc" -ne 0 ]] && printf '%s' "$out" | grep -q -- "--consult cannot be combined"; then
    pass "$name"
  else
    fail "$name" "rc=$rc out=$(printf '%s' "$out" | tr '\n' '|' | cut -c1-120)"
  fi
}
reject "--consult rejects --new-task"        --consult --new-task
reject "--consult rejects --role-handoff"    --consult --role-handoff --new-task
reject "--consult rejects --user-authorized" --consult --user-authorized --new-task
reject "--consult rejects --force"           --consult --force
reject "--consult rejects --fire"            --consult --fire
reject "--consult rejects --allow-relay"     --consult --allow-relay why
reject "--consult rejects --allow-fanout"    --consult --allow-fanout why

printf -- '----\nPASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

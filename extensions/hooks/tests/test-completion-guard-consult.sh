#!/usr/bin/env bash
#
# test-completion-guard-consult.sh — consultation and non-solo course checks.
#
# Assist pairs the two panes correctly but gives the working side no reason to ever
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
    return {"alias": alias, "pane_id": "%9"} if alias else {}

if __name__ == "__main__":
    print(json.dumps({"mode": os.environ.get("FAKE_MODE", "assist")}))
ROUTER
chmod +x "$TMP/bin/model-role-router"

cat > "$TMP/bin/tmux" <<'TMUX'
#!/usr/bin/env bash
case "$*" in
  capture-pane*) cat "$FAKE_PANE_EVIDENCE" ;;
  *"#{@project}"*) echo "$FAKE_PROJECT" ;;
  *"#{@column}"*) echo 3 ;;
  *"#S"*|*"#{session_name}"*) echo s1 ;;
  *"#{@alias}"*) echo tproj ;;
  *"#{@role}"*) echo claude-p3 ;;
  *"#{pane_current_command}"*) echo 2.1.227 ;;
  *"#{@prompt_state}"*) echo idle ;;
  *"#{@prompt_state_ts}"*) echo 1 ;;
  *) echo "" ;;
esac
TMUX
chmod +x "$TMP/bin/tmux"

cat > "$TMP/bin/intent-guard" <<'INTENT'
#!/usr/bin/env bash
case "${1-}" in
  reflect-observe)
    printf '%s\n' "$*" >> "${FAKE_REFLECTION_LOG:?}"
    printf '%s\n' "${FAKE_REFLECTION_STATE-ok}"
    ;;
  consult-observe)
    printf '%s\n' "$*" >> "${FAKE_REFLECTION_LOG:?}"
    shift
    message_id=0; outcome=""; reason=""; evidence=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --message-id) message_id="$2"; shift 2 ;;
        --outcome) outcome="$2"; shift 2 ;;
        --reason) reason="$2"; shift 2 ;;
        --evidence-hash) evidence="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    python3 - "$FAKE_STATE_FILE" "$message_id" "$outcome" "$reason" "$evidence" <<'PY'
import json, sys
path, mid, outcome, reason, evidence = sys.argv[1:]
state = json.load(open(path, encoding="utf-8"))
entry = next(v for v in state["entries"].values() if v.get("status") == "active")
entry["consultation"] = {"message_id": int(mid), "outcome": outcome, "reason": reason,
                         "evidence_hash": evidence}
json.dump(state, open(path, "w", encoding="utf-8"))
PY
    ;;
  reflect)
    printf '%s\n' "$*" >> "${FAKE_REFLECTION_LOG:?}"
    printf 'Reflection: consult\n'
    ;;
  *) exit 1 ;;
esac
INTENT
chmod +x "$TMP/bin/intent-guard"

DB="$TMP/messages.db"
sqlite3 "$DB" "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, from_alias TEXT, to_alias TEXT, body TEXT, direction TEXT, delivery TEXT, msg_kind TEXT, task_run_id TEXT, created_at INTEGER, delivered_at INTEGER);"
printf 'pane-start\n' > "$TMP/pane-evidence"
printf '{"generated_at":%s,"sides":{"cc":{"status":"ok","main_remaining_percent":50},"cdx":{"status":"ok","main_remaining_percent":50}}}\n' "$(date +%s)" > "$TMP/weekly.json"

printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"

write_lock() {  # <task_run_id> <owner_alias> [wait|send|none|legacy]
  python3 -c "
import hashlib, json, sys
key = hashlib.md5(sys.argv[1].encode('utf-8')).hexdigest()  # same key intent-guard writes
run = {} if sys.argv[2] == '-' else {'task_run_id': sys.argv[2]}
policy = {} if sys.argv[4] == 'legacy' else {'assist_consult_policy': sys.argv[4]}
state = {'version': 1, 'entries': {key: dict({
    'cwd': sys.argv[1], 'intent': 'x', 'status': 'active',
    'started_at': '2020-01-01T00:00:00Z', 'started_at_epoch': 1,
    'owner_session': 's1', 'owner_alias': sys.argv[3]}, **run, **policy)}}
json.dump(state, open(sys.argv[5], 'w', encoding='utf-8'))
" "$TMP/proj" "$1" "$2" "${3-legacy}" "$TMP/ig/state.json"
}

add_msg() {  # <kind> <task_run_id> [delivery] [body]
  sqlite3 "$DB" "INSERT INTO messages (session, from_alias, to_alias, body, direction, delivery, msg_kind, task_run_id, created_at, delivered_at)
                 VALUES ('s1','tproj.cc','tproj.cdx','${4-hello}','outbound','${3-send-keys}','$1','$2',$(date +%s),$(date +%s));"
}

add_reply() {
  sqlite3 "$DB" "INSERT INTO messages (session, from_alias, to_alias, body, direction, delivery, msg_kind, task_run_id, created_at)
                 VALUES ('s1','tproj.cdx','tproj.cc','advice','inbound','send-keys','','',$(date +%s));"
}

set_entry() { # <python body mutating entry>
  python3 -c "import json; p='$TMP/ig/state.json'; s=json.load(open(p)); e=next(iter(s['entries'].values())); $1; json.dump(s,open(p,'w'))"
}

run_guard() {
  local event="${GUARD_EVENT-stop}" payload
  if [[ "$event" == "pretool" ]]; then
    payload=$(jq -nc --arg tool "${PRETOOL_TOOL-apply_patch}" --arg command "${PRETOOL_COMMAND-}" \
      '{tool_name:$tool,tool_input:{command:$command}}')
  elif [[ "$event" == "posttool" ]]; then
    if [[ -n "${POSTTOOL_EXIT_CODE+x}" ]]; then
      payload=$(jq -nc --arg tool "${POSTTOOL_TOOL-functions.exec_command}" \
        --arg command "${POSTTOOL_COMMAND-bash tests/example.sh}" \
        --argjson exit_code "$POSTTOOL_EXIT_CODE" \
        '{tool_name:$tool,tool_input:{command:$command},tool_response:{exit_code:$exit_code}}')
    else
      payload=$(jq -nc --arg tool "${POSTTOOL_TOOL-functions.exec_command}" \
        --arg command "${POSTTOOL_COMMAND-bash tests/example.sh}" \
        '{tool_name:$tool,tool_input:{command:$command},tool_response:{}}')
    fi
  else
    payload='{"last_assistant_message":"done"}'
  fi
  printf '%s' "$payload" | \
    env PATH="$TMP/bin:$PATH" \
        FAKE_CACHE="$TMP/cache" \
        FAKE_PROJECT="$TMP/proj" \
        FAKE_PEER="${FAKE_PEER-tproj.cdx}" \
        FAKE_MODE="${FAKE_MODE-assist}" \
        TPROJ_MSG_DB_PATH="$DB" \
        INTENT_GUARD_DIR="$TMP/ig" \
        FAKE_REFLECTION_STATE="${FAKE_REFLECTION_STATE-ok}" \
        FAKE_REFLECTION_LOG="$TMP/reflection.log" \
        FAKE_PANE_EVIDENCE="$TMP/pane-evidence" \
        FAKE_STATE_FILE="$TMP/ig/state.json" \
        TPROJ_USAGE_STATE_PATH="$TMP/weekly.json" \
        TPROJ_PANE="%8" \
        TMUX_PANE="%8" \
        "$GUARD" --event "$event" 2>&1
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

# `send` gates the first mutation on the outbound consultation. `wait` additionally
# requires a real inbound peer message after that consultation.
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-S tproj.cc send
GUARD_EVENT=pretool expect "send policy blocks the first mutation before consultation" yes
add_msg consult run-S
GUARD_EVENT=pretool expect "send policy allows mutation after consultation is sent" no

sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-W tproj.cc wait
GUARD_EVENT=pretool expect "wait policy blocks mutation before consultation" yes
add_msg consult run-W
GUARD_EVENT=pretool expect "wait policy still blocks while the reply is pending" yes
expect "wait policy also holds a plan-only Stop while the reply is pending" yes
add_reply
reply_id=$(sqlite3 "$DB" 'SELECT MAX(id) FROM messages;')
GUARD_EVENT=pretool expect "wait policy requires anchored acknowledgement after the peer reply" yes
set_entry "e['advice']={'message_id':$reply_id,'decision':'adopt','reason':'use the safer boundary'}"
GUARD_EVENT=pretool expect "wait policy allows mutation after anchored acknowledgement" no
expect "wait policy allows completion after anchored acknowledgement" no

# Adaptive policy waits only while delivered peer evidence is unchanged. A changed
# pane degrades to send, while a later direct reply still requires acknowledgement.
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-A tproj.cc adaptive
add_msg consult run-A
GUARD_EVENT=pretool expect "adaptive policy records a peer baseline and waits" yes
GUARD_EVENT=pretool expect "adaptive policy keeps waiting while peer evidence is unchanged" yes
printf 'pane-changed\n' > "$TMP/pane-evidence"
GUARD_EVENT=pretool expect "adaptive policy degrades after peer pane evidence changes" no
if python3 - "$TMP/ig/state.json" <<'PY'
import json, sys
entry = next(iter(json.load(open(sys.argv[1], encoding="utf-8"))["entries"].values()))
raise SystemExit(0 if (entry.get("consultation") or {}).get("outcome") == "degraded" else 1)
PY
then
  pass "adaptive degradation is recorded by the canonical writer"
else
  fail "adaptive degradation is recorded by the canonical writer" "state did not record degraded"
fi
GUARD_EVENT=pretool expect "adaptive degradation persists without re-blocking the next mutation" no
add_reply
reply_id=$(sqlite3 "$DB" 'SELECT MAX(id) FROM messages;')
GUARD_EVENT=pretool expect "a late reply after degradation still requires acknowledgement" yes
set_entry "e['advice']={'message_id':$reply_id,'decision':'partial','reason':'adopt the bounded part'}"
GUARD_EVENT=pretool expect "adaptive policy resumes after the late reply is acknowledged" no

sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-Q tproj.cc adaptive
add_msg consult run-Q
printf '{"generated_at":%s,"sides":{"cc":{"status":"ok","main_remaining_percent":50},"cdx":{"status":"unavailable","main_remaining_percent":0}}}\n' "$(date +%s)" > "$TMP/weekly.json"
GUARD_EVENT=pretool expect "adaptive policy pre-degrades when the peer weekly state is freshly unavailable" no
printf '{"generated_at":%s,"sides":{"cc":{"status":"ok","main_remaining_percent":50},"cdx":{"status":"ok","main_remaining_percent":50}}}\n' "$(date +%s)" > "$TMP/weekly.json"

# Reflection state is owned by intent-guard. Semantic acknowledgement clears the
# first course check; a repeated machine signature escalates to a newer consult.
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-F tproj.cc send
add_msg consult run-F
set_entry "e['reflection']={'state':'due-reflect','anchor_message_id':0}"
GUARD_EVENT=pretool expect "a failed verification asks the Assist working side to reflect" yes
PRETOOL_TOOL=Bash PRETOOL_COMMAND='intent-guard reflect --assessment course-correct --evidence changed --next retry' \
  GUARD_EVENT=pretool expect "the semantic reflection command cannot block itself" no

# A repeated signature remains blocked until a consultation newer than the anchor.
anchor=$(sqlite3 "$DB" 'SELECT COALESCE(MAX(id),0) FROM messages;')
set_entry "e['reflection']={'state':'due-consult','anchor_message_id':$anchor}"
GUARD_EVENT=pretool expect "a repeated failure signature requires a fresh consultation" yes
add_msg consult run-F
: > "$TMP/reflection.log"
GUARD_EVENT=pretool expect "a newer consultation releases the repeated failure" no
grep -q -- "--consulted --message-id" "$TMP/reflection.log" \
  && pass "the released consultation is durably acknowledged through intent-guard" \
  || fail "the released consultation is durably acknowledged through intent-guard" "log=$(cat "$TMP/reflection.log" 2>/dev/null)"

# Collab workers get the same course check without changing delegated-task
# lifecycle; Solo remains completely outside it.
printf '{"role":"worker"}' > "$TMP/cache/s1/3/tproj.cc.json"
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-C tproj.cc send
add_msg consult run-C
set_entry "e['reflection']={'state':'due-reflect','anchor_message_id':0}"
FAKE_MODE=collab GUARD_EVENT=pretool expect "a Collab worker receives the same course check" yes
printf '{"role":"solo-fallback"}' > "$TMP/cache/s1/3/tproj.cc.json"
FAKE_MODE=solo GUARD_EVENT=pretool expect "Solo mode never runs the reflection gate" no
FAKE_MODE=assist

# PostToolUse never blocks. With a proven non-zero exit it records a machine
# command signature; missing exits and simple predicates fail open.
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-P tproj.cc send
add_msg consult run-P
: > "$TMP/reflection.log"
POSTTOOL_EXIT_CODE=1 GUARD_EVENT=posttool run_guard >/dev/null
grep -q -- "reflect-observe --failure-signature" "$TMP/reflection.log" \
  && pass "an explicit shell failure records a machine signature" \
  || fail "an explicit shell failure records a machine signature" "log=$(cat "$TMP/reflection.log" 2>/dev/null)"
before=$(wc -l < "$TMP/reflection.log" | tr -d ' ')
POSTTOOL_COMMAND='rg missing file' POSTTOOL_EXIT_CODE=1 GUARD_EVENT=posttool run_guard >/dev/null
unset POSTTOOL_EXIT_CODE
GUARD_EVENT=posttool run_guard >/dev/null
after=$(wc -l < "$TMP/reflection.log" | tr -d ' ')
[[ "$before" == "$after" ]] \
  && pass "predicate failures and unproven exits do not create reflection episodes" \
  || fail "predicate failures and unproven exits do not create reflection episodes" "before=$before after=$after"

sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-N tproj.cc none
GUARD_EVENT=pretool expect "none policy leaves a local mutation alone" no
write_lock run-R tproj.cc wait
PRETOOL_TOOL=Bash PRETOOL_COMMAND="git status" GUARD_EVENT=pretool expect "read-only shell work is allowed while advice is pending" no
FAKE_PEER="" GUARD_EVENT=pretool expect "an unavailable peer never wedges the first mutation" no

# The whole reason the run id had to reach the message row: `created_at` has
# one-second resolution, so a boundary made of time alone lets a consultation sent
# for the previous task satisfy the next one when the two share a second.
sqlite3 "$DB" "DELETE FROM messages;"
add_msg consult run-A
expect "a consultation belonging to another task run does not count" yes

# Ordinary traffic and the router's own pairing ping must not pass as consultation.
sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-B tproj.cc send
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
FAKE_MODE=collab expect "collab mode does not use this gate" no
printf '{"role":"assist"}' > "$TMP/cache/s1/3/tproj.cc.json"
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

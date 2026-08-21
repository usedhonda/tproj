#!/usr/bin/env bash
#
# test-completion-guard-consult.sh — consultation and non-solo course checks.
#
# Consultation and course checks remain auditable, but they are advice rather than
# permission. This regression pins the boundary: no consultation state, pending
# reply, unacknowledged reply, or reflection state may block mutation or Stop.

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
expect "Assist Stop never waits for a consultation" no
GUARD_EVENT=pretool expect "Assist mutation never waits for a consultation" no

sqlite3 "$DB" "DELETE FROM messages;"
write_lock run-W tproj.cc wait
add_msg consult run-W
GUARD_EVENT=pretool expect "a pending peer reply does not block mutation" no
expect "a pending peer reply does not block Stop" no
add_reply
GUARD_EVENT=pretool expect "an unacknowledged peer reply does not block mutation" no
expect "an unacknowledged peer reply does not block Stop" no

# Reflection remains an audit signal, never a permission gate.
write_lock run-F tproj.cc send
set_entry "e['reflection']={'state':'due-reflect','anchor_message_id':0}"
GUARD_EVENT=pretool expect "a due reflection does not block mutation" no
set_entry "e['reflection']={'state':'due-consult','anchor_message_id':0}"
GUARD_EVENT=pretool expect "a repeated failure signal does not block mutation" no

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

# `--consult` remains a distinct audit kind and stays incompatible with control or
# delivery-bypass flags even though consultation is no longer an execution gate.
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

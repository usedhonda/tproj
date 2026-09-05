#!/usr/bin/env bash
#
# test-bridge-server.sh — hermetic check of extensions/messaging/bridge/tproj-bridge.py
#
# Fakes both neighbours of the bridge: a `codex` on PATH that writes the -o file,
# and a ClawGate-shaped receiver that records what lands on /v1/tproj-msg-deliver.
# Then drives the real bridge over loopback and asserts the contract:
#   health idle/busy, inbox -> codex -> deliver payload shape, id mismatch 409,
#   duplicate trace_id not re-run, bad JSON 400.
set -u

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
BRIDGE="$REPO/extensions/messaging/bridge/tproj-bridge.py"
WORK="$(mktemp -d)"
trap 'kill $BRIDGE_PID $RECV_PID 2>/dev/null; wait $BRIDGE_PID $RECV_PID 2>/dev/null; find "$WORK" -depth -delete 2>/dev/null || true' EXIT
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL  %s: %s\n' "$1" "$2"; }

command -v python3 >/dev/null || { echo "SKIP python3 missing"; exit 0; }

free_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'; }
BPORT=$(free_port); RPORT=$(free_port)

# --- fake codex: sleeps a little (so busy is observable), writes -o ----------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/codex" <<'CODEX'
#!/usr/bin/env bash
argv_all="$*"
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac
done
prompt=$(cat)
printf '%s\n' "$prompt" > "${FAKE_CODEX_PROMPT_FILE}"
# The bridge inherits its env at start, so the delay is read from a file the
# test can change per case.
sleep "$(cat "${FAKE_CODEX_PROMPT_FILE}.sleep" 2>/dev/null || echo 0)"
printf '%s\n' "$argv_all" > "${FAKE_CODEX_PROMPT_FILE}.argv"
if [[ -f "${FAKE_CODEX_PROMPT_FILE}.exit" ]]; then echo "boom on stderr" >&2; exit "$(cat "${FAKE_CODEX_PROMPT_FILE}.exit")"; fi
if [[ -f "${FAKE_CODEX_PROMPT_FILE}.empty" ]]; then : > "$out"; exit 0; fi
printf 'reply to: %s' "$prompt" > "$out"
CODEX
chmod +x "$WORK/bin/codex"

# --- fake ClawGate receiver --------------------------------------------------
cat > "$WORK/recv.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
path = sys.argv[2]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        with open(path, "ab") as fh:
            fh.write(self.path.encode() + b" " + body + b"\n")
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(b'{"ok":true}')
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
python3 "$WORK/recv.py" "$RPORT" "$WORK/delivered.log" &
RECV_PID=$!

# --- real bridge -------------------------------------------------------------
export PATH="$WORK/bin:$PATH"
export FAKE_CODEX_PROMPT_FILE="$WORK/prompt.txt"
TPROJ_BRIDGE_ID=bot01 TPROJ_BRIDGE_PORT="$BPORT" TPROJ_BRIDGE_BIND=127.0.0.1 \
  TPROJ_BRIDGE_REPO="$WORK" TPROJ_BRIDGE_CODEX="$WORK/bin/codex" \
  TPROJ_BRIDGE_NETWORK=1 TPROJ_BRIDGE_ADD_DIRS="$WORK/extra" \
  python3 "$BRIDGE" 2>"$WORK/bridge.log" &
BRIDGE_PID=$!
for _ in $(seq 1 50); do
  curl -s "http://127.0.0.1:$BPORT/v1/health" >/dev/null 2>&1 && break
  sleep 0.1
done

health() { curl -s "http://127.0.0.1:$BPORT/v1/health"; }
inbox() { curl -s -o "$WORK/resp.json" -w '%{http_code}' -X POST "http://127.0.0.1:$BPORT/v1/inbox" -H 'Content-Type: application/json' -d "$1"; }
wait_delivered() { for _ in $(seq 1 100); do [[ -s "$WORK/delivered.log" ]] && grep -q "$1" "$WORK/delivered.log" && return 0; sleep 0.1; done; return 1; }

# 1. health idle
h=$(health)
[[ "$h" == *'"ok": true'* && "$h" == *'"id": "bot01"'* && "$h" == *'"busy": false'* ]] \
  && pass health_idle || fail health_idle "$h"

# 2. inbox -> codex -> deliver, payload shape
env1=$(printf '{"from":"tproj.cc","to":"gate:bot01","session":"tproj-workspace","text":"hello box","trace_id":"t-1","return_url":"http://127.0.0.1:%s","reply_as":"bot01.cdx"}' "$RPORT")
code=$(inbox "$env1")
[[ "$code" == "202" ]] && pass inbox_accepted_202 || fail inbox_accepted_202 "code=$code $(cat "$WORK/resp.json")"
if wait_delivered "t-1\|hello box"; then
  line=$(tail -1 "$WORK/delivered.log")
  body=${line#* }
  t=$(printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["session"], d["target"], d["senderAs"], d["text"])')
  [[ "$line" == "/v1/tproj-msg-deliver "* && "$t" == "tproj-workspace tproj.cc bot01.cdx reply to: [from:tproj.cc] hello box" ]] \
    && pass deliver_payload_shape || fail deliver_payload_shape "$line"
  grep -q '^\[from:tproj.cc\] hello box' "$WORK/prompt.txt" && pass prompt_carries_sender || fail prompt_carries_sender "$(cat "$WORK/prompt.txt")"
else
  fail deliver_payload_shape "nothing delivered: $(cat "$WORK/bridge.log")"
  fail prompt_carries_sender "no delivery"
fi

# 3. busy while a job runs
: > "$WORK/delivered.log"
env2=$(printf '{"from":"tproj.cc","to":"gate:bot01","session":"tproj-workspace","text":"slow","trace_id":"t-2","return_url":"http://127.0.0.1:%s","reply_as":"bot01.cdx"}' "$RPORT")
printf 1.5 > "$WORK/prompt.txt.sleep"
inbox "$env2" >/dev/null
sleep 0.4
h=$(health)
[[ "$h" == *'"busy": true'* ]] && pass health_busy_during_job || fail health_busy_during_job "$h"
wait_delivered "slow" >/dev/null
rm -f "$WORK/prompt.txt.sleep"
h=$(health)
[[ "$h" == *'"busy": false'* ]] && pass health_idle_after_job || fail health_idle_after_job "$h"

# 4. addressed to another id -> 409, nothing run
: > "$WORK/prompt.txt"
env3=$(printf '{"from":"tproj.cc","to":"gate:bot02","session":"s","text":"wrong box","trace_id":"t-3","return_url":"http://127.0.0.1:%s","reply_as":"bot02.cdx"}' "$RPORT")
code=$(inbox "$env3")
sleep 0.3
[[ "$code" == "409" && ! -s "$WORK/prompt.txt" ]] && pass wrong_id_refused_409 || fail wrong_id_refused_409 "code=$code prompt=$(cat "$WORK/prompt.txt")"

# 5. duplicate trace_id acknowledged but not re-run
: > "$WORK/delivered.log"; : > "$WORK/prompt.txt"
code=$(inbox "$env1")
sleep 0.5
[[ "$code" == "202" && "$(cat "$WORK/resp.json")" == *'"duplicate": true'* && ! -s "$WORK/prompt.txt" ]] \
  && pass duplicate_trace_not_rerun || fail duplicate_trace_not_rerun "code=$code resp=$(cat "$WORK/resp.json") prompt=$(cat "$WORK/prompt.txt")"

# 6. bad JSON -> 400
code=$(inbox '{not json')
[[ "$code" == "400" ]] && pass bad_json_400 || fail bad_json_400 "code=$code"

# 7. the effective sandbox policy is visible on /v1/health and applied to codex
h=$(health)
argv=$(cat "$WORK/prompt.txt.argv" 2>/dev/null || true)
if [[ "$h" == *'"sandbox": "workspace-write"'* && "$h" == *'"network": true'* && "$h" == *"$WORK/extra"* \
      && "$argv" == *"-s workspace-write"* && "$argv" == *"sandbox_workspace_write.network_access=true"* && "$argv" == *"--add-dir $WORK/extra"* ]]; then
  pass health_exposes_policy_and_codex_gets_it
else
  fail health_exposes_policy_and_codex_gets_it "health=$h argv=$argv"
fi

# 8. a clean run with an empty last message delivers nothing (a 返信不要 is not a fault)
: > "$WORK/delivered.log"; touch "$WORK/prompt.txt.empty"
env8=$(printf '{"from":"tproj.cc","to":"gate:bot01","session":"s","text":"FYI only","trace_id":"t-8","return_url":"http://127.0.0.1:%s","reply_as":"bot01.cdx"}' "$RPORT")
inbox "$env8" >/dev/null; sleep 0.8
if [[ ! -s "$WORK/delivered.log" ]] && grep -q "t-8 (exit 0, empty last message; nothing delivered)" "$WORK/bridge.log"; then
  pass empty_reply_not_delivered
else
  fail empty_reply_not_delivered "delivered=$(cat "$WORK/delivered.log") log=$(grep t-8 "$WORK/bridge.log")"
fi
rm -f "$WORK/prompt.txt.empty"

# 9. a failing run is delivered with the reason, so the pane is never left waiting
: > "$WORK/delivered.log"; printf 3 > "$WORK/prompt.txt.exit"
env9=$(printf '{"from":"tproj.cc","to":"gate:bot01","session":"s","text":"break","trace_id":"t-9","return_url":"http://127.0.0.1:%s","reply_as":"bot01.cdx"}' "$RPORT")
inbox "$env9" >/dev/null
if wait_delivered "could not complete" && grep -q "exited 3" "$WORK/delivered.log" && grep -q "boom on stderr" "$WORK/delivered.log"; then
  pass failed_run_delivered_with_reason
else
  fail failed_run_delivered_with_reason "$(cat "$WORK/delivered.log")"
fi
rm -f "$WORK/prompt.txt.exit"

printf '%s\n' '----'
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

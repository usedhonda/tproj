#!/usr/bin/env bash
#
# test-registry-contract.sh — model-role-router <-> tproj-msg registry contract.
#
# Local producer/consumer contract; requires the sibling model-role-router.
# P1 and P2 are fatal assertions. P3 is a non-gating observation only and
# does not establish deterministic multi-candidate selection.
#   P1  router accepts only registered, live PID-start-bound peers
#   P2a recorded pid_start absent -> REJECT pid_start_unrecorded
# Fail-closed consumer guards:
#   P2b recorded pid_start present and matching        -> VERIFIED
#   P2c recorded pid_start present but mismatching      -> REJECT
# Observation only (Task 4, non-fatal): find_registry_state_file candidate pick.
#
# Uses MODEL_ROLE_CACHE / TPROJ_MSG_DB_PATH overrides exclusively; never touches
# the real ~/.cache/tproj-model-role or the production messages.db.
#
# Usage: bash extensions/messaging/tests/test-registry-contract.sh \
#          [path-to-tproj-msg] [path-to-model-role-router]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REAL_TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"
ROUTER="${2:-$SCRIPT_DIR/../../../../general/system/model-role-router/model-role-router}"

if [[ ! -x "$REAL_TPROJ_MSG" ]]; then
  echo "FATAL: tproj-msg not found/executable at: $REAL_TPROJ_MSG" >&2
  exit 2
fi
if [[ ! -f "$ROUTER" ]]; then
  echo "FATAL: model-role-router not found at: $ROUTER" >&2
  exit 2
fi

PASS=0; FAIL=0

# --- sandbox -----------------------------------------------------------------
WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-regcontract.XXXXXX")
FAKE_DIR="$WORK/fixtures"; BIN_DIR="$WORK/bin"
mkdir -p "$FAKE_DIR" "$BIN_DIR" "$WORK/home"
export HOME="$WORK/home"
unset MODEL_ROLE_PEER_JSON
SLEEP_PID=""
trap '[[ -n "$SLEEP_PID" ]] && kill "$SLEEP_PID" 2>/dev/null; rm -rf "$WORK"' EXIT

# =============================================================================
# P1: current router never reconstructs an unregistered peer from pane tags.
# A registered peer must retain its PID-start binding; test the real reader.
if MODEL_ROLE_CACHE="$WORK/router-cache" ROUTER_PATH="$ROUTER" python3 - <<'PY'
import importlib.util, os, sys
from importlib.machinery import SourceFileLoader
router = os.environ["ROUTER_PATH"]
# CACHE_DIR is read at import time from MODEL_ROLE_CACHE (already set, empty dir).
# The router file has no .py suffix, so give importlib an explicit source loader.
loader = SourceFileLoader("mrr", router)
spec = importlib.util.spec_from_loader("mrr", loader)
mrr = importlib.util.module_from_spec(spec)
loader.exec_module(mrr)

# Supply observed process/liveness through the seam; no real pane is contacted.
mrr.pid_alive = lambda pid, start=0: pid == 4242 and start in (0, 100)
mrr.caller_ancestry = lambda pid: {4242}
mrr.run_tmux = lambda args: "%2\ttest\t1\tcodex-p1\t4242\t0\tgpt-5.6-sol\tgpt-5.6\tunresolved\t0\t/proj\tnode"
identity = {"alias": "test.cc", "column": "1", "session": "fixture", "pane_id": "%1"}
assert mrr.pane_peer(identity) == {}, "pane tags must not create a binding"
path = mrr.state_path({**identity, "alias": "test.cdx"})
path.parent.mkdir(parents=True, exist_ok=True)
import json
for start in (None, 101, 100):
    saved = {"alias": "test.cdx", "pid": 4242, "pid_start": start}
    path.write_text(json.dumps(saved))
    peer = mrr.pane_peer(identity)
    assert peer == (saved if start == 100 else {}), (start, peer)

PY
then
  printf 'PASS  P1_router_requires_registered_live_pid_start\n'; PASS=$((PASS+1))
else
  rc=$?
  if [[ "$rc" -eq 1 ]]; then
    printf 'FAIL  P1_router_requires_registered_live_pid_start (peer path omits pid_start)\n'
  else
    printf 'FAIL  P1_router_requires_registered_live_pid_start (harness error rc=%s)\n' "$rc"
  fi
  FAIL=$((FAIL+1))
fi

# =============================================================================
# P2 — verify_as_caller_identity contract. Hermetic harness mirrors the gate
# suite: a wrapper renames a forked process to "claude" and writes the registry
# entry for tproj.cc using THAT process's own (pid, pid_start) immediately before
# exec'ing the real tproj-msg as its direct child, so the ancestor walk is
# deterministic. REG_MODE selects the registry shape under test.
# =============================================================================
REGISTRY_ROOT="$WORK/registry"
mkdir -p "$REGISTRY_ROOT/tproj-workspace/1"
export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/db-errors.log"
# E4 (msg-repair): hard invariant -- never run against the real production
# messages.db. Abort loudly if the isolation override above was ever dropped.
if [[ -z "${TPROJ_MSG_DB_PATH:-}" || "$TPROJ_MSG_DB_PATH" == "$HOME/.local/share/tproj-msg/messages.db" ]]; then
  echo "FATAL: TPROJ_MSG_DB_PATH not isolated to a temp DB (would pollute the real messages.db)" >&2
  exit 2
fi

# A live but non-ancestor pid for the find/liveness observation (P3).
sleep 600 & SLEEP_PID=$!
disown "$SLEEP_PID" 2>/dev/null || true

# fake tmux — enough for a running (sendable) normal send to tproj.cc.
cat > "$BIN_DIR/tmux" <<'TMUX'
#!/usr/bin/env bash
set -uo pipefail
FAKE_DIR="$FAKE_DIR_ENV"
sub="${1:-}"; shift || true
target=""; fmt=""; optname=""; args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    -t) target="${args[$((i+1))]:-}";;
    -p|-F) fmt="${args[$((i+1))]:-}";;
    -v) optname="${args[$((i+1))]:-}";;
  esac
done
pane="$target"
readf() { [[ -f "$FAKE_DIR/$1" ]] && cat "$FAKE_DIR/$1" || true; }
case "$sub" in
  display-message)
    if [[ "$fmt" == "#S" || -z "$fmt" && -z "$target" ]]; then printf '%s' "tproj-workspace"; exit 0; fi
    case "$fmt" in
      *pane_tty*) readf "tty_${pane}";;
      *@role*)    readf "role_${pane}";;
      *@alias*)   printf '%s' "tproj";;
      *@column*)  printf '%s' "1";;
      *pane_id*)  printf '%s' "${pane:-%1}";;
      "#S")       printf '%s' "tproj-workspace";;
      *) : ;;
    esac ;;
  list-panes) readf "panes";;
  show-options)
    case "$optname" in
      @prompt_state) readf "promptstate_${pane}";;
      *) : ;;
    esac ;;
  capture-pane) readf "capture_${pane}";;
  send-keys) printf 'SENDKEYS %s\n' "$*" >> "$FAKE_DIR/sendkeys.log";;
  has-session) exit 0;;
  set-option|set|setenv) exit 0;;
  *) : ;;
esac
exit 0
TMUX
chmod +x "$BIN_DIR/tmux"
cat > "$BIN_DIR/websocat" <<'WS'
#!/usr/bin/env bash
printf '%s\n' '{"type":"host_info","host":"test"}'
[[ -f "$FAKE_DIR_ENV/ws.json" ]] && cat "$FAKE_DIR_ENV/ws.json"
exit 0
WS
chmod +x "$BIN_DIR/websocat"
export FAKE_DIR_ENV="$FAKE_DIR"
export PATH="$BIN_DIR:$PATH"

cat > "$FAKE_DIR/panes" <<'PANES'
%1:claude-p1:tproj:1
%2:codex-p1:tproj:1
PANES
printf '%s' "/dev/ttys001" > "$FAKE_DIR/tty_%1"
printf '%s' "claude-p1"    > "$FAKE_DIR/role_%1"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"type":"sessions.list","sessions":[{"tty":"/dev/ttys001","status":"running","updated_at":"%s"}]}\n' "$now" > "$FAKE_DIR/ws.json"
printf '%s' "...generating output..." > "$FAKE_DIR/capture_%1"

TPROJ_MSG="$BIN_DIR/tproj-msg-verified"
cat > "$TPROJ_MSG" <<WRAPPER
#!/bin/bash
if [[ "\${_VERIFIED_REINVOKED:-}" != "1" ]]; then
  export _VERIFIED_REINVOKED=1
  exec -a claude bash "\$0" "\$@"
fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
obs=\$(date +%s)
regdir="$REGISTRY_ROOT/tproj-workspace/1"
regf="\$regdir/tproj.cc.json"
mkdir -p "\$regdir"
case "\${REG_MODE:-}" in
  null_ancestor)
    printf '{"alias":"tproj.cc","pid":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$obs" > "\$regf" ;;
  match)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$obs" > "\$regf" ;;
  mismatch)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$((mystart+9999))" "\$obs" > "\$regf" ;;
  multi_live_plus_dead)
    # Live ancestor entry in window 1 + a dead-pid entry (same alias) in another
    # window. find_registry_state_file must resolve to the LIVE entry (B3).
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$obs" > "\$regf"
    mkdir -p "$REGISTRY_ROOT/tproj-workspace/9"
    printf '{"alias":"tproj.cc","pid":999999,"pid_start":111111,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$obs" > "$REGISTRY_ROOT/tproj-workspace/9/tproj.cc.json" ;;
esac
"$REAL_TPROJ_MSG" "\$@"
WRAPPER
chmod +x "$TPROJ_MSG"

# run_verify <REG_MODE> -> echoes "VERDICT reason" (VERIFY|REJECT)
run_verify() {
  local mode="$1" out
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  out=$(REG_MODE="$mode" "$TPROJ_MSG" --session tproj-workspace --as tproj.cc tproj.cc "contract $mode $$-$RANDOM" 2>&1)
  if grep -q "could not be verified" <<<"$out"; then
    printf 'REJECT %s' "$(sed -n 's/.*reason: \([a-z_]*\).*/\1/p' <<<"$out" | head -1)"
  else
    printf 'VERIFY none'
  fi
}

# P2a — recorded pid_start absent -> REJECT pid_start_unrecorded. Re-deriving
# reg_pid's own live start at verify time is a tautology (same fn, same pid, no
# pid-reuse defence), so an unrecorded pid_start is fail-closed. The router now
# stamps pid_start on the peer path (B1/6a1e7e4), making this a transient race.
res=$(run_verify null_ancestor)
if [[ "$res" == "REJECT pid_start_unrecorded" ]]; then
  printf 'PASS  P2a_null_pidstart_rejects\n'; PASS=$((PASS+1))
else
  printf 'FAIL  P2a_null_pidstart_rejects (want REJECT pid_start_unrecorded, got %s)\n' "$res"
  FAIL=$((FAIL+1))
fi

# P2b — recorded pid_start present and matching -> VERIFY (fail-closed guard, stays green).
res=$(run_verify match)
if [[ "$res" == VERIFY* ]]; then
  printf 'PASS  P2b_matching_pidstart_verifies\n'; PASS=$((PASS+1))
else
  printf 'FAIL  P2b_matching_pidstart_verifies (regression: got %s)\n' "$res"
  FAIL=$((FAIL+1))
fi

# P2c — recorded pid_start present but WRONG -> REJECT (fail-closed guard, stays green).
res=$(run_verify mismatch)
if [[ "$res" == REJECT* ]]; then
  printf 'PASS  P2c_mismatched_pidstart_rejects\n'; PASS=$((PASS+1))
else
  printf 'FAIL  P2c_mismatched_pidstart_rejects (fail-open regression: got %s)\n' "$res"
  FAIL=$((FAIL+1))
fi

# P3 — OBSERVATION ONLY (Task 4, non-fatal). Multiple same-alias registry files
# across windows: find_registry_state_file takes the first find(1) match with no
# liveness/mtime tiebreak, so the chosen entry is filesystem-traversal dependent.
# With a live-ancestor entry AND a dead-pid entry present, the current resolver
# may bind the dead one (-> no_agent_ancestor/pid_start_mismatch). B3 makes this
# deterministically prefer the live entry. Recorded, not asserted, to avoid a
# flaky committed gate.
res=$(run_verify multi_live_plus_dead)
printf 'OBSERVE P3_find_multi_candidate: verdict=%s (non-gating observation; not a determinism assertion)\n' "$res"

echo "----"
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]

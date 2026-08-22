#!/usr/bin/env bash
#
# test-caller-verify-hardening.sh — R2 Stage 2 hardening fixtures for tproj-msg
# caller identity verification (msg-repair).
#
# Covers the behaviours added after the initial R2 Stage 1 landing:
#   - pid_start live-recompute withdrawal (unrecorded is fail-closed elsewhere);
#     here we exercise the pid-reuse mismatch that stays REJECT.
#   - observed_at bounded on BOTH sides (future timestamp -> registry_stale).
#   - the alias.role ancestry walk is bounded by
#     TPROJ_MSG_VERIFIER_MAX_ANCESTOR_HOPS (deep nesting past the cap -> reject).
#   - a recorded reg_pid that is NOT in the caller's ancestry (reparent/disown
#     proxy) -> no_agent_ancestor.
#   - the in-tmux pane-derived path requires the pane's pane_pid to be a genuine
#     ancestor (spoofed TMUX_PANE -> pane_ancestry_mismatch; genuine -> VERIFY).
#   - the CWD auto-detect fallback binds identity through the registry, not a
#     comm-name match (good registry -> VERIFY; bad pid_start -> REJECT).
#   - every send writes exactly one bodyless caller-audit row carrying auth_path
#     and anchor_pid; on a spoof reject the real invoker (caller_pid) and the
#     verification anchor (anchor_pid) diverge.
#
# Hermetic: shims tmux/websocat onto PATH and drives the REAL tproj-msg. Uses
# MODEL_ROLE_CACHE / TPROJ_MSG_DB_PATH overrides exclusively; never touches the
# real ~/.cache/tproj-model-role or the production messages.db.
#
# Usage: bash extensions/messaging/tests/test-caller-verify-hardening.sh \
#          [path-to-tproj-msg]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REAL_TPROJ_MSG="${1:-$SCRIPT_DIR/../tproj-msg}"
if [[ ! -x "$REAL_TPROJ_MSG" ]]; then
  echo "FATAL: tproj-msg not found/executable at: $REAL_TPROJ_MSG" >&2
  exit 2
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/tproj-cvh.XXXXXX")
FAKE_DIR="$WORK/fixtures"; BIN_DIR="$WORK/bin"
mkdir -p "$FAKE_DIR" "$BIN_DIR" "$WORK/queue"
SLEEP_PID=""
trap '[[ -n "$SLEEP_PID" ]] && kill "$SLEEP_PID" 2>/dev/null; rm -rf "$WORK"' EXIT

REGISTRY_ROOT="$WORK/registry"
mkdir -p "$REGISTRY_ROOT/tproj-workspace/1"
export MODEL_ROLE_CACHE="$REGISTRY_ROOT"
export TPROJ_MSG_DB_PATH="$WORK/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$WORK/db-errors.log"
export TPROJ_MSG_SEND_DEDUP_DIR="$WORK/send-dedup"
export TPROJ_MSG_FLUSH_WORKER_LOG="$WORK/flush-worker.log"
export TPROJ_MSG_QUEUE_DIR="$WORK/queue"
# E4 (msg-repair): hard invariant -- never run against the real production DB.
if [[ -z "${TPROJ_MSG_DB_PATH:-}" || "$TPROJ_MSG_DB_PATH" == "$HOME/.local/share/tproj-msg/messages.db" ]]; then
  echo "FATAL: TPROJ_MSG_DB_PATH not isolated to a temp DB (would pollute the real messages.db)" >&2
  exit 2
fi

# --- fake tmux ---------------------------------------------------------------
# Adds a pane_pid handler on top of the usual --status shims. HARNESS_PANE_PID
# ($$) is a genuine ancestor of the tproj-msg it spawns; SPOOF_PANE_PID lets a
# case forge a pane_pid that is NOT an ancestor.
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
      *pane_pid*) printf '%s' "${SPOOF_PANE_PID:-${HARNESS_PANE_PID:-0}}";;
      *pane_id*)  printf '%s' "${pane:-%1}";;
      "#S")       printf '%s' "tproj-workspace";;
      *) : ;;
    esac ;;
  list-panes) readf "panes";;
  show-options) case "$optname" in @prompt_state) readf "promptstate_${pane}";; *) : ;; esac ;;
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

# Exercise the fresh WebSocket liveness evidence on hosts without GNU timeout
# (macOS CI/dev machines commonly lack timeout/gtimeout).
for timeout_name in timeout gtimeout; do
  cat > "$BIN_DIR/$timeout_name" <<'TIMEOUT'
#!/usr/bin/env bash
[[ "${1:-}" =~ ^[0-9]+([.][0-9]+)?$ ]] && shift
exec "$@"
TIMEOUT
  chmod +x "$BIN_DIR/$timeout_name"
done

export FAKE_DIR_ENV="$FAKE_DIR"
export PATH="$BIN_DIR:$PATH"
export HARNESS_PANE_PID=$$

cat > "$FAKE_DIR/panes" <<'PANES'
%1:claude-p1:tproj:1
%2:codex-p1:tproj:1
PANES
printf '%s' "/dev/ttys001" > "$FAKE_DIR/tty_%1"
printf '%s' "/dev/ttys002" > "$FAKE_DIR/tty_%2"
printf '%s' "claude-p1" > "$FAKE_DIR/role_%1"
printf '%s' "codex-p1"  > "$FAKE_DIR/role_%2"
now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"type":"sessions.list","sessions":[{"tty":"/dev/ttys001","status":"running","updated_at":"%s"},{"tty":"/dev/ttys002","status":"running","updated_at":"%s"}]}\n' \
  "$now_iso" "$now_iso" > "$FAKE_DIR/ws.json"
# The liveness contract now requires fresh target-bound evidence; native prompt
# markers keep these caller-auth tests focused on sender verification rather
# than the stale-process rejection path.
printf '%s' $'...generating output...\n❯ ' > "$FAKE_DIR/capture_%1"
printf '%s' $'...generating output...\n› ' > "$FAKE_DIR/capture_%2"

# A live but non-ancestor pid (reparent/disown proxy).
sleep 600 & SLEEP_PID=$!
disown "$SLEEP_PID" 2>/dev/null || true

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf 'PASS  %s\n' "$1"; }
no()   { FAIL=$((FAIL+1)); printf 'FAIL  %s: %s\n' "$1" "$2"; }
skip() { SKIP=$((SKIP+1)); printf 'SKIP  %s: %s\n' "$1" "$2"; }
HAS_SQLITE=0; command -v sqlite3 >/dev/null 2>&1 && HAS_SQLITE=1

reason_of() { sed -n 's/.*reason: \([a-z_]*\).*/\1/p' <<<"$1" | head -1; }
verdict_of() { # combined-output -> "VERIFY" | "REJECT <reason>"
  if grep -q "could not be verified" <<<"$1"; then printf 'REJECT %s' "$(reason_of "$1")"; else printf 'VERIFY'; fi
}

# --- explicit --as wrapper with a tunable registry (REG_MODE) ---------------
AS_WRAP="$BIN_DIR/as-wrap"
cat > "$AS_WRAP" <<WRAP
#!/bin/bash
if [[ "\${_R:-}" != "1" ]]; then export _R=1; exec -a claude bash "\$0" "\$@"; fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
obs=\$(date +%s)
regf="$REGISTRY_ROOT/tproj-workspace/1/tproj.cc.json"
case "\${REG_MODE:-}" in
  good)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$obs" > "\$regf" ;;
  future_observed)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$((obs+100000))" > "\$regf" ;;
  pid_reuse)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$((mystart+9999))" "\$obs" > "\$regf" ;;
  nonancestor)
    printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\${NONANC_PID:-999999}" "\$mystart" "\$obs" > "\$regf" ;;
esac
"$REAL_TPROJ_MSG" "\$@"
WRAP
chmod +x "$AS_WRAP"

run_as() { # <REG_MODE> [msg-tag] -> verdict
  local mode="$1" tag="${2:-x}" out
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  out=$(REG_MODE="$mode" "$AS_WRAP" --session tproj-workspace --as tproj.cc tproj.cc "cvh $mode $tag $$-$RANDOM" 2>&1)
  verdict_of "$out"
}

# 1. future observed_at (clock skew / forged) -> REJECT registry_stale.
r=$(run_as future_observed); [[ "$r" == "REJECT registry_stale" ]] \
  && ok cvh01_future_observed_stale || no cvh01_future_observed_stale "got [$r]"

# 2. good recorded pid_start + live ancestor -> VERIFY (sanity anchor).
r=$(run_as good); [[ "$r" == "VERIFY" ]] \
  && ok cvh02_good_explicit_verifies || no cvh02_good_explicit_verifies "got [$r]"

# 3. pid reuse: recorded pid_start != live start -> REJECT pid_start_mismatch.
r=$(run_as pid_reuse); [[ "$r" == "REJECT pid_start_mismatch" ]] \
  && ok cvh03_pid_reuse_rejects || no cvh03_pid_reuse_rejects "got [$r]"

# 4. recorded reg_pid is a live NON-ancestor (reparent/disown proxy) ->
#    REJECT no_agent_ancestor (fail-closed: identity not provable).
export NONANC_PID="$SLEEP_PID"
r=$(run_as nonancestor); [[ "$r" == "REJECT no_agent_ancestor" ]] \
  && ok cvh04_nonancestor_rejects || no cvh04_nonancestor_rejects "got [$r]"
unset NONANC_PID

# --- deep-nesting ancestry-hop bound ----------------------------------------
# claude(wrapper) -> one intermediate bash (fork, no exec) -> tproj-msg, so the
# claude reg_pid sits at ancestry hop 2. The trailing "; true" prevents bash
# from exec-optimising the single command (which would collapse the depth).
DEPTH_WRAP="$BIN_DIR/depth-wrap"
cat > "$DEPTH_WRAP" <<WRAP
#!/bin/bash
if [[ "\${_R:-}" != "1" ]]; then export _R=1; exec -a claude bash "\$0" "\$@"; fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
regf="$REGISTRY_ROOT/tproj-workspace/1/tproj.cc.json"
printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$mystart" "\$(date +%s)" > "\$regf"
bash -c '"\$0" "\$@"; true' "$REAL_TPROJ_MSG" "\$@"
WRAP
chmod +x "$DEPTH_WRAP"

run_depth() { # <cap> -> verdict
  local cap="$1" out
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  out=$(TPROJ_MSG_VERIFIER_MAX_ANCESTOR_HOPS="$cap" "$DEPTH_WRAP" \
    --session tproj-workspace --as tproj.cc tproj.cc "cvh depth cap=$cap $$-$RANDOM" 2>&1)
  verdict_of "$out"
}

# 5. claude at hop 2, cap 1 -> cannot reach it -> REJECT no_agent_ancestor.
r=$(run_depth 1); [[ "$r" == "REJECT no_agent_ancestor" ]] \
  && ok cvh05_hop_over_cap_rejects || no cvh05_hop_over_cap_rejects "got [$r]"

# 6. same chain, cap 2 -> reaches claude at hop 2 -> VERIFY.
r=$(run_depth 2); [[ "$r" == "VERIFY" ]] \
  && ok cvh06_hop_within_cap_verifies || no cvh06_hop_within_cap_verifies "got [$r]"

# --- in-tmux pane-derived path ----------------------------------------------
run_intmux() { # <pane> <spoof_pane_pid|""> -> verdict
  local pane="$1" spoof="$2" target out
  case "$pane" in %1) target="tproj.cc";; %2) target="tproj.cdx";; esac
  rm -f "$FAKE_DIR/sendkeys.log"
  if [[ -n "$spoof" ]]; then
    out=$(SPOOF_PANE_PID="$spoof" TMUX=1 TMUX_PANE="$pane" "$REAL_TPROJ_MSG" "$target" "cvh intmux $pane $$-$RANDOM" 2>&1)
  else
    out=$(TMUX=1 TMUX_PANE="$pane" "$REAL_TPROJ_MSG" "$target" "cvh intmux $pane $$-$RANDOM" 2>&1)
  fi
  verdict_of "$out"
}

# 7. genuine in-tmux CC pane (pane_pid is a real ancestor) -> VERIFY.
r=$(run_intmux %1 ""); [[ "$r" == "VERIFY" ]] \
  && ok cvh07_intmux_cc_pane_verifies || no cvh07_intmux_cc_pane_verifies "got [$r]"

# 8. genuine in-tmux Cdx pane -> VERIFY (platform-agnostic pane ancestry).
r=$(run_intmux %2 ""); [[ "$r" == "VERIFY" ]] \
  && ok cvh08_intmux_cdx_pane_verifies || no cvh08_intmux_cdx_pane_verifies "got [$r]"

# 8b. a pane-derived --new-task carries its [Task: id] in the DELIVERED body.
#     The body is the only channel a send-keys receiver has, and the lifecycle
#     contract requires the receiver to answer with that exact id. The tag used
#     to be prepended only for --as sends, so a pane-derived delegation reached
#     its receiver with no id and came back as [ACK: <alias>-unknown].
rm -f "$FAKE_DIR/sendkeys.log"
nt_out=$(TMUX=1 TMUX_PANE="%1" "$REAL_TPROJ_MSG" --new-task tproj.cdx "cvh newtask body $$-$RANDOM" 2>&1)
nt_id=$(printf '%s\n' "$nt_out" | sed -n 's/.*TASK_ID=\([^ ]*\).*/\1/p' | head -n 1)
if [[ -n "$nt_id" ]] && grep -q "\[Task: $nt_id\]" "$FAKE_DIR/sendkeys.log" 2>/dev/null; then
  ok cvh08b_pane_derived_new_task_body_carries_task_id
else
  no cvh08b_pane_derived_new_task_body_carries_task_id "id=[$nt_id] sendkeys=[$(tr '\n' '|' < "$FAKE_DIR/sendkeys.log" 2>/dev/null | cut -c1-160)]"
fi

# 9. spoofed TMUX_PANE (pane_pid is NOT an ancestor) -> REJECT
#    pane_ancestry_mismatch before any send-keys.
r=$(run_intmux %1 999999); [[ "$r" == "REJECT pane_ancestry_mismatch" ]] \
  && ok cvh09_intmux_spoof_rejects || no cvh09_intmux_spoof_rejects "got [$r]"

# --- CWD auto-detect fallback (--session, no --as) --------------------------
CWD_HOME="$WORK/cwdhome"; PROJDIR="$WORK/proj"
mkdir -p "$CWD_HOME/.config/tproj" "$PROJDIR"
# Normalise PROJDIR so the workspace.yaml path matches what `pwd` reports after
# `cd` (TMPDIR can carry a trailing slash -> a double slash mktemp path that pwd
# collapses, which would otherwise defeat the exact-string CWD lookup).
PROJDIR=$(cd "$PROJDIR" && pwd)
cat > "$CWD_HOME/.config/tproj/workspace.yaml" <<YAML
projects:
  - alias: tproj
    path: $PROJDIR
YAML
CWD_WRAP="$BIN_DIR/cwd-wrap"
cat > "$CWD_WRAP" <<WRAP
#!/bin/bash
if [[ "\${_R:-}" != "1" ]]; then export _R=1; exec -a claude bash "\$0" "\$@"; fi
mypid=\$\$
mystart=\$(date -j -f "%a %b %d %H:%M:%S %Y" "\$(ps -p \$mypid -o lstart=)" +%s 2>/dev/null || echo 0)
case "\${CWD_MODE:-good}" in
  good) ps=\$mystart ;;
  bad)  ps=\$((mystart+9999)) ;;
esac
regf="$REGISTRY_ROOT/tproj-workspace/1/tproj.cc.json"
printf '{"alias":"tproj.cc","pid":%s,"pid_start":%s,"role_epoch":1,"role":"worker","orchestrator_alias":"tproj.cdx","observed_at":%s}\n' "\$mypid" "\$ps" "\$(date +%s)" > "\$regf"
cd "$PROJDIR" || exit 99
"$REAL_TPROJ_MSG" "\$@"
WRAP
chmod +x "$CWD_WRAP"

run_cwd() { # <mode> -> verdict
  local mode="$1" out
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  out=$(HOME="$CWD_HOME" CWD_MODE="$mode" "$CWD_WRAP" --session tproj-workspace tproj.cc "cvh cwd $mode $$-$RANDOM" 2>&1)
  verdict_of "$out"
}

if command -v yq >/dev/null 2>&1; then
  # 10. CWD alias + registry-verified identity -> VERIFY (comm-name gate removed).
  r=$(run_cwd good); [[ "$r" == "VERIFY" ]] \
    && ok cvh10_cwd_autodetect_verifies || no cvh10_cwd_autodetect_verifies "got [$r]"
  # 11. CWD alias but registry pid_start wrong -> REJECT pid_start_mismatch.
  r=$(run_cwd bad); [[ "$r" == "REJECT pid_start_mismatch" ]] \
    && ok cvh11_cwd_bad_registry_rejects || no cvh11_cwd_bad_registry_rejects "got [$r]"
else
  skip cvh10_cwd_autodetect_verifies "yq not available"
  skip cvh11_cwd_bad_registry_rejects "yq not available"
fi

# --- audit attribution (auth_path + anchor_pid, exactly one row) ------------
if [[ "$HAS_SQLITE" -eq 1 ]]; then
  # 12. accept: exactly one bodyless caller-audit row, auth_path explicit-as-
  #     verified, anchor_pid set to the registry reg_pid, body/hash empty.
  rm -f "$FAKE_DIR/sendkeys.log"
  rm -f "$REGISTRY_ROOT"/tproj-workspace/*/tproj.cc.json 2>/dev/null
  before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COALESCE(MAX(id),0) FROM messages;" 2>/dev/null || echo 0)
  REG_MODE=good "$AS_WRAP" --session tproj-workspace --as tproj.cc tproj.cc "cvh audit accept $$-$RANDOM" >/dev/null 2>&1
  newcnt=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE id>${before} AND length(body)=0 AND ifnull(length(payload_sha256),0)=64;" 2>/dev/null || echo 0)
  arow=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT verified, ifnull(auth_path,''), ifnull(anchor_pid,-1), length(body), ifnull(length(body_hash),-1), ifnull(length(payload_sha256),0) FROM messages WHERE id>${before} AND length(body)=0 AND ifnull(length(payload_sha256),0)=64 ORDER BY id DESC LIMIT 1;" 2>/dev/null || true)
  IFS='|' read -r av aauth aanchor ablen abhlen ashalen <<<"$arow"
  if [[ "$newcnt" == "1" && "$av" == "1" && "$aauth" == "explicit-as-verified" \
        && "$aanchor" -gt 0 && "$ablen" == "0" && "$abhlen" == "0" && "$ashalen" == "64" ]]; then
    ok cvh12_accept_audit_authpath_anchor
  else
    no cvh12_accept_audit_authpath_anchor "newcnt=$newcnt row=[$arow]"
  fi

  # 13. spoof reject: exactly one bodyless reject row, auth_path pane-derived-
  #     rejected, reason pane_ancestry_mismatch, anchor_pid = the forged pane_pid,
  #     and the REAL invoker caller_pid diverges from anchor_pid (attribution).
  rm -f "$FAKE_DIR/sendkeys.log"
  before=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COALESCE(MAX(id),0) FROM messages;" 2>/dev/null || echo 0)
  SPOOF_PANE_PID=999999 TMUX=1 TMUX_PANE=%1 "$REAL_TPROJ_MSG" tproj.cc "cvh audit spoof $$-$RANDOM" >/dev/null 2>&1
  newcnt=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT COUNT(*) FROM messages WHERE id>${before} AND length(body)=0 AND ifnull(length(payload_sha256),0)=64;" 2>/dev/null || echo 0)
  srow=$(sqlite3 "$TPROJ_MSG_DB_PATH" "SELECT verified, ifnull(rejection_reason,''), ifnull(auth_path,''), ifnull(anchor_pid,-1), ifnull(caller_pid,-1), length(body), ifnull(length(payload_sha256),0) FROM messages WHERE id>${before} AND length(body)=0 AND ifnull(length(payload_sha256),0)=64 ORDER BY id DESC LIMIT 1;" 2>/dev/null || true)
  IFS='|' read -r sv sreason sauth sanchor scaller sblen sshalen <<<"$srow"
  if [[ "$newcnt" == "1" && "$sv" == "0" && "$sreason" == "pane_ancestry_mismatch" \
        && "$sauth" == "pane-derived-rejected" && "$sanchor" == "999999" \
        && "$scaller" -gt 0 && "$scaller" != "999999" && "$sblen" == "0" && "$sshalen" == "64" ]]; then
    ok cvh13_spoof_reject_audit_divergence
  else
    no cvh13_spoof_reject_audit_divergence "newcnt=$newcnt row=[$srow]"
  fi
else
  skip cvh12_accept_audit_authpath_anchor "no sqlite3"
  skip cvh13_spoof_reject_audit_divergence "no sqlite3"
fi

# 14. nested tmux: runtime-unobserved on this host (single tmux server; agent
#     panes are children of it, not of a nested server). The anchor is the inner
#     pane_pid, and a forged outer-pane pane_pid is a non-ancestor -- already
#     covered by cvh09's spoof (non-ancestor pane_pid -> reject). Recorded as a
#     defensive skip rather than a flaky fabricated nested-server fixture.
skip cvh14_nested_tmux "runtime-unobserved; inner-pane anchor is exercised by cvh09 spoof"

echo "----"
printf 'PASS=%d FAIL=%d SKIP=%d\n' "$PASS" "$FAIL" "$SKIP"
[[ "$FAIL" -eq 0 ]]
